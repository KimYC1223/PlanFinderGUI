"""Tests for MainWindow transactional file move operations."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch, call
from typing import Any

import pytest


class TestTransactionalMoves:
    """Tests for _execute_transactional_moves and related rollback behavior."""

    @pytest.fixture
    def mock_main_window(self, tmp_path: Path):
        """Create a MainWindow instance with mocked Qt components."""
        # Create temporary directory structure
        report_dir = tmp_path / "reports"
        pending_dir = report_dir / "pending"
        reject_dir = report_dir / "reject"
        pending_dir.mkdir(parents=True)
        reject_dir.mkdir(parents=True)

        # Mock all Qt dependencies
        with patch("plan_finder_gui.ui.main_window.QMainWindow"), \
             patch("plan_finder_gui.ui.main_window.QSettings"), \
             patch("plan_finder_gui.ui.main_window.QTimer"), \
             patch("plan_finder_gui.ui.main_window.QMenu"), \
             patch("plan_finder_gui.ui.main_window.QAction"), \
             patch("plan_finder_gui.ui.main_window.QWidget"), \
             patch("plan_finder_gui.ui.main_window.QSplitter"), \
             patch("plan_finder_gui.ui.main_window.QVBoxLayout"), \
             patch("plan_finder_gui.ui.main_window.QHBoxLayout"), \
             patch("plan_finder_gui.ui.main_window.QTabWidget"), \
             patch("plan_finder_gui.ui.main_window.QCheckBox"), \
             patch("plan_finder_gui.ui.main_window.QLabel"), \
             patch("plan_finder_gui.ui.main_window.QSystemTrayIcon"), \
             patch("plan_finder_gui.ui.main_window.QIcon"), \
             patch("plan_finder_gui.ui.main_window.SessionManager"), \
             patch("plan_finder_gui.ui.main_window.ConfigPanel"), \
             patch("plan_finder_gui.ui.main_window.LogPanel") as mock_log_panel, \
             patch("plan_finder_gui.ui.main_window.ReportBrowser") as mock_report_browser, \
             patch("plan_finder_gui.ui.main_window.SessionsPanel"), \
             patch("plan_finder_gui.ui.main_window.StatusBar"), \
             patch("plan_finder_gui.ui.main_window.ClaudeSessionPanel"):

            from plan_finder_gui.ui.main_window import MainWindow

            window = MainWindow.__new__(MainWindow)

            # Setup mock log panel
            window.log_panel = MagicMock()

            # Setup mock report browser
            window.report_browser = MagicMock()

            # Store paths for test access
            window._test_report_dir = report_dir
            window._test_pending_dir = pending_dir
            window._test_reject_dir = reject_dir

            # Mock _get_report_dir to return our temp directory
            window._get_report_dir = MagicMock(return_value=report_dir)

            yield window

    def test_execute_transactional_moves_success(self, mock_main_window, tmp_path: Path):
        """Test successful transactional move of all files."""
        from plan_finder_gui.ui.main_window import MainWindow

        window = mock_main_window
        src_dir = tmp_path / "source"
        dest_dir = tmp_path / "dest"
        src_dir.mkdir()
        dest_dir.mkdir()

        # Create test files
        file1 = src_dir / "plan1.md"
        file2 = src_dir / "plan2.md"
        file1.write_text("content1")
        file2.write_text("content2")

        moves = [
            (file1, dest_dir / "plan1.md"),
            (file2, dest_dir / "plan2.md"),
        ]

        # Bind the methods to our mock window
        window._rollback_moves = MainWindow._rollback_moves.__get__(window, MainWindow)
        window._execute_transactional_moves = MainWindow._execute_transactional_moves.__get__(
            window, MainWindow
        )

        with patch("plan_finder_gui.ui.main_window._is_translated_md", return_value=False):
            success, main_files, completed = window._execute_transactional_moves(
                moves, operation_name="test"
            )

        assert success is True
        assert len(main_files) == 2
        assert len(completed) == 2
        assert (dest_dir / "plan1.md").exists()
        assert (dest_dir / "plan2.md").exists()
        assert not file1.exists()
        assert not file2.exists()

    def test_execute_transactional_moves_rollback_on_failure(
        self, mock_main_window, tmp_path: Path
    ):
        """Test that partial failure triggers rollback of all completed moves."""
        from plan_finder_gui.ui.main_window import MainWindow

        window = mock_main_window
        src_dir = tmp_path / "source"
        dest_dir = tmp_path / "dest"
        src_dir.mkdir()
        dest_dir.mkdir()

        # Create test files
        file1 = src_dir / "plan1.md"
        file2 = src_dir / "plan2.md"
        file3 = src_dir / "plan3.md"
        file1.write_text("content1")
        file2.write_text("content2")
        file3.write_text("content3")

        moves = [
            (file1, dest_dir / "plan1.md"),
            (file2, dest_dir / "plan2.md"),
            (file3, dest_dir / "plan3.md"),
        ]

        # Bind the methods to our mock window
        window._rollback_moves = MainWindow._rollback_moves.__get__(window, MainWindow)
        window._execute_transactional_moves = MainWindow._execute_transactional_moves.__get__(
            window, MainWindow
        )

        # Track rename calls and fail on the 3rd one
        original_rename = Path.rename
        rename_call_count = 0

        def mock_rename(self: Path, target: Path) -> Path:
            nonlocal rename_call_count
            rename_call_count += 1
            if rename_call_count == 3:
                raise OSError("Permission denied")
            return original_rename(self, target)

        with patch.object(Path, "rename", mock_rename), \
             patch("plan_finder_gui.ui.main_window._is_translated_md", return_value=False), \
             patch("plan_finder_gui.engine.executor._show_error") as mock_show_error:

            success, main_files, completed = window._execute_transactional_moves(
                moves, operation_name="test"
            )

        # Should have failed
        assert success is False
        assert len(main_files) == 0
        assert len(completed) == 0

        # All source files should be back in original locations (rolled back)
        assert file1.exists(), "file1 should be rolled back to source"
        assert file2.exists(), "file2 should be rolled back to source"
        assert file3.exists(), "file3 should still be in source (never moved)"

        # Destination should be empty
        assert not (dest_dir / "plan1.md").exists()
        assert not (dest_dir / "plan2.md").exists()
        assert not (dest_dir / "plan3.md").exists()

        # Error dialog should have been shown
        mock_show_error.assert_called_once()
        call_args = mock_show_error.call_args
        assert "test" in call_args[0][0]  # operation_name in title

    def test_reject_requested_uses_transactional_moves(
        self, mock_main_window, tmp_path: Path
    ):
        """Test that _on_reject_requested uses transactional move pattern."""
        from plan_finder_gui.ui.main_window import MainWindow

        window = mock_main_window
        pending_dir = window._test_pending_dir
        reject_dir = window._test_reject_dir

        # Create test files
        file1 = pending_dir / "plan1.md"
        file2 = pending_dir / "plan2.md"
        file1.write_text("content1")
        file2.write_text("content2")

        # Bind required methods
        window._rollback_moves = MainWindow._rollback_moves.__get__(window, MainWindow)
        window._execute_transactional_moves = MainWindow._execute_transactional_moves.__get__(
            window, MainWindow
        )
        window._on_reject_requested = MainWindow._on_reject_requested.__get__(
            window, MainWindow
        )

        with patch("plan_finder_gui.ui.main_window._find_translated_helper", return_value=None), \
             patch("plan_finder_gui.ui.main_window._is_translated_md", return_value=False):

            window._on_reject_requested([str(file1), str(file2)])

        # Files should be in reject directory
        assert (reject_dir / "plan1.md").exists()
        assert (reject_dir / "plan2.md").exists()
        assert not file1.exists()
        assert not file2.exists()

        # Report browser should be refreshed
        window.report_browser.refresh.assert_called()

    def test_reject_requested_rollback_on_partial_failure(
        self, mock_main_window, tmp_path: Path
    ):
        """Test that _on_reject_requested rolls back on partial failure."""
        from plan_finder_gui.ui.main_window import MainWindow

        window = mock_main_window
        pending_dir = window._test_pending_dir
        reject_dir = window._test_reject_dir

        # Create test files
        file1 = pending_dir / "plan1.md"
        file2 = pending_dir / "plan2.md"
        file3 = pending_dir / "plan3.md"
        file1.write_text("content1")
        file2.write_text("content2")
        file3.write_text("content3")

        # Bind required methods
        window._rollback_moves = MainWindow._rollback_moves.__get__(window, MainWindow)
        window._execute_transactional_moves = MainWindow._execute_transactional_moves.__get__(
            window, MainWindow
        )
        window._on_reject_requested = MainWindow._on_reject_requested.__get__(
            window, MainWindow
        )

        # Track rename calls and fail on the 3rd one
        original_rename = Path.rename
        rename_call_count = 0

        def mock_rename(self: Path, target: Path) -> Path:
            nonlocal rename_call_count
            rename_call_count += 1
            if rename_call_count == 3:
                raise OSError("Disk full")
            return original_rename(self, target)

        with patch.object(Path, "rename", mock_rename), \
             patch("plan_finder_gui.ui.main_window._find_translated_helper", return_value=None), \
             patch("plan_finder_gui.ui.main_window._is_translated_md", return_value=False), \
             patch("plan_finder_gui.engine.executor._show_error"):

            window._on_reject_requested([str(file1), str(file2), str(file3)])

        # All files should be back in pending (rolled back)
        assert file1.exists(), "file1 should be rolled back"
        assert file2.exists(), "file2 should be rolled back"
        assert file3.exists(), "file3 should still be in pending"

        # Reject directory should be empty
        assert not (reject_dir / "plan1.md").exists()
        assert not (reject_dir / "plan2.md").exists()
        assert not (reject_dir / "plan3.md").exists()

    def test_restore_requested_uses_transactional_moves(
        self, mock_main_window, tmp_path: Path
    ):
        """Test that _on_restore_requested uses transactional move pattern."""
        from plan_finder_gui.ui.main_window import MainWindow

        window = mock_main_window
        pending_dir = window._test_pending_dir
        reject_dir = window._test_reject_dir

        # Create test files in reject directory
        file1 = reject_dir / "plan1.md"
        file2 = reject_dir / "plan2.md"
        file1.write_text("content1")
        file2.write_text("content2")

        # Bind required methods
        window._rollback_moves = MainWindow._rollback_moves.__get__(window, MainWindow)
        window._execute_transactional_moves = MainWindow._execute_transactional_moves.__get__(
            window, MainWindow
        )
        window._on_restore_requested = MainWindow._on_restore_requested.__get__(
            window, MainWindow
        )

        with patch("plan_finder_gui.ui.main_window._find_translated_helper", return_value=None), \
             patch("plan_finder_gui.ui.main_window._is_translated_md", return_value=False):

            window._on_restore_requested([str(file1), str(file2)])

        # Files should be in pending directory
        assert (pending_dir / "plan1.md").exists()
        assert (pending_dir / "plan2.md").exists()
        assert not file1.exists()
        assert not file2.exists()

        # Report browser should be refreshed
        window.report_browser.refresh.assert_called()

    def test_restore_requested_rollback_on_partial_failure(
        self, mock_main_window, tmp_path: Path
    ):
        """Test that _on_restore_requested rolls back on partial failure."""
        from plan_finder_gui.ui.main_window import MainWindow

        window = mock_main_window
        pending_dir = window._test_pending_dir
        reject_dir = window._test_reject_dir

        # Create test files in reject directory
        file1 = reject_dir / "plan1.md"
        file2 = reject_dir / "plan2.md"
        file3 = reject_dir / "plan3.md"
        file1.write_text("content1")
        file2.write_text("content2")
        file3.write_text("content3")

        # Bind required methods
        window._rollback_moves = MainWindow._rollback_moves.__get__(window, MainWindow)
        window._execute_transactional_moves = MainWindow._execute_transactional_moves.__get__(
            window, MainWindow
        )
        window._on_restore_requested = MainWindow._on_restore_requested.__get__(
            window, MainWindow
        )

        # Track rename calls and fail on the 3rd one
        original_rename = Path.rename
        rename_call_count = 0

        def mock_rename(self: Path, target: Path) -> Path:
            nonlocal rename_call_count
            rename_call_count += 1
            if rename_call_count == 3:
                raise OSError("File locked by antivirus")
            return original_rename(self, target)

        with patch.object(Path, "rename", mock_rename), \
             patch("plan_finder_gui.ui.main_window._find_translated_helper", return_value=None), \
             patch("plan_finder_gui.ui.main_window._is_translated_md", return_value=False), \
             patch("plan_finder_gui.engine.executor._show_error"):

            window._on_restore_requested([str(file1), str(file2), str(file3)])

        # All files should be back in reject (rolled back)
        assert file1.exists(), "file1 should be rolled back"
        assert file2.exists(), "file2 should be rolled back"
        assert file3.exists(), "file3 should still be in reject"

        # Pending directory should be empty
        assert not (pending_dir / "plan1.md").exists()
        assert not (pending_dir / "plan2.md").exists()
        assert not (pending_dir / "plan3.md").exists()

    def test_translation_files_included_in_transactional_move(
        self, mock_main_window, tmp_path: Path
    ):
        """Test that translation files are included in the transactional batch."""
        from plan_finder_gui.ui.main_window import MainWindow

        window = mock_main_window
        pending_dir = window._test_pending_dir
        reject_dir = window._test_reject_dir
        pending_trans_dir = pending_dir / "translated"
        reject_trans_dir = reject_dir / "translated"
        pending_trans_dir.mkdir(parents=True)

        # Create main file and translation
        main_file = pending_dir / "plan1.md"
        trans_file = pending_trans_dir / "plan1.ko.md"
        main_file.write_text("main content")
        trans_file.write_text("translated content")

        # Bind required methods
        window._rollback_moves = MainWindow._rollback_moves.__get__(window, MainWindow)
        window._execute_transactional_moves = MainWindow._execute_transactional_moves.__get__(
            window, MainWindow
        )
        window._on_reject_requested = MainWindow._on_reject_requested.__get__(
            window, MainWindow
        )

        def mock_find_translated(orig: Path) -> Path | None:
            if orig.name == "plan1.md":
                return pending_trans_dir / "plan1.ko.md"
            return None

        def mock_is_translated(path: Path) -> bool:
            return path.stem.endswith(".ko")

        with patch("plan_finder_gui.ui.main_window._find_translated_helper", mock_find_translated), \
             patch("plan_finder_gui.ui.main_window._is_translated_md", mock_is_translated):

            window._on_reject_requested([str(main_file)])

        # Both main and translation should be in reject
        assert (reject_dir / "plan1.md").exists()
        assert (reject_trans_dir / "plan1.ko.md").exists()

        # Neither should be in pending
        assert not main_file.exists()
        assert not trans_file.exists()

    def test_translation_rollback_on_main_file_failure(
        self, mock_main_window, tmp_path: Path
    ):
        """Test that if main file fails, translations already moved are rolled back."""
        from plan_finder_gui.ui.main_window import MainWindow

        window = mock_main_window
        pending_dir = window._test_pending_dir
        reject_dir = window._test_reject_dir
        pending_trans_dir = pending_dir / "translated"
        pending_trans_dir.mkdir(parents=True)

        # Create two main files with translations
        main1 = pending_dir / "plan1.md"
        trans1 = pending_trans_dir / "plan1.ko.md"
        main2 = pending_dir / "plan2.md"
        trans2 = pending_trans_dir / "plan2.ko.md"

        main1.write_text("main1")
        trans1.write_text("trans1")
        main2.write_text("main2")
        trans2.write_text("trans2")

        # Bind required methods
        window._rollback_moves = MainWindow._rollback_moves.__get__(window, MainWindow)
        window._execute_transactional_moves = MainWindow._execute_transactional_moves.__get__(
            window, MainWindow
        )
        window._on_reject_requested = MainWindow._on_reject_requested.__get__(
            window, MainWindow
        )

        def mock_find_translated(orig: Path) -> Path | None:
            if orig.name == "plan1.md":
                return pending_trans_dir / "plan1.ko.md"
            if orig.name == "plan2.md":
                return pending_trans_dir / "plan2.ko.md"
            return None

        def mock_is_translated(path: Path) -> bool:
            return path.stem.endswith(".ko")

        # Move order: main1, trans1, main2, trans2
        # Fail on main2 (3rd move) - should rollback main1 and trans1
        original_rename = Path.rename
        rename_call_count = 0

        def mock_rename(self: Path, target: Path) -> Path:
            nonlocal rename_call_count
            rename_call_count += 1
            if rename_call_count == 3:  # Fail on main2
                raise OSError("Permission denied")
            return original_rename(self, target)

        with patch.object(Path, "rename", mock_rename), \
             patch("plan_finder_gui.ui.main_window._find_translated_helper", mock_find_translated), \
             patch("plan_finder_gui.ui.main_window._is_translated_md", mock_is_translated), \
             patch("plan_finder_gui.engine.executor._show_error"):

            window._on_reject_requested([str(main1), str(main2)])

        # All files should be back in pending (including translations)
        assert main1.exists(), "main1 should be rolled back"
        assert trans1.exists(), "trans1 should be rolled back"
        assert main2.exists(), "main2 never moved"
        assert trans2.exists(), "trans2 never moved"

    def test_empty_moves_list_succeeds(self, mock_main_window, tmp_path: Path):
        """Test that empty moves list returns success without side effects."""
        from plan_finder_gui.ui.main_window import MainWindow

        window = mock_main_window

        # Bind required methods
        window._rollback_moves = MainWindow._rollback_moves.__get__(window, MainWindow)
        window._execute_transactional_moves = MainWindow._execute_transactional_moves.__get__(
            window, MainWindow
        )

        success, main_files, completed = window._execute_transactional_moves(
            [], operation_name="test"
        )

        assert success is True
        assert main_files == []
        assert completed == []


class TestRollbackMoves:
    """Tests for the _rollback_moves helper method."""

    @pytest.fixture
    def mock_main_window(self):
        """Create a minimal MainWindow mock for rollback testing."""
        with patch("plan_finder_gui.ui.main_window.QMainWindow"):
            from plan_finder_gui.ui.main_window import MainWindow

            window = MainWindow.__new__(MainWindow)
            window.log_panel = MagicMock()
            yield window

    def test_rollback_reverses_moves_in_correct_order(
        self, mock_main_window, tmp_path: Path
    ):
        """Test that rollback happens in reverse order (translation before main)."""
        from plan_finder_gui.ui.main_window import MainWindow

        window = mock_main_window
        window._rollback_moves = MainWindow._rollback_moves.__get__(window, MainWindow)

        src_dir = tmp_path / "source"
        dest_dir = tmp_path / "dest"
        src_dir.mkdir()
        dest_dir.mkdir()

        # Simulate completed moves (files now at destinations)
        dest1 = dest_dir / "plan1.md"
        dest2 = dest_dir / "plan1.ko.md"  # translation
        dest1.write_text("main")
        dest2.write_text("trans")

        src1 = src_dir / "plan1.md"
        src2 = src_dir / "plan1.ko.md"

        completed_moves = [
            (src1, dest1),  # main file moved first
            (src2, dest2),  # translation moved second
        ]

        success_count, failed = window._rollback_moves(completed_moves)

        assert success_count == 2
        assert failed == []
        # Files should be back at source
        assert src1.exists()
        assert src2.exists()
        assert not dest1.exists()
        assert not dest2.exists()

    def test_rollback_handles_already_at_source(self, mock_main_window, tmp_path: Path):
        """Test rollback handles case where file is already at original location."""
        from plan_finder_gui.ui.main_window import MainWindow

        window = mock_main_window
        window._rollback_moves = MainWindow._rollback_moves.__get__(window, MainWindow)

        src_dir = tmp_path / "source"
        src_dir.mkdir()

        # File already at source (rollback not needed)
        src = src_dir / "plan1.md"
        dest = tmp_path / "dest" / "plan1.md"
        src.write_text("content")

        completed_moves = [(src, dest)]

        success_count, failed = window._rollback_moves(completed_moves)

        assert success_count == 1
        assert failed == []
        assert src.exists()

    def test_rollback_reports_missing_files(self, mock_main_window, tmp_path: Path):
        """Test rollback reports files missing from both locations."""
        from plan_finder_gui.ui.main_window import MainWindow

        window = mock_main_window
        window._rollback_moves = MainWindow._rollback_moves.__get__(window, MainWindow)

        src = tmp_path / "source" / "plan1.md"
        dest = tmp_path / "dest" / "plan1.md"
        # Neither exists

        completed_moves = [(src, dest)]

        success_count, failed = window._rollback_moves(completed_moves)

        assert success_count == 0
        assert "plan1.md" in failed
