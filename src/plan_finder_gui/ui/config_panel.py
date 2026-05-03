from __future__ import annotations

from datetime import time as dtime

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTextEdit,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import QTime

_MODELS = [
    "claude-opus-4-5",
    "claude-sonnet-4-5",
    "claude-haiku-4-5",
    "claude-opus-4-7",
    "claude-sonnet-4-6",
]


class ConfigPanel(QWidget):
    """Left sidebar: project, prompt, and session settings."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(260)
        self.setMaximumWidth(380)
        self.setStyleSheet("background: #1e1e1e;")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: #1e1e1e; }")
        outer.addWidget(scroll, stretch=1)

        inner = QWidget()
        inner.setStyleSheet("background: #1e1e1e;")
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(12, 12, 12, 8)
        layout.setSpacing(12)
        scroll.setWidget(inner)

        # -- Title --
        title = QLabel("Plan Finder")
        title.setStyleSheet("color: #e8e8e8; font-size: 16px; font-weight: bold; padding: 4px 0;")
        layout.addWidget(title)

        # -- Project group --
        proj_group = _group("Project")
        proj_form = QFormLayout()
        proj_form.setSpacing(6)

        dir_row = QHBoxLayout()
        self.project_dir_edit = QLineEdit()
        self.project_dir_edit.setPlaceholderText("/path/to/project")
        _style_input(self.project_dir_edit)
        browse_btn = QPushButton("…")
        browse_btn.setFixedWidth(28)
        browse_btn.setFixedHeight(26)
        browse_btn.setStyleSheet(
            "QPushButton { background: #333; color: #ccc; border-radius: 3px; }"
            "QPushButton:hover { background: #444; }"
        )
        browse_btn.clicked.connect(self._browse_project)
        dir_row.addWidget(self.project_dir_edit)
        dir_row.addWidget(browse_btn)

        proj_form.addRow(_label("Directory"), _wrap(dir_row))
        proj_group.layout().addLayout(proj_form)
        layout.addWidget(proj_group)

        # -- Prompt group --
        prompt_group = _group("Prompt")
        p_layout = QVBoxLayout()
        self.prompt_edit = QTextEdit()
        self.prompt_edit.setPlaceholderText(
            "e.g. Find bugs, improve error handling, add type hints…"
        )
        self.prompt_edit.setMinimumHeight(80)
        self.prompt_edit.setMaximumHeight(140)
        self.prompt_edit.setStyleSheet(
            "QTextEdit { background: #2d2d2d; color: #ccc; border: 1px solid #444;"
            "border-radius: 4px; padding: 4px; font-size: 12px; }"
        )
        p_layout.addWidget(self.prompt_edit)
        prompt_group.layout().addLayout(p_layout)
        layout.addWidget(prompt_group)

        # -- Session settings group --
        sess_group = _group("Session Settings")
        sess_form = QFormLayout()
        sess_form.setSpacing(6)

        self.model_combo = QComboBox()
        self.model_combo.addItems(_MODELS)
        self.model_combo.setEditable(True)
        self.model_combo.setCurrentIndex(0)
        _style_combo(self.model_combo)

        self.budget_spin = QDoubleSpinBox()
        self.budget_spin.setRange(1.0, 500.0)
        self.budget_spin.setValue(40.0)
        self.budget_spin.setSuffix(" $")
        self.budget_spin.setSingleStep(5.0)
        _style_spin(self.budget_spin)

        self.max_iter_spin = QSpinBox()
        self.max_iter_spin.setRange(0, 9999)
        self.max_iter_spin.setValue(0)
        self.max_iter_spin.setSpecialValueText("∞")
        _style_spin(self.max_iter_spin)

        self.max_turns_spin = QSpinBox()
        self.max_turns_spin.setRange(1, 200)
        self.max_turns_spin.setValue(80)
        _style_spin(self.max_turns_spin)

        sess_form.addRow(_label("Model"), self.model_combo)
        sess_form.addRow(_label("Budget"), self.budget_spin)
        sess_form.addRow(_label("Max iter"), self.max_iter_spin)
        sess_form.addRow(_label("Max turns"), self.max_turns_spin)

        # Stop-at time
        stop_row = QHBoxLayout()
        self.stop_at_check = QCheckBox()
        self.stop_at_check.setStyleSheet("QCheckBox { color: #ccc; }")
        self.stop_at_edit = QTimeEdit()
        self.stop_at_edit.setDisplayFormat("HH:mm")
        self.stop_at_edit.setTime(QTime(7, 30))
        self.stop_at_edit.setEnabled(False)
        _style_spin(self.stop_at_edit)
        self.stop_at_check.toggled.connect(self.stop_at_edit.setEnabled)
        stop_row.addWidget(self.stop_at_check)
        stop_row.addWidget(self.stop_at_edit)
        stop_row.addStretch()
        sess_form.addRow(_label("Stop at"), _wrap(stop_row))

        sess_group.layout().addLayout(sess_form)
        layout.addWidget(sess_group)

        # -- Options group --
        opts_group = _group("Options")
        opts_layout = QVBoxLayout()
        # auto_check is hidden; auto mode is always on
        self.auto_check = QCheckBox("Auto mode (unattended)")
        self.auto_check.setChecked(True)
        self.auto_check.setVisible(False)
        self.throttle_check = QCheckBox("Enable throttle (requires ccusage)")
        self.no_resume_check = QCheckBox("Fresh session each iteration")
        for cb in (self.throttle_check, self.no_resume_check):
            cb.setStyleSheet("QCheckBox { color: #ccc; font-size: 12px; }")
            opts_layout.addWidget(cb)
        opts_group.layout().addLayout(opts_layout)
        layout.addWidget(opts_group)

        # -- Translation group --
        trans_group = _group("Translation")
        trans_layout = QVBoxLayout()
        self.translate_check = QCheckBox("Auto-translate reports")
        self.translate_check.setStyleSheet("QCheckBox { color: #ccc; font-size: 12px; }")
        trans_layout.addWidget(self.translate_check)

        self.translate_method_combo = QComboBox()
        self.translate_method_combo.addItems(["Google Translate API", "Claude"])
        _style_combo(self.translate_method_combo)
        self.translate_method_combo.setVisible(False)
        trans_layout.addWidget(self.translate_method_combo)

        self.translate_check.toggled.connect(self.translate_method_combo.setVisible)

        trans_group.layout().addLayout(trans_layout)
        layout.addWidget(trans_group)

        layout.addStretch()

        self.restore_settings()

        # -- Buttons --
        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("▶  Start")
        self.start_btn.setFixedHeight(36)
        self.start_btn.setStyleSheet(
            "QPushButton { background: #0e78d5; color: white; border-radius: 4px;"
            "font-size: 13px; font-weight: bold; }"
            "QPushButton:hover { background: #1e88e5; }"
            "QPushButton:disabled { background: #333; color: #666; }"
        )
        self.stop_btn = QPushButton("■  Stop")
        self.stop_btn.setFixedHeight(36)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet(
            "QPushButton { background: #444; color: #ccc; border-radius: 4px; font-size: 13px; }"
            "QPushButton:hover { background: #555; }"
            "QPushButton:disabled { background: #2a2a2a; color: #555; }"
        )
        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.stop_btn)

        btn_container = QWidget()
        btn_container.setStyleSheet("background: #1e1e1e;")
        bc_layout = QVBoxLayout(btn_container)
        bc_layout.setContentsMargins(12, 8, 12, 12)
        bc_layout.addLayout(btn_row)
        outer.addWidget(btn_container)

    def get_config(self) -> dict:
        """Return current field values."""
        stop_at = None
        if self.stop_at_check.isChecked():
            qt = self.stop_at_edit.time()
            stop_at = dtime(qt.hour(), qt.minute())

        return {
            "project_dir": self.project_dir_edit.text().strip(),
            "prompt": self.prompt_edit.toPlainText().strip(),
            "model": self.model_combo.currentText().strip(),
            "budget": self.budget_spin.value(),
            "max_iter": self.max_iter_spin.value() or None,
            "max_turns": self.max_turns_spin.value(),
            "auto": True,  # always on
            "throttle_enabled": self.throttle_check.isChecked(),
            "no_resume": self.no_resume_check.isChecked(),
            "stop_at": stop_at,
            "translate_enabled": self.translate_check.isChecked(),
            "translate_method": self.translate_method_combo.currentText(),
        }

    def save_settings(self) -> None:
        s = QSettings()
        s.setValue("project_dir", self.project_dir_edit.text())
        s.setValue("prompt", self.prompt_edit.toPlainText())
        s.setValue("model", self.model_combo.currentText())
        s.setValue("budget", self.budget_spin.value())
        s.setValue("max_iter", self.max_iter_spin.value())
        s.setValue("max_turns", self.max_turns_spin.value())
        s.setValue("stop_at_enabled", self.stop_at_check.isChecked())
        t = self.stop_at_edit.time()
        s.setValue("stop_at_time", f"{t.hour():02d}:{t.minute():02d}")
        s.setValue("throttle_enabled", self.throttle_check.isChecked())
        s.setValue("no_resume", self.no_resume_check.isChecked())
        s.setValue("translate_enabled", self.translate_check.isChecked())
        s.setValue("translate_method", self.translate_method_combo.currentText())

    def restore_settings(self) -> None:
        s = QSettings()

        project_dir = s.value("project_dir", "")
        if project_dir:
            self.project_dir_edit.setText(project_dir)

        prompt = s.value("prompt", "")
        if prompt:
            self.prompt_edit.setPlainText(prompt)

        model = s.value("model", "")
        if model:
            idx = self.model_combo.findText(model)
            if idx >= 0:
                self.model_combo.setCurrentIndex(idx)
            else:
                self.model_combo.setCurrentText(model)

        for attr, key, cast in (
            ("budget_spin", "budget", float),
            ("max_iter_spin", "max_iter", int),
            ("max_turns_spin", "max_turns", int),
        ):
            val = s.value(key)
            if val is not None:
                try:
                    getattr(self, attr).setValue(cast(val))
                except (ValueError, TypeError):
                    pass

        stop_at_enabled = s.value("stop_at_enabled", False)
        self.stop_at_check.setChecked(stop_at_enabled in (True, "true", "True", "1"))

        stop_at_time = s.value("stop_at_time", "07:30")
        try:
            h, m = str(stop_at_time).split(":")
            self.stop_at_edit.setTime(QTime(int(h), int(m)))
        except (ValueError, AttributeError):
            pass

        for attr, key in (
            ("throttle_check", "throttle_enabled"),
            ("no_resume_check", "no_resume"),
        ):
            val = s.value(key, False)
            getattr(self, attr).setChecked(val in (True, "true", "True", "1"))

        translate_enabled = s.value("translate_enabled", False)
        self.translate_check.setChecked(translate_enabled in (True, "true", "True", "1"))

        translate_method = s.value("translate_method", "Google Translate API")
        idx = self.translate_method_combo.findText(str(translate_method))
        if idx >= 0:
            self.translate_method_combo.setCurrentIndex(idx)

    def _browse_project(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Select Project Directory", self.project_dir_edit.text() or ""
        )
        if path:
            self.project_dir_edit.setText(path)


# --- helpers ---

def _group(title: str) -> QGroupBox:
    g = QGroupBox(title)
    g.setStyleSheet(
        "QGroupBox { color: #888; font-size: 10px; font-weight: bold;"
        "border: 1px solid #333; border-radius: 4px; margin-top: 8px; padding-top: 8px; }"
        "QGroupBox::title { subcontrol-origin: margin; left: 8px; }"
    )
    g.setLayout(QVBoxLayout())
    g.layout().setContentsMargins(8, 8, 8, 8)
    g.layout().setSpacing(4)
    return g


def _label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet("color: #888; font-size: 11px;")
    return lbl


def _style_input(w: QLineEdit) -> None:
    w.setStyleSheet(
        "QLineEdit { background: #2d2d2d; color: #ccc; border: 1px solid #444;"
        "border-radius: 4px; padding: 3px 6px; font-size: 12px; }"
        "QLineEdit:focus { border-color: #0e78d5; }"
    )


def _style_spin(w: QWidget) -> None:
    w.setStyleSheet(
        "background: #2d2d2d; color: #ccc; border: 1px solid #444;"
        "border-radius: 4px; padding: 2px 4px; font-size: 12px;"
    )


def _style_combo(w: QComboBox) -> None:
    w.setStyleSheet(
        "QComboBox { background: #2d2d2d; color: #ccc; border: 1px solid #444;"
        "border-radius: 4px; padding: 2px 4px; font-size: 12px; }"
        "QComboBox::drop-down { border: none; }"
        "QComboBox QAbstractItemView { background: #2d2d2d; color: #ccc; }"
    )


def _wrap(layout) -> QWidget:
    w = QWidget()
    w.setStyleSheet("background: transparent;")
    w.setLayout(layout)
    return w
