"""Tests for the reporter module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from plan_finder_gui.engine.reporter import (
    ExistingPlanSummary,
    scan_existing_plans,
    _parse_plan_filename,
)


class TestParseFilename:
    """Tests for _parse_plan_filename helper."""

    def test_standard_format(self):
        """Test parsing a standard plan filename."""
        keyword, title = _parse_plan_filename("TestKeyword__20260509_143000_test-plan-title")
        assert keyword == "TestKeyword"
        assert title == "test plan title"

    def test_missing_keyword(self):
        """Test parsing filename without keyword prefix."""
        keyword, title = _parse_plan_filename("some-plan-name")
        assert keyword == "Unassigned"
        assert title == "some plan name"

    def test_empty_keyword(self):
        """Test parsing filename with empty keyword."""
        keyword, title = _parse_plan_filename("__20260509_143000_test-title")
        assert keyword == "Unassigned"


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
