from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


# ---------------------------------------------------------------------------
# ADC helpers
# ---------------------------------------------------------------------------

def _adc_path() -> Path:
    """Application Default Credentials file path (platform-aware)."""
    if platform.system() == "Windows":
        appdata = os.environ.get("APPDATA", "")
        return Path(appdata) / "gcloud" / "application_default_credentials.json"
    return Path.home() / ".config" / "gcloud" / "application_default_credentials.json"


def _adc_quota_project() -> str | None:
    """Return quota_project_id from ADC file, or None if not set."""
    try:
        data = json.loads(_adc_path().read_text(encoding="utf-8"))
        return data.get("quota_project_id") or None
    except Exception:
        return None


def _is_gcloud_installed() -> bool:
    return shutil.which("gcloud") is not None


def _gcloud_install_command() -> str:
    system = platform.system()
    if system == "Darwin":
        return "brew install --cask google-cloud-sdk"
    if system == "Windows":
        return "winget install Google.CloudSDK"
    return "curl https://sdk.cloud.google.com | bash"


# ---------------------------------------------------------------------------
# Style constants
# ---------------------------------------------------------------------------

_CODE_STYLE = (
    "font-family: 'Menlo', 'Consolas', monospace;"
    "font-size: 12px; background: #111; color: #50fa7b;"
    "padding: 10px 14px; border-radius: 4px; border: 1px solid #333;"
)

_HEADING_STYLE = "color: #fff; font-weight: bold; font-size: 13px;"
_SUBHEADING_STYLE = "color: #fff; font-weight: bold; font-size: 12px; margin-top: 4px;"
_BODY_STYLE = "color: #aaa; font-size: 12px; line-height: 1.5;"
_BTN_STYLE = (
    "QPushButton { background: #333; color: #ccc; border-radius: 4px;"
    "  padding: 4px 12px; font-size: 12px; }"
    "QPushButton:hover { background: #444; }"
)


def _hr() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Sunken)
    line.setStyleSheet("color: #333; background: #333;")
    line.setFixedHeight(1)
    return line


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------

class GoogleAuthDialog(QDialog):
    """Guides the user through GCP project setup, gcloud install, and ADC login."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Google Cloud 인증 필요")
        self.setMinimumWidth(620)
        self.setMinimumHeight(620)
        self.setStyleSheet(
            "QDialog { background: #1e1e1e; color: #ccc; }"
            "QLabel { color: #ccc; font-size: 12px; }"
            f"{_BTN_STYLE}"
            "QLineEdit { background: #2d2d2d; color: #ccc; border: 1px solid #555;"
            "  border-radius: 3px; padding: 4px 8px; font-size: 12px; }"
            "QScrollArea { border: none; background: #1e1e1e; }"
        )
        self._build_ui()

    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll, stretch=1)

        inner = QWidget()
        scroll.setWidget(inner)
        layout = QVBoxLayout(inner)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 20, 20, 20)

        # ── 인트로 ──────────────────────────────────────────────────────
        intro = QLabel(
            "Google Cloud Translation API를 사용하려면 다음 단계를 차례대로 완료해야 합니다.\n"
            "이미 완료한 단계는 건너뛰셔도 됩니다."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(_BODY_STYLE)
        layout.addWidget(intro)

        # ── 0-1단계: 프로젝트 생성 ─────────────────────────────────────
        layout.addWidget(_hr())
        self._add_section_title(layout, "0-1단계. Google Cloud 프로젝트 만들기")
        self._add_body(
            layout,
            "이미 사용 중인 GCP 프로젝트가 있다면 건너뛰세요.\n"
            "1) 아래 버튼으로 Google Cloud Console 접속\n"
            "2) 상단의 프로젝트 선택 메뉴 → “새 프로젝트” 클릭\n"
            "3) 이름을 입력하고 “만들기”\n"
            "4) 만든 프로젝트의 ID를 메모해 두세요 (2단계에서 사용)",
        )
        self._add_link_row(
            layout,
            "Google Cloud Console 열기",
            "https://console.cloud.google.com/projectcreate",
        )

        # ── 0-2단계: API 활성화 ────────────────────────────────────────
        layout.addWidget(_hr())
        self._add_section_title(layout, "0-2단계. Cloud Translation API 활성화")
        self._add_body(
            layout,
            "1) 아래 버튼으로 API 라이브러리 페이지 접속\n"
            "2) 우측 상단에서 0-1단계에서 만든 프로젝트가 선택돼 있는지 확인\n"
            "3) “Cloud Translation API”를 검색해 클릭\n"
            "4) “사용” 버튼 클릭",
        )
        self._add_link_row(
            layout,
            "Translation API 라이브러리 열기",
            "https://console.cloud.google.com/apis/library/translate.googleapis.com",
        )

        # ── 0-3단계: gcloud CLI 설치 ───────────────────────────────────
        layout.addWidget(_hr())
        self._add_section_title(layout, "0-3단계. gcloud CLI 설치")

        installed = _is_gcloud_installed()
        if installed:
            installed_lbl = QLabel("✓ gcloud가 이미 설치돼 있습니다. 다음 단계로 넘어가세요.")
            installed_lbl.setStyleSheet("color: #66bb6a; font-size: 12px;")
            layout.addWidget(installed_lbl)
        else:
            warn_lbl = QLabel("✗ gcloud를 찾을 수 없습니다. 아래 명령으로 설치하세요.")
            warn_lbl.setStyleSheet("color: #f44336; font-size: 12px;")
            layout.addWidget(warn_lbl)

        system = platform.system()
        if system == "Darwin":
            self._add_body(
                layout,
                "macOS는 Homebrew로 설치하는 것이 가장 간단합니다.\n"
                "Homebrew가 없다면 https://brew.sh 에서 먼저 설치하세요.",
            )
        elif system == "Windows":
            self._add_body(
                layout,
                "Windows는 winget으로 설치하거나 공식 인스톨러를 사용하세요.\n"
                "(winget이 없는 경우 아래 다운로드 링크 사용)",
            )
        else:
            self._add_body(
                layout,
                "Linux는 공식 설치 스크립트를 사용하거나 배포판 패키지 매니저를 사용하세요.",
            )

        install_cmd = _gcloud_install_command()
        cmd_install_label = QLabel(install_cmd)
        cmd_install_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        cmd_install_label.setWordWrap(True)
        cmd_install_label.setStyleSheet(_CODE_STYLE)
        layout.addWidget(cmd_install_label)

        install_btn_row = QHBoxLayout()
        install_btn_row.setSpacing(8)
        copy_install_btn = QPushButton("설치 명령어 복사")
        copy_install_btn.clicked.connect(lambda: self._copy(install_cmd))
        install_btn_row.addWidget(copy_install_btn)

        docs_btn = QPushButton("공식 설치 가이드 열기")
        docs_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://cloud.google.com/sdk/docs/install"))
        )
        install_btn_row.addWidget(docs_btn)
        install_btn_row.addStretch()
        layout.addLayout(install_btn_row)

        # ── 1단계: ADC 로그인 ─────────────────────────────────────────
        layout.addWidget(_hr())
        self._add_section_title(layout, "1단계. Google 계정으로 로그인")
        self._add_body(
            layout,
            "터미널에서 아래 명령을 실행하면 브라우저가 열립니다.\n"
            "0-1단계에서 만든 프로젝트에 접근 권한이 있는 Google 계정으로 로그인하세요.",
        )

        cmd1 = "gcloud auth application-default login"
        cmd1_label = QLabel(cmd1)
        cmd1_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        cmd1_label.setStyleSheet(_CODE_STYLE)
        layout.addWidget(cmd1_label)

        btn_row1 = QHBoxLayout()
        btn_row1.setSpacing(8)
        copy_btn1 = QPushButton("명령어 복사")
        copy_btn1.clicked.connect(lambda: self._copy(cmd1))
        btn_row1.addWidget(copy_btn1)

        terminal_btn = QPushButton("터미널 열기")
        terminal_btn.clicked.connect(self._open_terminal)
        btn_row1.addWidget(terminal_btn)
        btn_row1.addStretch()
        layout.addLayout(btn_row1)

        # ── 2단계: quota 프로젝트 설정 ─────────────────────────────────
        layout.addWidget(_hr())
        self._add_section_title(layout, "2단계. Quota 프로젝트 설정")
        self._add_body(
            layout,
            "Translation API 호출은 과금 프로젝트(quota project)가 있어야 동작합니다.\n"
            "0-1단계에서 만든 GCP 프로젝트 ID를 입력한 뒤 명령어를 복사해 터미널에서 실행하세요.",
        )

        proj_row = QHBoxLayout()
        proj_row.setSpacing(8)
        self._project_input = QLineEdit()
        self._project_input.setPlaceholderText("GCP 프로젝트 ID (예: my-project-123456)")
        saved_project = _adc_quota_project() or ""
        if saved_project:
            self._project_input.setText(saved_project)
        self._project_input.textChanged.connect(self._update_cmd2_label)
        proj_row.addWidget(self._project_input)
        layout.addLayout(proj_row)

        self._cmd2_label = QLabel("gcloud auth application-default set-quota-project YOUR_PROJECT_ID")
        self._cmd2_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._cmd2_label.setWordWrap(True)
        self._cmd2_label.setStyleSheet(_CODE_STYLE)
        layout.addWidget(self._cmd2_label)

        btn_row2 = QHBoxLayout()
        btn_row2.setSpacing(8)
        copy_btn2 = QPushButton("명령어 복사")
        copy_btn2.clicked.connect(self._copy_cmd2)
        btn_row2.addWidget(copy_btn2)
        btn_row2.addStretch()
        layout.addLayout(btn_row2)

        if saved_project:
            self._update_cmd2_label(saved_project)

        # ── Status ──────────────────────────────────────────────────────
        layout.addWidget(_hr())
        self._status_label = QLabel("")
        self._status_label.setStyleSheet("font-size: 11px;")
        self._status_label.setWordWrap(True)
        self._status_label.setVisible(False)
        layout.addWidget(self._status_label)

        layout.addStretch()

        # ── 하단 버튼 (스크롤 밖에 고정) ─────────────────────────────
        button_bar = QWidget()
        button_bar.setStyleSheet("background: #1e1e1e; border-top: 1px solid #333;")
        bar_layout = QHBoxLayout(button_bar)
        bar_layout.setContentsMargins(20, 12, 20, 12)
        bar_layout.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        check_btn = buttons.addButton("인증 완료", QDialogButtonBox.ButtonRole.AcceptRole)
        check_btn.setStyleSheet(
            "QPushButton { background: #0e78d5; color: white; border-radius: 4px;"
            "  padding: 6px 18px; font-weight: bold; }"
            "QPushButton:hover { background: #1e88e5; }"
        )
        buttons.accepted.connect(self._on_check)
        buttons.rejected.connect(self.reject)
        bar_layout.addWidget(buttons)
        outer.addWidget(button_bar)

    # ------------------------------------------------------------------ #
    #  Section helpers                                                     #
    # ------------------------------------------------------------------ #

    def _add_section_title(self, layout: QVBoxLayout, text: str) -> None:
        lbl = QLabel(text)
        lbl.setStyleSheet(_HEADING_STYLE)
        layout.addWidget(lbl)

    def _add_body(self, layout: QVBoxLayout, text: str) -> None:
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(_BODY_STYLE)
        layout.addWidget(lbl)

    def _add_link_row(self, layout: QVBoxLayout, label: str, url: str) -> None:
        row = QHBoxLayout()
        row.setSpacing(8)
        btn = QPushButton(label)
        btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(url)))
        row.addWidget(btn)
        row.addStretch()
        layout.addLayout(row)

    # ------------------------------------------------------------------ #
    #  Behavior                                                            #
    # ------------------------------------------------------------------ #

    def _update_cmd2_label(self, project_id: str) -> None:
        pid = project_id.strip() or "YOUR_PROJECT_ID"
        self._cmd2_label.setText(
            f"gcloud auth application-default set-quota-project {pid}"
        )

    def _copy(self, text: str) -> None:
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(text)
        self._set_status("클립보드에 복사됐습니다.", success=True)

    def _copy_cmd2(self) -> None:
        pid = self._project_input.text().strip() or "YOUR_PROJECT_ID"
        self._copy(f"gcloud auth application-default set-quota-project {pid}")

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
        if not _is_gcloud_installed():
            self._set_status(
                "gcloud CLI가 아직 설치되지 않았습니다.\n"
                "0-3단계를 먼저 완료하세요.",
                success=False,
            )
            return
        if not _adc_path().exists():
            self._set_status(
                f"인증 파일을 찾을 수 없습니다. ({_adc_path()})\n"
                "1단계 명령을 실행한 뒤 다시 눌러주세요.",
                success=False,
            )
            return
        if not _adc_quota_project():
            self._set_status(
                "Quota 프로젝트가 설정되지 않았습니다.\n"
                "2단계 명령을 실행한 뒤 다시 눌러주세요.",
                success=False,
            )
            return
        self.accept()

    def _set_status(self, msg: str, *, success: bool) -> None:
        color = "#66bb6a" if success else "#f44336"
        self._status_label.setStyleSheet(f"font-size: 11px; color: {color};")
        self._status_label.setText(msg)
        self._status_label.setVisible(True)

    # ------------------------------------------------------------------ #
    #  Static helpers                                                       #
    # ------------------------------------------------------------------ #

    @staticmethod
    def load_saved_credentials() -> bool:
        """True if gcloud is installed AND ADC credentials file exists with quota project."""
        return (
            _is_gcloud_installed()
            and _adc_path().exists()
            and _adc_quota_project() is not None
        )

    @staticmethod
    def ensure_credentials(parent: QWidget | None = None) -> bool:
        """Return True if ADC is ready (with quota project); show dialog if not."""
        if GoogleAuthDialog.load_saved_credentials():
            return True
        dlg = GoogleAuthDialog(parent)
        return dlg.exec() == QDialog.DialogCode.Accepted
