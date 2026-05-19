"""Tests for the reporter module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from plan_finder_gui.engine.reporter import (
    ExistingPlanSummary,
    scan_existing_plans,
    save_plan,
    _parse_plan_filename,
)
from plan_finder_gui.engine.models import DiscoveredPlan, PlanCategory, EffortSize


class TestParseFilename:
    """Tests for _parse_plan_filename helper."""

    def test_standard_format(self):
        """Test parsing a standard plan filename."""
        keyword, title, timestamp_str = _parse_plan_filename("TestKeyword__20260509_143000_test-plan-title")
        assert keyword == "TestKeyword"
        assert title == "test plan title"
        assert timestamp_str == "20260509_143000"

    def test_missing_keyword(self):
        """Test parsing filename without keyword prefix."""
        keyword, title, timestamp_str = _parse_plan_filename("some-plan-name")
        assert keyword == "Unassigned"
        assert title == "some plan name"
        assert timestamp_str == ""

    def test_empty_keyword(self):
        """Test parsing filename with empty keyword."""
        keyword, title, timestamp_str = _parse_plan_filename("__20260509_143000_test-title")
        assert keyword == "Unassigned"
        assert timestamp_str == "20260509_143000"

    def test_malformed_timestamp(self):
        """Test parsing filename with malformed timestamp portion."""
        keyword, title, timestamp_str = _parse_plan_filename("Feature__incomplete")
        assert keyword == "Feature"
        assert timestamp_str == ""  # Malformed, no valid timestamp

    def test_new_format_with_microseconds(self):
        """Test parsing new format with microseconds."""
        keyword, title, timestamp_str = _parse_plan_filename(
            "TestKeyword__20260509_143000_123456_test-plan-title"
        )
        assert keyword == "TestKeyword"
        assert title == "test plan title"
        assert timestamp_str == "20260509_143000"

    def test_new_format_with_microseconds_and_collision_suffix(self):
        """Test parsing new format with microseconds and collision counter suffix."""
        keyword, title, timestamp_str = _parse_plan_filename(
            "TestKeyword__20260509_143000_123456_test-plan-title_2"
        )
        assert keyword == "TestKeyword"
        # Title includes the collision suffix as part of it
        assert "test plan title" in title
        assert timestamp_str == "20260509_143000"

    def test_old_format_backward_compatibility(self):
        """Test that old format without microseconds still parses correctly."""
        # This verifies backward compatibility with existing plan files
        keyword, title, timestamp_str = _parse_plan_filename(
            "Feature__20260101_120000_my-old-plan"
        )
        assert keyword == "Feature"
        assert title == "my old plan"
        assert timestamp_str == "20260101_120000"


class TestScanExistingPlans:
    """Tests for scan_existing_plans function."""

    @pytest.fixture
    def temp_report_dir(self, tmp_path: Path) -> Path:
        """Create a temporary report directory with plan files."""
        report_dir = tmp_path / "reports"
        report_dir.mkdir()

        # Create status directories
        (report_dir / "pending").mkdir()
        (report_dir / "working").mkdir()
        (report_dir / "reviewed").mkdir()
        (report_dir / "reject").mkdir()

        # Add some plan files
        (report_dir / "pending" / "Feature__20260509_100000_new-feature.md").write_text("# Plan")
        (report_dir / "working" / "BugFix__20260509_110000_fix-crash.md").write_text("# Plan")
        (report_dir / "reviewed" / "Refactor__20260509_120000_cleanup-code.md").write_text("# Plan")

        return report_dir

    def test_scan_finds_plans_in_all_directories(self, temp_report_dir: Path):
        """Test that scan finds plans across all status directories."""
        plans = scan_existing_plans(temp_report_dir)

        assert len(plans) == 3

        statuses = {p.status for p in plans}
        assert statuses == {"pending", "working", "reviewed"}

        keywords = {p.keyword for p in plans}
        assert keywords == {"Feature", "BugFix", "Refactor"}

        # Verify timestamp_str is populated
        for plan in plans:
            assert plan.timestamp_str != ""
            assert "_" in plan.timestamp_str  # Format: YYYYMMDD_HHMMSS

    def test_scan_handles_missing_directories(self, tmp_path: Path):
        """Test that scan handles missing status directories gracefully."""
        report_dir = tmp_path / "reports"
        report_dir.mkdir()

        # Only create pending directory
        (report_dir / "pending").mkdir()
        (report_dir / "pending" / "Test__20260509_100000_test-plan.md").write_text("# Plan")

        plans = scan_existing_plans(report_dir)

        assert len(plans) == 1
        assert plans[0].status == "pending"
        assert plans[0].keyword == "Test"

    def test_scan_skips_translated_files(self, tmp_path: Path):
        """Test that translated companion files are skipped."""
        report_dir = tmp_path / "reports"
        report_dir.mkdir()
        (report_dir / "pending").mkdir()

        # Original file and translated companion
        (report_dir / "pending" / "Test__20260509_100000_test-plan.md").write_text("# Plan")
        (report_dir / "pending" / "Test__20260509_100000_test-plan.ko.md").write_text("# Translated")

        plans = scan_existing_plans(report_dir)

        assert len(plans) == 1
        assert plans[0].keyword == "Test"

    def test_glob_permission_error_returns_partial_result(self, temp_report_dir: Path):
        """When glob() raises PermissionError, scan returns partial results.

        This test verifies the fix for the bug where OSError from glob()
        would crash the entire discovery loop. Now it should log a warning
        and continue with remaining directories.
        """
        plans_before_error = []
        original_glob = Path.glob

        def mock_glob(self, pattern):
            # Allow pending to succeed
            if "pending" in str(self):
                return original_glob(self, pattern)
            # Fail on working directory
            if "working" in str(self):
                raise PermissionError("Access denied by antivirus")
            # Allow remaining directories
            return original_glob(self, pattern)

        with patch.object(Path, "glob", mock_glob):
            plans = scan_existing_plans(temp_report_dir)

        # Should have plans from pending and reviewed, but not working
        assert len(plans) == 2
        statuses = {p.status for p in plans}
        assert "pending" in statuses
        assert "reviewed" in statuses
        assert "working" not in statuses

    def test_glob_oserror_logs_warning(self, temp_report_dir: Path, caplog):
        """Verify that OSError during glob() is logged as a warning."""
        import logging

        original_glob = Path.glob

        def mock_glob(self, pattern):
            if "pending" in str(self):
                raise OSError("Network filesystem timeout")
            return original_glob(self, pattern)

        with patch.object(Path, "glob", mock_glob):
            with caplog.at_level(logging.WARNING):
                plans = scan_existing_plans(temp_report_dir)

        # Verify warning was logged
        assert any("Failed to scan directory" in record.message for record in caplog.records)
        assert any("Network filesystem timeout" in record.message for record in caplog.records)

        # Should still have plans from other directories
        assert len(plans) == 2

    def test_all_directories_fail_returns_empty_list(self, tmp_path: Path, caplog):
        """When all directories fail to scan, return empty list instead of crashing."""
        import logging

        report_dir = tmp_path / "reports"
        report_dir.mkdir()

        # Create directories
        (report_dir / "pending").mkdir()
        (report_dir / "working").mkdir()

        def mock_glob(self, pattern):
            raise PermissionError("All directories locked")

        with patch.object(Path, "glob", mock_glob):
            with caplog.at_level(logging.WARNING):
                plans = scan_existing_plans(report_dir)

        # Should return empty list, not crash
        assert plans == []

        # Should have logged warnings for each failed directory
        warning_count = sum(
            1 for record in caplog.records
            if "Failed to scan directory" in record.message
        )
        assert warning_count == 2

    def test_parse_error_does_not_affect_other_files(self, tmp_path: Path):
        """When a single file fails to parse, other files are still processed."""
        report_dir = tmp_path / "reports"
        report_dir.mkdir()
        (report_dir / "pending").mkdir()

        # Create valid and problematic files
        (report_dir / "pending" / "Valid__20260509_100000_good-plan.md").write_text("# Plan")
        (report_dir / "pending" / "Another__20260509_110000_also-good.md").write_text("# Plan")

        # Mock _parse_plan_filename to fail on one specific file
        original_parse = _parse_plan_filename

        def mock_parse(stem):
            if "good-plan" in stem:
                raise ValueError("Simulated parse error")
            return original_parse(stem)

        with patch("plan_finder_gui.engine.reporter._parse_plan_filename", mock_parse):
            plans = scan_existing_plans(report_dir)

        # Should still get the other valid plan
        assert len(plans) == 1
        assert plans[0].keyword == "Another"


class TestSavePlan:
    """Tests for save_plan function."""

    @pytest.fixture
    def sample_plan(self) -> DiscoveredPlan:
        """Create a sample plan for testing."""
        return DiscoveredPlan(
            title="Test Plan Title",
            description="Test description",
            rationale="Test rationale",
            files_affected=["test.py"],
            implementation_steps=["Step 1", "Step 2"],
            category=PlanCategory.ENHANCEMENT,
            priority=3,
            estimated_effort=EffortSize.SMALL,
            keyword="TestKeyword",
            risks=[],
        )

    def test_filename_includes_microseconds(self, tmp_path: Path, sample_plan: DiscoveredPlan):
        """Test that saved filename includes microseconds for sub-second precision."""
        report_dir = tmp_path / "reports"
        report_dir.mkdir()

        filepath = save_plan(sample_plan, iteration=1, report_dir=report_dir)

        # Filename should match pattern: Keyword__YYYYMMDD_HHMMSS_ffffff_safe-title.md
        stem = filepath.stem
        parts = stem.split("__", 1)
        assert len(parts) == 2
        assert parts[0] == "TestKeyword"

        timestamp_parts = parts[1].split("_", 3)
        assert len(timestamp_parts) >= 4
        # parts[0] = YYYYMMDD (8 chars)
        assert len(timestamp_parts[0]) == 8 and timestamp_parts[0].isdigit()
        # parts[1] = HHMMSS (6 chars)
        assert len(timestamp_parts[1]) == 6 and timestamp_parts[1].isdigit()
        # parts[2] = microseconds (6 chars)
        assert len(timestamp_parts[2]) == 6 and timestamp_parts[2].isdigit()

    def test_collision_detection_appends_counter(self, tmp_path: Path, sample_plan: DiscoveredPlan):
        """Test that collision detection appends counter suffix when file exists."""
        report_dir = tmp_path / "reports"
        report_dir.mkdir()

        # Save first plan
        filepath1 = save_plan(sample_plan, iteration=1, report_dir=report_dir)
        assert filepath1.exists()

        # Create a collision by manually creating a file with the same name pattern
        # (In real scenario this would be extremely rare due to microseconds)
        # We mock datetime.now() to return the same timestamp
        from datetime import datetime
        from unittest.mock import patch

        fixed_time = datetime(2026, 5, 19, 12, 0, 0, 123456)

        with patch("plan_finder_gui.engine.reporter.datetime") as mock_datetime:
            mock_datetime.now.return_value = fixed_time

            # First save with fixed timestamp
            filepath_a = save_plan(sample_plan, iteration=1, report_dir=report_dir)

            # Second save with same fixed timestamp should append _2
            filepath_b = save_plan(sample_plan, iteration=1, report_dir=report_dir)

        assert filepath_a.exists()
        assert filepath_b.exists()
        assert filepath_a != filepath_b
        assert "_2.md" in filepath_b.name

    def test_collision_logs_warning(self, tmp_path: Path, sample_plan: DiscoveredPlan, caplog):
        """Test that collision detection logs a warning when file already exists."""
        import logging
        from datetime import datetime
        from unittest.mock import patch

        report_dir = tmp_path / "reports"
        report_dir.mkdir()

        fixed_time = datetime(2026, 5, 19, 12, 0, 0, 123456)

        with patch("plan_finder_gui.engine.reporter.datetime") as mock_datetime:
            mock_datetime.now.return_value = fixed_time

            with caplog.at_level(logging.WARNING):
                # First save
                save_plan(sample_plan, iteration=1, report_dir=report_dir)
                # Second save should trigger collision warning
                save_plan(sample_plan, iteration=1, report_dir=report_dir)

        assert any("collision detected" in record.message for record in caplog.records)
