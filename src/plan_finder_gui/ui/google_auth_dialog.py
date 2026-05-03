from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


def _adc_path() -> Path:
    """Application Default Credentials file path (platform-aware)."""
    if platform.system() == "Windows":
        appdata = os.environ.get("APPDATA", "")
        return Path(appdata) / "gcloud" / "application_default_credentials.json"
    return Path.home() / ".config" / "gcloud" / "application_default_credentials.json"


class GoogleAuthDialog(QDialog):
    """Shown when gcloud Application Default Credentials are not found.

    Guides the user to run `gcloud auth application-default login` and
    verifies the ADC file exists before accepting.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Google Cloud 인증 필요")
        self.setMinimumWidth(520)
        self.setStyleSheet(
            "QDialog { background: #1e1e1e; color: #ccc; }"
            "QLabel { color: #ccc; font-size: 12px; }"
            "QPushButton { background: #333; color: #ccc; border-radius: 4px;"
            "  padding: 4px 12px; font-size: 12px; }"
            "QPushButton:hover { background: #444; }"
        )
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 20, 20, 20)

        info = QLabel(
            "Google Translate를 사용하려면 gcloud CLI 인증이 필요합니다.\n"
            "터미널에서 아래 명령을 실행한 뒤 '인증 완료' 버튼을 눌러주세요."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #aaa; font-size: 12px; line-height: 1.5;")
        layout.addWidget(info)

        # Command block
        cmd_label = QLabel("gcloud auth application-default login")
        cmd_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        cmd_label.setStyleSheet(
            "font-family: 'Menlo', 'Consolas', monospace;"
            "font-size: 13px;"
            "background: #111;"
            "color: #50fa7b;"
            "padding: 10px 14px;"
            "border-radius: 4px;"
            "border: 1px solid #333;"
        )
        layout.addWidget(cmd_label)

        # Copy + open terminal button row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        copy_btn = QPushButton("명령어 복사")
        copy_btn.clicked.connect(self._copy_command)
        btn_row.addWidget(copy_btn)

        terminal_btn = QPushButton("터미널 열기")
        terminal_btn.clicked.connect(self._open_terminal)
        btn_row.addWidget(terminal_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        # Status feedback
        self._status_label = QLabel("")
        self._status_label.setStyleSheet("font-size: 11px;")
        self._status_label.setVisible(False)
        layout.addWidget(self._status_label)

        # OK / Cancel
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        check_btn = buttons.addButton("인증 완료", QDialogButtonBox.ButtonRole.AcceptRole)
        check_btn.setStyleSheet(
            "QPushButton { background: #0e78d5; color: white; border-radius: 4px;"
            "  padding: 4px 16px; font-weight: bold; }"
            "QPushButton:hover { background: #1e88e5; }"
        )
        buttons.accepted.connect(self._on_check)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _copy_command(self) -> None:
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText("gcloud auth application-default login")
        self._set_status("클립보드에 복사됐습니다.", success=True)

    def _open_terminal(self) -> None:
        try:
            if platform.system() == "Darwin":
                subprocess.Popen(["open", "-a", "Terminal"])
            elif platform.system() == "Windows":
                subprocess.Popen(["cmd.exe"])
            else:
                for term in ("gnome-terminal", "xterm", "konsole"):
                    try:
                        subprocess.Popen([term])
                        break
                    except FileNotFoundError:
                        continue
        except Exception:
            pass

    def _on_check(self) -> None:
        if _adc_path().exists():
            self.accept()
        else:
            self._set_status(
                f"인증 파일을 찾을 수 없습니다. ({_adc_path()})\n"
                "명령을 실행한 뒤 다시 눌러주세요.",
                success=False,
            )

    def _set_status(self, msg: str, *, success: bool) -> None:
        color = "#66bb6a" if success else "#f44336"
        self._status_label.setStyleSheet(f"font-size: 11px; color: {color};")
        self._status_label.setText(msg)
        self._status_label.setVisible(True)

    # ------------------------------------------------------------------ #
    #  Static helpers (same interface as before)                           #
    # ------------------------------------------------------------------ #

    @staticmethod
    def load_saved_credentials() -> bool:
        """True if ADC credentials file exists."""
        return _adc_path().exists()

    @staticmethod
    def ensure_credentials(parent: QWidget | None = None) -> bool:
        """Return True if ADC is ready; show dialog if not."""
        if GoogleAuthDialog.load_saved_credentials():
            return True
        dlg = GoogleAuthDialog(parent)
        return dlg.exec() == QDialog.DialogCode.Accepted
