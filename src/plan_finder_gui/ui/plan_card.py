from __future__ import annotations

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QKeySequence, QShortcut

from .icon_loader import load_icon
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..engine.models import DiscoveredPlan

_CATEGORY_COLORS = {
    "bug_fix":      "#f44336",
    "refactoring":  "#9c27b0",
    "performance":  "#ff9800",
    "security":     "#f44336",
    "code_quality": "#2196f3",
    "documentation":"#607d8b",
    "testing":      "#4caf50",
    "architecture": "#673ab7",
    "dependency":   "#795548",
    "feature":      "#00bcd4",
    "other":        "#9e9e9e",
}

_EFFORT_LABELS = {
    "trivial": "XS",
    "small":   "S",
    "medium":  "M",
    "large":   "L",
    "epic":    "XL",
}

_PRIORITY_LABELS = {1: "심각", 2: "매우 높음", 3: "높음", 4: "보통", 5: "낮음"}


class PlanCard(QWidget):
    """Displays a discovered plan and collects user approval.

    Emits approval_submitted(action, feedback) when the user acts.
    """

    approval_submitted = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()
        self.show_idle()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- State: idle / running ---
        self._idle_widget = QLabel("Start a session to discover improvements.")
        self._idle_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._idle_widget.setStyleSheet("color: #666; font-size: 14px;")
        root.addWidget(self._idle_widget)

        self._running_label = QLabel("Claude is analyzing the codebase…")
        self._running_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._running_label.setStyleSheet("color: #888; font-size: 14px; font-style: italic;")
        root.addWidget(self._running_label)

        self._done_label = QLabel("No more improvements found. The codebase looks good!")
        self._done_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._done_label.setStyleSheet("color: #4caf50; font-size: 14px;")
        root.addWidget(self._done_label)

        # --- State: plan_ready (scrollable content) ---
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        content = QWidget()
        content.setStyleSheet("background: #252526;")
        self._content_layout = QVBoxLayout(content)
        self._content_layout.setContentsMargins(16, 16, 16, 16)
        self._content_layout.setSpacing(12)

        # Header row: category badge + effort badge + priority
        header_row = QHBoxLayout()
        self._category_badge = QLabel()
        self._category_badge.setFixedHeight(22)
        self._category_badge.setStyleSheet(
            "border-radius: 4px; padding: 2px 8px; font-size: 11px; font-weight: bold; color: white;"
        )
        self._effort_badge = QLabel()
        self._effort_badge.setFixedHeight(22)
        self._effort_badge.setStyleSheet(
            "background: #444; border-radius: 4px; padding: 2px 8px;"
            "font-size: 11px; color: #ccc;"
        )
        self._priority_label = QLabel()
        self._priority_label.setStyleSheet("color: #aaa; font-size: 12px;")
        self._iteration_label = QLabel()
        self._iteration_label.setStyleSheet("color: #666; font-size: 11px;")
        header_row.addWidget(self._category_badge)
        header_row.addWidget(self._effort_badge)
        header_row.addWidget(self._priority_label)
        header_row.addStretch()
        header_row.addWidget(self._iteration_label)
        self._content_layout.addLayout(header_row)

        # Title
        self._title_label = QLabel()
        self._title_label.setWordWrap(True)
        self._title_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._title_label.setStyleSheet(
            "color: #e8e8e8; font-size: 16px; font-weight: bold;"
        )
        self._content_layout.addWidget(self._title_label)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #333;")
        self._content_layout.addWidget(sep)

        # Description
        self._desc_label = _section_label()
        self._content_layout.addWidget(_section_heading("Description"))
        self._content_layout.addWidget(self._desc_label)

        # Rationale
        self._rationale_label = _section_label("italic")
        self._content_layout.addWidget(_section_heading("Rationale"))
        self._content_layout.addWidget(self._rationale_label)

        # Files affected
        self._content_layout.addWidget(_section_heading("Files Affected"))
        self._files_list = QListWidget()
        self._files_list.setMaximumHeight(120)
        self._files_list.setStyleSheet(
            "QListWidget { background: #1e1e1e; color: #7ec8e3; border: 1px solid #333;"
            "font-family: 'Menlo','Consolas',monospace; font-size: 11px; }"
        )
        self._content_layout.addWidget(self._files_list)

        # Implementation steps
        self._content_layout.addWidget(_section_heading("Implementation Steps"))
        self._steps_list = QListWidget()
        self._steps_list.setStyleSheet(
            "QListWidget { background: #1e1e1e; color: #ccc; border: 1px solid #333; font-size: 12px; }"
            "QListWidget::item { padding: 4px 8px; }"
        )
        self._content_layout.addWidget(self._steps_list)

        # Risks
        self._risks_heading = _section_heading("Risks")
        self._risks_label = _section_label(color="#ff9800")
        self._content_layout.addWidget(self._risks_heading)
        self._content_layout.addWidget(self._risks_label)

        # Action buttons
        btn_row = QHBoxLayout()
        self._approve_btn = QPushButton("Approve (Ctrl+A)")
        self._approve_btn.setIcon(load_icon("check"))
        self._approve_btn.setIconSize(QSize(16, 16))
        self._approve_btn.setFixedHeight(36)
        self._approve_btn.setStyleSheet(
            "QPushButton { background: #2e7d32; color: white; border-radius: 4px; font-size: 13px; font-weight: bold; padding: 0 12px; }"
            "QPushButton:hover { background: #388e3c; }"
            "QPushButton:disabled { background: #333; color: #666; }"
        )
        self._reject_btn = QPushButton("Reject (Ctrl+R)")
        self._reject_btn.setIcon(load_icon("x"))
        self._reject_btn.setIconSize(QSize(16, 16))
        self._reject_btn.setFixedHeight(36)
        self._reject_btn.setStyleSheet(
            "QPushButton { background: #b71c1c; color: white; border-radius: 4px; font-size: 13px; font-weight: bold; padding: 0 12px; }"
            "QPushButton:hover { background: #c62828; }"
            "QPushButton:disabled { background: #333; color: #666; }"
        )
        self._revise_btn = QPushButton("Revise… (Ctrl+E)")
        self._revise_btn.setIcon(load_icon("restart"))
        self._revise_btn.setIconSize(QSize(16, 16))
        self._revise_btn.setFixedHeight(36)
        self._revise_btn.setStyleSheet(
            "QPushButton { background: #0d47a1; color: white; border-radius: 4px; font-size: 13px; font-weight: bold; padding: 0 12px; }"
            "QPushButton:hover { background: #1565c0; }"
            "QPushButton:disabled { background: #333; color: #666; }"
        )
        btn_row.addWidget(self._approve_btn)
        btn_row.addWidget(self._reject_btn)
        btn_row.addWidget(self._revise_btn)
        self._content_layout.addLayout(btn_row)

        # Revision area (hidden until Revise clicked)
        self._revision_area = QWidget()
        rev_layout = QVBoxLayout(self._revision_area)
        rev_layout.setContentsMargins(0, 8, 0, 0)
        rev_layout.setSpacing(6)
        rev_layout.addWidget(QLabel("Feedback for Claude:"))
        self._feedback_edit = QTextEdit()
        self._feedback_edit.setFixedHeight(80)
        self._feedback_edit.setPlaceholderText("Describe what to change or what's wrong with this plan…")
        self._feedback_edit.setStyleSheet(
            "QTextEdit { background: #1e1e1e; color: #ccc; border: 1px solid #555; "
            "border-radius: 4px; padding: 4px; font-size: 12px; }"
        )
        rev_layout.addWidget(self._feedback_edit)
        rev_btns = QHBoxLayout()
        self._send_feedback_btn = QPushButton("Send Feedback")
        self._send_feedback_btn.setFixedHeight(30)
        self._send_feedback_btn.setStyleSheet(
            "QPushButton { background: #1565c0; color: white; border-radius: 4px; }"
            "QPushButton:hover { background: #1976d2; }"
        )
        self._cancel_revise_btn = QPushButton("Cancel")
        self._cancel_revise_btn.setFixedHeight(30)
        self._cancel_revise_btn.setStyleSheet(
            "QPushButton { background: #444; color: #ccc; border-radius: 4px; }"
            "QPushButton:hover { background: #555; }"
        )
        rev_btns.addWidget(self._send_feedback_btn)
        rev_btns.addWidget(self._cancel_revise_btn)
        rev_layout.addLayout(rev_btns)
        self._content_layout.addWidget(self._revision_area)
        self._revision_area.setVisible(False)

        self._content_layout.addStretch()

        scroll.setWidget(content)
        self._plan_widget = scroll
        root.addWidget(self._plan_widget)

        # Connect buttons
        self._approve_btn.clicked.connect(self._on_approve)
        self._reject_btn.clicked.connect(self._on_reject)
        self._revise_btn.clicked.connect(self._on_revise)
        self._send_feedback_btn.clicked.connect(self._on_send_feedback)
        self._cancel_revise_btn.clicked.connect(self._on_cancel_revise)

        # Keyboard shortcuts (disabled until a plan is shown)
        self._approve_shortcut = QShortcut(QKeySequence("Ctrl+A"), self)
        self._approve_shortcut.activated.connect(self._on_approve)
        self._approve_shortcut.setEnabled(False)
        self._reject_shortcut = QShortcut(QKeySequence("Ctrl+R"), self)
        self._reject_shortcut.activated.connect(self._on_reject)
        self._reject_shortcut.setEnabled(False)
        self._revise_shortcut = QShortcut(QKeySequence("Ctrl+E"), self)
        self._revise_shortcut.activated.connect(self._on_revise)
        self._revise_shortcut.setEnabled(False)

    # --- State transitions ---

    def show_idle(self) -> None:
        self._idle_widget.setVisible(True)
        self._running_label.setVisible(False)
        self._done_label.setVisible(False)
        self._plan_widget.setVisible(False)

    def show_running(self) -> None:
        self._idle_widget.setVisible(False)
        self._running_label.setVisible(True)
        self._done_label.setVisible(False)
        self._plan_widget.setVisible(False)

    def show_done(self) -> None:
        self._idle_widget.setVisible(False)
        self._running_label.setVisible(False)
        self._done_label.setVisible(True)
        self._plan_widget.setVisible(False)

    def show_plan(self, plan: DiscoveredPlan, iteration: int) -> None:
        """Populate the card with plan data and show action buttons."""
        self._idle_widget.setVisible(False)
        self._running_label.setVisible(False)
        self._done_label.setVisible(False)
        self._plan_widget.setVisible(True)
        self._revision_area.setVisible(False)
        self._feedback_edit.clear()

        cat = plan.category.value
        color = _CATEGORY_COLORS.get(cat, "#9e9e9e")
        self._category_badge.setText(cat.replace("_", " ").title())
        self._category_badge.setStyleSheet(
            f"background: {color}; border-radius: 4px; padding: 2px 8px;"
            "font-size: 11px; font-weight: bold; color: white;"
        )

        effort = _EFFORT_LABELS.get(plan.estimated_effort.value, plan.estimated_effort.value)
        self._effort_badge.setText(f"Effort: {effort}")

        priority_text = _PRIORITY_LABELS.get(plan.priority, str(plan.priority))
        self._priority_label.setText(f"우선순위: {priority_text}")

        self._iteration_label.setText(f"#{iteration}")
        self._title_label.setText(plan.title)
        self._desc_label.setText(plan.description)
        self._rationale_label.setText(plan.rationale)

        self._files_list.clear()
        for f in plan.files_affected:
            self._files_list.addItem(QListWidgetItem(f))
        self._files_list.setVisible(bool(plan.files_affected))
        # Resize to content
        self._files_list.setMaximumHeight(
            min(120, max(40, self._files_list.count() * 22 + 8))
        )

        self._steps_list.clear()
        for i, step in enumerate(plan.implementation_steps, 1):
            self._steps_list.addItem(QListWidgetItem(f"{i}. {step}"))
        self._steps_list.setMaximumHeight(
            min(200, max(60, self._steps_list.count() * 26 + 8))
        )

        if plan.risks:
            self._risks_heading.setVisible(True)
            self._risks_label.setVisible(True)
            self._risks_label.setText("\n".join(f"• {r}" for r in plan.risks))
        else:
            self._risks_heading.setVisible(False)
            self._risks_label.setVisible(False)

        self._set_buttons_enabled(True)

    # --- Button handlers ---

    def _set_buttons_enabled(self, enabled: bool) -> None:
        self._approve_btn.setEnabled(enabled)
        self._reject_btn.setEnabled(enabled)
        self._revise_btn.setEnabled(enabled)
        self._approve_shortcut.setEnabled(enabled)
        self._reject_shortcut.setEnabled(enabled)
        self._revise_shortcut.setEnabled(enabled)

    def _on_approve(self) -> None:
        self._set_buttons_enabled(False)
        self.approval_submitted.emit("approve", "")

    def _on_reject(self) -> None:
        reason, ok = QInputDialog.getText(
            self, "Reject Plan", "Reason (optional, press OK to skip):"
        )
        if ok:
            self._set_buttons_enabled(False)
            self.approval_submitted.emit("reject", reason)
        # If user pressed Cancel on the dialog, do nothing (keep buttons enabled)

    def _on_revise(self) -> None:
        self._revision_area.setVisible(True)
        self._revise_btn.setEnabled(False)
        self._feedback_edit.setFocus()

    def _on_send_feedback(self) -> None:
        feedback = self._feedback_edit.toPlainText().strip()
        if not feedback:
            self._feedback_edit.setStyleSheet(
                "QTextEdit { background: #1e1e1e; color: #ccc; border: 2px solid #f44336; "
                "border-radius: 4px; padding: 4px; font-size: 12px; }"
            )
            self._feedback_edit.setFocus()
            return
        self._feedback_edit.setStyleSheet(
            "QTextEdit { background: #1e1e1e; color: #ccc; border: 1px solid #555; "
            "border-radius: 4px; padding: 4px; font-size: 12px; }"
        )
        self._set_buttons_enabled(False)
        self._revision_area.setVisible(False)
        self.approval_submitted.emit("revise", feedback)

    def _on_cancel_revise(self) -> None:
        self._revision_area.setVisible(False)
        self._revise_btn.setEnabled(True)
        self._feedback_edit.clear()


def _section_heading(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet("color: #aaa; font-size: 11px; font-weight: bold; text-transform: uppercase;")
    return lbl


def _section_label(style: str = "", color: str = "#cccccc") -> QLabel:
    lbl = QLabel()
    lbl.setWordWrap(True)
    lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    font_style = f"font-style: {style};" if style else ""
    lbl.setStyleSheet(f"color: {color}; font-size: 13px; {font_style}")
    return lbl
