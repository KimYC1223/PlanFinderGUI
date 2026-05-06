from __future__ import annotations

import json
import re
from typing import Optional
from urllib.error import URLError
from urllib.request import Request, urlopen

from PySide6.QtCore import QObject, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox, QWidget


GITHUB_API_LATEST = "https://api.github.com/repos/KimYC1223/PlanFinderGUI/releases/latest"
RELEASES_PAGE_URL = "https://github.com/KimYC1223/PlanFinderGUI/releases"


def _parse_version(text: str) -> tuple[int, ...]:
    """Parse '1.2.3', 'v1.2.3', '1.2.3-beta.1' -> (1, 2, 3).

    Pre-release suffixes are stripped for comparison purposes.
    Non-numeric segments are skipped. Returns () on failure.
    """
    if not text:
        return ()
    m = re.match(r"v?\s*(\d+(?:\.\d+)*)", text.strip())
    if not m:
        return ()
    try:
        return tuple(int(x) for x in m.group(1).split("."))
    except ValueError:
        return ()


def is_newer(remote: str, local: str) -> bool:
    r = _parse_version(remote)
    l = _parse_version(local)
    if not r or not l:
        return False
    return r > l


class _ReleaseFetcher(QObject):
    """Fetches the latest release tag from GitHub. Runs on a worker thread."""

    found = Signal(str, str)  # tag_name, html_url
    failed = Signal(str)      # error message (for logging only)

    def run(self) -> None:
        try:
            req = Request(
                GITHUB_API_LATEST,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "PlanFinderGUI-update-check",
                },
            )
            with urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (URLError, TimeoutError, ValueError, OSError) as e:
            self.failed.emit(str(e))
            return

        tag = str(data.get("tag_name") or "").strip()
        url = str(data.get("html_url") or RELEASES_PAGE_URL).strip()
        if not tag:
            self.failed.emit("no tag_name in response")
            return
        self.found.emit(tag, url)


class UpdateChecker(QObject):
    """Background-checks GitHub for a newer release and prompts the user.

    Usage:
        checker = UpdateChecker(parent_window, current_version="0.1.0")
        checker.start()
    """

    _SKIP_KEY = "update_checker/skip_version"

    def __init__(
        self,
        parent: QWidget,
        current_version: str,
    ) -> None:
        super().__init__(parent)
        self._parent_widget = parent
        self._current = current_version
        self._thread: QThread | None = None
        self._worker: _ReleaseFetcher | None = None

    def start(self) -> None:
        self._thread = QThread(self)
        self._worker = _ReleaseFetcher()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.found.connect(self._on_found)
        self._worker.failed.connect(self._on_failed)
        self._worker.found.connect(self._cleanup)
        self._worker.failed.connect(self._cleanup)
        self._thread.start()

    def _cleanup(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(2000)
            self._thread = None
        self._worker = None

    def _on_failed(self, _msg: str) -> None:
        # Silent: network errors, rate limiting, no releases yet, etc.
        return

    def _on_found(self, tag: str, url: str) -> None:
        if not is_newer(tag, self._current):
            return

        from PySide6.QtCore import QSettings
        settings = QSettings()
        skipped = str(settings.value(self._SKIP_KEY, "") or "")
        if skipped and _parse_version(skipped) >= _parse_version(tag):
            return

        self._prompt(tag, url)

    def _prompt(self, tag: str, url: str) -> None:
        box = QMessageBox(self._parent_widget)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("업데이트 확인")
        box.setText(
            f"새 버전이 출시되었습니다.\n\n"
            f"현재 버전: {self._current}\n"
            f"최신 버전: {tag}\n\n"
            f"업데이트가 있습니다. 다운로드 받으실래요?"
        )
        download_btn = box.addButton("다운로드", QMessageBox.ButtonRole.AcceptRole)
        skip_btn = box.addButton("이 버전 건너뛰기", QMessageBox.ButtonRole.DestructiveRole)
        later_btn = box.addButton("나중에", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(download_btn)
        box.exec()

        clicked = box.clickedButton()
        if clicked is download_btn:
            QDesktopServices.openUrl(QUrl(url or RELEASES_PAGE_URL))
        elif clicked is skip_btn:
            from PySide6.QtCore import QSettings
            QSettings().setValue(self._SKIP_KEY, tag)
        # later_btn: do nothing, ask again next launch


def check_for_updates(parent: QWidget, current_version: Optional[str] = None) -> UpdateChecker:
    """Convenience entry point: start a background update check."""
    if current_version is None:
        try:
            from importlib.metadata import version
            current_version = version("plan-finder-gui")
        except Exception:
            from .. import __version__ as current_version  # type: ignore

    checker = UpdateChecker(parent, current_version=current_version)
    checker.start()
    return checker
