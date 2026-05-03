from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QVBoxLayout, QWidget

_LEVEL_COLORS = {
    "info":    "#cccccc",
    "dim":     "#888888",
    "success": "#4caf50",
    "reject":  "#f44336",
    "error":   "#ff5252",
    "warn":    "#ff9800",
}


class LogPanel(QWidget):
    """Scrollable activity log with a live activity indicator at the top."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._activity_label = QLabel("Idle")
        self._activity_label.setStyleSheet(
            "color: #888; font-size: 11px; padding: 2px 4px;"
        )
        self._activity_label.setWordWrap(True)
        layout.addWidget(self._activity_label)

        self._log_edit = QPlainTextEdit()
        self._log_edit.setReadOnly(True)
        self._log_edit.setMaximumBlockCount(2000)
        self._log_edit.setStyleSheet(
            "QPlainTextEdit {"
            "  background: #1e1e1e;"
            "  color: #cccccc;"
            "  font-family: 'Menlo', 'Consolas', monospace;"
            "  font-size: 11px;"
            "  border: none;"
            "  padding: 4px;"
            "}"
            "QScrollBar:vertical { width: 0px; }"
            "QScrollBar:horizontal { height: 0px; }"
        )
        layout.addWidget(self._log_edit)

    def append_log(self, message: str, level: str = "info") -> None:
        color = _LEVEL_COLORS.get(level, _LEVEL_COLORS["info"])
        ts = datetime.now().strftime("%H:%M:%S")
        # Use HTML for color; QPlainTextEdit supports appendHtml via cursor
        cursor = self._log_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._log_edit.setTextCursor(cursor)
        self._log_edit.appendHtml(
            f'<span style="color:#555">[{ts}]</span> '
            f'<span style="color:{color}">{_escape_html(message)}</span>'
        )
        self._scroll_to_bottom()

    def set_activity(self, detail: str) -> None:
        self._activity_label.setText(f"Claude: {detail}")

    def clear_activity(self) -> None:
        self._activity_label.setText("Idle")

    def _scroll_to_bottom(self) -> None:
        sb = self._log_edit.verticalScrollBar()
        sb.setValue(sb.maximum())


def _escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
