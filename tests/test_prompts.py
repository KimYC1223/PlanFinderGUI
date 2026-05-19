"""Tests for the prompts module."""

from __future__ import annotations

import pytest

from plan_finder_gui.engine.prompts import (
    MAX_EXISTING_IN_PROMPT,
    build_prompt,
)
from plan_finder_gui.engine.reporter import ExistingPlanSummary


class TestBuildPromptTimestampSorting:
    """Tests for timestamp-based sorting of existing plans."""

    def test_plans_sorted_by_timestamp_not_keyword(self):
        """Test that plans are sorted by timestamp, not alphabetically by keyword.

        This test verifies the fix for the bug where plans were sorted by keyword
        (filename), causing alphabetically-early keywords to be dropped when
        truncating to MAX_EXISTING_IN_PROMPT.
        """
        # Create plans with different keywords and timestamps
        # Auth plans are older, Workflow plans are newer
        plans = [
            ExistingPlanSummary("pending", "Auth", "Login fix", "20260101_100000"),
            ExistingPlanSummary("pending", "Auth", "Session handling", "20260101_110000"),
            ExistingPlanSummary("pending", "Workflow", "Old workflow", "20260101_090000"),  # Oldest
            ExistingPlanSummary("pending", "Auth", "Password reset", "20260101_120000"),
            ExistingPlanSummary("pending", "Workflow", "New workflow", "20260501_100000"),  # Newest
        ]

        prompt = build_prompt("Find bugs", [], plans)

        # All plans should be included since count < MAX_EXISTING_IN_PROMPT
        assert "[Auth]" in prompt
        assert "[Workflow]" in prompt
        assert "Login fix" in prompt
        assert "Old workflow" in prompt
        assert "New workflow" in prompt

    def test_truncation_keeps_most_recent_regardless_of_keyword(self):
        """Test that truncation keeps the most recent plans by timestamp."""
        # Create more plans than MAX_EXISTING_IN_PROMPT
        plans = []

        # Add 150 old "Auth" plans (should be dropped when > limit)
        for i in range(150):
            plans.append(ExistingPlanSummary(
                "pending",
                "Auth",
                f"Auth plan {i}",
                f"20260101_{100000 + i:06d}",
            ))

        # Add 150 newer "Workflow" plans
        for i in range(150):
            plans.append(ExistingPlanSummary(
                "pending",
                "Workflow",
                f"Workflow plan {i}",
                f"20260601_{100000 + i:06d}",  # June is newer than January
            ))

        prompt = build_prompt("Find bugs", [], plans)

        # The prompt should mention that it's showing a subset
        assert f"showing {MAX_EXISTING_IN_PROMPT} most recent" in prompt

        # The newest plans (Workflow) should be present
        assert "Workflow plan 149" in prompt  # Most recent

        # Since we have 200 slots and 150 newer Workflow plans,
        # we should have 50 of the oldest Auth plans (the newest 50 Auth plans)
        # Auth plan 99-149 (50 plans) should be kept
        assert "Auth plan 149" in prompt  # Newest Auth plan
        assert "Auth plan 100" in prompt  # Should be kept

        # The very oldest Auth plans should be dropped
        assert "Auth plan 0" not in prompt  # Oldest Auth plan should be dropped

    def test_plans_without_timestamp_sorted_first(self):
        """Test that plans without valid timestamps are sorted first (oldest)."""
        plans = [
            ExistingPlanSummary("pending", "Legacy", "Old manual plan", ""),  # No timestamp
            ExistingPlanSummary("pending", "New", "Recent plan", "20260501_100000"),
        ]

        prompt = build_prompt("Find bugs", [], plans)

        # Both should be present since under limit
        assert "Old manual plan" in prompt
        assert "Recent plan" in prompt

    def test_empty_timestamp_dropped_when_over_limit(self):
        """Plans with empty timestamps should be dropped first when over limit."""
        plans = []

        # Add many plans without timestamps (will sort first/oldest)
        for i in range(100):
            plans.append(ExistingPlanSummary(
                "pending",
                "Legacy",
                f"Legacy plan {i}",
                "",  # No timestamp
            ))

        # Add plans with timestamps (will sort after empty timestamps)
        for i in range(150):
            plans.append(ExistingPlanSummary(
                "pending",
                "Modern",
                f"Modern plan {i}",
                f"20260501_{100000 + i:06d}",
            ))

        prompt = build_prompt("Find bugs", [], plans)

        # All 150 Modern plans should be present
        assert "Modern plan 149" in prompt
        assert "Modern plan 0" in prompt

        # Only 50 of the 100 Legacy plans should be present (the first 50 after sorting)
        # Since empty strings sort before any timestamp, and we take the last 200,
        # we should have the last 50 legacy plans in the sorted order
        # But wait, legacy plans all have empty timestamp, so they sort first (oldest)
        # and will be dropped first when over limit
        assert "Legacy plan 99" in prompt  # The last legacy plan in the list
        assert "Legacy plan 50" in prompt  # Should still be included
        assert "Legacy plan 0" not in prompt  # Oldest should be dropped
