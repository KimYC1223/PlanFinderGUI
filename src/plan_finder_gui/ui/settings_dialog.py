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
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from . import sound_player


# ---------------------------------------------------------------------------
# Safe type conversion helpers
# ---------------------------------------------------------------------------


def _safe_int(value, default: int) -> int:
    """Safely convert a QSettings value to int, returning default on failure.

    QSettings values may be corrupted, manually edited with invalid data,
    or have unexpected types due to cross-platform serialization differences.
    This function ensures graceful degradation to a default value rather
    than crashing the application.
    """
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _safe_float(value, default: float) -> float:
    """Safely convert a QSettings value to float, returning default on failure.

    QSettings values may be corrupted, manually edited with invalid data,
    or have unexpected types due to cross-platform serialization differences.
    This function ensures graceful degradation to a default value rather
    than crashing the application.
    """
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


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
        from .api_key_widget import ApiKeyEditor

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # ── API 키 ─────────────────────────────────────────────────────
        api_group = QGroupBox("API 키")
        api_group.setStyleSheet(_GROUP_SS)
        api_inner = QVBoxLayout(api_group)
        api_inner.setContentsMargins(8, 8, 8, 8)
        api_inner.setSpacing(6)

        api_label = QLabel("PlanFinder용 API Key")
        api_label.setStyleSheet(_LABEL_SS)
        api_inner.addWidget(api_label)

        self._api_key_editor = ApiKeyEditor()
        api_inner.addWidget(self._api_key_editor)
        layout.addWidget(api_group)

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

        # ── Claude CLI ───────────────────────────────────────────────────
        cli_group = QGroupBox("Claude CLI")
        cli_group.setStyleSheet(_GROUP_SS)
        cli_inner = QVBoxLayout(cli_group)
        cli_inner.setContentsMargins(8, 8, 8, 8)
        cli_inner.setSpacing(6)

        cli_row = QHBoxLayout()
        cli_row.setSpacing(4)
        self._cli_path_edit = QLineEdit()
        self._cli_path_edit.setPlaceholderText("기본값: PATH에서 자동 탐색")
        self._cli_path_edit.setStyleSheet(
            "QLineEdit { background: #2d2d2d; color: #ccc; border: 1px solid #444;"
            "border-radius: 4px; padding: 3px 6px; font-size: 12px; }"
            "QLineEdit:focus { border-color: #0e78d5; }"
        )

        cli_browse_btn = QPushButton("…")
        cli_browse_btn.setFixedWidth(28)
        cli_browse_btn.setStyleSheet(
            "QPushButton { background: #333; color: #ccc; border-radius: 3px; }"
            "QPushButton:hover { background: #444; }"
        )
        cli_browse_btn.clicked.connect(self._browse_cli_path)
        cli_row.addWidget(self._cli_path_edit)
        cli_row.addWidget(cli_browse_btn)

        cli_note = QLabel("nvm 등으로 설치한 경우 경로를 직접 지정하세요.")
        cli_note.setStyleSheet(_DIM_SS)
        cli_note.setWordWrap(True)

        cli_inner.addLayout(cli_row)
        cli_inner.addWidget(cli_note)
        layout.addWidget(cli_group)

        # ── 프리셋 ───────────────────────────────────────────────────────
        preset_group = QGroupBox("프리셋")
        preset_group.setStyleSheet(_GROUP_SS)
        preset_inner = QVBoxLayout(preset_group)
        preset_inner.setContentsMargins(8, 8, 8, 8)
        preset_inner.setSpacing(6)

        preset_row = QHBoxLayout()
        preset_row.setSpacing(4)
        self._preset_dir_edit = QLineEdit()
        self._preset_dir_edit.setPlaceholderText("프리셋 .md 파일이 있는 디렉토리")
        self._preset_dir_edit.setStyleSheet(
            "QLineEdit { background: #2d2d2d; color: #ccc; border: 1px solid #444;"
            "border-radius: 4px; padding: 3px 6px; font-size: 12px; }"
            "QLineEdit:focus { border-color: #0e78d5; }"
        )
        preset_browse_btn = QPushButton("…")
        preset_browse_btn.setFixedWidth(28)
        preset_browse_btn.setStyleSheet(
            "QPushButton { background: #333; color: #ccc; border-radius: 3px; }"
            "QPushButton:hover { background: #444; }"
        )
        preset_browse_btn.clicked.connect(self._browse_preset_dir)
        preset_row.addWidget(self._preset_dir_edit)
        preset_row.addWidget(preset_browse_btn)

        preset_note = QLabel(
            "이 디렉토리의 .md 파일이 프롬프트 프리셋 드롭다운에 추가됩니다.\n"
            "포맷: # 제목 / ## Description / ## Tags / ## Prompt (Prompt 섹션이 없으면 파일 전체를 프롬프트로 사용)."
        )
        preset_note.setStyleSheet(_DIM_SS)
        preset_note.setWordWrap(True)

        preset_inner.addLayout(preset_row)
        preset_inner.addWidget(preset_note)
        layout.addWidget(preset_group)

        # ── Git ──────────────────────────────────────────────────────────
        git_group = QGroupBox("Git")
        git_group.setStyleSheet(_GROUP_SS)
        git_inner = QVBoxLayout(git_group)
        git_inner.setContentsMargins(8, 8, 8, 8)
        git_inner.setSpacing(8)

        self._batch_resolve_check = QCheckBox(
            "체크된 Plan들을 한 Claude 세션에서 일괄 Resolve"
        )
        self._batch_resolve_check.setStyleSheet(_CHECK_SS)
        git_inner.addWidget(self._batch_resolve_check)

        batch_note = QLabel(
            "여러 Plan을 동시에 Resolve/Restart할 때 파일마다 세션을 새로 띄우지 않고 "
            "하나의 세션에서 한꺼번에 처리합니다. 자동 커밋이 켜져 있으면 커밋도 한 번만 생성됩니다."
        )
        batch_note.setStyleSheet(_DIM_SS)
        batch_note.setWordWrap(True)
        git_inner.addWidget(batch_note)

        self._auto_commit_check = QCheckBox("Resolve Plan 완료 후 자동 커밋")
        self._auto_commit_check.setStyleSheet(_CHECK_SS)
        git_inner.addWidget(self._auto_commit_check)

        lang_row = QHBoxLayout()
        lang_row.setSpacing(8)
        lang_lbl = QLabel("작업 언어")
        lang_lbl.setStyleSheet(_LABEL_SS)

        from PySide6.QtWidgets import QComboBox
        self._work_lang_combo = QComboBox()
        self._work_lang_combo.addItem("한국어", "ko")
        self._work_lang_combo.addItem("English", "en")
        self._work_lang_combo.setStyleSheet(
            "QComboBox { background: #2d2d2d; color: #ccc; border: 1px solid #444;"
            "border-radius: 4px; padding: 2px 6px; font-size: 12px; }"
            "QComboBox::drop-down { border: none; width: 0px; }"
            "QComboBox QAbstractItemView { background: #2d2d2d; color: #ccc; }"
        )

        lang_row.addWidget(lang_lbl)
        lang_row.addWidget(self._work_lang_combo, stretch=1)
        git_inner.addLayout(lang_row)

        lang_note = QLabel("Claude가 커밋 메시지나 주석을 달 때 사용할 언어입니다.")
        lang_note.setStyleSheet(_DIM_SS)
        lang_note.setWordWrap(True)
        git_inner.addWidget(lang_note)

        layout.addWidget(git_group)

        # ── ccusage ─────────────────────────────────────────────────────
        from .ccusage_install_dialog import is_ccusage_installed

        cc_group = QGroupBox("ccusage")
        cc_group.setStyleSheet(_GROUP_SS)
        cc_inner = QVBoxLayout(cc_group)
        cc_inner.setContentsMargins(8, 8, 8, 8)
        cc_inner.setSpacing(6)

        self._cc_status = QLabel()
        self._cc_status.setStyleSheet(_LABEL_SS)
        self._cc_status.setWordWrap(True)

        cc_btn_row = QHBoxLayout()
        cc_btn_row.setSpacing(6)
        self._cc_install_btn = QPushButton("설치 안내 열기")
        self._cc_install_btn.setStyleSheet(
            "QPushButton { background: #333; color: #ccc; border-radius: 4px;"
            "  font-size: 12px; padding: 4px 10px; border: 1px solid #444; }"
            "QPushButton:hover { background: #444; }"
        )
        self._cc_install_btn.clicked.connect(self._open_ccusage_dialog)
        cc_btn_row.addWidget(self._cc_install_btn)
        cc_btn_row.addStretch(1)

        cc_inner.addWidget(self._cc_status)
        cc_inner.addLayout(cc_btn_row)
        layout.addWidget(cc_group)

        self._refresh_ccusage_status()

        # ── 팀원 ────────────────────────────────────────────────────────
        team_group = QGroupBox("팀원")
        team_group.setStyleSheet(_GROUP_SS)
        team_inner = QVBoxLayout(team_group)
        team_inner.setContentsMargins(8, 8, 8, 8)
        team_inner.setSpacing(6)

        my_row = QHBoxLayout()
        my_row.setSpacing(8)
        my_lbl = QLabel("본인 이름")
        my_lbl.setStyleSheet(_LABEL_SS)
        my_lbl.setFixedWidth(70)
        self._my_name_edit = QLineEdit()
        self._my_name_edit.setPlaceholderText("예: youngchan")
        self._my_name_edit.setStyleSheet(
            "QLineEdit { background: #2d2d2d; color: #ccc; border: 1px solid #444;"
            "border-radius: 4px; padding: 3px 6px; font-size: 12px; }"
            "QLineEdit:focus { border-color: #0e78d5; }"
        )
        my_row.addWidget(my_lbl)
        my_row.addWidget(self._my_name_edit, stretch=1)
        team_inner.addLayout(my_row)

        members_lbl = QLabel("팀원 이름 (한 줄에 한 명)")
        members_lbl.setStyleSheet(_LABEL_SS)
        team_inner.addWidget(members_lbl)

        self._team_members_edit = QPlainTextEdit()
        self._team_members_edit.setPlaceholderText("alice\nbob\ncharlie")
        self._team_members_edit.setFixedHeight(80)
        self._team_members_edit.setStyleSheet(
            "QPlainTextEdit { background: #2d2d2d; color: #ccc; border: 1px solid #444;"
            "border-radius: 4px; padding: 4px 6px; font-size: 12px; }"
            "QPlainTextEdit:focus { border-color: #0e78d5; }"
        )
        team_inner.addWidget(self._team_members_edit)

        team_warn = QLabel(
            "⚠ 팀원 목록에 본인 이름을 넣으면 안 됩니다. "
            "본인은 위 '본인 이름' 칸에만 적어주세요."
        )
        team_warn.setStyleSheet(
            "color: #ffb74d; font-size: 11px; background: transparent;"
        )
        team_warn.setWordWrap(True)
        team_inner.addWidget(team_warn)

        layout.addWidget(team_group)

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
        volume = _safe_int(s.value("sound_volume", 50), 50)
        self._slider.setValue(volume)
        self._vol_pct.setText(f"{volume}%")
        self._autolaunch_check.setChecked(is_auto_launch_enabled())
        self._cli_path_edit.setText(s.value("claude_cli_path", ""))
        self._preset_dir_edit.setText(s.value("preset_dir", ""))

        auto_commit = s.value("auto_commit", False)
        self._auto_commit_check.setChecked(auto_commit in (True, "true", "True", "1"))

        batch_resolve = s.value("batch_resolve", False)
        self._batch_resolve_check.setChecked(batch_resolve in (True, "true", "True", "1"))

        work_lang = s.value("work_lang", s.value("commit_lang", "ko")) or "ko"
        idx = self._work_lang_combo.findData(work_lang)
        if idx >= 0:
            self._work_lang_combo.setCurrentIndex(idx)

        my_name = str(s.value("team/my_name", "") or "")
        members_raw = str(s.value("team/members", "") or "")
        self._my_name_edit.setText(my_name)
        self._team_members_edit.setPlainText(members_raw)

    def _on_volume_changed(self, value: int) -> None:
        self._vol_pct.setText(f"{value}%")
        sound_player.set_volume(value / 100.0)

    def _preview_sound(self) -> None:
        sound_player.play("button.wav")

    def _refresh_ccusage_status(self) -> None:
        from .ccusage_install_dialog import is_ccusage_installed

        if is_ccusage_installed():
            self._cc_status.setText("✓ ccusage 설치됨")
            self._cc_status.setStyleSheet(
                "color: #4caf50; font-size: 12px; background: transparent;"
            )
        else:
            self._cc_status.setText("✗ ccusage 미설치 — 예산 Throttle/세션 모니터링에 필요")
            self._cc_status.setStyleSheet(
                "color: #d39c2a; font-size: 12px; background: transparent;"
            )

    def _open_ccusage_dialog(self) -> None:
        from .ccusage_install_dialog import CcusageInstallDialog

        s = QSettings()
        dlg = CcusageInstallDialog(self)
        dlg.exec()
        if dlg.dont_ask_again():
            s.setValue("ccusage/skip_install_prompt", True)
        else:
            s.setValue("ccusage/skip_install_prompt", False)
        self._refresh_ccusage_status()

    def _browse_cli_path(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Claude CLI 실행 파일 선택", self._cli_path_edit.text() or ""
        )
        if path:
            self._cli_path_edit.setText(path)

    def _browse_preset_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "프리셋 디렉토리 선택", self._preset_dir_edit.text() or ""
        )
        if path:
            self._preset_dir_edit.setText(path)

    def _save_and_accept(self) -> None:
        my_name = self._my_name_edit.text().strip()
        members = _parse_team_members(self._team_members_edit.toPlainText())

        if my_name and my_name in members:
            QMessageBox.warning(
                self,
                "팀원 이름 오류",
                f"'{my_name}'은(는) 본인 이름입니다. "
                f"팀원 목록에서 제거해 주세요.\n\n"
                f"본인은 '본인 이름' 칸에만 적어야 합니다.",
            )
            return

        s = QSettings()
        s.setValue("sound_volume", self._slider.value())
        s.setValue("claude_cli_path", self._cli_path_edit.text().strip())
        s.setValue("preset_dir", self._preset_dir_edit.text().strip())
        s.setValue("auto_commit", self._auto_commit_check.isChecked())
        s.setValue("batch_resolve", self._batch_resolve_check.isChecked())
        s.setValue("work_lang", self._work_lang_combo.currentData())
        s.setValue("team/my_name", my_name)
        s.setValue("team/members", "\n".join(members))
        try:
            set_auto_launch(self._autolaunch_check.isChecked())
        except Exception as e:
            QMessageBox.warning(
                self,
                "자동 실행 설정 실패",
                f"자동 실행 설정 중 오류가 발생했습니다:\n{e}",
            )
        self.accept()


def _parse_team_members(raw: str) -> list[str]:
    """Parse the team members textarea into a deduped, ordered list."""
    seen: set[str] = set()
    out: list[str] = []
    for line in raw.splitlines():
        name = line.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out
