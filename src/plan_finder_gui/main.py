from __future__ import annotations

import asyncio
import sys

import qasync
from PySide6.QtWidgets import QApplication

from .ui.main_window import MainWindow


def main() -> None:
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

    from PySide6.QtCore import QSettings
    from .ui import sound_player

    # Restore saved volume
    _s = QSettings()
    _saved_vol = int(_s.value("sound_volume", 50))
    sound_player.set_volume(_saved_vol / 100.0)

    sound_player.play("tscrdy00.wav")

    with loop:
        loop.run_forever()


if __name__ == "__main__":
    main()
