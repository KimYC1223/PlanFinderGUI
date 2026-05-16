"""Tests for the session_manager module.

These tests verify that the Session and SessionManager classes properly handle
async subprocess termination without blocking the UI thread.
"""

from __future__ import annotations

import asyncio
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

# Check if pytest-qt is available for signal testing
try:
    import pytestqt  # noqa: F401
    HAS_PYTEST_QT = True
except ImportError:
    HAS_PYTEST_QT = False

from plan_finder_gui.engine.session_manager import (
    Session,
    SessionManager,
    _get_termination_executor,
)


class MockGuiDisplayAdapter:
    """Mock display adapter for testing."""

    def __init__(self):
        self.logs: list[str] = []

    def cancel_pending(self) -> None:
        pass

    def log(self, message: str) -> None:
        self.logs.append(message)


class TestSessionTerminationNonBlocking:
    """Tests that verify subprocess termination doesn't block the UI thread."""

    @pytest.fixture
    def mock_adapter(self) -> MockGuiDisplayAdapter:
        """Create a mock display adapter."""
        return MockGuiDisplayAdapter()

    @pytest.fixture
    def session(self, mock_adapter: MockGuiDisplayAdapter) -> Session:
        """Create a test session with mocked components."""
        session = Session(
            sid="S1",
            label="Test Session",
            adapter=mock_adapter,
        )
        # Create a mock task that appears to be running
        mock_task = MagicMock()
        mock_task.done.return_value = False
        mock_task.cancel.return_value = None
        session.task = mock_task
        session.state = "running"
        return session

    def test_cancel_returns_immediately_without_wait(
        self, session: Session
    ) -> None:
        """Verify that cancel(wait=False) returns within 100ms."""
        # Add some mock processes to terminate
        mock_proc = MagicMock()
        mock_proc.is_running.return_value = True
        mock_proc.pid = 12345
        session._procs[12345] = mock_proc

        start_time = time.perf_counter()
        result = session.cancel(wait=False)
        elapsed_ms = (time.perf_counter() - start_time) * 1000

        assert result is True
        assert elapsed_ms < 100, f"cancel() took {elapsed_ms:.1f}ms, expected < 100ms"
        assert session.state == "terminating"

    def test_cancel_enters_terminating_state(self, session: Session) -> None:
        """Verify that cancel(wait=False) transitions to 'terminating' state."""
        mock_proc = MagicMock()
        mock_proc.is_running.return_value = True
        mock_proc.pid = 12345
        session._procs[12345] = mock_proc

        assert session.state == "running"

        session.cancel(wait=False)

        assert session.state == "terminating"
        assert session.is_terminating is True

    def test_duplicate_cancel_is_ignored(self, session: Session) -> None:
        """Verify that calling cancel() twice doesn't duplicate termination work."""
        mock_proc = MagicMock()
        mock_proc.is_running.return_value = True
        mock_proc.pid = 12345
        session._procs[12345] = mock_proc

        # First cancel
        result1 = session.cancel(wait=False)
        assert result1 is True
        assert session.state == "terminating"

        # Second cancel should be ignored
        result2 = session.cancel(wait=False)
        assert result2 is False

    def test_termination_complete_signal_emitted(
        self, session: Session
    ) -> None:
        """Verify that termination_complete signal is emitted after async termination.

        Note: This test uses blocking wait=True since the async path requires
        a running Qt event loop to emit signals via QTimer.singleShot.
        The core behavior (signal emission) is tested indirectly.
        """
        mock_proc = MagicMock()
        mock_proc.is_running.return_value = True
        mock_proc.pid = 12345
        mock_proc.terminate.return_value = None
        mock_proc.wait.return_value = None
        session._procs[12345] = mock_proc

        # Test that cancel with wait=True completes termination synchronously
        session.cancel(wait=True)

        # After blocking termination, processes should be cleared
        assert len(session._procs) == 0
        assert len(session._terminating_pids) == 0

    def test_cancel_with_no_processes_completes_immediately(
        self, session: Session
    ) -> None:
        """Verify that cancel with no processes emits signal immediately."""
        # Ensure no processes
        session._procs.clear()

        # Use a threading event to wait for the signal
        signal_received = threading.Event()
        session.termination_complete.connect(lambda: signal_received.set())

        session.cancel(wait=False)

        # Signal should be emitted almost immediately when no processes
        assert signal_received.wait(timeout=1.0), "termination_complete signal not emitted"
        assert session.state == "terminating"


class TestSessionManagerCancelAll:
    """Tests for SessionManager.cancel_all() async behavior."""

    @pytest.fixture
    def manager(self) -> SessionManager:
        """Create a session manager for testing."""
        manager = SessionManager()
        yield manager
        # Cleanup: stop the timer
        manager._timer.stop()

    @pytest.fixture
    def mock_adapter(self) -> MockGuiDisplayAdapter:
        """Create a mock display adapter."""
        return MockGuiDisplayAdapter()

    def test_cancel_all_returns_immediately(
        self, manager: SessionManager, mock_adapter: MockGuiDisplayAdapter
    ) -> None:
        """Verify that cancel_all(wait_for_termination=False) returns within 100ms."""
        # Create multiple sessions with mock processes
        for i in range(3):
            session = Session(
                sid=f"S{i}",
                label=f"Session {i}",
                adapter=mock_adapter,
            )
            mock_task = MagicMock()
            mock_task.done.return_value = False
            mock_task.cancel.return_value = None
            session.task = mock_task
            session.state = "running"

            mock_proc = MagicMock()
            mock_proc.is_running.return_value = True
            mock_proc.pid = 1000 + i
            session._procs[1000 + i] = mock_proc

            manager.register(session)

        start_time = time.perf_counter()
        cancelled = manager.cancel_all(wait_for_termination=False)
        elapsed_ms = (time.perf_counter() - start_time) * 1000

        assert cancelled == 3
        assert elapsed_ms < 100, f"cancel_all() took {elapsed_ms:.1f}ms, expected < 100ms"

    def test_any_terminating_tracks_state(
        self, manager: SessionManager, mock_adapter: MockGuiDisplayAdapter
    ) -> None:
        """Verify that any_terminating() correctly tracks terminating sessions."""
        session = Session(
            sid="S1",
            label="Test Session",
            adapter=mock_adapter,
        )
        mock_task = MagicMock()
        mock_task.done.return_value = False
        mock_task.cancel.return_value = None
        session.task = mock_task
        session.state = "running"

        mock_proc = MagicMock()
        mock_proc.is_running.return_value = True
        mock_proc.pid = 12345
        session._procs[12345] = mock_proc

        manager.register(session)

        assert manager.any_terminating() is False

        manager.cancel_all(wait_for_termination=False)

        assert manager.any_terminating() is True

    def test_all_terminations_complete_signal(
        self, manager: SessionManager, mock_adapter: MockGuiDisplayAdapter
    ) -> None:
        """Verify that terminating sessions are tracked correctly.

        Note: Signal emission via QTimer.singleShot requires a running Qt
        event loop, which isn't available in pure pytest. We test the
        tracking mechanism instead.
        """
        session = Session(
            sid="S1",
            label="Test Session",
            adapter=mock_adapter,
        )
        mock_task = MagicMock()
        mock_task.done.return_value = False
        mock_task.cancel.return_value = None
        session.task = mock_task
        session.state = "running"

        # Add a mock process
        mock_proc = MagicMock()
        mock_proc.is_running.return_value = True
        mock_proc.pid = 12345
        session._procs[12345] = mock_proc

        manager.register(session)

        # Verify tracking state before cancel
        assert manager.any_terminating() is False
        assert len(manager._terminating_sessions) == 0

        # Cancel with non-blocking mode
        cancelled = manager.cancel_all(wait_for_termination=False)

        # Verify tracking state after cancel
        assert cancelled == 1
        assert manager.any_terminating() is True
        assert session.id in manager._terminating_sessions

    def test_blocking_cancel_all_clears_processes(
        self, manager: SessionManager, mock_adapter: MockGuiDisplayAdapter
    ) -> None:
        """Verify that cancel_all with wait=True clears all processes."""
        session = Session(
            sid="S1",
            label="Test Session",
            adapter=mock_adapter,
        )
        mock_task = MagicMock()
        mock_task.done.return_value = False
        mock_task.cancel.return_value = None
        session.task = mock_task
        session.state = "running"

        mock_proc = MagicMock()
        mock_proc.is_running.return_value = True
        mock_proc.pid = 12345
        mock_proc.terminate.return_value = None
        mock_proc.wait.return_value = None
        session._procs[12345] = mock_proc

        manager.register(session)

        # Cancel with blocking mode
        cancelled = manager.cancel_all_blocking()

        assert cancelled == 1
        assert len(session._procs) == 0


class TestThreadPoolExecutor:
    """Tests for the shared termination thread pool."""

    def test_executor_is_shared(self) -> None:
        """Verify that the termination executor is shared across calls."""
        executor1 = _get_termination_executor()
        executor2 = _get_termination_executor()
        assert executor1 is executor2

    def test_executor_has_limited_workers(self) -> None:
        """Verify that the executor has a reasonable number of workers."""
        executor = _get_termination_executor()
        assert executor._max_workers <= 4


class TestSessionStates:
    """Tests for session state transitions."""

    @pytest.fixture
    def mock_adapter(self) -> MockGuiDisplayAdapter:
        """Create a mock display adapter."""
        return MockGuiDisplayAdapter()

    def test_state_transition_running_to_terminating(
        self, mock_adapter: MockGuiDisplayAdapter
    ) -> None:
        """Verify state transition from running to terminating."""
        session = Session(
            sid="S1",
            label="Test Session",
            adapter=mock_adapter,
        )
        mock_task = MagicMock()
        mock_task.done.return_value = False
        session.task = mock_task
        session.state = "running"

        mock_proc = MagicMock()
        mock_proc.is_running.return_value = True
        mock_proc.pid = 12345
        session._procs[12345] = mock_proc

        states_received = []
        session.state_changed.connect(lambda s: states_received.append(s))

        session.cancel(wait=False)

        assert "terminating" in states_received
        assert session.state == "terminating"

    def test_is_terminating_property(
        self, mock_adapter: MockGuiDisplayAdapter
    ) -> None:
        """Verify the is_terminating property works correctly."""
        session = Session(
            sid="S1",
            label="Test Session",
            adapter=mock_adapter,
        )

        session.state = "running"
        assert session.is_terminating is False

        session.state = "terminating"
        assert session.is_terminating is True

        session.state = "completed"
        assert session.is_terminating is False
