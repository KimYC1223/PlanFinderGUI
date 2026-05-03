from __future__ import annotations

import platform
import subprocess
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QUrl, Signal
from . import sound_player
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


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
    restart_requested = Signal(list)   # list[Path]
    restore_requested = Signal(list)   # list[Path]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._report_dir: Path | None = None
        self._is_running: bool = False
        self._current_file: Path | None = None   # original path of displayed file
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
        self._tree.setStyleSheet(
            "QTreeWidget {"
            "  background: #1e1e1e; color: #ccc; border: none; font-size: 12px;"
            "}"
            "QTreeWidget::item { padding: 3px 4px; }"
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
        left_layout.addWidget(self._tree, stretch=1)

        # Button bar
        self._btn_bar = QWidget()
        self._btn_bar.setStyleSheet("background: #252526; border-top: 1px solid #333;")
        btn_layout = QHBoxLayout(self._btn_bar)
        btn_layout.setContentsMargins(8, 6, 8, 6)
        btn_layout.setSpacing(6)

        self._resolve_btn  = _action_btn("✓  Resolve", "#2e7d32", "#388e3c")
        self._reject_btn_a = _action_btn("✗  Reject",  "#c62828", "#d32f2f")
        self._restart_btn  = _action_btn("↺  Restart", "#0d47a1", "#1565c0")
        self._restore_btn  = _action_btn("↩  Restore", "#4a4a4a", "#5a5a5a")

        for btn in (self._resolve_btn, self._reject_btn_a, self._restart_btn, self._restore_btn):
            btn_layout.addWidget(btn)
            btn.setVisible(False)

        btn_layout.addStretch()
        self._btn_bar.setVisible(False)
        left_layout.addWidget(self._btn_bar)

        self._resolve_btn.clicked.connect(self._on_resolve)
        self._reject_btn_a.clicked.connect(self._on_reject_action)
        self._restart_btn.clicked.connect(self._on_restart)
        self._restore_btn.clicked.connect(self._on_restore)

        splitter.addWidget(left_widget)

        # ---- Right: markdown viewer ----
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
        self._viewer.setVisible(False)
        splitter.addWidget(self._viewer)
        splitter.setSizes([1, 0])
        root.addWidget(splitter, stretch=1)

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def set_report_dir(self, path: Path) -> None:
        self._report_dir = path
        self._deselect_file()
        self.refresh()

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

            color = _CATEGORY_COLORS.get(cat, "#ccc")
            bg    = _CATEGORY_BG.get(cat, "#2a2a2a")
            label = _CATEGORY_LABELS.get(cat, cat)
            folder_item = QTreeWidgetItem([f"  {label}  ({len(files)})"])
            folder_item.setData(0, Qt.ItemDataRole.UserRole, ("folder", cat))
            folder_item.setForeground(0, QColor(color))
            folder_item.setBackground(0, QColor(bg))

            for f in files:
                name = _display_name(f)
                file_item = QTreeWidgetItem([f"    {name}"])
                file_item.setCheckState(0, Qt.CheckState.Unchecked)
                file_item.setData(0, Qt.ItemDataRole.UserRole, ("file", str(f), cat))
                file_item.setForeground(0, QColor("#cccccc"))
                folder_item.addChild(file_item)

            self._tree.addTopLevelItem(folder_item)
            # pending is expanded by default; others collapsed
            folder_item.setExpanded(cat == "pending")

        self._tree.blockSignals(False)
        self._update_buttons()

    def set_running(self, running: bool) -> None:
        self._is_running = running
        self._banner.setVisible(running)
        self._update_buttons()

    # ------------------------------------------------------------------ #
    #  Tree interaction                                                    #
    # ------------------------------------------------------------------ #

    def _on_item_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and data[0] == "file":
            path = Path(data[1])
            if path == self._current_file:
                # Same file clicked again → deselect
                self._deselect_file()
                self._tree.clearSelection()
            else:
                self._show_file(path)
        elif data and data[0] == "folder":
            # Folder clicked → deselect any open file
            self._deselect_file()

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        self._update_buttons()

    def _deselect_file(self) -> None:
        self._current_file = None
        self._viewer.setVisible(False)

    def _show_file(self, original: Path) -> None:
        was_hidden = not self._viewer.isVisible()
        self._current_file = original
        if was_hidden:
            self._viewer.setVisible(True)
            self._splitter.setSizes([280, 720])
        translated = _find_translated(original)
        target = translated if (translated and translated.exists()) else original
        if not target.exists():
            self._viewer.setPlainText("파일을 찾을 수 없습니다.")
            return
        try:
            content = target.read_text(encoding="utf-8")
        except Exception as e:
            self._viewer.setPlainText(f"파일 읽기 오류: {e}")
            return
        try:
            self._viewer.setHtml(_build_viewer_html(content))
        except ImportError:
            # markdown library not installed — use Qt's built-in renderer
            self._viewer.setMarkdown(content)

    def _on_viewer_context_menu(self, pos: QPoint) -> None:
        if not self._current_file:
            return
        self._show_file_context_menu(self._current_file, self._viewer.mapToGlobal(pos))

    def _on_tree_context_menu(self, pos: QPoint) -> None:
        item = self._tree.itemAt(pos)
        if item is None:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return

        if data[0] == "file":
            file_path = Path(data[1])
            self._show_file(file_path)
            self._show_file_context_menu(file_path, self._tree.mapToGlobal(pos))
        elif data[0] == "folder":
            self._show_folder_context_menu(item, self._tree.mapToGlobal(pos))

    def _show_folder_context_menu(self, folder_item: QTreeWidgetItem, global_pos: QPoint) -> None:
        if folder_item.childCount() == 0:
            return

        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background: #2d2d2d; color: #ccc; border: 1px solid #444; }"
            "QMenu::item { padding: 6px 20px; }"
            "QMenu::item:selected { background: #094771; color: white; }"
        )

        select_all_act   = menu.addAction("전체 선택")
        deselect_all_act = menu.addAction("전체 선택 해제")

        chosen = menu.exec(global_pos)

        self._tree.blockSignals(True)
        if chosen == select_all_act:
            for i in range(folder_item.childCount()):
                folder_item.child(i).setCheckState(0, Qt.CheckState.Checked)
        elif chosen == deselect_all_act:
            for i in range(folder_item.childCount()):
                folder_item.child(i).setCheckState(0, Qt.CheckState.Unchecked)
        self._tree.blockSignals(False)
        self._update_buttons()

    def _show_file_context_menu(self, path: Path, global_pos: QPoint) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background: #2d2d2d; color: #ccc; border: 1px solid #444; }"
            "QMenu::item { padding: 6px 20px; }"
            "QMenu::item:selected { background: #094771; color: white; }"
            "QMenu::separator { height: 1px; background: #444; margin: 2px 8px; }"
        )

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

        chosen = menu.exec(global_pos)

        if chosen == open_act:
            _open_file(path)
        elif chosen == reveal_act:
            _reveal_in_explorer(path)
        elif translate_act is not None and chosen == translate_act:
            self._translate_file(path)

    def _translate_file(self, path: Path) -> None:
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import (
            QApplication, QComboBox, QDialog, QDialogButtonBox,
            QLabel, QMessageBox, QVBoxLayout,
        )
        from ..engine.translator import save_translated, translate_with_claude, translate_with_google

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

        if "Google" in method:
            from .google_auth_dialog import GoogleAuthDialog
            if not GoogleAuthDialog.ensure_credentials(self):
                return

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            content = path.read_text(encoding="utf-8")
            if "Google" in method:
                translated_text = translate_with_google(content)
            else:
                translated_text = translate_with_claude(content)
            save_translated(path, translated_text)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            sound_player.play_random("tscerr00.wav", "tscerr01.wav")
            QMessageBox.warning(self, "번역 실패", f"번역 중 오류가 발생했습니다:\n{e}")
            return
        QApplication.restoreOverrideCursor()
        sound_player.play("trescue.wav")
        if self._current_file == path:
            self._show_file(path)

    # ------------------------------------------------------------------ #
    #  Button state management                                             #
    # ------------------------------------------------------------------ #

    def _collect_checked(self) -> dict[str, list[Path]]:
        result: dict[str, list[Path]] = {}
        root = self._tree.invisibleRootItem()
        for i in range(root.childCount()):
            folder = root.child(i)
            fdata = folder.data(0, Qt.ItemDataRole.UserRole)
            if fdata is None:
                continue
            cat = fdata[1]
            for j in range(folder.childCount()):
                child = folder.child(j)
                if child.checkState(0) == Qt.CheckState.Checked:
                    cdata = child.data(0, Qt.ItemDataRole.UserRole)
                    if cdata and cdata[0] == "file":
                        result.setdefault(cat, []).append(Path(cdata[1]))
        return result

    def _update_buttons(self) -> None:
        checked = self._collect_checked()
        cats = set(checked.keys())

        for btn in (self._resolve_btn, self._reject_btn_a, self._restart_btn, self._restore_btn):
            btn.setVisible(False)

        if not cats:
            self._btn_bar.setVisible(False)
            return

        self._btn_bar.setVisible(True)

        if cats == {"pending"}:
            self._resolve_btn.setVisible(True)
            self._reject_btn_a.setVisible(True)
        elif cats == {"working"}:
            self._restart_btn.setVisible(True)
            self._restart_btn.setEnabled(not self._is_running)
        elif cats == {"reject"}:
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

    def _on_restart(self) -> None:
        paths = self._collect_checked().get("working", [])
        if paths:
            self.restart_requested.emit(paths)

    def _on_restore(self) -> None:
        paths = self._collect_checked().get("reject", [])
        if paths:
            self.restore_requested.emit(paths)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
