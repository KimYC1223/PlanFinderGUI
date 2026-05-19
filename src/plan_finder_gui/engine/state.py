from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Generator

from filelock import FileLock, Timeout

from .fileutil import atomic_write
from .models import DiscoveredPlan, PlanFinderState, RejectionRecord


# Default timeout for acquiring file locks (in seconds)
_LOCK_TIMEOUT_SECONDS = 10.0


@contextmanager
def _locked_state(
    lock_path: Path,
    exclusive: bool = False,
    timeout: float = _LOCK_TIMEOUT_SECONDS,
) -> Generator[FileLock, None, None]:
    """Context manager for acquiring file locks on state files.

    Args:
        lock_path: Path to the lock file (typically .state.lock).
        exclusive: If True, acquire an exclusive (write) lock.
                   If False, acquire a shared (read) lock.
                   Note: filelock always acquires exclusive locks, but we use
                   this parameter semantically for documentation and potential
                   future enhancements with platform-specific shared locking.
        timeout: Maximum time to wait for lock acquisition (in seconds).
                 Set to -1 for blocking indefinitely.

    Yields:
        The acquired FileLock instance.

    Raises:
        Timeout: If the lock cannot be acquired within the timeout period.
        FileLockException: If there are other issues acquiring the lock.

    Note:
        The filelock library handles cross-platform locking (Windows, Unix, macOS)
        and automatically cleans up stale lock files when processes crash.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(lock_path), timeout=timeout)
    try:
        lock.acquire()
        yield lock
    finally:
        lock.release()


class StateManager:
    """Manages rejection state stored as .state.json inside the report dir.

    This class uses file locking to prevent race conditions when multiple
    processes access the same state file concurrently. A .state.lock file
    is created alongside .state.json to coordinate access.
    """

    def __init__(self, report_dir: Path) -> None:
        self.path = report_dir / ".state.json"
        self.lock_path = report_dir / ".state.lock"
        self._state: PlanFinderState | None = None
        self.load_error: bool = False
        self.backup_path: Path | None = None

    def load(self) -> PlanFinderState:
        """Load state from disk with file locking to prevent concurrent access issues.

        Acquires a shared (read) lock before reading the state file to ensure
        consistency when multiple processes may be accessing the same file.
        """
        try:
            with _locked_state(self.lock_path, exclusive=False):
                self._load_unlocked()
        except Timeout:
            # If we can't acquire the lock, log warning and load anyway
            # (better to have potentially stale data than crash)
            import sys
            print(
                f"[StateManager] Warning: Could not acquire lock for {self.path}, "
                "loading without lock",
                file=sys.stderr,
            )
            self._load_unlocked()
        return self._state  # type: ignore[return-value]

    def _load_unlocked(self) -> None:
        """Internal load implementation without locking."""
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self._state = PlanFinderState.model_validate(data)
            except Exception:
                import shutil
                backup = self.path.with_suffix(
                    f".json.corrupted.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                )
                shutil.copy2(self.path, backup)
                self.backup_path = backup
                self._state = PlanFinderState()
                self.load_error = True
        else:
            self._state = PlanFinderState()

    def save(self) -> None:
        """Save state to disk with file locking to prevent concurrent write issues.

        Acquires an exclusive (write) lock before writing to ensure only one
        process can modify the state file at a time, preventing lost updates.
        """
        if self._state is None:
            return
        try:
            with _locked_state(self.lock_path, exclusive=True):
                self._save_unlocked()
        except Timeout:
            # If we can't acquire the lock, log warning and save anyway
            # (risk of lost update is better than losing all pending changes)
            import sys
            print(
                f"[StateManager] Warning: Could not acquire lock for {self.path}, "
                "saving without lock (potential data race)",
                file=sys.stderr,
            )
            self._save_unlocked()

    def _save_unlocked(self) -> None:
        """Internal save implementation without locking."""
        if self._state is None:
            return
        self._state.last_run = datetime.now()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(self.path, self._state.model_dump_json(indent=2))

    @property
    def state(self) -> PlanFinderState:
        if self._state is None:
            return self.load()
        return self._state

    def add_rejection(self, plan: DiscoveredPlan, reason: str = "") -> None:
        record = RejectionRecord(
            title=plan.title,
            category=plan.category.value,
            description_summary=plan.description[:200],
            rejected_at=datetime.now(),
            reason=reason,
        )
        self.state.rejected_plans.append(record)
        self.state.total_rejected += 1
        self.save()

    def add_pending(self, plan: DiscoveredPlan) -> None:
        record = RejectionRecord(
            title=plan.title,
            category=plan.category.value,
            description_summary=plan.description[:200],
            rejected_at=datetime.now(),
            reason="(pending review)",
        )
        self.state.rejected_plans.append(record)
        self.save()

    def record_approval(self, plan: DiscoveredPlan) -> None:
        record = RejectionRecord(
            title=plan.title,
            category=plan.category.value,
            description_summary=plan.description[:200],
            rejected_at=datetime.now(),
            reason="(approved)",
        )
        self.state.rejected_plans.append(record)
        self.state.total_approved += 1
        self.save()

    def clear_rejections(self) -> None:
        self.state.rejected_plans.clear()
        self.save()
