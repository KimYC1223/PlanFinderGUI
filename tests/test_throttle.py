"""Tests for the throttle module."""

from __future__ import annotations

import asyncio
import json
import subprocess
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from plan_finder_gui.engine.throttle import (
    CcusageNotInstalled,
    NoActiveSession,
    SessionThrottle,
    _parse_ccusage_result,
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


def _make_completed_process(stdout: str, returncode: int = 0) -> subprocess.CompletedProcess:
    """Helper to create a mock CompletedProcess for testing."""
    return subprocess.CompletedProcess(
        args=["ccusage", "blocks", "--json", "--active"],
        returncode=returncode,
        stdout=stdout,
        stderr="",
    )


class TestParseCcusageResultMalformedTimeFields:
    """Tests for _parse_ccusage_result handling of malformed time fields."""

    def test_raises_no_active_session_when_start_time_missing(self):
        """Should raise NoActiveSession when active block is missing 'startTime' key."""
        # Valid JSON with active block, but missing startTime field
        ccusage_output = json.dumps({
            "blocks": [
                {
                    "isActive": True,
                    "endTime": "2026-05-16T12:00:00Z",
                    "costUSD": 5.0,
                    "models": ["claude-3-opus"],
                }
            ]
        })
        mock_result = _make_completed_process(ccusage_output)

        with pytest.raises(NoActiveSession) as exc_info:
            _parse_ccusage_result(mock_result)

        assert "without required time field" in str(exc_info.value)
        assert "'startTime'" in str(exc_info.value)

    def test_raises_no_active_session_when_end_time_is_null(self):
        """Should raise NoActiveSession when endTime is null (None)."""
        # Valid JSON with active block, but endTime is null
        ccusage_output = json.dumps({
            "blocks": [
                {
                    "isActive": True,
                    "startTime": "2026-05-16T08:00:00Z",
                    "endTime": None,
                    "costUSD": 5.0,
                    "models": ["claude-3-opus"],
                }
            ]
        })
        mock_result = _make_completed_process(ccusage_output)

        with pytest.raises(NoActiveSession) as exc_info:
            _parse_ccusage_result(mock_result)

        assert "invalid time value" in str(exc_info.value) or "null or wrong type" in str(exc_info.value)

    def test_raises_no_active_session_when_start_time_is_malformed(self):
        """Should raise NoActiveSession when startTime has malformed date string."""
        # Valid JSON with active block, but startTime is not a valid ISO format
        ccusage_output = json.dumps({
            "blocks": [
                {
                    "isActive": True,
                    "startTime": "invalid-date",
                    "endTime": "2026-05-16T12:00:00Z",
                    "costUSD": 5.0,
                    "models": ["claude-3-opus"],
                }
            ]
        })
        mock_result = _make_completed_process(ccusage_output)

        with pytest.raises(NoActiveSession) as exc_info:
            _parse_ccusage_result(mock_result)

        assert "malformed date string" in str(exc_info.value)

    def test_raises_no_active_session_when_end_time_is_malformed(self):
        """Should raise NoActiveSession when endTime has malformed date string."""
        # Valid JSON with active block, but endTime is not a valid ISO format
        ccusage_output = json.dumps({
            "blocks": [
                {
                    "isActive": True,
                    "startTime": "2026-05-16T08:00:00Z",
                    "endTime": "not-a-date-123",
                    "costUSD": 5.0,
                    "models": ["claude-3-opus"],
                }
            ]
        })
        mock_result = _make_completed_process(ccusage_output)

        with pytest.raises(NoActiveSession) as exc_info:
            _parse_ccusage_result(mock_result)

        assert "malformed date string" in str(exc_info.value)

    def test_raises_no_active_session_when_start_time_is_wrong_type(self):
        """Should raise NoActiveSession when startTime is wrong type (e.g., integer)."""
        # Valid JSON with active block, but startTime is an integer
        ccusage_output = json.dumps({
            "blocks": [
                {
                    "isActive": True,
                    "startTime": 1715846400,  # Unix timestamp instead of ISO string
                    "endTime": "2026-05-16T12:00:00Z",
                    "costUSD": 5.0,
                    "models": ["claude-3-opus"],
                }
            ]
        })
        mock_result = _make_completed_process(ccusage_output)

        with pytest.raises(NoActiveSession) as exc_info:
            _parse_ccusage_result(mock_result)

        # Should be caught by TypeError/AttributeError (int has no .replace method)
        assert "invalid time value" in str(exc_info.value) or "null or wrong type" in str(exc_info.value)


class TestParseCcusageResultCostUSDValidation:
    """Tests for _parse_ccusage_result handling of missing or malformed costUSD field."""

    def test_raises_no_active_session_when_cost_usd_missing(self):
        """Should raise NoActiveSession when active block is missing 'costUSD' key.

        This prevents silent budget tracking failures if ccusage renames the field
        (e.g., to 'cost', 'cost_usd', or 'totalCostUSD').
        """
        # Valid JSON with active block, but costUSD field is missing
        ccusage_output = json.dumps({
            "blocks": [
                {
                    "isActive": True,
                    "startTime": "2026-05-16T08:00:00Z",
                    "endTime": "2026-05-16T12:00:00Z",
                    # Missing costUSD field - simulating a renamed field
                    "cost": 5.0,  # Hypothetical renamed field
                    "models": ["claude-3-opus"],
                }
            ]
        })
        mock_result = _make_completed_process(ccusage_output)

        with pytest.raises(NoActiveSession) as exc_info:
            _parse_ccusage_result(mock_result)

        assert "without costUSD field" in str(exc_info.value)
        assert "ccusage version may be incompatible" in str(exc_info.value)

    def test_raises_no_active_session_when_cost_usd_renamed_to_total_cost(self):
        """Should raise NoActiveSession when costUSD is renamed to totalCostUSD."""
        ccusage_output = json.dumps({
            "blocks": [
                {
                    "isActive": True,
                    "startTime": "2026-05-16T08:00:00Z",
                    "endTime": "2026-05-16T12:00:00Z",
                    "totalCostUSD": 5.0,  # Hypothetical renamed field
                    "models": ["claude-3-opus"],
                }
            ]
        })
        mock_result = _make_completed_process(ccusage_output)

        with pytest.raises(NoActiveSession) as exc_info:
            _parse_ccusage_result(mock_result)

        assert "without costUSD field" in str(exc_info.value)

    def test_logs_warning_when_cost_usd_is_wrong_type(self, caplog):
        """Should log warning and fallback to 0.0 when costUSD has unexpected type."""
        import logging

        # Valid JSON with active block, but costUSD is a string instead of number
        ccusage_output = json.dumps({
            "blocks": [
                {
                    "isActive": True,
                    "startTime": "2026-05-16T08:00:00Z",
                    "endTime": "2026-05-16T12:00:00Z",
                    "costUSD": "5.00",  # String instead of number
                    "models": ["claude-3-opus"],
                }
            ]
        })
        mock_result = _make_completed_process(ccusage_output)

        with caplog.at_level(logging.WARNING):
            result = _parse_ccusage_result(mock_result)

        # Should fallback to 0.0 and log a warning
        assert result["cost_usd"] == 0.0
        assert "unexpected type" in caplog.text
        assert "str" in caplog.text

    def test_parses_cost_usd_correctly_when_valid(self):
        """Should correctly parse costUSD when it is a valid number."""
        ccusage_output = json.dumps({
            "blocks": [
                {
                    "isActive": True,
                    "startTime": "2026-05-16T08:00:00Z",
                    "endTime": "2026-05-16T12:00:00Z",
                    "costUSD": 15.75,
                    "models": ["claude-3-opus"],
                }
            ]
        })
        mock_result = _make_completed_process(ccusage_output)

        result = _parse_ccusage_result(mock_result)

        assert result["cost_usd"] == 15.75

    def test_parses_cost_usd_correctly_when_integer(self):
        """Should correctly parse costUSD when it is an integer (not float)."""
        ccusage_output = json.dumps({
            "blocks": [
                {
                    "isActive": True,
                    "startTime": "2026-05-16T08:00:00Z",
                    "endTime": "2026-05-16T12:00:00Z",
                    "costUSD": 10,  # Integer instead of float
                    "models": ["claude-3-opus"],
                }
            ]
        })
        mock_result = _make_completed_process(ccusage_output)

        result = _parse_ccusage_result(mock_result)

        assert result["cost_usd"] == 10.0
        assert isinstance(result["cost_usd"], float)
