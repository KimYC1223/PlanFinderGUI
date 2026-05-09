"""Tests for the throttle module."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from plan_finder_gui.engine.throttle import (
    CcusageNotInstalled,
    NoActiveSession,
    SessionThrottle,
)


def make_session_info(hours_duration: float = 5.0) -> dict:
    """Create mock session info for testing."""
    now = datetime.now()
    return {
        "session_start": now - timedelta(hours=1),
        "session_end": now + timedelta(hours=hours_duration - 1),
        "cost_usd": 1.5,
        "models": ["claude-3-opus"],
    }


class TestSessionThrottleReinitGracefulDegradation:
    """Tests for reinit() graceful degradation when ccusage becomes unavailable."""

    def test_reinit_handles_ccusage_not_installed_gracefully(self):
        """reinit() should gracefully disable throttling when CcusageNotInstalled is raised."""
        logs: list[str] = []

        def log_fn(msg: str) -> None:
            logs.append(msg)

        # Create throttle with successful initial session
        with patch(
            "plan_finder_gui.engine.throttle.detect_session",
            return_value=make_session_info(),
        ):
            throttle = SessionThrottle(session_budget=40.0, log_fn=log_fn)

        assert throttle.session_ready is True
        assert throttle.last_error is None

        # Now reinit() with ccusage becoming unavailable
        with patch(
            "plan_finder_gui.engine.throttle.detect_session",
            side_effect=CcusageNotInstalled("ccusage not found"),
        ):
            # Should NOT raise - should gracefully degrade
            throttle.reinit()

        # Verify throttle is disabled but not crashed
        assert throttle.session_ready is False
        assert throttle.last_error == "ccusage not found"
        assert any("ccusage became unavailable" in log for log in logs)

    def test_reinit_async_handles_ccusage_not_installed_gracefully(self):
        """reinit_async() should gracefully disable throttling when CcusageNotInstalled is raised."""
        logs: list[str] = []

        def log_fn(msg: str) -> None:
            logs.append(msg)

        async def run_test():
            # Create throttle with successful initial session
            with patch(
                "plan_finder_gui.engine.throttle.detect_session_async",
                return_value=make_session_info(),
            ):
                throttle = await SessionThrottle.create_async(
                    session_budget=40.0, log_fn=log_fn
                )

            assert throttle.session_ready is True
            assert throttle.last_error is None

            # Now reinit_async() with ccusage becoming unavailable
            with patch(
                "plan_finder_gui.engine.throttle.detect_session_async",
                side_effect=CcusageNotInstalled("ccusage binary deleted"),
            ):
                # Should NOT raise - should gracefully degrade
                await throttle.reinit_async()

            # Verify throttle is disabled but not crashed
            assert throttle.session_ready is False
            assert throttle.last_error == "ccusage binary deleted"
            assert any("ccusage became unavailable" in log for log in logs)

        asyncio.run(run_test())

    def test_reinit_handles_no_active_session_gracefully(self):
        """reinit() should gracefully disable throttling when NoActiveSession is raised."""
        logs: list[str] = []

        def log_fn(msg: str) -> None:
            logs.append(msg)

        # Create throttle with successful initial session
        with patch(
            "plan_finder_gui.engine.throttle.detect_session",
            return_value=make_session_info(),
        ):
            throttle = SessionThrottle(session_budget=40.0, log_fn=log_fn)

        assert throttle.session_ready is True

        # Now reinit() with no active session
        with patch(
            "plan_finder_gui.engine.throttle.detect_session",
            side_effect=NoActiveSession("Session ended"),
        ):
            throttle.reinit()

        # Verify throttle is disabled but not crashed
        assert throttle.session_ready is False
        assert throttle.last_error == "Session ended"
        assert any("No active session" in log for log in logs)

    def test_reinit_clears_last_error_on_success(self):
        """reinit() should clear last_error when session detection succeeds."""
        logs: list[str] = []

        def log_fn(msg: str) -> None:
            logs.append(msg)

        # Create throttle with initial CcusageNotInstalled
        with patch(
            "plan_finder_gui.engine.throttle.detect_session",
            side_effect=CcusageNotInstalled("ccusage not found"),
        ):
            throttle = SessionThrottle(session_budget=40.0, log_fn=log_fn)

        assert throttle.session_ready is False
        assert throttle.last_error == "ccusage not found"

        # Now reinit() with ccusage available again
        with patch(
            "plan_finder_gui.engine.throttle.detect_session",
            return_value=make_session_info(),
        ):
            throttle.reinit()

        # Verify throttle is enabled and error is cleared
        assert throttle.session_ready is True
        assert throttle.last_error is None

    def test_throttle_is_allowed_when_session_not_ready(self):
        """is_allowed() should return True when session_ready is False."""
        logs: list[str] = []

        with patch(
            "plan_finder_gui.engine.throttle.detect_session",
            side_effect=CcusageNotInstalled("ccusage not found"),
        ):
            throttle = SessionThrottle(session_budget=40.0, log_fn=logs.append)

        assert throttle.session_ready is False
        # Throttle should allow requests when disabled
        assert throttle.is_allowed() is True

    def test_status_line_indicates_disabled_state(self):
        """status_line() should indicate throttle is disabled when session_ready is False."""
        with patch(
            "plan_finder_gui.engine.throttle.detect_session",
            side_effect=CcusageNotInstalled("ccusage not found"),
        ):
            throttle = SessionThrottle(session_budget=40.0)

        status = throttle.status_line()
        assert "No active session" in status
        assert "throttle disabled" in status
