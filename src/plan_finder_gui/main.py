from __future__ import annotations

import asyncio
import re
import signal
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path

import qasync
from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton, QWidget

from .ui.main_window import MainWindow


def _get_crash_log_dir() -> Path:
    """Return the crash log directory, creating it if necessary."""
    if sys.platform == "win32":
        base = Path.home() / "AppData" / "Local" / "plan_finder_gui"
    else:
        base = Path.home() / ".plan_finder_gui"
    crash_dir = base / "crash_logs"
    crash_dir.mkdir(parents=True, exist_ok=True)
    return crash_dir


def _write_crash_log(exc_info: str) -> Path | None:
    """Write crash details to a timestamped log file. Returns the path or None on failure."""
    try:
        crash_dir = _get_crash_log_dir()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = crash_dir / f"crash_{timestamp}.log"
        log_path.write_text(exc_info, encoding="utf-8")
        return log_path
    except Exception:
        return None


def _show_crash_dialog(title: str, summary: str, details: str) -> None:
    """Show a crash dialog with Copy to Clipboard functionality."""
    try:
        # Check if QApplication exists
        app = QApplication.instance()
        if app is None:
            # No Qt app yet, just print to stderr
            print(f"{title}\n{summary}\n{details}", file=sys.stderr)
            return

        box = QMessageBox()
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle(title)
        box.setText(summary)
        # Truncate details for the detailed text area if too long
        if len(details) > 10000:
            details = details[:10000] + "\n\n... (truncated, see crash log for full details)"
        box.setDetailedText(details)

        # Add Copy to Clipboard button
        copy_btn = QPushButton("Copy to Clipboard")
        box.addButton(copy_btn, QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Close)

        def _copy_to_clipboard() -> None:
            clipboard = QApplication.clipboard()
            if clipboard:
                clipboard.setText(f"{summary}\n\n{details}")

        copy_btn.clicked.connect(_copy_to_clipboard)

        box.exec()
    except Exception:
        # Fallback: if dialog fails, at least print to stderr
        print(f"{title}\n{summary}\n{details}", file=sys.stderr)


def _global_exception_handler(exc_type, exc_value, exc_tb) -> None:
    """Global exception handler for uncaught exceptions."""
    # Don't intercept KeyboardInterrupt
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return

    try:
        # Format the exception
        tb_lines = traceback.format_exception(exc_type, exc_value, exc_tb)
        exc_info = "".join(tb_lines)

        # Always log to stderr
        print(f"[UNCAUGHT EXCEPTION]\n{exc_info}", file=sys.stderr)

        # Write crash log
        log_path = _write_crash_log(exc_info)
        log_msg = f"\nCrash log saved to: {log_path}" if log_path else ""

        # Show dialog
        _show_crash_dialog(
            title="Plan Finder - Unexpected Error",
            summary=(
                f"An unexpected error occurred: {exc_type.__name__}\n\n"
                f"{exc_value}\n"
                f"{log_msg}"
            ),
            details=exc_info,
        )
    except Exception as handler_exc:
        # Guard against recursive crash - last resort fallback
        print(f"[EXCEPTION IN EXCEPTION HANDLER]: {handler_exc}", file=sys.stderr)
        sys.__excepthook__(exc_type, exc_value, exc_tb)


def _asyncio_exception_handler(loop, context) -> None:
    """Exception handler for asyncio tasks."""
    try:
        exception = context.get("exception")

        # Ignore CancelledError - it's expected during shutdown
        if exception is not None and isinstance(exception, asyncio.CancelledError):
            return

        # Format error message
        message = context.get("message", "Unhandled exception in asyncio task")
        task = context.get("task")
        task_info = f"\nTask: {task}" if task else ""

        if exception is not None:
            tb_lines = traceback.format_exception(type(exception), exception, exception.__traceback__)
            exc_info = "".join(tb_lines)
        else:
            exc_info = str(context)

        full_details = f"{message}{task_info}\n\n{exc_info}"

        # Always log to stderr
        print(f"[ASYNCIO EXCEPTION]\n{full_details}", file=sys.stderr)

        # Write crash log
        log_path = _write_crash_log(full_details)
        log_msg = f"\nCrash log saved to: {log_path}" if log_path else ""

        # Show dialog (non-fatal for asyncio - don't exit)
        _show_crash_dialog(
            title="Plan Finder - Background Task Error",
            summary=(
                f"An error occurred in a background task.\n\n"
                f"{message}{log_msg}"
            ),
            details=full_details,
        )
    except Exception as handler_exc:
        # Guard against recursive crash
        print(f"[EXCEPTION IN ASYNCIO HANDLER]: {handler_exc}", file=sys.stderr)
        loop.default_exception_handler(context)


def _suppress_windows_subprocess_consoles() -> None:
    # PyInstaller ``console=False`` build has no parent console, so any
    # console-mode child (claude.cmd, node.exe, git.exe, …) gets a fresh
    # console window. Default ``creationflags`` to ``CREATE_NO_WINDOW`` so
    # subprocesses spawned by our code, asyncio, and the Claude SDK all
    # stay hidden.
    if sys.platform != "win32":
        return
    import subprocess

    CREATE_NO_WINDOW = 0x08000000
    DETACHED_PROCESS = 0x00000008
    CREATE_NEW_CONSOLE = 0x00000010
    _CONSOLE_FLAGS = CREATE_NO_WINDOW | DETACHED_PROCESS | CREATE_NEW_CONSOLE

    _orig_init = subprocess.Popen.__init__

    def _patched_init(self, *args, **kwargs):
        flags = kwargs.get("creationflags") or 0
        if not (flags & _CONSOLE_FLAGS):
            kwargs["creationflags"] = flags | CREATE_NO_WINDOW
        return _orig_init(self, *args, **kwargs)

    subprocess.Popen.__init__ = _patched_init


class _CliVersionWorker(QObject):
    """Worker that checks the CLI version in a background thread."""

    result_ready = Signal(str, str)  # installed_version, required_version
    finished = Signal()  # always emitted when run() completes

    def __init__(self, required_version: str) -> None:
        super().__init__()
        self._required_version = required_version

    def run(self) -> None:
        try:
            self._do_check()
        finally:
            self.finished.emit()

    def _do_check(self) -> None:
        from .engine.executor import _resolve_cli_path

        cli = _resolve_cli_path() or "claude"
        try:
            result = subprocess.run(
                [cli, "-v"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            output = result.stdout.strip() or result.stderr.strip()
        except Exception:
            return

        match = re.search(r"(\d+\.\d+\.\d+)", output)
        if not match:
            return

        installed = match.group(1)
        installed_parts = [int(x) for x in installed.split(".")]
        required_parts = [int(x) for x in self._required_version.split(".")]

        if installed_parts < required_parts:
            self.result_ready.emit(installed, self._required_version)


class _CliVersionChecker(QObject):
    """Background-checks CLI version and prompts if update is needed.

    Usage:
        checker = _CliVersionChecker(parent_window, required_version="1.0.0")
        checker.start()
    """

    def __init__(self, parent: QWidget, required_version: str) -> None:
        super().__init__(parent)
        self._parent_widget = parent
        self._required_version = required_version
        self._thread: QThread | None = None
        self._worker: _CliVersionWorker | None = None

    def start(self) -> None:
        self._thread = QThread(self)
        self._worker = _CliVersionWorker(self._required_version)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.result_ready.connect(self._on_version_mismatch)
        self._worker.finished.connect(self._cleanup)
        self._thread.start()

    def _cleanup(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(2000)
            self._thread = None
        self._worker = None

    def _on_version_mismatch(self, installed: str, required: str) -> None:
        box = QMessageBox(self._parent_widget)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Claude CLI 버전 업데이트 필요")
        box.setText(
            f"설치된 Claude CLI 버전이 너무 낮습니다.\n\n"
            f"현재: {installed}\n"
            f"필요: {required} 이상\n\n"
            "일부 기능이 정상 동작하지 않을 수 있습니다.\n"
            "터미널에서 아래 명령어로 업데이트하세요:\n\n"
            "npm update -g @anthropic-ai/claude-code"
        )
        box.exec()


def main() -> None:
    _suppress_windows_subprocess_consoles()

    # Install global exception handler early, before any Qt/asyncio setup
    sys.excepthook = _global_exception_handler

    # macOS .app bundles launched from Finder/Dock don't inherit the shell
    # PATH, so /opt/homebrew/bin and nvm-managed Node bins are missing. Pull
    # them in before any subprocess (ccusage, claude, npm, brew) is spawned.
    from .path_bootstrap import ensure_user_path
    ensure_user_path()

    # Windows requires SelectorEventLoop for asyncio + subprocesses
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    app = QApplication(sys.argv)
    app.setApplicationName("Plan Finder")
    app.setOrganizationName("PlanFinderGUI")

    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    # Install asyncio exception handler for unhandled exceptions in coroutines
    loop.set_exception_handler(_asyncio_exception_handler)

    window = MainWindow()
    window.setWindowTitle("Plan Finder")
    window.resize(1200, 800)
    window.show()

    # SIGTERM (e.g. `kill`, Activity Monitor quit) → close the window normally
    # so closeEvent runs and subprocesses are cleaned up.
    signal.signal(signal.SIGTERM, lambda *_: window.close())

    from PySide6.QtCore import QSettings, QTimer
    from .ui import sound_player
    from .ui.ccusage_install_dialog import (
        CcusageInstallDialog,
        is_ccusage_installed,
    )
    from .ui.update_checker import check_for_updates

    # Restore saved volume
    _s = QSettings()
    _saved_vol = int(_s.value("sound_volume", 50))
    sound_player.set_volume(_saved_vol / 100.0)

    sound_player.play("tscrdy00.wav")

    def _maybe_prompt_ccusage_install() -> None:
        if is_ccusage_installed():
            return
        if bool(_s.value("ccusage/skip_install_prompt", False, type=bool)):
            return
        dlg = CcusageInstallDialog(window)
        dlg.exec()
        if dlg.dont_ask_again():
            _s.setValue("ccusage/skip_install_prompt", True)

    QTimer.singleShot(0, _maybe_prompt_ccusage_install)

    # Quietly check GitHub for a newer release; prompts if one is available.
    _update_checker = None

    def _check_for_updates() -> None:
        nonlocal _update_checker
        _update_checker = check_for_updates(window)

    QTimer.singleShot(1500, _check_for_updates)

    _cli_version_checker = None

    def _check_cli_version() -> None:
        nonlocal _cli_version_checker
        try:
            from claude_agent_sdk._cli_version import __cli_version__ as required_version
        except ImportError:
            return
        _cli_version_checker = _CliVersionChecker(window, required_version)
        _cli_version_checker.start()

    QTimer.singleShot(800, _check_cli_version)

    with loop:
        loop.run_forever()


if __name__ == "__main__":
    main()
