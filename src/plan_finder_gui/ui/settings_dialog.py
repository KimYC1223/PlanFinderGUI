from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from . import sound_player


# ---------------------------------------------------------------------------
# Auto-launch helpers (platform-specific)
# ---------------------------------------------------------------------------

_PLIST_ID = "com.planfinder.gui"
_PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{_PLIST_ID}.plist"
_REG_NAME = "PlanFinderGUI"
_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_DESKTOP_PATH = Path.home() / ".config" / "autostart" / "planfinder-gui.desktop"

_FROZEN = getattr(sys, "frozen", False)


def _get_executable() -> str:
    """Return the path used in the auto-launch config."""
    if _FROZEN:
        return sys.executable
    # Dev mode: not useful, but return something deterministic
    return sys.executable


def is_auto_launch_enabled() -> bool:
    if platform.system() == "Darwin":
        return _PLIST_PATH.exists()
    if platform.system() == "Windows":
        return _win_is_enabled()
    # Linux
    return _DESKTOP_PATH.exists()


def set_auto_launch(enabled: bool) -> None:
    exe = _get_executable()
    if platform.system() == "Darwin":
        _macos_set(enabled, exe)
    elif platform.system() == "Windows":
        _win_set(enabled, exe)
    else:
        _linux_set(enabled, exe)


def _macos_set(enabled: bool, exe: str) -> None:
    import plistlib

    if enabled:
        plist: dict = {
            "Label": _PLIST_ID,
            "ProgramArguments": [exe],
            "RunAtLoad": True,
        }
        _PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_PLIST_PATH, "wb") as f:
            plistlib.dump(plist, f)
        subprocess.run(
            ["launchctl", "load", str(_PLIST_PATH)],
            capture_output=True,
        )
    else:
        if _PLIST_PATH.exists():
            subprocess.run(
                ["launchctl", "unload", str(_PLIST_PATH)],
                capture_output=True,
            )
            _PLIST_PATH.unlink(missing_ok=True)


def _win_is_enabled() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_KEY) as k:
            winreg.QueryValueEx(k, _REG_NAME)
            return True
    except Exception:
        return False


def _win_set(enabled: bool, exe: str) -> None:
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _REG_KEY, 0, winreg.KEY_SET_VALUE
        ) as k:
            if enabled:
                winreg.SetValueEx(k, _REG_NAME, 0, winreg.REG_SZ, exe)
            else:
                try:
                    winreg.DeleteValue(k, _REG_NAME)
                except FileNotFoundError:
                    pass
    except Exception:
        pass


def _linux_set(enabled: bool, exe: str) -> None:
    if enabled:
        _DESKTOP_PATH.parent.mkdir(parents=True, exist_ok=True)
        _DESKTOP_PATH.write_text(
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=Plan Finder\n"
            f"Exec={exe}\n"
            "Hidden=false\n"
            "NoDisplay=false\n"
            "X-GNOME-Autostart-enabled=true\n",
            encoding="utf-8",
        )
    else:
        _DESKTOP_PATH.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Settings dialog
# ---------------------------------------------------------------------------

_DARK = "background: #1e1e1e;"
_GROUP_SS = (
    "QGroupBox {"
    "  color: #888; font-size: 10px; font-weight: bold;"
    "  border: 1px solid #333; border-radius: 4px;"
    "  margin-top: 8px; padding-top: 4px;"
    "}"
    "QGroupBox::title { subcontrol-origin: margin; left: 8px; top: -1px; }"
)
_LABEL_SS = "color: #ccc; font-size: 12px; background: transparent;"
_DIM_SS   = "color: #888; font-size: 11px; background: transparent;"
_CHECK_SS = "QCheckBox { color: #ccc; font-size: 12px; } QCheckBox:disabled { color: #555; }"
_SLIDER_SS = (
    "QSlider::groove:horizontal {"
    "  height: 4px; background: #444; border-radius: 2px;"
    "}"
    "QSlider::handle:horizontal {"
    "  background: #0e78d5; border-radius: 6px;"
    "  width: 12px; height: 12px; margin: -4px 0;"
    "}"
    "QSlider::sub-page:horizontal {"
    "  background: #0e78d5; border-radius: 2px;"
    "}"
)


class SettingsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("환경설정")
        self.setMinimumWidth(380)
        self.setStyleSheet(
            f"QDialog {{ {_DARK} }}"
            "QLabel { background: transparent; }"
        )
        self._build_ui()
        self._load()

    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # ── 사운드 ──────────────────────────────────────────────────────
        sound_group = QGroupBox("사운드")
        sound_group.setStyleSheet(_GROUP_SS)
        sound_inner = QVBoxLayout(sound_group)
        sound_inner.setContentsMargins(8, 8, 8, 8)
        sound_inner.setSpacing(8)

        vol_row = QHBoxLayout()
        vol_row.setSpacing(8)
        vol_lbl = QLabel("효과음 볼륨")
        vol_lbl.setStyleSheet(_LABEL_SS)

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(0, 100)
        self._slider.setStyleSheet(_SLIDER_SS)

        self._vol_pct = QLabel("80%")
        self._vol_pct.setStyleSheet(_LABEL_SS)
        self._vol_pct.setFixedWidth(38)
        self._vol_pct.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        vol_row.addWidget(vol_lbl)
        vol_row.addWidget(self._slider, stretch=1)
        vol_row.addWidget(self._vol_pct)
        sound_inner.addLayout(vol_row)

        self._slider.valueChanged.connect(self._on_volume_changed)
        self._slider.sliderReleased.connect(self._preview_sound)

        layout.addWidget(sound_group)

        # ── 시스템 ──────────────────────────────────────────────────────
        sys_group = QGroupBox("시스템")
        sys_group.setStyleSheet(_GROUP_SS)
        sys_inner = QVBoxLayout(sys_group)
        sys_inner.setContentsMargins(8, 8, 8, 8)
        sys_inner.setSpacing(6)

        self._autolaunch_check = QCheckBox("컴퓨터 시작 시 자동 실행")
        self._autolaunch_check.setStyleSheet(_CHECK_SS)

        if not _FROZEN:
            self._autolaunch_check.setEnabled(False)
            self._autolaunch_check.setToolTip(
                "빌드된 앱(dist)에서만 지원됩니다."
            )
            note = QLabel("※ 빌드된 앱에서만 지원됩니다.")
            note.setStyleSheet(_DIM_SS)
            sys_inner.addWidget(self._autolaunch_check)
            sys_inner.addWidget(note)
        else:
            sys_inner.addWidget(self._autolaunch_check)

        layout.addWidget(sys_group)

        # ── 버튼 ────────────────────────────────────────────────────────
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        btns.setStyleSheet(
            "QPushButton { background: #333; color: #ccc; border-radius: 4px;"
            "  font-size: 12px; padding: 5px 18px; border: 1px solid #444; }"
            "QPushButton:hover { background: #444; }"
            "QPushButton:default { background: #0e78d5; color: white; border: none; }"
            "QPushButton:default:hover { background: #1e88e5; }"
        )
        btns.accepted.connect(self._save_and_accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    # ------------------------------------------------------------------ #

    def _load(self) -> None:
        s = QSettings()
        volume = int(s.value("sound_volume", 50))
        self._slider.setValue(volume)
        self._vol_pct.setText(f"{volume}%")
        self._autolaunch_check.setChecked(is_auto_launch_enabled())

    def _on_volume_changed(self, value: int) -> None:
        self._vol_pct.setText(f"{value}%")
        sound_player.set_volume(value / 100.0)

    def _preview_sound(self) -> None:
        sound_player.play("button.wav")

    def _save_and_accept(self) -> None:
        s = QSettings()
        s.setValue("sound_volume", self._slider.value())
        try:
            set_auto_launch(self._autolaunch_check.isChecked())
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self,
                "자동 실행 설정 실패",
                f"자동 실행 설정 중 오류가 발생했습니다:\n{e}",
            )
        self.accept()
