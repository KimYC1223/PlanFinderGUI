"""Tracks the PlanFinder-launched Claude sessions and their subprocess CPU usage.

Each ``Session`` corresponds to one in-flight ``run_discovery_loop`` /
``run_resolve_session`` coroutine. The ``SessionManager`` polls the descendant
processes of the host Python process via :mod:`psutil`, attributes each
``claude``/``node`` subtree to the session that started just before the
process spawned, and emits per-session CPU updates so the UI can render a
live sparkline.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Callable, Optional

from PySide6.QtCore import QObject, QTimer, Signal

if TYPE_CHECKING:  # pragma: no cover
    from ..ui.gui_display import GuiDisplayAdapter


CPU_HISTORY_LEN = 60     # seconds shown in the sparkline (1 sample/sec)
POLL_INTERVAL_MS = 1000  # CPU sampling cadence

# Shared thread pool for background termination work
_termination_executor: ThreadPoolExecutor | None = None


def _get_termination_executor() -> ThreadPoolExecutor:
    """Get or create the shared thread pool for subprocess termination."""
    global _termination_executor
    if _termination_executor is None:
        # Use a small pool - termination is mostly waiting, not CPU-bound
        _termination_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="term")
    return _termination_executor


class Session(QObject):
    """One PlanFinder-launched Claude session.

    The actual coroutine and adapter live elsewhere; this object just carries
    the metadata, owns the per-session CPU history, and exposes Qt signals so
    the UI can subscribe to changes.

    States:
        - "starting": Session created but not yet running
        - "running": Session is actively executing
        - "terminating": Cancellation requested, subprocess cleanup in progress
        - "completed": Session finished successfully
        - "cancelled": Session was cancelled by user
        - "failed": Session encountered an error
    """

    cpu_updated = Signal(float)        # latest cpu % (sum across owned PIDs)
    state_changed = Signal(str)        # "running" / "completed" / "cancelled" / "failed" / "terminating"
    termination_complete = Signal()    # emitted when async termination finishes

    def __init__(
        self,
        sid: str,
        label: str,
        adapter: "GuiDisplayAdapter",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.id = sid
        self.label = label
        self.adapter = adapter
        self.task: Optional[asyncio.Task] = None
        self.started_at: float = time.time()
        self.state: str = "starting"
        self.cpu: float = 0.0
        self.cpu_history: deque[float] = deque(
            [0.0] * CPU_HISTORY_LEN, maxlen=CPU_HISTORY_LEN
        )
        # psutil.Process objects we've claimed for this session, keyed by pid
        self._procs: dict[int, object] = {}
        # PIDs that are currently being terminated (to prevent duplicate attempts)
        self._terminating_pids: set[int] = set()

    def claim(self, pid: int, proc: object) -> None:
        self._procs[pid] = proc

    def claimed_pids(self) -> set[int]:
        return set(self._procs.keys())

    def drop_dead(self) -> None:
        try:
            import psutil
        except Exception:
            return
        dead = []
        for pid, proc in self._procs.items():
            try:
                if not proc.is_running() or proc.status() == psutil.STATUS_ZOMBIE:
                    dead.append(pid)
            except Exception:
                dead.append(pid)
        for pid in dead:
            self._procs.pop(pid, None)

    _cpu_count: int | None = None

    @classmethod
    def _logical_cpu_count(cls) -> int:
        if cls._cpu_count is None:
            try:
                import psutil
                cls._cpu_count = psutil.cpu_count(logical=True) or os.cpu_count() or 1
            except Exception:
                cls._cpu_count = os.cpu_count() or 1
        return cls._cpu_count

    def sample_cpu(self) -> float:
        """Sum cpu_percent across owned processes, normalized to 0–100% of total CPU."""
        total = 0.0
        for proc in list(self._procs.values()):
            try:
                total += float(proc.cpu_percent(interval=None) or 0.0)
            except Exception:
                continue
        # psutil returns per-core percentages (e.g. 200% on a process pinning 2 cores).
        # Normalize against logical core count so the gauge stays within 0–100%.
        normalized = min(100.0, total / self._logical_cpu_count())
        self.cpu = normalized
        self.cpu_history.append(normalized)
        return normalized

    def cancel(self, wait: bool = False) -> bool:
        """Cancel the session task and terminate subprocesses.

        By default, this method is non-blocking: it cancels the asyncio task,
        enters the "terminating" state, and schedules subprocess cleanup in a
        background thread. The UI remains responsive while termination proceeds.

        Args:
            wait: If True, blocks while waiting for subprocess termination
                  (legacy behavior, use sparingly - only for app shutdown).
                  If False (default), schedules termination asynchronously and
                  returns immediately.

        Returns:
            True if the task was running and was cancelled, False otherwise.
        """
        if self.state == "terminating":
            # Already terminating, don't duplicate the work
            return False

        if self.task and not self.task.done():
            self.task.cancel()

            if wait:
                # Blocking termination - only for app close scenarios
                self.terminate_procs()
            else:
                # Non-blocking: enter terminating state and schedule background work
                self.state = "terminating"
                self.state_changed.emit("terminating")
                self._schedule_termination_async()
            return True
        return False

    def _schedule_termination_async(
        self,
        timeout: float = 5.0,
        callback: Optional[Callable[[], None]] = None,
    ) -> None:
        """Schedule subprocess termination in a background thread.

        This method returns immediately. The actual termination work happens
        in a thread pool, and when complete, the termination_complete signal
        is emitted on the Qt main thread.

        Args:
            timeout: Maximum seconds to wait for graceful termination per process.
            callback: Optional callback to invoke after termination completes.
        """
        # Capture PIDs to terminate before the thread starts
        pids_to_terminate = set(self._procs.keys())
        if not pids_to_terminate:
            # No processes to terminate, emit completion immediately
            self.termination_complete.emit()
            if callback:
                callback()
            return

        # Mark these PIDs as being terminated
        self._terminating_pids.update(pids_to_terminate)

        def do_termination() -> None:
            try:
                self.terminate_procs(timeout)
            except Exception as e:
                logging.warning(f"Error during async termination: {e}")
            finally:
                self._terminating_pids.clear()

        def on_done(future) -> None:
            # Emit signal on Qt main thread via QTimer.singleShot
            QTimer.singleShot(0, self.termination_complete.emit)
            if callback:
                QTimer.singleShot(0, callback)

        executor = _get_termination_executor()
        future = executor.submit(do_termination)
        future.add_done_callback(on_done)

    @property
    def is_terminating(self) -> bool:
        """True if this session is currently in the terminating state."""
        return self.state == "terminating"

    def terminate_procs_nowait(self) -> None:
        """Send SIGTERM to all subprocesses without waiting for exit.

        This is a fire-and-forget variant for use when the app is closing
        or when immediate return is required. Processes that don't exit
        gracefully will be cleaned up by the OS or by a subsequent
        drop_dead() call.
        """
        try:
            import psutil
        except ImportError:
            return

        for proc in list(self._procs.values()):
            try:
                if proc.is_running():
                    proc.terminate()
            except psutil.NoSuchProcess:
                pass
            except psutil.AccessDenied:
                logging.warning(
                    f"Access denied when terminating PID {proc.pid}; "
                    "may require elevated privileges"
                )
            except Exception as e:
                logging.warning(f"Error terminating PID {proc.pid}: {e}")

        # Clear process tracking - cleanup will happen via drop_dead() or OS
        self._procs.clear()
        self._terminating_pids.clear()

    async def terminate_procs_async(self, timeout: float = 5.0) -> None:
        """Asynchronously terminate all subprocesses owned by this session.

        This method runs the blocking psutil wait() calls in a thread pool
        so the Qt main thread remains responsive.

        Args:
            timeout: Maximum seconds to wait for graceful termination.
        """
        await asyncio.to_thread(self.terminate_procs, timeout)

    def terminate_procs(self, timeout: float = 5.0) -> None:
        """Terminate all subprocesses owned by this session.

        First sends SIGTERM (terminate) to each process and waits up to
        ``timeout`` seconds for graceful exit. Any processes still running
        after the timeout are forcibly killed (SIGKILL).

        This method is safe to call from a background thread.

        Args:
            timeout: Maximum seconds to wait for graceful termination.
        """
        try:
            import psutil
        except ImportError:
            return

        procs_to_terminate = list(self._procs.values())
        if not procs_to_terminate:
            return

        # Phase 1: Send SIGTERM to all processes
        for proc in procs_to_terminate:
            try:
                if proc.is_running():
                    proc.terminate()
            except psutil.NoSuchProcess:
                # Process already exited
                pass
            except psutil.AccessDenied:
                # Cannot terminate (elevated privileges required)
                logging.warning(
                    f"Access denied when terminating PID {proc.pid}; "
                    "may require elevated privileges"
                )
            except Exception as e:
                logging.warning(f"Error terminating PID {proc.pid}: {e}")

        # Phase 2: Wait for graceful termination
        still_alive = []
        deadline = time.time() + timeout
        for proc in procs_to_terminate:
            try:
                remaining = max(0.0, deadline - time.time())
                proc.wait(timeout=remaining)
            except psutil.TimeoutExpired:
                still_alive.append(proc)
            except psutil.NoSuchProcess:
                pass
            except Exception:
                pass

        # Phase 3: Force kill any processes that didn't exit gracefully
        for proc in still_alive:
            try:
                if proc.is_running():
                    proc.kill()
            except psutil.NoSuchProcess:
                pass
            except psutil.AccessDenied:
                logging.warning(
                    f"Access denied when killing PID {proc.pid}; "
                    "process may still be running"
                )
            except Exception as e:
                logging.warning(f"Error killing PID {proc.pid}: {e}")

        # Clear the process tracking dict
        self._procs.clear()
        self._terminating_pids.clear()


class SessionManager(QObject):
    """Owns the live Session list and broadcasts CPU samples to the UI.

    The manager tracks sessions through their lifecycle including the new
    "terminating" state where subprocess cleanup is in progress.
    """

    session_registered = Signal(object)     # Session
    session_unregistered = Signal(object)   # Session
    session_state_changed = Signal(object)  # Session
    all_terminations_complete = Signal()    # Emitted when all pending terminations finish

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._sessions: dict[str, Session] = {}
        self._next_id: int = 0
        self._claimed_pids: set[int] = set()
        # Track sessions that are currently terminating
        self._terminating_sessions: set[str] = set()

        try:
            import psutil
            self._psutil = psutil
            self._self_proc = psutil.Process(os.getpid())
        except Exception:
            self._psutil = None
            self._self_proc = None

        self._timer = QTimer(self)
        self._timer.setInterval(POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # -- session lifecycle ---------------------------------------------- #

    def new_id(self) -> str:
        self._next_id += 1
        return f"S{self._next_id}"

    def register(self, session: Session) -> None:
        session.started_at = time.time()
        session.state = "running"
        self._sessions[session.id] = session
        self.session_registered.emit(session)
        self.session_state_changed.emit(session)

    def mark_state(self, session: Session, state: str) -> None:
        session.state = state
        session.state_changed.emit(state)
        self.session_state_changed.emit(session)

    def unregister(self, session: Session) -> None:
        """Unregister a session and clean up its subprocess tracking.

        Uses non-blocking termination to avoid freezing the UI during cleanup.
        Any lingering processes will be terminated via SIGTERM; the OS or
        subsequent drop_dead() calls handle stragglers.
        """
        # Send termination signals without blocking - by this point the session
        # task is already done, so we don't need to wait for process exit.
        session.terminate_procs_nowait()
        self._sessions.pop(session.id, None)
        for pid in session.claimed_pids():
            self._claimed_pids.discard(pid)
        self.session_unregistered.emit(session)

    def list(self) -> list[Session]:
        return list(self._sessions.values())

    def any_running(self) -> bool:
        return any(s.state == "running" for s in self._sessions.values())

    def cancel_all(self, wait_for_termination: bool = False) -> int:
        """Cancel all running sessions and terminate their subprocesses.

        By default, this method is non-blocking: it cancels all asyncio tasks
        and schedules subprocess cleanup in background threads. The UI remains
        responsive while termination proceeds.

        Args:
            wait_for_termination: If True, blocks while waiting for subprocess
                termination (legacy behavior, only for app shutdown).
                If False (default), sends SIGTERM and schedules async cleanup,
                returning immediately to keep the UI responsive.

        Returns:
            Number of sessions that were cancelled.
        """
        cancelled = 0
        sessions_to_cancel = [
            s for s in self._sessions.values()
            if s.state == "running"
        ]

        for s in sessions_to_cancel:
            if s.cancel(wait=wait_for_termination):
                cancelled += 1
                if not wait_for_termination:
                    self._terminating_sessions.add(s.id)
                    # Connect to the session's termination_complete signal
                    s.termination_complete.connect(
                        lambda sid=s.id: self._on_session_termination_complete(sid)
                    )
        return cancelled

    def _on_session_termination_complete(self, session_id: str) -> None:
        """Handle completion of a session's async termination."""
        self._terminating_sessions.discard(session_id)
        if not self._terminating_sessions:
            self.all_terminations_complete.emit()

    def any_terminating(self) -> bool:
        """Return True if any sessions are currently terminating."""
        return bool(self._terminating_sessions) or any(
            s.state == "terminating" for s in self._sessions.values()
        )

    def cancel_all_blocking(self, timeout: float = 10.0) -> int:
        """Cancel all running sessions with blocking termination.

        This method should only be used during app shutdown when we must
        ensure all subprocesses are cleaned up before exiting.

        Args:
            timeout: Maximum seconds to wait for all terminations.

        Returns:
            Number of sessions that were cancelled.
        """
        return self.cancel_all(wait_for_termination=True)

    # -- CPU polling ---------------------------------------------------- #

    def _tick(self) -> None:
        if self._psutil is None or self._self_proc is None:
            return

        try:
            descendants = self._self_proc.children(recursive=True)
        except Exception:
            descendants = []

        # Attribute newly-spawned descendants to the session that started most
        # recently before the process was created.
        running = sorted(
            (s for s in self._sessions.values() if s.state == "running"),
            key=lambda s: s.started_at,
        )
        for proc in descendants:
            pid = proc.pid
            if pid in self._claimed_pids:
                continue
            try:
                ctime = proc.create_time()
            except Exception:
                continue
            owner: Session | None = None
            for sess in running:
                if sess.started_at <= ctime + 0.001:
                    owner = sess  # latest-wins
            if owner is None:
                continue
            try:
                proc.cpu_percent(interval=None)  # prime
            except Exception:
                continue
            owner.claim(pid, proc)
            self._claimed_pids.add(pid)

        # Sample each session, drop dead procs, emit.
        for sess in self._sessions.values():
            sess.drop_dead()
            cpu = sess.sample_cpu()
            sess.cpu_updated.emit(cpu)
