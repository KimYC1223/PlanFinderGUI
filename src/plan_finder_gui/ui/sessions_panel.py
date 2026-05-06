"""Left-panel widget that lists currently running PlanFinder Claude sessions.

Each card shows the session id, label (Discovery / Resolve / Restart...),
state badge, current CPU%, and a 60-sample sparkline graph driven by the
:class:`SessionManager` polling tick.
"""

from __future__ import annotations

from collections import deque

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..engine.session_manager import CPU_HISTORY_LEN, Session, SessionManager
from . import sound_player


_GROUP_SS = (
    "QGroupBox {"
    "  color: #888; font-size: 10px; font-weight: bold;"
    "  border: 1px solid #333; border-radius: 4px;"
    "  margin-top: 8px; padding-top: 4px;"
    "}"
    "QGroupBox::title { subcontrol-origin: margin; left: 8px; top: -1px; }"
)
_DIM_SS  = "color: #888; font-size: 11px; background: transparent;"
_VAL_SS  = "color: #ccc; font-size: 11px; background: transparent;"
_ID_SS   = "color: #4fc3f7; font-size: 11px; font-weight: bold; background: transparent;"
_STATE_RUN_SS = (
    "color: #4caf50; font-size: 10px; background: transparent;"
    " padding: 0 4px; border: 1px solid #4caf50; border-radius: 6px;"
)
_STATE_DONE_SS = (
    "color: #888; font-size: 10px; background: transparent;"
    " padding: 0 4px; border: 1px solid #555; border-radius: 6px;"
)
_STATE_ERR_SS = (
    "color: #f44336; font-size: 10px; background: transparent;"
    " padding: 0 4px; border: 1px solid #f44336; border-radius: 6px;"
)


class _Sparkline(QWidget):
    """Tiny line chart of CPU% values, auto-scaling to the running max."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._values: deque[float] = deque([0.0] * CPU_HISTORY_LEN, maxlen=CPU_HISTORY_LEN)
        self.setMinimumHeight(28)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:
        return QSize(160, 28)

    def set_history(self, values) -> None:
        self._values = deque(values, maxlen=CPU_HISTORY_LEN)
        # Pad to full length so the line scrolls in from the right.
        while len(self._values) < CPU_HISTORY_LEN:
            self._values.appendleft(0.0)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = self.rect().adjusted(1, 1, -1, -1)
        # Background
        p.fillRect(self.rect(), QColor("#181818"))
        # Border
        p.setPen(QPen(QColor("#2c2c2c"), 1))
        p.drawRect(rect)

        if not self._values:
            return

        scale_max = 100.0

        w = rect.width()
        h = rect.height()
        n = len(self._values)
        if n < 2:
            return

        path = QPainterPath()
        for i, v in enumerate(self._values):
            x = rect.left() + (i / (n - 1)) * w
            y = rect.bottom() - (v / scale_max) * h
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)

        # Filled area below the line
        fill = QPainterPath(path)
        fill.lineTo(rect.right(), rect.bottom())
        fill.lineTo(rect.left(), rect.bottom())
        fill.closeSubpath()
        p.fillPath(fill, QColor(14, 120, 213, 60))

        p.setPen(QPen(QColor("#4fc3f7"), 1.4))
        p.drawPath(path)


class _SessionCard(QFrame):
    """One row in the SessionsPanel for a single Session."""

    def __init__(self, session: Session, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = session
        self.setStyleSheet(
            "QFrame { background: #232323; border: 1px solid #2c2c2c;"
            "         border-radius: 4px; }"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(4)

        header = QHBoxLayout()
        header.setSpacing(6)
        header.setContentsMargins(0, 0, 0, 0)

        self._id_lbl = QLabel(session.id)
        self._id_lbl.setStyleSheet(_ID_SS)
        header.addWidget(self._id_lbl)

        self._label_lbl = QLabel(session.label)
        self._label_lbl.setStyleSheet(_VAL_SS)
        self._label_lbl.setWordWrap(False)
        self._label_lbl.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        header.addWidget(self._label_lbl, stretch=1)

        self._state_lbl = QLabel("running")
        self._state_lbl.setStyleSheet(_STATE_RUN_SS)
        self._state_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(self._state_lbl)

        self._stop_btn = QPushButton("✕")
        self._stop_btn.setFixedSize(18, 18)
        self._stop_btn.setToolTip("이 세션 중단")
        self._stop_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #888; border: none;"
            "              font-size: 12px; }"
            "QPushButton:hover { color: #f44336; }"
        )
        self._stop_btn.clicked.connect(self._on_stop_clicked)
        header.addWidget(self._stop_btn)

        outer.addLayout(header)

        graph_row = QHBoxLayout()
        graph_row.setContentsMargins(0, 0, 0, 0)
        graph_row.setSpacing(4)

        self._spark = _Sparkline()
        graph_row.addWidget(self._spark, stretch=1)

        self._cpu_lbl = QLabel("0.0%")
        self._cpu_lbl.setStyleSheet(_DIM_SS)
        self._cpu_lbl.setFixedWidth(48)
        self._cpu_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        graph_row.addWidget(self._cpu_lbl)

        outer.addLayout(graph_row)

        # Hook the session's signals.
        session.cpu_updated.connect(self._on_cpu)
        session.state_changed.connect(self._on_state)

        self._on_cpu(session.cpu)
        self._on_state(session.state)

    def _on_cpu(self, value: float) -> None:
        self._cpu_lbl.setText(f"{value:.1f}%")
        self._spark.set_history(self.session.cpu_history)

    def _on_state(self, state: str) -> None:
        self._state_lbl.setText(state)
        if state == "running":
            self._state_lbl.setStyleSheet(_STATE_RUN_SS)
            self._stop_btn.setEnabled(True)
        elif state in ("failed", "cancelled"):
            self._state_lbl.setStyleSheet(_STATE_ERR_SS)
            self._stop_btn.setEnabled(False)
        else:
            self._state_lbl.setStyleSheet(_STATE_DONE_SS)
            self._stop_btn.setEnabled(False)

    def _on_stop_clicked(self) -> None:
        if self.session.state == "running":
            sound_player.play("buzz.wav")
        self.session.cancel()


class SessionsPanel(QWidget):
    """Left-panel widget rendering one card per active PlanFinder session."""

    def __init__(
        self, manager: SessionManager, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._manager = manager
        self._cards: dict[str, _SessionCard] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        group = QGroupBox("PlanFinder 세션")
        group.setStyleSheet(_GROUP_SS)
        group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

        self._inner = QVBoxLayout(group)
        self._inner.setContentsMargins(10, 10, 10, 10)
        self._inner.setSpacing(6)

        self._empty_lbl = QLabel("실행 중인 세션이 없습니다.")
        self._empty_lbl.setStyleSheet(_DIM_SS)
        self._inner.addWidget(self._empty_lbl)

        self._inner.addStretch(1)

        outer.addWidget(group)

        manager.session_registered.connect(self._on_registered)
        manager.session_unregistered.connect(self._on_unregistered)

    def _on_registered(self, session: Session) -> None:
        if session.id in self._cards:
            return
        card = _SessionCard(session, self)
        self._cards[session.id] = card
        # Insert before the trailing stretch.
        self._inner.insertWidget(self._inner.count() - 1, card)
        self._empty_lbl.setVisible(False)

    def _on_unregistered(self, session: Session) -> None:
        card = self._cards.pop(session.id, None)
        if card is not None:
            card.setParent(None)
            card.deleteLater()
        if not self._cards:
            self._empty_lbl.setVisible(True)
