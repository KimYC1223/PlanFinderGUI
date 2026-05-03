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

    with loop:
        loop.run_forever()


if __name__ == "__main__":
    main()
