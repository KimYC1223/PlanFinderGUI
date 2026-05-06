from __future__ import annotations

import shutil
import subprocess
import sys
from typing import Optional

from PySide6.QtCore import Qt, QObject, QThread, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


def is_ccusage_installed() -> bool:
    return shutil.which("ccusage") is not None


def _has_command(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def available_installers() -> list[tuple[str, list[str], str]]:
    """Return [(label, command_argv, display_command)] for installers detected on this system."""
    out: list[tuple[str, list[str], str]] = []

    if sys.platform == "darwin" and _has_command("brew"):
        out.append(("Homebrew", ["brew", "install", "ccusage"], "brew install ccusage"))

    if _has_command("npm"):
        out.append((
            "npm (global)",
            ["npm", "install", "-g", "ccusage"],
            "npm install -g ccusage",
        ))

    if _has_command("bun"):
        out.append((
            "bun (global)",
            ["bun", "add", "-g", "ccusage"],
            "bun add -g ccusage",
        ))

    return out


def manual_install_hint() -> str:
    if sys.platform == "darwin":
        return (
            "Homebrew 또는 Node.js(npm)를 먼저 설치해 주세요.\n"
            "  • Homebrew: https://brew.sh\n"
            "  • Node.js:  https://nodejs.org\n\n"
            "설치 후 터미널에서:\n"
            "  brew install ccusage\n"
            "  또는\n"
            "  npm install -g ccusage"
        )
    if sys.platform == "win32":
        return (
            "Node.js(npm)를 먼저 설치해 주세요.\n"
            "  • Node.js: https://nodejs.org\n\n"
            "설치 후 PowerShell에서:\n"
            "  npm install -g ccusage"
        )
    return (
        "Node.js(npm)를 먼저 설치해 주세요.\n"
        "  • Node.js: https://nodejs.org\n\n"
        "설치 후 터미널에서:\n"
        "  npm install -g ccusage"
    )


# ────────────────────────────────────────────────────────────────────────── #
#  Background worker for running the install command                         #
# ────────────────────────────────────────────────────────────────────────── #


class _InstallWorker(QObject):
    output = Signal(str)
    finished = Signal(int)  # exit code

    def __init__(self, argv: list[str]) -> None:
        super().__init__()
        self._argv = argv

    def run(self) -> None:
        try:
            proc = subprocess.Popen(
                self._argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError as e:
            self.output.emit(f"실행 실패: {e}")
            self.finished.emit(127)
            return
        except OSError as e:
            self.output.emit(f"실행 실패: {e}")
            self.finished.emit(1)
            return

        assert proc.stdout is not None
        for line in proc.stdout:
            self.output.emit(line.rstrip())
        proc.wait()
        self.finished.emit(proc.returncode)


# ────────────────────────────────────────────────────────────────────────── #
#  Dialog                                                                     #
# ────────────────────────────────────────────────────────────────────────── #


class CcusageInstallDialog(QDialog):
    """Prompts the user to install ccusage. Returns:
      - Accepted   : install succeeded (ccusage is now available)
      - Rejected   : user closed/declined
    Provides a 'don't ask again' checkbox accessible via `dont_ask_again()`.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("ccusage 설치 안내")
        self.setModal(True)
        self.resize(560, 420)
        self._thread: QThread | None = None
        self._worker: _InstallWorker | None = None
        self._installers = available_installers()
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(10)

        intro = QLabel(
            "<b>ccusage</b>가 설치되어 있지 않습니다.\n"
            "예산 Throttle 및 Claude 세션 모니터링에 필요합니다."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        if self._installers:
            row = QHBoxLayout()
            row.addWidget(QLabel("설치 방법:"))
            self._installer_combo = QComboBox()
            for label, _argv, display in self._installers:
                self._installer_combo.addItem(f"{label}  —  {display}")
            row.addWidget(self._installer_combo, 1)
            layout.addLayout(row)
        else:
            self._installer_combo = None
            hint = QLabel(manual_install_hint())
            hint.setStyleSheet("color: #d39c2a;")
            hint.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            hint.setWordWrap(True)
            layout.addWidget(hint)

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setStyleSheet(
            "QPlainTextEdit { background: #1e1e1e; color: #ddd; font-family: monospace; }"
        )
        self._log.setPlaceholderText("설치 로그가 여기에 표시됩니다.")
        layout.addWidget(self._log, 1)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)  # indeterminate
        self._progress.hide()
        layout.addWidget(self._progress)

        self._dont_ask = QCheckBox("다시 묻지 않음")
        layout.addWidget(self._dont_ask)

        btns = QDialogButtonBox()
        self._copy_btn = QPushButton("명령어 복사")
        self._install_btn = QPushButton("자동 설치")
        self._later_btn = QPushButton("나중에")

        if not self._installers:
            self._install_btn.setEnabled(False)

        btns.addButton(self._copy_btn, QDialogButtonBox.ButtonRole.ActionRole)
        btns.addButton(self._install_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        btns.addButton(self._later_btn, QDialogButtonBox.ButtonRole.RejectRole)
        layout.addWidget(btns)

        self._copy_btn.clicked.connect(self._on_copy)
        self._install_btn.clicked.connect(self._on_install)
        self._later_btn.clicked.connect(self.reject)

    def dont_ask_again(self) -> bool:
        return self._dont_ask.isChecked()

    def _selected_command(self) -> tuple[list[str], str] | None:
        if not self._installers or self._installer_combo is None:
            return None
        idx = self._installer_combo.currentIndex()
        if idx < 0:
            return None
        _label, argv, display = self._installers[idx]
        return argv, display

    def _on_copy(self) -> None:
        sel = self._selected_command()
        if sel is None:
            return
        _argv, display = sel
        QGuiApplication.clipboard().setText(display)
        self._append(f"클립보드에 복사됨: {display}")

    def _on_install(self) -> None:
        sel = self._selected_command()
        if sel is None:
            return
        argv, display = sel

        self._install_btn.setEnabled(False)
        self._later_btn.setEnabled(False)
        self._copy_btn.setEnabled(False)
        self._progress.show()
        self._append(f"$ {display}")

        self._thread = QThread(self)
        self._worker = _InstallWorker(argv)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.output.connect(self._append)
        self._worker.finished.connect(self._on_install_finished)
        self._thread.start()

    def _on_install_finished(self, code: int) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(2000)
            self._thread = None
        self._worker = None

        self._progress.hide()

        if code == 0 and is_ccusage_installed():
            self._append("✓ 설치 완료. ccusage 사용 준비 완료.")
            QMessageBox.information(
                self, "설치 완료", "ccusage가 성공적으로 설치되었습니다."
            )
            self.accept()
            return

        self._append(f"✗ 설치 실패 (exit code: {code})")
        if code == 0 and not is_ccusage_installed():
            self._append(
                "명령은 성공했지만 PATH에서 ccusage를 찾지 못했습니다. "
                "터미널을 새로 열거나 셸 환경을 갱신해 주세요."
            )
        self._install_btn.setEnabled(True)
        self._later_btn.setEnabled(True)
        self._copy_btn.setEnabled(True)

    def _append(self, line: str) -> None:
        self._log.appendPlainText(line)

    def reject(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            QMessageBox.warning(
                self, "설치 진행 중", "설치가 진행 중입니다. 잠시만 기다려 주세요."
            )
            return
        super().reject()
