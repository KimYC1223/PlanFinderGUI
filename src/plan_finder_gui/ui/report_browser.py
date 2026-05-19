from __future__ import annotations

import asyncio
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import (
    QEvent,
    QFileSystemWatcher,
    QMetaObject,
    QObject,
    QPoint,
    QRunnable,
    QSettings,
    Qt,
    QThreadPool,
    QTimer,
    QUrl,
    Signal,
    Slot,
)
from . import sound_player
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


# ---------------------------------------------------------------------------
# Translation worker for background threading
# ---------------------------------------------------------------------------


class TranslationSignals(QObject):
    """Signals for TranslationWorker to communicate with the main thread.

    Qt signals must be defined on a QObject, not QRunnable directly.
    """
    started = Signal(Path)           # Emitted when translation begins for a file
    finished = Signal(Path, str)     # Emitted on success: (file_path, translated_text)
    error = Signal(Path, str)        # Emitted on error: (file_path, error_message)
    progress = Signal(int, int)      # Emitted for batch progress: (current, total)


class TranslationWorker(QRunnable):
    """Background worker for translating files without blocking the UI.

    Runs the synchronous translation functions in a thread pool, emitting
    signals for thread-safe GUI updates via Qt's queued connections.
    """

    def __init__(
        self,
        file_path: Path,
        method: str,
        cancel_flag: list[bool] | None = None,
    ) -> None:
        """Initialize the translation worker.

        Args:
            file_path: Path to the markdown file to translate.
            method: Translation method - "Google Translate API" or "Claude".
            cancel_flag: A mutable list [bool] shared with the caller. If
                cancel_flag[0] becomes True, the worker skips processing.
        """
        super().__init__()
        self.file_path = file_path
        self.method = method
        self.cancel_flag = cancel_flag
        self.signals = TranslationSignals()
        self.setAutoDelete(True)

    def run(self) -> None:
        """Execute the translation in a background thread."""
        # Check cancellation before starting
        if self.cancel_flag and self.cancel_flag[0]:
            return

        self.signals.started.emit(self.file_path)

        try:
            from ..engine.translator import save_translated, translate_with_claude, translate_with_google

            # Check cancellation again before the expensive network call
            if self.cancel_flag and self.cancel_flag[0]:
                return

            content = self.file_path.read_text(encoding="utf-8")

            if "Google" in self.method:
                translated_text = translate_with_google(content)
            else:
                translated_text = translate_with_claude(content)

            # Check cancellation before saving
            if self.cancel_flag and self.cancel_flag[0]:
                return

            save_translated(self.file_path, translated_text)
            self.signals.finished.emit(self.file_path, translated_text)

        except Exception as e:
            self.signals.error.emit(self.file_path, str(e))


# ---------------------------------------------------------------------------
# Internal viewer HTML template (dark theme)
# ---------------------------------------------------------------------------

_BODY_FONT = "-apple-system, 'Apple SD Gothic Neo', 'Helvetica Neue', Arial, sans-serif"
_CODE_FONT = "'D2Coding', 'D2 Coding', Menlo, Consolas, 'Courier New', monospace"

_VIEWER_CSS = f"""
  body {{
    font-family: {_BODY_FONT};
    font-size: 13px;
    line-height: 1.6;
    color: #d4d4d4;
    background-color: #252526;
    margin: 0;
    padding: 16px 20px;
  }}
  h1, h2, h3, h4, p, li, td, th, blockquote {{
    font-family: {_BODY_FONT};
  }}
  h1 {{
    font-size: 20px;
    font-weight: bold;
    color: #e8e8e8;
    margin-top: 22px;
    margin-bottom: 6px;
    padding-bottom: 6px;
    border-bottom: 1px solid #444444;
  }}
  h2 {{
    font-size: 17px;
    font-weight: bold;
    color: #e8e8e8;
    margin-top: 18px;
    margin-bottom: 4px;
  }}
  h3 {{
    font-size: 14px;
    font-weight: bold;
    color: #d0d0d0;
    margin-top: 14px;
    margin-bottom: 4px;
  }}
  p {{ margin-top: 5px; margin-bottom: 5px; }}
  code {{
    font-family: {_CODE_FONT};
    font-size: 12px;
    background-color: #2a2d3e;
    color: #7ecfff;
    padding: 2px 6px;
    border-radius: 3px;
  }}
  pre {{
    font-family: {_CODE_FONT};
    font-size: 12px;
    color: #c8d3f5;
    background-color: #1a1b26;
    border: 1px solid #3d4060;
    border-radius: 5px;
    padding: 12px 14px;
    margin: 10px 0;
    line-height: 1.6;
  }}
  pre code {{
    font-family: {_CODE_FONT};
    font-size: 12px;
    background-color: transparent;
    color: #c8d3f5;
    padding: 0;
    border-radius: 0;
  }}
  blockquote {{
    color: #999999;
    border-left: 3px solid #555555;
    margin: 6px 0 6px 4px;
    padding: 2px 0 2px 14px;
  }}
  ul, ol {{ margin: 4px 0; padding-left: 22px; }}
  li {{ margin: 3px 0; }}
  a {{ color: #4fc3f7; }}
  hr {{
    border: none;
    border-top: 1px solid #444444;
    margin: 14px 0;
  }}
  table {{
    border-collapse: collapse;
    margin: 8px 0;
    width: 100%;
  }}
  th, td {{
    border: 1px solid #444444;
    padding: 5px 10px;
    text-align: left;
  }}
  th {{ background-color: #2d2d2d; color: #e8e8e8; font-weight: bold; }}
  strong {{ color: #e8e8e8; }}
  em {{ color: #c8c8c8; }}
"""


def _build_viewer_html(markdown_text: str) -> str:
    """Convert markdown to a self-contained dark-theme HTML string."""
    body = _md_to_html(markdown_text)
    body = _fix_code_blocks(body)
    return (
        f'<!DOCTYPE html><html><head>'
        f'<meta charset="utf-8">'
        f'<style>{_VIEWER_CSS}</style>'
        f'</head><body>{body}</body></html>'
    )


_CODE_BLOCK_STYLE = (
    f"font-family:{_CODE_FONT};"
    "font-size:12px;"
    "color:#c8d3f5;"
    "background-color:#1a1b26;"
    "border:1px solid #3d4060;"
    "border-radius:5px;"
    "padding:12px 14px;"
    "margin:10px 0;"
    "display:block;"
    "line-height:1.5;"
)


def _fix_code_blocks(html: str) -> str:
    """Replace <pre><code> with a <br>-based div to avoid Qt's per-line striping.

    Qt splits every \\n in <pre> into a separate QTextBlock, so the block
    background breaks between lines.  Using <br> keeps all lines inside a
    single QTextBlock → uniform background.  Leading spaces are converted to
    &nbsp; so indentation is preserved without white-space:pre.
    """
    import re

    def _encode(line: str) -> str:
        line = line.replace("\t", "&nbsp;&nbsp;&nbsp;&nbsp;")
        # Replace every space with &nbsp; to preserve indentation
        line = line.replace(" ", "&nbsp;")
        return line if line else "&nbsp;"  # empty line needs placeholder

    def replace_block(m: re.Match) -> str:
        code = m.group(1).rstrip("\n")
        inner = "<br/>".join(_encode(ln) for ln in code.split("\n"))
        return f'<div style="{_CODE_BLOCK_STYLE}">{inner}</div>'

    return re.sub(
        r"<pre><code[^>]*>(.*?)</code></pre>",
        replace_block,
        html,
        flags=re.DOTALL,
    )


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _is_translated(path: Path) -> bool:
    """True if filename matches *.XX.md pattern (2-letter lang code)."""
    parts = path.stem.rsplit(".", 1)
    return len(parts) == 2 and len(parts[1]) == 2


def _find_translated(original: Path) -> Path | None:
    """Find translated version.

    Checks two locations:
    1. Same directory as original: stem.XX.md
    2. translated/ subdirectory: translated/stem.XX.md
    """
    parent = original.parent
    stem = original.stem

    # Same-directory sibling
    for f in parent.glob(f"{stem}.*.md"):
        parts = f.stem.rsplit(".", 1)
        if len(parts) == 2 and len(parts[1]) == 2:
            return f

    # translated/ subdirectory
    trans_dir = parent / "translated"
    if trans_dir.is_dir():
        for f in trans_dir.glob(f"{stem}.*.md"):
            parts = f.stem.rsplit(".", 1)
            if len(parts) == 2 and len(parts[1]) == 2:
                return f

    return None


# ---------------------------------------------------------------------------
# Category configuration
# ---------------------------------------------------------------------------

_CATEGORIES = ["pending", "working", "reviewed", "reject"]

_CATEGORY_COLORS = {
    "pending":  "#ffa726",
    "working":  "#42a5f5",
    "reviewed": "#66bb6a",
    "reject":   "#ef5350",
}

_CATEGORY_ICONS = {
    "pending":  "⏳",
    "working":  "⚙",
    "reviewed": "✓",
    "reject":   "✗",
}

_CATEGORY_BG = {
    "pending":  "#221e10",
    "working":  "#0d1a2a",
    "reviewed": "#0e1e0e",
    "reject":   "#1e0e0e",
}

_CATEGORY_LABELS = {
    "pending":  "대기 중",
    "working":  "진행 중",
    "reviewed": "완료",
    "reject":   "거절됨",
}


class ReportBrowser(QWidget):
    """File tree browser + markdown viewer that replaces the PlanCard idle state.

    Layout:
        [Claude is analyzing… banner]  (top, hidden when not running)
        ┌─────────────────┬────────────────────────────────┐
        │  file tree      │  markdown viewer               │
        │  + button bar   │                                │
        └─────────────────┴────────────────────────────────┘
    """

    resolve_requested = Signal(list)   # list[Path]
    reject_requested  = Signal(list)   # list[Path]
    share_requested   = Signal(list, str)  # list[Path], member_name
    restart_requested = Signal(list)   # list[Path]
    restore_requested = Signal(list)   # list[Path]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._report_dir: Path | None = None
        self._is_running: bool = False
        self._current_file: Path | None = None   # original path of displayed file
        self._viewing_original: bool = False     # True → showing original even when translation exists
        self._suppress_click_deselect: bool = False  # set when itemChanged just previewed; itemClicked must not undo it
        self._chat_in_progress: bool = False
        self._chat_task: asyncio.Task | None = None
        self._chat_blocks: dict[Path, list[str]] = {}   # per-file HTML block fragments
        self._chat_pending: dict[Path, str | None] = {}  # per-file pending proposed content

        # Translation worker state for cancel coordination
        self._translation_cancel_flag: list[bool] = [False]  # mutable flag shared with workers
        self._translation_progress: QProgressDialog | None = None
        self._translation_pending_files: list[Path] = []  # files remaining in batch
        self._translation_errors: list[str] = []  # collected errors for batch summary
        self._translation_success_count: int = 0  # count of successful translations
        self._translation_method: str = ""  # current batch translation method

        self._fs_watcher = QFileSystemWatcher(self)
        self._fs_watcher.directoryChanged.connect(self._on_fs_change)
        self._fs_watcher.fileChanged.connect(self._on_fs_change)

        # Debounce rapid bursts of change events (e.g. batch file moves).
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(300)
        self._refresh_timer.timeout.connect(self.refresh)

        self._build_ui()

    # ------------------------------------------------------------------ #
    #  UI construction                                                     #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Running banner
        self._banner = QLabel("  ⚙  Claude is analyzing the codebase…")
        self._banner.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._banner.setFixedHeight(30)
        self._banner.setStyleSheet(
            "background: #1a3a5c; color: #64b5f6; font-size: 12px; font-style: italic;"
            "padding: 0 12px; border-bottom: 1px solid #2a5a8c;"
        )
        self._banner.setVisible(False)
        root.addWidget(self._banner)

        # Horizontal splitter
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setStyleSheet("QSplitter::handle { background: #333; width: 1px; }")
        splitter = self._splitter

        # ---- Left: file tree + button bar ----
        left_widget = QWidget()
        left_widget.setStyleSheet("background: #1e1e1e;")
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setRootIsDecorated(False)
        self._tree.setIndentation(14)
        self._tree.setStyleSheet(
            "QTreeWidget {"
            "  background: #1e1e1e; color: #ccc; border: none; font-size: 12px;"
            "}"
            "QTreeWidget::item { padding: 3px 4px 3px 0; }"
            "QTreeWidget::item:selected { background: #094771; color: #e8e8e8; }"
            "QTreeWidget::item:hover { background: #252527; }"
            "QTreeWidget::branch { background: #1e1e1e; }"
            "QTreeWidget::branch:has-children:!has-siblings:closed,"
            "QTreeWidget::branch:closed:has-children:has-siblings {"
            "  border-image: none; image: url(none); color: #ccc;"
            "}"
            "QScrollBar:vertical { width: 0px; }"
            "QScrollBar:horizontal { height: 0px; }"
        )
        self._tree.itemClicked.connect(self._on_item_clicked)
        self._tree.itemChanged.connect(self._on_item_changed)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_tree_context_menu)
        # Watch for clicks on empty area (no item under cursor) to deselect.
        self._tree.viewport().installEventFilter(self)
        left_layout.addWidget(self._tree, stretch=1)

        # Button bar
        self._btn_bar = QWidget()
        self._btn_bar.setStyleSheet("background: #252526; border-top: 1px solid #333;")
        btn_layout = QHBoxLayout(self._btn_bar)
        btn_layout.setContentsMargins(8, 6, 8, 6)
        btn_layout.setSpacing(6)

        self._resolve_btn  = _action_btn("✓  Resolve", "#2e7d32", "#388e3c")
        self._reject_btn_a = _action_btn("✗  Reject",  "#c62828", "#d32f2f")
        self._share_btn    = _action_btn("⬆  Share",   "#e65100", "#f57c00")
        self._restart_btn  = _action_btn("↺  Restart", "#0d47a1", "#1565c0")
        self._restore_btn  = _action_btn("↩  Restore", "#4a4a4a", "#5a5a5a")

        for btn in (self._resolve_btn, self._reject_btn_a, self._share_btn, self._restart_btn, self._restore_btn):
            btn_layout.addWidget(btn)
            btn.setVisible(False)

        btn_layout.addStretch()
        self._btn_bar.setVisible(False)
        left_layout.addWidget(self._btn_bar)

        self._resolve_btn.clicked.connect(self._on_resolve)
        self._reject_btn_a.clicked.connect(self._on_reject_action)
        self._share_btn.clicked.connect(self._on_share)
        self._restart_btn.clicked.connect(self._on_restart)
        self._restore_btn.clicked.connect(self._on_restore)

        splitter.addWidget(left_widget)

        # ---- Right: markdown viewer + view-mode toggle bar ----
        self._right_widget = QWidget()
        right_layout = QVBoxLayout(self._right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        self._viewer = QTextBrowser()
        self._viewer.setOpenExternalLinks(True)
        self._viewer.setWordWrapMode(
            __import__("PySide6.QtGui", fromlist=["QTextOption"]).QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere
        )
        self._viewer.setStyleSheet(
            "QTextBrowser {"
            "  background: #252526; color: #d4d4d4;"
            "  border: none;"
            "  padding: 10px;"
            "}"
            "QScrollBar:vertical { width: 0px; }"
            "QScrollBar:horizontal { height: 0px; }"
        )
        self._viewer.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._viewer.customContextMenuRequested.connect(self._on_viewer_context_menu)
        right_layout.addWidget(self._viewer, stretch=1)

        # Toggle view button bar (translated <-> original) + chat response language
        self._viewer_btn_bar = QWidget()
        self._viewer_btn_bar.setStyleSheet("background: #252526; border-top: 1px solid #333;")
        viewer_btn_layout = QHBoxLayout(self._viewer_btn_bar)
        viewer_btn_layout.setContentsMargins(8, 6, 8, 6)
        viewer_btn_layout.setSpacing(6)
        viewer_btn_layout.addStretch()
        self._chat_lang_combo = QComboBox()
        self._chat_lang_combo.addItem("한국어", "ko")
        self._chat_lang_combo.addItem("English", "en")
        self._chat_lang_combo.setFixedWidth(90)
        self._chat_lang_combo.setFixedHeight(26)
        self._chat_lang_combo.setStyleSheet(
            "QComboBox { background: #3c3c3c; color: #ccc; border: 1px solid #555;"
            " border-radius: 3px; padding: 2px 6px; font-size: 11px; }"
            "QComboBox::drop-down { border: none; }"
            "QComboBox QAbstractItemView { background: #3c3c3c; color: #ccc;"
            " selection-background-color: #094771; }"
        )
        viewer_btn_layout.addWidget(self._chat_lang_combo)
        self._toggle_view_btn = _action_btn("🌐  원문보기", "#00695c", "#00897b")
        self._toggle_view_btn.clicked.connect(self._on_toggle_view)
        viewer_btn_layout.addWidget(self._toggle_view_btn)
        self._viewer_btn_bar.setVisible(False)
        right_layout.addWidget(self._viewer_btn_bar)

        # Chat panel (below viewer_btn_bar)
        self._chat_panel = QWidget()
        self._chat_panel.setStyleSheet("background: #1e1e1e; border-top: 1px solid #2a2a2a;")
        chat_layout = QVBoxLayout(self._chat_panel)
        chat_layout.setContentsMargins(8, 6, 8, 6)
        chat_layout.setSpacing(4)

        self._chat_history = QTextBrowser()
        self._chat_history.setMaximumHeight(200)
        self._chat_history.setMinimumHeight(80)
        self._chat_history.setOpenExternalLinks(False)
        self._chat_history.document().setMaximumBlockCount(100)
        self._chat_history.setStyleSheet(
            "QTextBrowser { background: #1a1a1a; border: 1px solid #2e2e2e;"
            " border-radius: 4px; padding: 4px; font-size: 12px; color: #ccc; }"
            "QScrollBar:vertical { width: 0px; }"
        )
        self._chat_history.setVisible(False)
        chat_layout.addWidget(self._chat_history)

        input_bar = QWidget()
        input_layout = QHBoxLayout(input_bar)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(6)
        self._chat_input = QLineEdit()
        self._chat_input.setPlaceholderText("Claude에게 질문하거나 피드백을 입력하세요…")
        self._chat_input.setStyleSheet(
            "QLineEdit { background: #2d2d2d; color: #ccc; border: 1px solid #555;"
            " border-radius: 4px; padding: 4px 8px; font-size: 12px; }"
            "QLineEdit:focus { border: 1px solid #0e639c; }"
        )
        self._chat_input.returnPressed.connect(self._on_send_chat)
        self._chat_send_btn = _action_btn("전송", "#0e639c", "#1177bb")
        self._chat_send_btn.setFixedWidth(52)
        self._chat_send_btn.clicked.connect(self._on_send_chat)
        input_layout.addWidget(self._chat_input)
        input_layout.addWidget(self._chat_send_btn)
        chat_layout.addWidget(input_bar)

        self._chat_apply_bar = QWidget()
        apply_layout = QHBoxLayout(self._chat_apply_bar)
        apply_layout.setContentsMargins(0, 0, 0, 0)
        apply_layout.setSpacing(6)
        self._chat_auto_apply = QCheckBox("자동 적용")
        self._chat_auto_apply.setStyleSheet(
            "QCheckBox { color: #aaa; font-size: 11px; }"
            "QCheckBox::indicator { width: 13px; height: 13px; }"
        )
        self._chat_apply_btn = _action_btn("📝 변경사항 적용", "#2e7d32", "#388e3c")
        self._chat_apply_btn.clicked.connect(self._on_apply_chat_change)
        apply_layout.addStretch()
        apply_layout.addWidget(self._chat_auto_apply)
        apply_layout.addWidget(self._chat_apply_btn)
        self._chat_apply_bar.setVisible(False)
        chat_layout.addWidget(self._chat_apply_bar)

        self._chat_panel.setVisible(False)
        right_layout.addWidget(self._chat_panel)

        self._right_widget.setVisible(False)
        splitter.addWidget(self._right_widget)
        splitter.setSizes([1, 0])
        root.addWidget(splitter, stretch=1)

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def set_report_dir(self, path: Path) -> None:
        self._report_dir = path
        self._reset_watcher()
        self._deselect_file()
        self.refresh()

    def _reset_watcher(self) -> None:
        """Remove all previously watched paths and watch the current report dir tree."""
        watched_dirs = self._fs_watcher.directories()
        watched_files = self._fs_watcher.files()
        if watched_dirs:
            self._fs_watcher.removePaths(watched_dirs)
        if watched_files:
            self._fs_watcher.removePaths(watched_files)

        if not self._report_dir or not self._report_dir.is_dir():
            return

        paths_to_watch: list[str] = [str(self._report_dir)]
        for cat in _CATEGORIES:
            cat_dir = self._report_dir / cat
            if cat_dir.is_dir():
                paths_to_watch.append(str(cat_dir))
        self._fs_watcher.addPaths(paths_to_watch)

    def _on_fs_change(self, _path: str) -> None:
        # Re-arm the watcher for any category subdirs that might be newly created.
        self._reset_watcher()
        self._refresh_timer.start()

    def refresh(self) -> None:
        """Re-scan folder and rebuild tree, preserving expand/collapse state."""
        self._tree.blockSignals(True)
        self._tree.clear()

        for cat in _CATEGORIES:
            cat_dir = self._report_dir / cat if self._report_dir else None

            # Collect non-translated .md files (empty list if dir doesn't exist)
            files: list[Path] = []
            if cat_dir and cat_dir.is_dir():
                files = sorted(
                    [f for f in cat_dir.glob("*.md") if not _is_translated(f)],
                    key=lambda f: f.name,
                )

            # Group files by keyword (files without one fall under "Unassigned").
            by_keyword: dict[str, list[Path]] = {}
            for f in files:
                kw = _extract_keyword(f) or "Unassigned"
                by_keyword.setdefault(kw, []).append(f)

            color = _CATEGORY_COLORS.get(cat, "#ccc")
            bg    = _CATEGORY_BG.get(cat, "#2a2a2a")
            label = _CATEGORY_LABELS.get(cat, cat)
            folder_item = QTreeWidgetItem([f"{label}  ({len(files)})"])
            folder_item.setData(0, Qt.ItemDataRole.UserRole, ("folder", cat))
            folder_item.setForeground(0, QColor(color))
            folder_item.setBackground(0, QColor(bg))

            # Sort keywords alphabetically; "Unassigned" goes last.
            sorted_keywords = sorted(
                by_keyword.keys(),
                key=lambda k: (k == "Unassigned", k.lower()),
            )
            for kw in sorted_keywords:
                kw_files = by_keyword[kw]
                kw_item = QTreeWidgetItem([f"{kw}  ({len(kw_files)})"])
                kw_item.setData(0, Qt.ItemDataRole.UserRole, ("keyword", cat, kw))
                kw_item.setForeground(0, QColor("#9aa0a6"))
                folder_item.addChild(kw_item)

                for f in kw_files:
                    name = _display_name(f)
                    file_item = QTreeWidgetItem([f"{name}"])
                    file_item.setCheckState(0, Qt.CheckState.Unchecked)
                    file_item.setData(0, Qt.ItemDataRole.UserRole, ("file", str(f), cat))
                    file_item.setForeground(0, QColor("#cccccc"))
                    kw_item.addChild(file_item)

                # Keyword sub-folders are expanded so files are visible at a glance.
                kw_item.setExpanded(True)

            self._tree.addTopLevelItem(folder_item)
            # pending is expanded by default; others collapsed
            folder_item.setExpanded(cat == "pending")

        self._tree.blockSignals(False)
        self._update_buttons()
        self._purge_stale_chat_state()

    def _purge_stale_chat_state(self) -> None:
        """Remove chat state for files that no longer exist on disk."""
        if not self._chat_blocks:
            return
        stale = [p for p in self._chat_blocks if not p.exists()]
        for p in stale:
            del self._chat_blocks[p]
            self._chat_pending.pop(p, None)

    def set_running(self, running: bool) -> None:
        self._is_running = running
        self._banner.setVisible(running)
        self._update_buttons()

    # ------------------------------------------------------------------ #
    #  Tree interaction                                                    #
    # ------------------------------------------------------------------ #

    def eventFilter(self, obj, event):  # type: ignore[override]
        # Click on tree's empty area (no item under cursor) → deselect.
        if (
            obj is self._tree.viewport()
            and event.type() == QEvent.Type.MouseButtonPress
            and self._tree.itemAt(event.position().toPoint()) is None
        ):
            self._deselect_file()
            self._tree.clearSelection()
        return super().eventFilter(obj, event)

    def _on_item_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        # If a checkbox toggle just previewed this item, don't let the
        # accompanying itemClicked deselect it.
        if self._suppress_click_deselect:
            self._suppress_click_deselect = False
            return

        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and data[0] == "file":
            path = Path(data[1])
            if path == self._current_file:
                # Same file clicked again → deselect
                self._deselect_file()
                self._tree.clearSelection()
            else:
                self._show_file(path)
        elif data and data[0] in ("folder", "keyword"):
            # Category or keyword folder clicked → deselect any open file
            self._deselect_file()
            self._tree.clearSelection()

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        # A checkbox flip (check OR uncheck) counts as selecting that file:
        # show its preview. Bulk select-all/deselect-all paths block tree
        # signals, so this only fires for genuine single-item toggles.
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and data[0] == "file":
            self._tree.setCurrentItem(item)
            self._show_file(Path(data[1]))
            self._suppress_click_deselect = True
        self._update_buttons()

    def _deselect_file(self) -> None:
        self._current_file = None
        self._viewing_original = False
        self._right_widget.setVisible(False)
        self._unload_chat_ui()

    def _show_file(self, original: Path) -> None:
        was_hidden = not self._right_widget.isVisible()
        if original != self._current_file:
            self._viewing_original = False
            self._restore_chat_state(original)
        self._current_file = original
        if was_hidden:
            self._right_widget.setVisible(True)
            self._splitter.setSizes([280, 720])
        self._chat_panel.setVisible(True)
        translated = _find_translated(original)
        if translated and translated.exists() and not self._viewing_original:
            target = translated
        else:
            target = original
        if not target.exists():
            self._viewer.setPlainText("파일을 찾을 수 없습니다.")
            self._update_toggle_button(translated)
            return
        try:
            content = target.read_text(encoding="utf-8")
        except Exception as e:
            self._viewer.setPlainText(f"파일 읽기 오류: {e}")
            self._update_toggle_button(translated)
            return
        try:
            self._viewer.setHtml(_build_viewer_html(content))
        except ImportError:
            # markdown library not installed — use Qt's built-in renderer
            self._viewer.setMarkdown(content)
        self._update_toggle_button(translated)

    def _update_toggle_button(self, translated: Path | None) -> None:
        """Show button bar whenever a file is selected; toggle button only when translation exists."""
        has_translation = translated is not None and translated.exists()
        self._viewer_btn_bar.setVisible(self._current_file is not None)
        self._toggle_view_btn.setVisible(has_translation)
        if has_translation:
            self._toggle_view_btn.setText(
                "🌐  번역보기" if self._viewing_original else "🌐  원문보기"
            )

    def _on_toggle_view(self) -> None:
        if not self._current_file:
            return
        self._viewing_original = not self._viewing_original
        self._show_file(self._current_file)

    def _on_viewer_context_menu(self, pos: QPoint) -> None:
        if not self._current_file:
            return
        self._show_file_context_menu(
            self._current_file,
            self._viewer.mapToGlobal(pos),
            category=self._get_file_category(self._current_file),
        )

    def _on_tree_context_menu(self, pos: QPoint) -> None:
        item = self._tree.itemAt(pos)
        if item is None:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return

        if data[0] == "file":
            file_path = Path(data[1])
            cat = data[2] if len(data) > 2 else ""
            self._show_file(file_path)
            self._show_file_context_menu(file_path, self._tree.mapToGlobal(pos), category=cat)
        elif data[0] in ("folder", "keyword"):
            self._show_folder_context_menu(item, self._tree.mapToGlobal(pos))

    def _show_folder_context_menu(self, folder_item: QTreeWidgetItem, global_pos: QPoint) -> None:
        fdata = folder_item.data(0, Qt.ItemDataRole.UserRole)
        if not fdata or fdata[0] not in ("folder", "keyword"):
            return
        is_category = fdata[0] == "folder"
        cat = fdata[1]  # category name for both folder and keyword nodes

        # Walk descendants once — context menu actions operate on every file
        # under this node (one level for keyword, two for category).
        file_descendants: list[tuple[QTreeWidgetItem, Path]] = list(
            _iter_file_descendants(folder_item)
        )

        if not file_descendants and not (is_category and cat == "pending"):
            return

        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background: #2d2d2d; color: #ccc; border: 1px solid #444; }"
            "QMenu::item { padding: 6px 20px; }"
            "QMenu::item:selected { background: #094771; color: white; }"
            "QMenu::separator { height: 1px; background: #444; margin: 2px 8px; }"
        )

        select_all_act = None
        deselect_all_act = None
        if file_descendants:
            select_all_act   = menu.addAction("전체 선택")
            deselect_all_act = menu.addAction("전체 선택 해제")

        untranslated_files: list[Path] = [
            fp for _, fp in file_descendants
            if not _is_translated(fp) and _find_translated(fp) is None
        ]

        translate_all_act = None
        if untranslated_files:
            menu.addSeparator()
            translate_all_act = menu.addAction(f"번역 안된 파일 전체 번역하기 ({len(untranslated_files)}개)")

        distribute_act = None
        if is_category and cat == "pending":
            menu.addSeparator()
            n_pending = len(file_descendants)
            label = "팀원과 분배하기"
            if n_pending:
                label = f"팀원과 분배하기 ({n_pending}개)"
            distribute_act = menu.addAction(label)
            if n_pending == 0:
                distribute_act.setEnabled(False)

        chosen = menu.exec(global_pos)

        toggled: list[QTreeWidgetItem] = []
        self._tree.blockSignals(True)
        if select_all_act is not None and chosen == select_all_act:
            for child, _ in file_descendants:
                if child.checkState(0) != Qt.CheckState.Checked:
                    child.setCheckState(0, Qt.CheckState.Checked)
                    toggled.append(child)
        elif deselect_all_act is not None and chosen == deselect_all_act:
            for child, _ in file_descendants:
                if child.checkState(0) != Qt.CheckState.Unchecked:
                    child.setCheckState(0, Qt.CheckState.Unchecked)
                    toggled.append(child)
        self._tree.blockSignals(False)
        self._update_buttons()

        # Bulk select touching exactly one item still counts as a single
        # selection — preview it. Two or more is treated as no selection.
        if len(toggled) == 1:
            data = toggled[0].data(0, Qt.ItemDataRole.UserRole)
            if data and data[0] == "file":
                self._tree.setCurrentItem(toggled[0])
                self._show_file(Path(data[1]))

        if translate_all_act is not None and chosen == translate_all_act:
            self._translate_all_files(untranslated_files)
        elif distribute_act is not None and chosen == distribute_act:
            self._distribute_to_team(folder_item)

    def _show_file_context_menu(self, path: Path, global_pos: QPoint, category: str = "") -> None:
        _menu_style = (
            "QMenu { background: #2d2d2d; color: #ccc; border: 1px solid #444; }"
            "QMenu::item { padding: 6px 20px; }"
            "QMenu::item:selected { background: #094771; color: white; }"
            "QMenu::separator { height: 1px; background: #444; margin: 2px 8px; }"
        )
        menu = QMenu(self)
        menu.setStyleSheet(_menu_style)

        _is_mac = platform.system() == "Darwin"
        _is_win = platform.system() == "Windows"

        open_act  = menu.addAction("파일 열기")
        menu.addSeparator()
        if _is_mac:
            reveal_act = menu.addAction("Finder에서 보기")
        elif _is_win:
            reveal_act = menu.addAction("파일 탐색기에서 보기")
        else:
            reveal_act = menu.addAction("파일 관리자에서 보기")

        translate_act = None
        if not _is_translated(path) and _find_translated(path) is None:
            menu.addSeparator()
            translate_act = menu.addAction("번역하기")

        if category == "pending":
            from PySide6.QtCore import QSettings
            s = QSettings()
            my_name = str(s.value("team/my_name", "") or "").strip()
            members = [m for m in _read_team_members(s) if m != my_name]
            menu.addSeparator()
            share_menu = menu.addMenu("⬆  공유하기")
            share_menu.setStyleSheet(_menu_style)
            if members:
                for member in members:
                    act = share_menu.addAction(member)
                    act.triggered.connect(
                        lambda checked=False, m=member: self._do_share([path], m)
                    )
            else:
                no_act = share_menu.addAction("(팀원 없음 — 설정에서 추가)")
                no_act.setEnabled(False)

        chosen = menu.exec(global_pos)

        if chosen == open_act:
            _open_file(path)
        elif chosen == reveal_act:
            _reveal_in_explorer(path)
        elif translate_act is not None and chosen == translate_act:
            self._translate_file(path)

    def _translate_file(self, path: Path) -> None:
        """Translate a single file using a background worker thread.

        Shows a progress dialog that can be cancelled by the user. The UI
        remains responsive during translation.
        """
        from PySide6.QtCore import QSettings

        settings = QSettings()
        saved_method = str(settings.value("translate_method", "Google Translate API"))

        dialog = QDialog(self)
        dialog.setWindowTitle("번역하기")
        dialog.setFixedWidth(300)
        dialog.setStyleSheet(
            "QDialog { background: #252526; color: #ccc; }"
            "QLabel { color: #ccc; font-size: 12px; }"
            "QComboBox {"
            "  background: #3c3c3c; color: #ccc;"
            "  border: 1px solid #555; padding: 4px 8px;"
            "}"
            "QComboBox QAbstractItemView { background: #3c3c3c; color: #ccc; }"
            "QPushButton {"
            "  background: #0e639c; color: white;"
            "  border: none; padding: 6px 16px;"
            "}"
            "QPushButton:hover { background: #1177bb; }"
        )
        dlg_layout = QVBoxLayout(dialog)
        dlg_layout.setSpacing(10)
        dlg_layout.setContentsMargins(16, 16, 16, 16)
        dlg_layout.addWidget(QLabel("번역 방법을 선택하세요:"))
        combo = QComboBox()
        combo.addItems(["Google Translate API", "Claude"])
        idx = combo.findText(saved_method)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        dlg_layout.addWidget(combo)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        dlg_layout.addWidget(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        method = combo.currentText()
        settings.setValue("translate_method", method)

        if "Google" in method:
            from .google_auth_dialog import GoogleAuthDialog
            if not GoogleAuthDialog.ensure_credentials(self):
                return

        # Create a non-modal progress dialog with cancel button
        progress = QProgressDialog(
            f"번역 중: {path.name}",
            "취소",
            0, 0,  # 0, 0 makes it an indeterminate progress bar
            self,
        )
        progress.setWindowTitle("번역 중...")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)  # Show immediately
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setStyleSheet(
            "QProgressDialog { background: #252526; color: #ccc; }"
            "QLabel { color: #ccc; }"
            "QPushButton { background: #c62828; color: white; border: none;"
            "  padding: 6px 16px; border-radius: 3px; }"
            "QPushButton:hover { background: #d32f2f; }"
        )

        # Reset cancel flag
        self._translation_cancel_flag = [False]

        # Connect cancel button to set cancel flag
        progress.canceled.connect(lambda: self._on_single_translation_cancelled(progress))

        # Create worker
        worker = TranslationWorker(path, method, self._translation_cancel_flag)

        # Store progress dialog reference to check validity in callbacks
        self._translation_progress = progress

        # Connect signals with queued connection for thread safety
        worker.signals.finished.connect(
            lambda fp, _: self._on_single_translation_finished(fp, progress),
            Qt.ConnectionType.QueuedConnection,
        )
        worker.signals.error.connect(
            lambda fp, err: self._on_single_translation_error(fp, err, progress),
            Qt.ConnectionType.QueuedConnection,
        )

        # Submit to thread pool
        QThreadPool.globalInstance().start(worker)

    def _on_single_translation_cancelled(self, progress: QProgressDialog) -> None:
        """Handle cancellation of single file translation."""
        self._translation_cancel_flag[0] = True
        if progress and not progress.wasCanceled():
            progress.cancel()
        self._translation_progress = None

    def _on_single_translation_finished(self, path: Path, progress: QProgressDialog) -> None:
        """Handle successful completion of single file translation."""
        # Check if progress dialog is still valid
        if self._translation_progress is not progress:
            return  # Widget was closed or a different translation is running

        progress.close()
        self._translation_progress = None

        sound_player.play("trescue.wav")
        if self._current_file == path:
            self._show_file(path)

    def _on_single_translation_error(
        self, path: Path, error: str, progress: QProgressDialog
    ) -> None:
        """Handle error during single file translation."""
        # Check if progress dialog is still valid
        if self._translation_progress is not progress:
            return

        progress.close()
        self._translation_progress = None

        sound_player.play_random("tscerr00.wav", "tscerr01.wav")
        QMessageBox.warning(self, "번역 실패", f"번역 중 오류가 발생했습니다:\n{error}")

    def _translate_all_files(self, files: list[Path]) -> None:
        """Translate multiple files using background worker threads.

        Files are processed sequentially (one at a time) to avoid overwhelming
        the translation APIs. A progress dialog shows the current file and
        allows cancellation. Errors are collected and shown in a summary at
        the end.
        """
        from PySide6.QtCore import QSettings

        settings = QSettings()
        saved_method = str(settings.value("translate_method", "Google Translate API"))

        dialog = QDialog(self)
        dialog.setWindowTitle("번역 안된 파일 전체 번역하기")
        dialog.setFixedWidth(300)
        dialog.setStyleSheet(
            "QDialog { background: #252526; color: #ccc; }"
            "QLabel { color: #ccc; font-size: 12px; }"
            "QComboBox {"
            "  background: #3c3c3c; color: #ccc;"
            "  border: 1px solid #555; padding: 4px 8px;"
            "}"
            "QComboBox QAbstractItemView { background: #3c3c3c; color: #ccc; }"
            "QPushButton {"
            "  background: #0e639c; color: white;"
            "  border: none; padding: 6px 16px;"
            "}"
            "QPushButton:hover { background: #1177bb; }"
        )
        dlg_layout = QVBoxLayout(dialog)
        dlg_layout.setSpacing(10)
        dlg_layout.setContentsMargins(16, 16, 16, 16)
        dlg_layout.addWidget(QLabel(f"번역 안된 파일 {len(files)}개를 번역합니다.\n번역 방법을 선택하세요:"))
        combo = QComboBox()
        combo.addItems(["Google Translate API", "Claude"])
        idx = combo.findText(saved_method)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        dlg_layout.addWidget(combo)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        dlg_layout.addWidget(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        method = combo.currentText()
        settings.setValue("translate_method", method)

        if "Google" in method:
            from .google_auth_dialog import GoogleAuthDialog
            if not GoogleAuthDialog.ensure_credentials(self):
                return

        # Initialize batch translation state
        self._translation_cancel_flag = [False]
        self._translation_pending_files = list(files)  # Copy to avoid mutation issues
        self._translation_errors = []
        self._translation_success_count = 0
        self._translation_method = method
        total_files = len(files)

        # Create progress dialog
        progress = QProgressDialog(
            f"번역 중: 파일 1 / {total_files}",
            "취소",
            0, total_files,
            self,
        )
        progress.setWindowTitle("번역 중...")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setStyleSheet(
            "QProgressDialog { background: #252526; color: #ccc; }"
            "QLabel { color: #ccc; }"
            "QProgressBar { background: #333; border: 1px solid #555;"
            "  border-radius: 3px; text-align: center; color: #ccc; }"
            "QProgressBar::chunk { background: #0e639c; }"
            "QPushButton { background: #c62828; color: white; border: none;"
            "  padding: 6px 16px; border-radius: 3px; }"
            "QPushButton:hover { background: #d32f2f; }"
        )

        self._translation_progress = progress

        # Connect cancel button
        progress.canceled.connect(self._on_batch_translation_cancelled)

        # Start the first translation
        self._start_next_batch_translation()

    def _start_next_batch_translation(self) -> None:
        """Start translation for the next file in the batch queue."""
        # Check if cancelled or no more files
        if self._translation_cancel_flag[0] or not self._translation_pending_files:
            self._finish_batch_translation()
            return

        # Get the next file
        path = self._translation_pending_files.pop(0)
        total = (
            len(self._translation_pending_files)
            + self._translation_success_count
            + len(self._translation_errors)
            + 1  # current file
        )
        current = self._translation_success_count + len(self._translation_errors) + 1

        # Update progress dialog
        if self._translation_progress and not self._translation_progress.wasCanceled():
            self._translation_progress.setLabelText(
                f"번역 중: 파일 {current} / {total}\n{path.name}"
            )
            self._translation_progress.setValue(current - 1)

        # Create and start worker
        worker = TranslationWorker(path, self._translation_method, self._translation_cancel_flag)

        worker.signals.finished.connect(
            self._on_batch_file_finished,
            Qt.ConnectionType.QueuedConnection,
        )
        worker.signals.error.connect(
            self._on_batch_file_error,
            Qt.ConnectionType.QueuedConnection,
        )

        QThreadPool.globalInstance().start(worker)

    def _on_batch_file_finished(self, path: Path, translated_text: str) -> None:
        """Handle successful translation of a file in batch mode."""
        self._translation_success_count += 1

        # Update viewer if this file is currently displayed
        if self._current_file == path:
            self._show_file(path)

        # Continue with next file
        self._start_next_batch_translation()

    def _on_batch_file_error(self, path: Path, error: str) -> None:
        """Handle translation error for a file in batch mode."""
        self._translation_errors.append(f"{path.name}: {error}")

        # Continue with next file (don't stop the batch on individual errors)
        self._start_next_batch_translation()

    def _on_batch_translation_cancelled(self) -> None:
        """Handle user cancellation of batch translation."""
        self._translation_cancel_flag[0] = True
        # The current worker will check the flag and stop.
        # _finish_batch_translation will be called when _start_next_batch_translation
        # sees the cancel flag.

    def _finish_batch_translation(self) -> None:
        """Complete the batch translation and show summary."""
        # Close progress dialog
        if self._translation_progress:
            self._translation_progress.close()
            self._translation_progress = None

        errors = self._translation_errors
        success_count = self._translation_success_count
        was_cancelled = self._translation_cancel_flag[0]
        remaining = len(self._translation_pending_files)

        # Reset state
        self._translation_pending_files = []
        self._translation_errors = []
        self._translation_success_count = 0

        # Show summary
        if was_cancelled and remaining > 0:
            # User cancelled with files remaining
            if errors:
                sound_player.play_random("tscerr00.wav", "tscerr01.wav")
                QMessageBox.warning(
                    self,
                    "번역 취소됨",
                    f"번역이 취소되었습니다.\n\n"
                    f"완료: {success_count}개\n"
                    f"실패: {len(errors)}개\n"
                    f"취소됨: {remaining}개\n\n"
                    f"실패한 파일:\n" + "\n".join(errors[:10])
                    + ("\n..." if len(errors) > 10 else ""),
                )
            else:
                QMessageBox.information(
                    self,
                    "번역 취소됨",
                    f"번역이 취소되었습니다.\n\n"
                    f"완료: {success_count}개\n"
                    f"취소됨: {remaining}개",
                )
        elif errors:
            # Completed with some errors
            sound_player.play_random("tscerr00.wav", "tscerr01.wav")
            QMessageBox.warning(
                self,
                "번역 일부 실패",
                f"번역이 완료되었습니다.\n\n"
                f"성공: {success_count}개\n"
                f"실패: {len(errors)}개\n\n"
                f"실패한 파일:\n" + "\n".join(errors[:10])
                + ("\n..." if len(errors) > 10 else ""),
            )
        elif success_count > 0:
            # All successful
            sound_player.play("trescue.wav")
            QMessageBox.information(
                self,
                "번역 완료",
                f"모든 파일({success_count}개)이 성공적으로 번역되었습니다.",
            )

    # ------------------------------------------------------------------ #
    #  Team distribution                                                   #
    # ------------------------------------------------------------------ #

    def _distribute_to_team(self, folder_item: QTreeWidgetItem) -> None:
        """Distribute pending plans to team members by keyword.

        Flow:
          1. Validate team settings (alert / force-open settings).
          2. Extract unique keywords from pending plans.
          3. Ask the user to assign each keyword to a member.
          4. Copy files into ~/Desktop/claude-reports/<project>/<member>/
             (translated versions go into translated/ subdir).
          5. Zip each member's folder, then delete the unzipped folder.
          6. Move non-self plans from pending → reviewed.
        """
        if self._report_dir is None:
            return

        pending_files: list[Path] = [
            fp for _, fp in _iter_file_descendants(folder_item)
            if fp.exists() and not _is_translated(fp)
        ]

        if not pending_files:
            QMessageBox.information(
                self, "분배할 파일 없음", "Pending 폴더에 분배할 파일이 없습니다."
            )
            return

        # 1. Validate team settings.
        s = QSettings()
        my_name = str(s.value("team/my_name", "") or "").strip()
        members = _read_team_members(s)

        my_empty = not my_name
        team_empty = not members

        if my_empty and team_empty:
            QMessageBox.warning(
                self,
                "팀원 설정이 비어있습니다",
                "본인 이름과 팀원 목록이 모두 비어있어 분배할 수 없습니다.\n"
                "설정 창을 열어 입력해주세요.",
            )
            self._open_settings_dialog()
            # Reload after settings dialog closes.
            s = QSettings()
            my_name = str(s.value("team/my_name", "") or "").strip()
            members = _read_team_members(s)
            if not my_name and not members:
                return
        elif my_empty or team_empty:
            missing = "본인 이름" if my_empty else "팀원 목록"
            reply = QMessageBox.question(
                self,
                "확인",
                f"{missing}이(가) 비어있습니다. 이대로 진행하시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        if my_name and my_name in members:
            QMessageBox.warning(
                self,
                "팀원 설정 오류",
                f"'{my_name}'은(는) 본인 이름이지만 팀원 목록에도 있습니다. "
                f"설정 창에서 팀원 목록을 수정해주세요.",
            )
            return

        candidates: list[str] = []
        if my_name:
            candidates.append(my_name)
        candidates.extend(m for m in members if m != my_name)
        if not candidates:
            return

        # 2. Build keyword → list[file] map.
        keyword_files: dict[str, list[Path]] = {}
        for fp in pending_files:
            kw = _extract_keyword(fp) or "Unassigned"
            keyword_files.setdefault(kw, []).append(fp)

        # 3. Ask user to assign each keyword to a candidate.
        dlg = _KeywordAssignmentDialog(
            keywords=sorted(keyword_files.keys()),
            candidates=candidates,
            my_name=my_name,
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        keyword_to_member = dlg.assignments()

        # 4. Group files by member and copy them.
        member_files: dict[str, list[Path]] = {}
        for kw, files in keyword_files.items():
            assignee = keyword_to_member.get(kw)
            if not assignee:
                continue
            member_files.setdefault(assignee, []).extend(files)

        if not member_files:
            return

        project_name = self._report_dir.name
        desktop = _desktop_dir()
        base_dir = desktop / "claude-reports" / project_name

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        copy_errors: list[str] = []
        archives: list[Path] = []
        try:
            for member, files in member_files.items():
                member_dir = base_dir / _safe_dirname(member)
                if member_dir.exists():
                    shutil.rmtree(member_dir, ignore_errors=True)
                member_dir.mkdir(parents=True, exist_ok=True)
                trans_dir = member_dir / "translated"

                for fp in files:
                    try:
                        shutil.copy2(fp, member_dir / fp.name)
                        trans = _find_translated(fp)
                        if trans and trans.exists():
                            trans_dir.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(trans, trans_dir / trans.name)
                    except Exception as e:
                        copy_errors.append(f"{member}/{fp.name}: {e}")

                # 5. Zip the member folder and remove the original.
                try:
                    archive_base = str(member_dir)
                    archive_path = shutil.make_archive(
                        archive_base, "zip", root_dir=member_dir
                    )
                    archives.append(Path(archive_path))
                    shutil.rmtree(member_dir, ignore_errors=True)
                except Exception as e:
                    copy_errors.append(f"{member} 압축 실패: {e}")

            # 6. Move non-self plans from pending → reviewed.
            reviewed_dir = self._report_dir / "reviewed"
            reviewed_dir.mkdir(parents=True, exist_ok=True)
            move_errors: list[str] = []
            moved_count = 0
            for member, files in member_files.items():
                if member == my_name:
                    continue
                for fp in files:
                    try:
                        if not fp.exists():
                            continue
                        old_trans = _find_translated_in_pending(
                            self._report_dir / "pending", fp.name
                        )
                        fp.rename(reviewed_dir / fp.name)
                        moved_count += 1
                        if old_trans and old_trans.exists():
                            new_trans_dir = reviewed_dir / "translated"
                            new_trans_dir.mkdir(parents=True, exist_ok=True)
                            old_trans.rename(new_trans_dir / old_trans.name)
                    except Exception as e:
                        move_errors.append(f"{fp.name}: {e}")
            copy_errors.extend(move_errors)
        finally:
            QApplication.restoreOverrideCursor()

        self.refresh()

        summary_lines = [
            f"바탕화면에 압축본 {len(archives)}개를 만들었습니다.",
            f"위치: {base_dir}",
        ]
        if archives:
            summary_lines.append("")
            summary_lines.extend(f"• {a.name}" for a in archives)

        if copy_errors:
            sound_player.play_random("tscerr00.wav", "tscerr01.wav")
            QMessageBox.warning(
                self,
                "분배 일부 실패",
                "\n".join(summary_lines)
                + "\n\n다음 항목에서 문제가 발생했습니다:\n"
                + "\n".join(copy_errors),
            )
        else:
            sound_player.play("trescue.wav")
            QMessageBox.information(
                self,
                "분배 완료",
                "\n".join(summary_lines),
            )

    def _open_settings_dialog(self) -> None:
        from .settings_dialog import SettingsDialog
        SettingsDialog(self).exec()

    # ------------------------------------------------------------------ #
    #  Button state management                                             #
    # ------------------------------------------------------------------ #

    def _collect_checked(self) -> dict[str, list[Path]]:
        result: dict[str, list[Path]] = {}
        root = self._tree.invisibleRootItem()
        for i in range(root.childCount()):
            folder = root.child(i)
            fdata = folder.data(0, Qt.ItemDataRole.UserRole)
            if fdata is None or fdata[0] != "folder":
                continue
            cat = fdata[1]
            # Walk through keyword sub-folders → file items.
            for j in range(folder.childCount()):
                kw_item = folder.child(j)
                for k in range(kw_item.childCount()):
                    child = kw_item.child(k)
                    if child.checkState(0) == Qt.CheckState.Checked:
                        cdata = child.data(0, Qt.ItemDataRole.UserRole)
                        if cdata and cdata[0] == "file":
                            result.setdefault(cat, []).append(Path(cdata[1]))
        return result

    def _update_buttons(self) -> None:
        checked = self._collect_checked()
        cats = set(checked.keys())

        for btn in (self._resolve_btn, self._reject_btn_a, self._share_btn, self._restart_btn, self._restore_btn):
            btn.setVisible(False)

        if not cats:
            self._btn_bar.setVisible(False)
            return

        self._btn_bar.setVisible(True)

        if cats == {"pending"}:
            self._resolve_btn.setVisible(True)
            self._resolve_btn.setEnabled(not self._is_running)
            self._resolve_btn.setToolTip(
                "Cannot resolve while another session is running" if self._is_running else ""
            )
            self._reject_btn_a.setVisible(True)
            self._reject_btn_a.setEnabled(True)
            self._reject_btn_a.setToolTip("")
            self._share_btn.setVisible(True)
        elif cats == {"working"}:
            self._restart_btn.setVisible(True)
            self._restart_btn.setEnabled(not self._is_running)
        elif cats == {"reject"} or cats == {"reviewed"}:
            self._restore_btn.setVisible(True)

    # ------------------------------------------------------------------ #
    #  Button handlers                                                     #
    # ------------------------------------------------------------------ #

    def _on_resolve(self) -> None:
        paths = self._collect_checked().get("pending", [])
        if paths:
            self.resolve_requested.emit(paths)

    def _on_reject_action(self) -> None:
        paths = self._collect_checked().get("pending", [])
        if paths:
            self.reject_requested.emit(paths)

    def _on_share(self) -> None:
        paths = self._collect_checked().get("pending", [])
        if not paths:
            return
        from PySide6.QtCore import QSettings
        s = QSettings()
        my_name = str(s.value("team/my_name", "") or "").strip()
        members = [m for m in _read_team_members(s) if m != my_name]
        if not members:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self, "팀원 없음",
                "공유할 팀원이 없습니다.\n설정에서 팀원 목록을 추가해주세요.",
            )
            return
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background: #2d2d2d; color: #ccc; border: 1px solid #444; }"
            "QMenu::item { padding: 6px 20px; }"
            "QMenu::item:selected { background: #094771; color: white; }"
        )
        for member in members:
            act = menu.addAction(member)
            act.triggered.connect(
                lambda checked=False, m=member, p=paths: self._do_share(p, m)
            )
        menu.exec(self._share_btn.mapToGlobal(self._share_btn.rect().bottomLeft()))

    def _do_share(self, paths: list, member: str) -> None:
        self.share_requested.emit(paths, member)

    def _get_file_category(self, path: Path) -> str:
        if self._report_dir is None:
            return ""
        try:
            rel = path.relative_to(self._report_dir)
            return rel.parts[0] if rel.parts else ""
        except ValueError:
            return ""

    def _on_restart(self) -> None:
        paths = self._collect_checked().get("working", [])
        if paths:
            self.restart_requested.emit(paths)

    def _on_restore(self) -> None:
        checked = self._collect_checked()
        paths = checked.get("reject", []) + checked.get("reviewed", [])
        if paths:
            self.restore_requested.emit(paths)

    # ------------------------------------------------------------------ #
    #  Chat panel                                                          #
    # ------------------------------------------------------------------ #

    def _restore_chat_state(self, path: Path) -> None:
        blocks = self._chat_blocks.get(path, [])
        pending = self._chat_pending.get(path)
        self._chat_history.setHtml("")
        if blocks:
            for block in blocks:
                self._chat_history.append(block)
            self._chat_history.setVisible(True)
            sb = self._chat_history.verticalScrollBar()
            sb.setValue(sb.maximum())
        else:
            self._chat_history.setVisible(False)
        self._chat_apply_bar.setVisible(pending is not None)

    def _unload_chat_ui(self) -> None:
        """Reset chat UI to empty state without touching per-file state dicts."""
        self._chat_history.setHtml("")
        self._chat_history.setVisible(False)
        self._chat_apply_bar.setVisible(False)
        self._chat_in_progress = False

    def _clear_chat(self) -> None:
        """Clear chat history for the current file and remove its saved state."""
        if self._current_file is not None:
            self._chat_blocks.pop(self._current_file, None)
            self._chat_pending.pop(self._current_file, None)
        self._unload_chat_ui()

    def _on_send_chat(self) -> None:
        if self._chat_in_progress or not self._current_file:
            return
        message = self._chat_input.text().strip()
        if not message:
            return
        self._chat_input.clear()
        self._chat_send_btn.setEnabled(False)
        self._chat_in_progress = True
        self._append_chat_msg("user", message)
        lang = self._chat_lang_combo.currentData()
        self._chat_task = asyncio.ensure_future(
            self._do_chat(self._current_file, message, lang)
        )
        self._chat_task.add_done_callback(self._on_chat_task_done)

    def _on_chat_task_done(self, task: asyncio.Task) -> None:
        self._chat_task = None
        if not task.cancelled() and task.exception() is not None:
            self._append_chat_msg("error", f"오류: {task.exception()}")

    async def _do_chat(self, original_path: Path, message: str, lang: str) -> None:
        from ..engine.executor import chat_with_plan
        try:
            response, proposed = await chat_with_plan(
                original_path, message, lang,
                on_activity=lambda detail: self._on_chat_activity(original_path, detail),
            )
            self._append_chat_msg("claude", response, target_path=original_path, proposed_content=proposed)
            if proposed:
                self._chat_pending[original_path] = proposed
                if self._current_file == original_path:
                    self._chat_apply_bar.setVisible(True)
                    if self._chat_auto_apply.isChecked():
                        self._on_apply_chat_change()
        except Exception as e:
            self._append_chat_msg("error", f"오류: {e}", target_path=original_path)
        finally:
            self._chat_send_btn.setEnabled(True)
            self._chat_in_progress = False

    def _on_chat_activity(self, path: Path, detail: str) -> None:
        self._append_chat_msg("activity", detail, target_path=path)

    def _build_chat_html_block(
        self, role: str, text: str, proposed_content: str | None = None
    ) -> str:
        import html as html_lib
        safe = html_lib.escape(text).replace("\n", "<br>")
        if role == "user":
            return (
                f'<div style="margin:6px 0; text-align:right;">'
                f'<span style="background:#0e4e8a;color:#ddd;padding:8px 14px;'
                f'border-radius:14px;display:inline-block;max-width:85%;font-size:12px;'
                f'word-break:break-word;">{safe}</span></div>'
            )
        elif role == "claude":
            file_note = ""
            if proposed_content is not None:
                file_note = (
                    '<div style="color:#66bb6a;font-size:11px;margin-top:4px;">'
                    '📝 파일 수정 제안 있음</div>'
                )
            return (
                f'<div style="margin:6px 0;">'
                f'<span style="color:#666;font-size:10px;">Claude</span>'
                f'<div style="background:#2a2a2a;color:#d4d4d4;padding:8px 12px;'
                f'border-radius:12px;font-size:12px;margin-top:2px;word-break:break-word;">'
                f'{safe}{file_note}</div></div>'
            )
        elif role == "activity":
            return (
                f'<div style="margin:1px 0 1px 8px;color:#555;font-size:10px;'
                f'font-style:italic;">↳ {safe}</div>'
            )
        else:  # error
            return (
                f'<div style="margin:6px 0;color:#ef5350;font-size:12px;">{safe}</div>'
            )

    def _append_chat_msg(
        self, role: str, text: str, target_path: Path | None = None,
        proposed_content: str | None = None
    ) -> None:
        block = self._build_chat_html_block(role, text, proposed_content)
        path = target_path if target_path is not None else self._current_file
        if path is not None:
            if path not in self._chat_blocks:
                self._chat_blocks[path] = []
            self._chat_blocks[path].append(block)
        if target_path is None or target_path == self._current_file:
            self._chat_history.setVisible(True)
            self._chat_history.append(block)
            sb = self._chat_history.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _on_apply_chat_change(self) -> None:
        if not self._current_file:
            return
        proposed = self._chat_pending.get(self._current_file)
        if not proposed:
            return
        try:
            self._current_file.write_text(proposed, encoding="utf-8")
            self._chat_pending[self._current_file] = None
            self._chat_apply_bar.setVisible(False)
            self._show_file(self._current_file)
        except Exception as e:
            QMessageBox.warning(self, "저장 실패", f"파일 저장 실패: {e}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _iter_file_descendants(item: QTreeWidgetItem):
    """Recursively yield (file_item, path) pairs for every file under `item`."""
    for i in range(item.childCount()):
        child = item.child(i)
        data = child.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            continue
        if data[0] == "file":
            yield child, Path(data[1])
        elif data[0] in ("folder", "keyword"):
            yield from _iter_file_descendants(child)


def _extract_h1(path: Path) -> str | None:
    """Return the first '# ...' heading text in the file, or None."""
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("# "):
                return stripped[2:].strip()
    except Exception:
        pass
    return None


def _display_name(original: Path) -> str:
    """Show H1 heading from translated file if available, else from original.
    Falls back to filename stem when no H1 is found.
    """
    source = _find_translated(original) or original
    h1 = _extract_h1(source)
    if h1:
        return h1
    # Fallback: stem without language suffix (e.g. plan.ko → plan)
    stem = source.stem
    parts = stem.rsplit(".", 1)
    return parts[0] if len(parts) == 2 and len(parts[1]) == 2 else stem


def _open_file(path: Path) -> None:
    """Open file with the system default application."""
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def _reveal_in_explorer(path: Path) -> None:
    """Reveal the file in Finder / Explorer / file manager."""
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.run(["open", "-R", str(path)], check=False)
        elif system == "Windows":
            subprocess.run(["explorer", f"/select,{path}"], check=False)
        else:
            # Linux: open parent directory
            subprocess.run(["xdg-open", str(path.parent)], check=False)
    except Exception:
        # Fallback: open parent directory
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))


def _open_in_browser(original: Path) -> None:
    """Render markdown to a temp HTML file and open in the default browser."""
    translated = _find_translated(original)
    source = translated if (translated and translated.exists()) else original

    try:
        content = source.read_text(encoding="utf-8")
    except Exception:
        return

    # Convert markdown to HTML with styling
    html_body = _md_to_html(content)
    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{source.stem}</title>
<style>
  body {{
    font-family: -apple-system, 'Helvetica Neue', Arial, sans-serif;
    font-size: 15px;
    line-height: 1.6;
    max-width: 820px;
    margin: 40px auto;
    padding: 0 24px;
    color: #24292e;
    background: #fff;
  }}
  h1, h2, h3 {{ margin-top: 24px; margin-bottom: 8px; }}
  h1 {{ font-size: 28px; border-bottom: 1px solid #eee; padding-bottom: 8px; }}
  h2 {{ font-size: 22px; }}
  h3 {{ font-size: 18px; }}
  code {{
    font-family: Menlo, Consolas, 'Courier New', monospace;
    font-size: 13px;
    background: #f6f8fa;
    color: #e36209;
    padding: 2px 6px;
    border-radius: 4px;
  }}
  pre {{
    background: #f6f8fa;
    padding: 14px 18px;
    border-radius: 6px;
    overflow-x: auto;
    font-size: 13px;
  }}
  pre code {{ background: none; padding: 0; color: inherit; }}
  blockquote {{
    color: #6a737d;
    border-left: 4px solid #dfe2e5;
    margin: 0;
    padding: 0 16px;
  }}
  a {{ color: #0366d6; }}
  li {{ margin: 4px 0; }}
</style>
</head>
<body>
{html_body}
</body>
</html>"""

    tmp = tempfile.NamedTemporaryFile(
        suffix=".html", mode="w", encoding="utf-8", delete=False
    )
    tmp.write(html)
    tmp.close()
    QDesktopServices.openUrl(QUrl.fromLocalFile(tmp.name))


def _md_to_html(text: str) -> str:
    """Convert markdown to HTML using the markdown library."""
    import markdown as md_lib
    return md_lib.markdown(text, extensions=["fenced_code", "tables"])


def _action_btn(label: str, bg: str, hover_bg: str) -> QPushButton:
    btn = QPushButton(label)
    btn.setFixedHeight(28)
    btn.setStyleSheet(
        f"QPushButton {{ background: {bg}; color: white; border-radius: 4px;"
        f" font-size: 12px; font-weight: bold; padding: 0 12px; }}"
        f"QPushButton:hover {{ background: {hover_bg}; }}"
        f"QPushButton:disabled {{ background: #333; color: #555; }}"
    )
    return btn


# ---------------------------------------------------------------------------
# Team distribution helpers
# ---------------------------------------------------------------------------

_KEYWORD_LINE_RE = re.compile(r"\*\*Keyword:\*\*\s*`?([^`\n]+?)`?\s*$")
_META_KEYWORD_RE = re.compile(r"Keyword:\s*([^|\n]+?)(?:\s*\||\s*$)")
_TITLE_CLASS_RE  = re.compile(r"^#\s+([A-Z][A-Za-z0-9_]+)([:\.\(]|\s|$)")
_CAMEL_CASE_RE   = re.compile(r"[a-z][A-Z]")


def _extract_keyword(path: Path) -> str | None:
    """Pull the Keyword tag out of a plan markdown file, if present.

    Order of preference:
      1. `**Keyword:** ...` body line (newer plans).
      2. `Keyword: ...` token in the iteration meta line.
      3. CamelCase identifier at the start of the H1 title (older plans
         without an explicit Keyword tag).
    """
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None

    for line in text.splitlines()[:60]:
        m = _KEYWORD_LINE_RE.search(line)
        if m:
            kw = m.group(1).strip()
            if kw:
                return kw
        m = _META_KEYWORD_RE.search(line)
        if m and "Iteration" in line:
            kw = m.group(1).strip()
            if kw:
                return kw

    # Fallback: derive from the H1 title (e.g. "# ClassName.method() …" or
    # "# ClassName: …"). We only accept identifiers that look like a C#-style
    # class — followed by `.`/`:`/`(`, or with internal CamelCase when followed
    # by whitespace.
    for line in text.splitlines()[:10]:
        if line.startswith("#") and not line.startswith("##"):
            tm = _TITLE_CLASS_RE.match(line)
            if not tm:
                break
            ident, delim = tm.group(1), tm.group(2)
            if delim in (".", ":", "("):
                return ident
            if _CAMEL_CASE_RE.search(ident):
                return ident
            break
    return None


def _read_team_members(s: QSettings) -> list[str]:
    raw = str(s.value("team/members", "") or "")
    seen: set[str] = set()
    out: list[str] = []
    for line in raw.splitlines():
        name = line.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def _desktop_dir() -> Path:
    """Return the user's Desktop directory (Mac & Windows compatible)."""
    home = Path.home()
    candidate = home / "Desktop"
    if candidate.exists():
        return candidate
    if platform.system() == "Windows":
        import os
        userprofile = os.environ.get("USERPROFILE")
        if userprofile:
            alt = Path(userprofile) / "Desktop"
            if alt.exists():
                return alt
    candidate.mkdir(parents=True, exist_ok=True)
    return candidate


def _safe_dirname(name: str) -> str:
    cleaned = "".join(c for c in name if c.isalnum() or c in ("-", "_", "."))
    return cleaned or "unnamed"


def _find_translated_in_pending(pending_dir: Path, original_name: str) -> Path | None:
    """Locate a translated companion file inside pending/translated/."""
    trans_dir = pending_dir / "translated"
    if not trans_dir.is_dir():
        return None
    stem = Path(original_name).stem
    for f in trans_dir.glob(f"{stem}.*.md"):
        parts = f.stem.rsplit(".", 1)
        if len(parts) == 2 and len(parts[1]) == 2:
            return f
    return None


class _KeywordAssignmentDialog(QDialog):
    """Single dialog asking who owns each Keyword.

    For each keyword, a row of buttons (one per candidate) is shown. The
    selected button is highlighted. OK is only enabled when every keyword
    has an assignee.
    """

    def __init__(
        self,
        keywords: list[str],
        candidates: list[str],
        my_name: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Keyword 담당자 지정")
        self._keywords = list(keywords)
        self._candidates = list(candidates)
        self._my_name = my_name
        self._assignments: dict[str, str] = {}
        self._groups: dict[str, QButtonGroup] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        self.setStyleSheet(
            "QDialog { background: #252526; color: #ccc; }"
            "QLabel { color: #ccc; background: transparent; }"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        intro = QLabel(
            "각 Keyword의 담당자를 선택하세요. "
            "본인 이름은 진하게 표시됩니다."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #ccc; font-size: 12px; background: transparent;")
        outer.addWidget(intro)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            "QScrollArea { background: #1e1e1e; border: 1px solid #333; }"
            "QScrollBar:vertical { width: 10px; background: #1e1e1e; }"
            "QScrollBar::handle:vertical { background: #444; border-radius: 4px; }"
        )

        body = QWidget()
        body.setStyleSheet("background: #1e1e1e;")
        grid = QGridLayout(body)
        grid.setContentsMargins(10, 10, 10, 10)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)

        for row, kw in enumerate(self._keywords):
            kw_label = QLabel(kw)
            kw_label.setStyleSheet(
                "color: #e8e8e8; font-size: 12px; font-weight: bold;"
                "background: transparent; padding: 4px 0;"
            )
            grid.addWidget(kw_label, row, 0)

            btn_row = QWidget()
            btn_row.setStyleSheet("background: transparent;")
            btn_layout = QHBoxLayout(btn_row)
            btn_layout.setContentsMargins(0, 0, 0, 0)
            btn_layout.setSpacing(4)

            group = QButtonGroup(self)
            group.setExclusive(True)
            self._groups[kw] = group

            for cand in self._candidates:
                btn = QPushButton(cand if cand != self._my_name else f"{cand} (나)")
                btn.setCheckable(True)
                btn.setProperty("candidate", cand)
                btn.setStyleSheet(
                    "QPushButton {"
                    "  background: #2d2d2d; color: #ccc;"
                    "  border: 1px solid #444; border-radius: 4px;"
                    "  padding: 4px 10px; font-size: 11px;"
                    "}"
                    "QPushButton:hover { background: #3a3a3a; }"
                    "QPushButton:checked {"
                    "  background: #0e639c; color: white;"
                    "  border-color: #1177bb; font-weight: bold;"
                    "}"
                )
                if cand == self._my_name:
                    f = btn.font()
                    f.setBold(True)
                    btn.setFont(f)
                group.addButton(btn)
                btn_layout.addWidget(btn)

            btn_layout.addStretch(1)
            grid.addWidget(btn_row, row, 1)

            group.buttonClicked.connect(
                lambda b, k=kw: self._on_picked(k, b)
            )

        grid.setColumnStretch(1, 1)
        scroll.setWidget(body)
        outer.addWidget(scroll, stretch=1)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet(
            "color: #ffb74d; font-size: 11px; background: transparent;"
        )
        outer.addWidget(self._status_label)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.setStyleSheet(
            "QPushButton { background: #333; color: #ccc; border-radius: 4px;"
            "  font-size: 12px; padding: 5px 18px; border: 1px solid #444; }"
            "QPushButton:hover { background: #444; }"
            "QPushButton:default { background: #0e78d5; color: white; border: none; }"
            "QPushButton:default:hover { background: #1e88e5; }"
        )
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        outer.addWidget(self._buttons)

        self.resize(560, min(560, 140 + 36 * max(len(self._keywords), 1)))
        self._update_state()

    def _on_picked(self, keyword: str, button) -> None:
        cand = button.property("candidate")
        if cand:
            self._assignments[keyword] = cand
        self._update_state()

    def _update_state(self) -> None:
        missing = [k for k in self._keywords if k not in self._assignments]
        ok_btn = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        if missing:
            self._status_label.setText(
                f"미지정 Keyword {len(missing)}개: {', '.join(missing[:5])}"
                + ("…" if len(missing) > 5 else "")
            )
            ok_btn.setEnabled(False)
        else:
            self._status_label.setText("")
            ok_btn.setEnabled(True)

    def assignments(self) -> dict[str, str]:
        return dict(self._assignments)
