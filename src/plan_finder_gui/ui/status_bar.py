from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QWidget,
)


class StatusBar(QWidget):
    """Bottom strip showing session stats: cost, counts, iteration, progress."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(36)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            "QWidget { background: #252526; border-top: 1px solid #333; }"
            "QLabel { color: #ccc; font-size: 11px; padding: 0 6px; }"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(0)

        self._cost_label = QLabel("Cost: $0.00")
        self._tokens_label = QLabel("Tok: 0")
        self._turns_label = QLabel("T: 0")
        self._approved_label = QLabel("✓ 0")
        self._approved_label.setStyleSheet("color: #4caf50; font-size: 11px; padding: 0 6px;")
        self._rejected_label = QLabel("✗ 0")
        self._rejected_label.setStyleSheet("color: #f44336; font-size: 11px; padding: 0 6px;")
        self._iter_label = QLabel("Iter: —")

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)  # indeterminate
        self._progress.setFixedWidth(80)
        self._progress.setFixedHeight(6)
        self._progress.setStyleSheet(
            "QProgressBar { border: none; background: #333; border-radius: 3px; }"
            "QProgressBar::chunk { background: #0e78d5; border-radius: 3px; }"
        )
        self._progress.setVisible(False)

        layout.addWidget(self._cost_label)
        layout.addWidget(self._tokens_label)
        layout.addWidget(self._turns_label)
        layout.addWidget(self._approved_label)
        layout.addWidget(self._rejected_label)
        layout.addWidget(self._iter_label)
        layout.addStretch()
        layout.addWidget(self._progress)

        self._approved = 0
        self._rejected = 0
        self._cumulative_cost: float = 0.0
        self._cumulative_tokens: int = 0
        self._cumulative_turns: int = 0

    def reset(self) -> None:
        self._approved = 0
        self._rejected = 0
        self._cumulative_cost = 0.0
        self._cumulative_tokens = 0
        self._cumulative_turns = 0
        self._cost_label.setText("Cost: $0.00")
        self._tokens_label.setText("Tok: 0")
        self._turns_label.setText("T: 0")
        self._approved_label.setText("✓ 0")
        self._rejected_label.setText("✗ 0")
        self._iter_label.setText("Iter: —")
        self._progress.setVisible(False)

    def set_running(self, running: bool) -> None:
        self._progress.setVisible(running)

    def set_iteration(self, n: int) -> None:
        self._iter_label.setText(f"Iter: {n}")

    def set_iteration_for(self, sid: str, n: int) -> None:
        """Show the most recent per-session iteration tick."""
        self._iter_label.setText(f"Iter: {sid}={n}")

    def update_cost(self, cost: float, tokens: int, turns: int) -> None:
        self._cumulative_cost += cost
        self._cumulative_tokens += tokens
        self._cumulative_turns += turns
        self._cost_label.setText(f"Cost: ${self._cumulative_cost:.2f}")
        self._tokens_label.setText(f"Tok: {_fmt_tokens(self._cumulative_tokens)}")
        self._turns_label.setText(f"T: {self._cumulative_turns}")

    def increment_approved(self) -> None:
        self._approved += 1
        self._approved_label.setText(f"✓ {self._approved}")

    def increment_rejected(self) -> None:
        self._rejected += 1
        self._rejected_label.setText(f"✗ {self._rejected}")


def _fmt_tokens(tokens: int) -> str:
    if tokens >= 1_000_000:
        return f"{tokens / 1_000_000:.1f}M"
    if tokens >= 1_000:
        return f"{tokens / 1_000:.1f}K"
    return str(tokens)
