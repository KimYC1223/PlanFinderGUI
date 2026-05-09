"""Tests for the engine module."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from plan_finder_gui.engine.discovery import DiscoveryResult
from plan_finder_gui.engine.engine import run_discovery_loop
from plan_finder_gui.engine.models import (
    DiscoveredPlan,
    EffortLevel,
    PlanCategory,
)


def make_mock_plan(title: str = "Test Plan") -> DiscoveredPlan:
    """Create a mock DiscoveredPlan for testing."""
    return DiscoveredPlan(
        title=title,
        keyword="TestKeyword",
        category=PlanCategory.feature,
        priority=3,
        estimated_effort=EffortLevel.small,
        description="Test description",
        rationale="Test rationale",
        files_affected=["test.py"],
        implementation_steps=["Step 1", "Step 2"],
        risks=["Risk 1"],
        found_nothing=False,
    )


def make_discovery_result(plan: DiscoveredPlan | None = None) -> DiscoveryResult:
    """Create a mock DiscoveryResult for testing."""
    return DiscoveryResult(
        plan=plan,
        session_id="test-session-123",
        cost_usd=0.01,
        total_tokens=100,
        num_turns=1,
        model="claude-3-opus",
    )


class MockDisplayInterface:
    """Mock display interface for testing."""

    def __init__(self):
        self.logs: list[str] = []
        self.errors: list[str] = []
        self.pending_plans: list[tuple[DiscoveredPlan, Path]] = []
        self.approval_responses: list[tuple[str, str]] = []
        self._approval_index = 0

    def log(self, message: str) -> None:
        self.logs.append(message)

    def on_iteration_start(self, iteration: int) -> None:
        pass

    def on_activity(self, detail: str) -> None:
        pass

    def on_iteration_cost(self, cost: float, tokens: int, turns: int) -> None:
        pass

    async def request_approval(
        self, plan: DiscoveredPlan, iteration: int
    ) -> tuple[str, str]:
        if self._approval_index < len(self.approval_responses):
            response = self.approval_responses[self._approval_index]
            self._approval_index += 1
            return response
        return ("approve", "")

    def on_plan_approved(self, plan: DiscoveredPlan, filepath: object) -> None:
        pass

    def on_plan_rejected(self, plan: DiscoveredPlan, reason: str) -> None:
        pass

    def on_plan_pending(self, plan: DiscoveredPlan, filepath: object) -> None:
        self.pending_plans.append((plan, filepath))

    def on_no_more_plans(self) -> None:
        pass

    def on_session_finished(
        self, approved: int, rejected: int, pending: int
    ) -> None:
        pass

    def on_error(self, message: str) -> None:
        self.errors.append(message)


class TestRevisionFailurePreservesPlan:
    """Tests that verify plans are preserved when revision fails."""

    @pytest.fixture
    def temp_report_dir(self, tmp_path: Path) -> Path:
        """Create a temporary report directory."""
        report_dir = tmp_path / "reports"
        report_dir.mkdir()
        return report_dir

    @pytest.fixture
    def mock_display(self) -> MockDisplayInterface:
        """Create a mock display interface."""
        return MockDisplayInterface()

    def test_rate_limit_during_revision_saves_original_plan(
        self, temp_report_dir: Path, mock_display: MockDisplayInterface
    ):
        """When revision fails due to rate limit, original plan should be saved as pending."""
        original_plan = make_mock_plan("Original Plan")

        # First call: return original plan
        # Second call (revision): raise rate limit error
        discover_call_count = [0]

        async def mock_discover(*args, **kwargs):
            discover_call_count[0] += 1
            if discover_call_count[0] == 1:
                return make_discovery_result(original_plan)
            else:
                raise Exception("Rate limit exceeded")

        # User requests revise, then we hit rate limit
        mock_display.approval_responses = [("revise", "Please improve this")]

        async def run_test():
            with patch(
                "plan_finder_gui.engine.engine.discover_plan",
                side_effect=mock_discover,
            ), patch(
                "plan_finder_gui.engine.engine._wait_for_next_session",
                new_callable=AsyncMock,
            ), patch(
                "plan_finder_gui.engine.engine._wait_if_quiet_hours",
                new_callable=AsyncMock,
            ):
                await run_discovery_loop(
                    plan_prompt="Find improvements",
                    display=mock_display,
                    max_iterations=1,
                    report_dir=temp_report_dir,
                    auto=False,
                )

        asyncio.run(run_test())

        # Verify the original plan was saved as pending
        assert len(mock_display.pending_plans) == 1
        saved_plan, saved_path = mock_display.pending_plans[0]
        assert saved_plan.title == "Original Plan"

        # Verify log message about saving
        assert any(
            "Original plan saved as pending" in log for log in mock_display.logs
        )

        # Verify the file was actually created in pending directory
        pending_dir = temp_report_dir / "pending"
        assert pending_dir.exists()
        pending_files = list(pending_dir.glob("*.md"))
        assert len(pending_files) == 1

    def test_retriable_error_during_revision_saves_original_plan(
        self, temp_report_dir: Path, mock_display: MockDisplayInterface
    ):
        """When revision fails due to retriable error, original plan should be saved as pending."""
        original_plan = make_mock_plan("Original Plan")

        discover_call_count = [0]

        async def mock_discover(*args, **kwargs):
            discover_call_count[0] += 1
            if discover_call_count[0] == 1:
                return make_discovery_result(original_plan)
            else:
                raise Exception("Connection timeout")

        mock_display.approval_responses = [("revise", "Please improve this")]

        async def run_test():
            with patch(
                "plan_finder_gui.engine.engine.discover_plan",
                side_effect=mock_discover,
            ), patch(
                "plan_finder_gui.engine.engine._wait_for_next_session",
                new_callable=AsyncMock,
            ), patch(
                "plan_finder_gui.engine.engine._wait_if_quiet_hours",
                new_callable=AsyncMock,
            ):
                await run_discovery_loop(
                    plan_prompt="Find improvements",
                    display=mock_display,
                    max_iterations=1,
                    report_dir=temp_report_dir,
                    auto=False,
                )

        asyncio.run(run_test())

        # Verify the original plan was saved as pending
        assert len(mock_display.pending_plans) == 1
        saved_plan, _ = mock_display.pending_plans[0]
        assert saved_plan.title == "Original Plan"

    def test_revision_produces_no_plan_saves_original_plan(
        self, temp_report_dir: Path, mock_display: MockDisplayInterface
    ):
        """When revision returns no plan, original plan should be saved as pending."""
        original_plan = make_mock_plan("Original Plan")

        discover_call_count = [0]

        async def mock_discover(*args, **kwargs):
            discover_call_count[0] += 1
            if discover_call_count[0] == 1:
                return make_discovery_result(original_plan)
            else:
                # Revision returns no plan
                return make_discovery_result(None)

        mock_display.approval_responses = [("revise", "Please improve this")]

        async def run_test():
            with patch(
                "plan_finder_gui.engine.engine.discover_plan",
                side_effect=mock_discover,
            ), patch(
                "plan_finder_gui.engine.engine._wait_if_quiet_hours",
                new_callable=AsyncMock,
            ):
                await run_discovery_loop(
                    plan_prompt="Find improvements",
                    display=mock_display,
                    max_iterations=1,
                    report_dir=temp_report_dir,
                    auto=False,
                )

        asyncio.run(run_test())

        # Verify the original plan was saved as pending
        assert len(mock_display.pending_plans) == 1
        saved_plan, _ = mock_display.pending_plans[0]
        assert saved_plan.title == "Original Plan"

        # Verify error message about revision failure
        assert any("Revision failed to produce" in err for err in mock_display.errors)

        # Verify log message about saving
        assert any(
            "Original plan saved as pending" in log for log in mock_display.logs
        )

    def test_revision_produces_found_nothing_saves_original_plan(
        self, temp_report_dir: Path, mock_display: MockDisplayInterface
    ):
        """When revision returns found_nothing, original plan should be saved as pending."""
        original_plan = make_mock_plan("Original Plan")
        found_nothing_plan = make_mock_plan("Nothing Found")
        found_nothing_plan.found_nothing = True

        discover_call_count = [0]

        async def mock_discover(*args, **kwargs):
            discover_call_count[0] += 1
            if discover_call_count[0] == 1:
                return make_discovery_result(original_plan)
            else:
                return make_discovery_result(found_nothing_plan)

        mock_display.approval_responses = [("revise", "Please improve this")]

        async def run_test():
            with patch(
                "plan_finder_gui.engine.engine.discover_plan",
                side_effect=mock_discover,
            ), patch(
                "plan_finder_gui.engine.engine._wait_if_quiet_hours",
                new_callable=AsyncMock,
            ):
                await run_discovery_loop(
                    plan_prompt="Find improvements",
                    display=mock_display,
                    max_iterations=1,
                    report_dir=temp_report_dir,
                    auto=False,
                )

        asyncio.run(run_test())

        # Verify the original plan was saved as pending
        assert len(mock_display.pending_plans) == 1
        saved_plan, _ = mock_display.pending_plans[0]
        assert saved_plan.title == "Original Plan"

    def test_unexpected_error_during_revision_saves_original_plan(
        self, temp_report_dir: Path, mock_display: MockDisplayInterface
    ):
        """When revision fails with unexpected error, original plan should be saved as pending."""
        original_plan = make_mock_plan("Original Plan")

        discover_call_count = [0]

        async def mock_discover(*args, **kwargs):
            discover_call_count[0] += 1
            if discover_call_count[0] == 1:
                return make_discovery_result(original_plan)
            else:
                raise Exception("Some unexpected error")

        mock_display.approval_responses = [("revise", "Please improve this")]

        async def run_test():
            with patch(
                "plan_finder_gui.engine.engine.discover_plan",
                side_effect=mock_discover,
            ), patch(
                "plan_finder_gui.engine.engine._wait_if_quiet_hours",
                new_callable=AsyncMock,
            ):
                await run_discovery_loop(
                    plan_prompt="Find improvements",
                    display=mock_display,
                    max_iterations=1,
                    report_dir=temp_report_dir,
                    auto=False,
                )

        asyncio.run(run_test())

        # Verify the original plan was saved as pending
        assert len(mock_display.pending_plans) == 1
        saved_plan, _ = mock_display.pending_plans[0]
        assert saved_plan.title == "Original Plan"

        # Verify error message about unexpected error
        assert any("Unexpected error during revision" in err for err in mock_display.errors)

    def test_save_plan_failure_is_handled_gracefully(
        self, temp_report_dir: Path, mock_display: MockDisplayInterface
    ):
        """When saving the original plan fails, error should be logged but not crash."""
        original_plan = make_mock_plan("Original Plan")

        discover_call_count = [0]

        async def mock_discover(*args, **kwargs):
            discover_call_count[0] += 1
            if discover_call_count[0] == 1:
                return make_discovery_result(original_plan)
            else:
                raise Exception("Rate limit exceeded")

        mock_display.approval_responses = [("revise", "Please improve this")]

        def mock_save_plan(*args, **kwargs):
            raise IOError("Disk full")

        async def run_test():
            with patch(
                "plan_finder_gui.engine.engine.discover_plan",
                side_effect=mock_discover,
            ), patch(
                "plan_finder_gui.engine.engine.save_plan",
                side_effect=mock_save_plan,
            ), patch(
                "plan_finder_gui.engine.engine._wait_for_next_session",
                new_callable=AsyncMock,
            ), patch(
                "plan_finder_gui.engine.engine._wait_if_quiet_hours",
                new_callable=AsyncMock,
            ):
                # Should not raise an exception
                await run_discovery_loop(
                    plan_prompt="Find improvements",
                    display=mock_display,
                    max_iterations=1,
                    report_dir=temp_report_dir,
                    auto=False,
                )

        asyncio.run(run_test())

        # Verify error about save failure was logged
        assert any("Failed to save original plan" in err for err in mock_display.errors)


class TestValidationErrorPreservesCost:
    """Tests that verify cost data is preserved when ValidationError occurs."""

    @pytest.fixture
    def temp_report_dir(self, tmp_path: Path) -> Path:
        """Create a temporary report directory."""
        report_dir = tmp_path / "reports"
        report_dir.mkdir()
        return report_dir

    @pytest.fixture
    def mock_display(self) -> MockDisplayInterface:
        """Create a mock display interface."""
        display = MockDisplayInterface()
        display.costs: list[tuple[float, int, int]] = []
        original_on_iteration_cost = display.on_iteration_cost

        def track_cost(cost: float, tokens: int, turns: int) -> None:
            display.costs.append((cost, tokens, turns))
            original_on_iteration_cost(cost, tokens, turns)

        display.on_iteration_cost = track_cost
        return display

    def test_validation_error_in_structured_output_preserves_cost(
        self, temp_report_dir: Path, mock_display: MockDisplayInterface
    ):
        """When model_validate fails, cost should still be tracked."""
        from claude_agent_sdk import AssistantMessage, ResultMessage

        from plan_finder_gui.engine.discovery import discover_plan

        # Create mock messages that simulate the SDK returning invalid data
        mock_assistant_msg = MagicMock(spec=AssistantMessage)
        mock_assistant_msg.model = "claude-3-opus"
        mock_assistant_msg.content = []

        mock_result_msg = MagicMock(spec=ResultMessage)
        mock_result_msg.subtype = "success"
        mock_result_msg.total_cost_usd = 0.05  # Cost incurred
        mock_result_msg.session_id = "test-session-456"
        mock_result_msg.usage = {
            "input_tokens": 500,
            "output_tokens": 200,
            "cache_read_input_tokens": 100,
            "cache_creation_input_tokens": 50,
        }
        # Invalid structured output: priority=0 is outside valid range [1,5]
        mock_result_msg.structured_output = {
            "title": "Test Plan",
            "keyword": "TestKeyword",
            "category": "feature",
            "priority": 0,  # Invalid: must be 1-5
            "estimated_effort": "small",
            "description": "Test description",
            "rationale": "Test rationale",
            "files_affected": ["test.py"],
            "implementation_steps": ["Step 1"],
            "risks": [],
            "found_nothing": False,
        }

        async def mock_query(*args, **kwargs):
            yield mock_assistant_msg
            yield mock_result_msg

        async def run_test():
            with patch(
                "plan_finder_gui.engine.discovery.query",
                side_effect=mock_query,
            ), patch(
                "plan_finder_gui.engine.executor._resolve_cli_path",
                return_value=None,
            ), patch(
                "plan_finder_gui.engine.executor._resolve_anthropic_api_key",
                return_value=None,
            ):
                result = await discover_plan(
                    prompt="Find improvements",
                    cwd=str(temp_report_dir),
                )

                # Verify plan is None due to ValidationError
                assert result.plan is None

                # Verify cost data is still preserved
                assert result.cost_usd == 0.05
                assert result.total_tokens == 850  # 500 + 200 + 100 + 50
                assert result.session_id == "test-session-456"

        asyncio.run(run_test())

    def test_validation_error_cost_tracked_in_discovery_loop(
        self, temp_report_dir: Path, mock_display: MockDisplayInterface
    ):
        """When ValidationError occurs, cost should still be tracked in the discovery loop."""
        # First call: return result with plan=None (simulating ValidationError)
        # Second call: return valid found_nothing plan to end loop
        discover_call_count = [0]

        found_nothing_plan = make_mock_plan("Nothing Found")
        found_nothing_plan.found_nothing = True

        async def mock_discover(*args, **kwargs):
            discover_call_count[0] += 1
            if discover_call_count[0] == 1:
                # Simulates result after ValidationError - plan is None but cost is tracked
                return DiscoveryResult(
                    plan=None,
                    session_id="test-session",
                    cost_usd=0.03,  # Cost was incurred
                    total_tokens=300,
                    num_turns=2,
                    model="claude-3-opus",
                )
            else:
                # Return found_nothing to end the loop
                return make_discovery_result(found_nothing_plan)

        async def run_test():
            with patch(
                "plan_finder_gui.engine.engine.discover_plan",
                side_effect=mock_discover,
            ), patch(
                "plan_finder_gui.engine.engine._wait_if_quiet_hours",
                new_callable=AsyncMock,
            ):
                await run_discovery_loop(
                    plan_prompt="Find improvements",
                    display=mock_display,
                    max_iterations=5,
                    report_dir=temp_report_dir,
                    auto=True,
                )

        asyncio.run(run_test())

        # Verify cost was tracked for both iterations
        assert len(mock_display.costs) == 2

        # First iteration had the ValidationError result - cost should still be tracked
        assert mock_display.costs[0] == (0.03, 300, 2)

        # Verify "Failed to get structured output" was logged (retry behavior)
        assert any(
            "Failed to get structured output" in log for log in mock_display.logs
        )
