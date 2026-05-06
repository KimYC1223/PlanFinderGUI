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
import os
import time
from collections import deque
from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import QObject, QTimer, Signal

if TYPE_CHECKING:  # pragma: no cover
    from ..ui.gui_display import GuiDisplayAdapter


CPU_HISTORY_LEN = 60     # seconds shown in the sparkline (1 sample/sec)
POLL_INTERVAL_MS = 1000  # CPU sampling cadence


class Session(QObject):
    """One PlanFinder-launched Claude session.

    The actual coroutine and adapter live elsewhere; this object just carries
    the metadata, owns the per-session CPU history, and exposes Qt signals so
    the UI can subscribe to changes.
    """

    cpu_updated = Signal(float)        # latest cpu % (sum across owned PIDs)
    state_changed = Signal(str)        # "running" / "completed" / "cancelled" / "failed"

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

    def cancel(self) -> bool:
        if self.task and not self.task.done():
            self.task.cancel()
            return True
        return False


class SessionManager(QObject):
    """Owns the live Session list and broadcasts CPU samples to the UI."""

    session_registered = Signal(object)     # Session
    session_unregistered = Signal(object)   # Session
    session_state_changed = Signal(object)  # Session

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._sessions: dict[str, Session] = {}
        self._next_id: int = 0
        self._claimed_pids: set[int] = set()

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
        self._sessions.pop(session.id, None)
        for pid in session.claimed_pids():
            self._claimed_pids.discard(pid)
        self.session_unregistered.emit(session)

    def list(self) -> list[Session]:
        return list(self._sessions.values())

    def any_running(self) -> bool:
        return any(s.state == "running" for s in self._sessions.values())

    def cancel_all(self) -> int:
        cancelled = 0
        for s in self._sessions.values():
            if s.cancel():
                cancelled += 1
        return cancelled

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
