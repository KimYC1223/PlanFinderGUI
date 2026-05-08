from __future__ import annotations

import asyncio
import sys

import qasync
from PySide6.QtWidgets import QApplication

from .ui.main_window import MainWindow


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


def main() -> None:
    _suppress_windows_subprocess_consoles()

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

    window = MainWindow()
    window.setWindowTitle("Plan Finder")
    window.resize(1200, 800)
    window.show()

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

    def _check_cli_version() -> None:
        import re
        import subprocess

        from .engine.executor import _resolve_cli_path

        try:
            from claude_agent_sdk._cli_version import __cli_version__ as required_version
        except ImportError:
            return

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
        required_parts = [int(x) for x in required_version.split(".")]

        if installed_parts < required_parts:
            from PySide6.QtWidgets import QMessageBox
            box = QMessageBox(window)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("Claude CLI 버전 업데이트 필요")
            box.setText(
                f"설치된 Claude CLI 버전이 너무 낮습니다.\n\n"
                f"현재: {installed}\n"
                f"필요: {required_version} 이상\n\n"
                "일부 기능이 정상 동작하지 않을 수 있습니다.\n"
                "터미널에서 아래 명령어로 업데이트하세요:\n\n"
                "npm update -g @anthropic-ai/claude-code"
            )
            box.exec()

    QTimer.singleShot(800, _check_cli_version)

    with loop:
        loop.run_forever()


if __name__ == "__main__":
    main()
