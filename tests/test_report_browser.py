"""Tests for the ReportBrowser UI component."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestUpdateButtonsRunningState:
    """Tests for button enable/disable based on _is_running flag."""

    @pytest.fixture
    def mock_report_browser(self):
        """Create a ReportBrowser instance with mocked Qt components."""
        # Mock the QApplication requirement and Qt classes
        with patch("plan_finder_gui.ui.report_browser.QWidget"), \
             patch("plan_finder_gui.ui.report_browser.QVBoxLayout"), \
             patch("plan_finder_gui.ui.report_browser.QHBoxLayout"), \
             patch("plan_finder_gui.ui.report_browser.QSplitter"), \
             patch("plan_finder_gui.ui.report_browser.QLabel"), \
             patch("plan_finder_gui.ui.report_browser.QTreeWidget"), \
             patch("plan_finder_gui.ui.report_browser.QTextBrowser"), \
             patch("plan_finder_gui.ui.report_browser._action_btn") as mock_action_btn:

            # Create mock buttons
            mock_resolve = MagicMock()
            mock_reject = MagicMock()
            mock_restart = MagicMock()
            mock_restore = MagicMock()
            mock_action_btn.side_effect = [mock_resolve, mock_reject, mock_restart, mock_restore]

            from plan_finder_gui.ui.report_browser import ReportBrowser

            browser = ReportBrowser.__new__(ReportBrowser)
            browser._is_running = False
            browser._resolve_btn = mock_resolve
            browser._reject_btn_a = mock_reject
            browser._restart_btn = mock_restart
            browser._restore_btn = mock_restore
            browser._btn_bar = MagicMock()

            yield browser

    def test_resolve_and_reject_enabled_when_not_running(self, mock_report_browser):
        """Verify Resolve and Reject buttons are enabled when no session is running."""
        browser = mock_report_browser
        browser._is_running = False
        browser._collect_checked = MagicMock(return_value={"pending": [Path("test.md")]})

        browser._update_buttons()

        # Buttons should be visible
        browser._resolve_btn.setVisible.assert_called_with(True)
        browser._reject_btn_a.setVisible.assert_called_with(True)

        # Buttons should be enabled (not disabled)
        browser._resolve_btn.setEnabled.assert_called_with(True)
        browser._reject_btn_a.setEnabled.assert_called_with(True)

        # Tooltips should be empty
        browser._resolve_btn.setToolTip.assert_called_with("")
        browser._reject_btn_a.setToolTip.assert_called_with("")

    def test_resolve_and_reject_disabled_when_running(self, mock_report_browser):
        """Verify Resolve and Reject buttons are disabled when a session is running."""
        browser = mock_report_browser
        browser._is_running = True
        browser._collect_checked = MagicMock(return_value={"pending": [Path("test.md")]})

        browser._update_buttons()

        # Buttons should be visible
        browser._resolve_btn.setVisible.assert_called_with(True)
        browser._reject_btn_a.setVisible.assert_called_with(True)

        # Buttons should be disabled
        browser._resolve_btn.setEnabled.assert_called_with(False)
        browser._reject_btn_a.setEnabled.assert_called_with(False)

        # Tooltips should explain why disabled
        browser._resolve_btn.setToolTip.assert_called_with(
            "Cannot resolve while another session is running"
        )
        browser._reject_btn_a.setToolTip.assert_called_with(
            "Cannot reject while another session is running"
        )

    def test_restart_disabled_when_running(self, mock_report_browser):
        """Verify Restart button is also disabled when a session is running."""
        browser = mock_report_browser
        browser._is_running = True
        browser._collect_checked = MagicMock(return_value={"working": [Path("test.md")]})

        browser._update_buttons()

        browser._restart_btn.setVisible.assert_called_with(True)
        browser._restart_btn.setEnabled.assert_called_with(False)

    def test_restart_enabled_when_not_running(self, mock_report_browser):
        """Verify Restart button is enabled when no session is running."""
        browser = mock_report_browser
        browser._is_running = False
        browser._collect_checked = MagicMock(return_value={"working": [Path("test.md")]})

        browser._update_buttons()

        browser._restart_btn.setVisible.assert_called_with(True)
        browser._restart_btn.setEnabled.assert_called_with(True)

    def test_set_running_updates_flag(self, mock_report_browser):
        """Verify set_running updates the _is_running flag."""
        browser = mock_report_browser
        assert browser._is_running is False

        browser.set_running = lambda running: setattr(browser, "_is_running", running)
        browser.set_running(True)
        assert browser._is_running is True

        browser.set_running(False)
        assert browser._is_running is False
