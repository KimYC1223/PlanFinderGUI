"""Tests for SettingsDialog safe type conversion helpers."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


class TestSafeTypeConversion:
    """Tests for _safe_int and _safe_float helper functions."""

    def test_safe_int_with_valid_int(self):
        """Test _safe_int with a valid integer value."""
        from plan_finder_gui.ui.settings_dialog import _safe_int

        assert _safe_int(42, 0) == 42
        assert _safe_int(-10, 0) == -10
        assert _safe_int(0, 100) == 0

    def test_safe_int_with_valid_string(self):
        """Test _safe_int with a valid numeric string."""
        from plan_finder_gui.ui.settings_dialog import _safe_int

        assert _safe_int("50", 0) == 50
        assert _safe_int("-25", 0) == -25
        assert _safe_int("0", 100) == 0

    def test_safe_int_with_invalid_string(self):
        """Test _safe_int with invalid string returns default."""
        from plan_finder_gui.ui.settings_dialog import _safe_int

        assert _safe_int("invalid", 50) == 50
        assert _safe_int("abc123", 100) == 100
        assert _safe_int("", 75) == 75
        assert _safe_int("12.5", 0) == 0  # float string not valid for int()

    def test_safe_int_with_none(self):
        """Test _safe_int with None returns default."""
        from plan_finder_gui.ui.settings_dialog import _safe_int

        assert _safe_int(None, 50) == 50

    def test_safe_int_with_float(self):
        """Test _safe_int with float truncates to int."""
        from plan_finder_gui.ui.settings_dialog import _safe_int

        assert _safe_int(42.9, 0) == 42
        assert _safe_int(10.1, 0) == 10

    def test_safe_int_with_unexpected_object(self):
        """Test _safe_int with unexpected object returns default."""
        from plan_finder_gui.ui.settings_dialog import _safe_int

        assert _safe_int([], 50) == 50
        assert _safe_int({}, 50) == 50
        assert _safe_int(object(), 50) == 50

    def test_safe_float_with_valid_float(self):
        """Test _safe_float with a valid float value."""
        from plan_finder_gui.ui.settings_dialog import _safe_float

        assert _safe_float(3.14, 0.0) == 3.14
        assert _safe_float(-2.5, 0.0) == -2.5
        assert _safe_float(0.0, 100.0) == 0.0

    def test_safe_float_with_valid_int(self):
        """Test _safe_float with a valid integer value."""
        from plan_finder_gui.ui.settings_dialog import _safe_float

        assert _safe_float(42, 0.0) == 42.0
        assert _safe_float(-10, 0.0) == -10.0

    def test_safe_float_with_valid_string(self):
        """Test _safe_float with a valid numeric string."""
        from plan_finder_gui.ui.settings_dialog import _safe_float

        assert _safe_float("50.5", 0.0) == 50.5
        assert _safe_float("-25.3", 0.0) == -25.3
        assert _safe_float("0", 100.0) == 0.0
        assert _safe_float("42", 0.0) == 42.0

    def test_safe_float_with_invalid_string(self):
        """Test _safe_float with invalid string returns default."""
        from plan_finder_gui.ui.settings_dialog import _safe_float

        assert _safe_float("invalid", 50.0) == 50.0
        assert _safe_float("abc123", 100.0) == 100.0
        assert _safe_float("", 75.0) == 75.0

    def test_safe_float_with_none(self):
        """Test _safe_float with None returns default."""
        from plan_finder_gui.ui.settings_dialog import _safe_float

        assert _safe_float(None, 50.0) == 50.0

    def test_safe_float_with_unexpected_object(self):
        """Test _safe_float with unexpected object returns default."""
        from plan_finder_gui.ui.settings_dialog import _safe_float

        assert _safe_float([], 50.0) == 50.0
        assert _safe_float({}, 50.0) == 50.0
        assert _safe_float(object(), 50.0) == 50.0


class TestSettingsDialogLoad:
    """Tests for SettingsDialog._load() method with corrupted settings."""

    @pytest.fixture
    def mock_qsettings(self):
        """Create a mock QSettings that returns corrupted values."""
        mock = MagicMock()
        return mock

    def test_load_with_corrupted_volume_string(self, mock_qsettings):
        """Test that corrupted volume string falls back to default."""
        from plan_finder_gui.ui.settings_dialog import _safe_int

        # Simulate corrupted QSettings value
        mock_qsettings.value.return_value = "invalid"

        volume = _safe_int(mock_qsettings.value("sound_volume", 50), 50)

        assert volume == 50

    def test_load_with_none_volume(self, mock_qsettings):
        """Test that None volume value falls back to default."""
        from plan_finder_gui.ui.settings_dialog import _safe_int

        mock_qsettings.value.return_value = None

        volume = _safe_int(mock_qsettings.value("sound_volume", 50), 50)

        assert volume == 50

    def test_load_with_valid_volume(self, mock_qsettings):
        """Test that valid volume value is used correctly."""
        from plan_finder_gui.ui.settings_dialog import _safe_int

        mock_qsettings.value.return_value = "80"

        volume = _safe_int(mock_qsettings.value("sound_volume", 50), 50)

        assert volume == 80

    def test_load_with_volume_as_int(self, mock_qsettings):
        """Test that integer volume value is used correctly."""
        from plan_finder_gui.ui.settings_dialog import _safe_int

        mock_qsettings.value.return_value = 75

        volume = _safe_int(mock_qsettings.value("sound_volume", 50), 50)

        assert volume == 75


class TestSettingsDialogIntegration:
    """Integration tests for SettingsDialog with mocked Qt components."""

    def test_dialog_opens_with_corrupted_settings(self):
        """Test that SettingsDialog opens even when QSettings has corrupted values."""
        # Mock all Qt dependencies
        with patch("plan_finder_gui.ui.settings_dialog.QDialog"), \
             patch("plan_finder_gui.ui.settings_dialog.QSettings") as mock_settings_class, \
             patch("plan_finder_gui.ui.settings_dialog.QGroupBox"), \
             patch("plan_finder_gui.ui.settings_dialog.QVBoxLayout"), \
             patch("plan_finder_gui.ui.settings_dialog.QHBoxLayout"), \
             patch("plan_finder_gui.ui.settings_dialog.QLabel"), \
             patch("plan_finder_gui.ui.settings_dialog.QLineEdit"), \
             patch("plan_finder_gui.ui.settings_dialog.QSlider") as mock_slider_class, \
             patch("plan_finder_gui.ui.settings_dialog.QCheckBox"), \
             patch("plan_finder_gui.ui.settings_dialog.QPushButton"), \
             patch("plan_finder_gui.ui.settings_dialog.QDialogButtonBox"), \
             patch("plan_finder_gui.ui.settings_dialog.QPlainTextEdit"), \
             patch("plan_finder_gui.ui.settings_dialog.is_auto_launch_enabled", return_value=False), \
             patch("plan_finder_gui.ui.settings_dialog.sound_player"), \
             patch("plan_finder_gui.ui.settings_dialog._FROZEN", False):

            from PySide6.QtWidgets import QComboBox
            with patch.object(QComboBox, "__init__", return_value=None), \
                 patch.object(QComboBox, "addItem"), \
                 patch.object(QComboBox, "findData", return_value=0), \
                 patch.object(QComboBox, "setCurrentIndex"), \
                 patch.object(QComboBox, "currentData", return_value="ko"), \
                 patch.object(QComboBox, "setStyleSheet"):

                # Configure mock QSettings to return corrupted value for volume
                mock_settings = MagicMock()
                mock_settings.value.side_effect = lambda key, default=None: {
                    "sound_volume": "corrupted_string",  # Corrupted!
                    "claude_cli_path": "",
                    "preset_dir": "",
                    "auto_commit": False,
                    "batch_resolve": False,
                    "work_lang": "ko",
                    "commit_lang": "ko",
                    "team/my_name": "",
                    "team/members": "",
                }.get(key, default)
                mock_settings_class.return_value = mock_settings

                # Configure mock slider
                mock_slider = MagicMock()
                mock_slider_class.return_value = mock_slider

                from plan_finder_gui.ui.settings_dialog import SettingsDialog

                # This should NOT raise an exception
                try:
                    dialog = SettingsDialog.__new__(SettingsDialog)
                    dialog.setWindowTitle = MagicMock()
                    dialog.setMinimumWidth = MagicMock()
                    dialog.setStyleSheet = MagicMock()
                    dialog._build_ui = MagicMock()
                    dialog._slider = mock_slider
                    dialog._vol_pct = MagicMock()
                    dialog._autolaunch_check = MagicMock()
                    dialog._cli_path_edit = MagicMock()
                    dialog._preset_dir_edit = MagicMock()
                    dialog._auto_commit_check = MagicMock()
                    dialog._batch_resolve_check = MagicMock()
                    dialog._work_lang_combo = MagicMock()
                    dialog._work_lang_combo.findData.return_value = 0
                    dialog._my_name_edit = MagicMock()
                    dialog._team_members_edit = MagicMock()

                    # Call _load directly with corrupted settings
                    dialog._load()

                    # Verify slider was set with default value (50) not corrupted
                    mock_slider.setValue.assert_called_once_with(50)
                except (ValueError, TypeError) as e:
                    pytest.fail(f"SettingsDialog._load() raised exception with corrupted settings: {e}")
