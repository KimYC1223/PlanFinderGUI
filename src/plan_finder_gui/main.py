from __future__ import annotations

import asyncio
import sys

import qasync
from PySide6.QtWidgets import QApplication

from .ui.main_window import MainWindow


def main() -> None:
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

    with loop:
        loop.run_forever()


if __name__ == "__main__":
    main()
