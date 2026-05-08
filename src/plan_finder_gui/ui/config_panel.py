from __future__ import annotations

from datetime import datetime as ddatetime

from PySide6.QtCore import QDate, QEvent, QObject, QSettings, Qt, QTime, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTextEdit,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)


class _WheelBlocker(QObject):
    """Event filter that swallows wheel events on focus-sensitive inputs.

    Spinboxes and comboboxes change value on scroll by default, which is easy
    to trigger by accident while scrolling the surrounding panel.
    """

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Wheel:
            event.ignore()
            return True
        return False


_MODELS = [
    "claude-opus-4-5",
    "claude-sonnet-4-5",
    "claude-haiku-4-5",
    "claude-opus-4-7",
    "claude-sonnet-4-6",
]

_INPUT_H = 26   # uniform height for all single-line inputs


class ConfigPanel(QWidget):
    """왼쪽 사이드바: 프로젝트·프롬프트·세션 설정."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setStyleSheet("background: #1e1e1e;")
        self._wheel_blocker = _WheelBlocker(self)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            "QScrollArea { border: none; background: #1e1e1e; }"
            "QScrollBar:vertical { width: 0px; }"
            "QScrollBar:horizontal { height: 0px; }"
        )
        outer.addWidget(scroll, stretch=1)

        inner = QWidget()
        inner.setStyleSheet("background: #1e1e1e;")
        inner.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        scroll.setWidget(inner)

        # ── 프로젝트 ─────────────────────────────────────────────
        proj_group = _group("프로젝트")
        proj_form = _form()

        dir_row = QHBoxLayout()
        dir_row.setSpacing(4)
        self.project_dir_edit = QLineEdit()
        self.project_dir_edit.setPlaceholderText("/경로/프로젝트")
        self.project_dir_edit.setFixedHeight(_INPUT_H)
        _style_input(self.project_dir_edit)
        self.browse_btn = QPushButton("…")
        self.browse_btn.setFixedWidth(28)
        self.browse_btn.setFixedHeight(_INPUT_H)
        self.browse_btn.setStyleSheet(
            "QPushButton { background: #333; color: #ccc; border-radius: 3px; }"
            "QPushButton:hover { background: #444; }"
            "QPushButton:disabled { background: #2a2a2a; color: #555; }"
        )
        self.browse_btn.clicked.connect(self._browse_project)
        dir_row.addWidget(self.project_dir_edit)
        dir_row.addWidget(self.browse_btn)

        proj_form.addRow(_label("디렉토리"), _wrap(dir_row))
        proj_group.layout().addLayout(proj_form)
        proj_group.layout().addStretch()
        layout.addWidget(proj_group, stretch=1)

        # ── 프롬프트 ─────────────────────────────────────────────
        prompt_group = _group("프롬프트")

        # Preset selector row
        preset_row = QHBoxLayout()
        preset_row.setContentsMargins(0, 0, 0, 0)
        preset_row.setSpacing(4)
        self.preset_combo = QComboBox()
        self.preset_combo.setFixedHeight(_INPUT_H)
        self.preset_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        _style_combo(self.preset_combo)
        preset_refresh_btn = QPushButton("↻")
        preset_refresh_btn.setFixedSize(_INPUT_H, _INPUT_H)
        preset_refresh_btn.setToolTip("프리셋 목록 새로고침")
        preset_refresh_btn.setStyleSheet(
            "QPushButton { background: #333; color: #ccc; border-radius: 3px; }"
            "QPushButton:hover { background: #444; }"
        )
        preset_refresh_btn.clicked.connect(self.refresh_presets)
        preset_row.addWidget(self.preset_combo, stretch=1)
        preset_row.addWidget(preset_refresh_btn)
        prompt_group.layout().addLayout(preset_row)

        self.prompt_edit = QTextEdit()
        self.prompt_edit.setPlaceholderText(
            "예: 버그 찾기, 에러 처리 개선, 타입 힌트 추가…"
        )
        self.prompt_edit.setMinimumHeight(80)
        self.prompt_edit.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.prompt_edit.setStyleSheet(
            "QTextEdit { background: #2d2d2d; color: #ccc; border: 1px solid #444;"
            "border-radius: 4px; padding: 4px 6px; font-size: 12px; }"
            "QTextEdit:read-only { background: #262626; color: #aaa; }"
        )
        prompt_group.layout().addWidget(self.prompt_edit)
        layout.addWidget(prompt_group, stretch=4)

        # Stash custom-typed prompt so we can restore it when toggling between
        # presets and "직접 입력". Populated from QSettings in restore_settings().
        self._custom_prompt: str = ""
        self._loading_preset: bool = False  # guard against textChanged feedback
        self.prompt_edit.textChanged.connect(self._on_prompt_text_changed)
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        self.refresh_presets()

        # ── 세션 설정 ─────────────────────────────────────────────
        sess_group = _group("세션 설정")
        sess_form = _form()

        self.model_combo = QComboBox()
        self.model_combo.addItems(_MODELS)
        self.model_combo.setEditable(True)
        self.model_combo.setCurrentIndex(0)
        self.model_combo.setFixedHeight(_INPUT_H)
        self.model_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        _style_combo(self.model_combo)

        self.budget_spin = QDoubleSpinBox()
        self.budget_spin.setRange(1.0, 500.0)
        self.budget_spin.setValue(80.0)
        self.budget_spin.setSuffix(" $")
        self.budget_spin.setSingleStep(5.0)
        self.budget_spin.setFixedHeight(_INPUT_H)
        self.budget_spin.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        _style_spin(self.budget_spin)

        self.max_iter_spin = QSpinBox()
        self.max_iter_spin.setRange(0, 9999)
        self.max_iter_spin.setValue(0)
        self.max_iter_spin.setSpecialValueText("∞")
        self.max_iter_spin.setFixedHeight(_INPUT_H)
        self.max_iter_spin.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        _style_spin_with_arrows(self.max_iter_spin)

        self.max_turns_spin = QSpinBox()
        self.max_turns_spin.setRange(1, 200)
        self.max_turns_spin.setValue(80)
        self.max_turns_spin.setFixedHeight(_INPUT_H)
        self.max_turns_spin.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        _style_spin(self.max_turns_spin)

        for w in (
            self.model_combo,
            self.budget_spin,
            self.max_iter_spin,
            self.max_turns_spin,
        ):
            w.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            w.installEventFilter(self._wheel_blocker)

        sess_form.addRow(_label("모델"),      _with_info(self.model_combo, _INFO_MODEL))
        sess_form.addRow(_label("예산"),      _with_info(self.budget_spin, _INFO_BUDGET))
        sess_form.addRow(_label("최대 반복"), _with_info(self.max_iter_spin, _INFO_MAX_ITER))
        sess_form.addRow(_label("최대 턴"),   _with_info(self.max_turns_spin, _INFO_MAX_TURNS))

        # 중단 시간 (날짜 + 시간)
        stop_row = QHBoxLayout()
        stop_row.setSpacing(6)
        self.stop_at_check = QCheckBox()
        self.stop_at_check.setStyleSheet("QCheckBox { color: #ccc; padding-right: 6px; }")
        self.stop_at_check.setFixedHeight(_INPUT_H)

        self.stop_at_date_edit = QDateEdit()
        self.stop_at_date_edit.setDisplayFormat("yyyy-MM-dd")
        self.stop_at_date_edit.setDate(QDate.currentDate())
        self.stop_at_date_edit.setCalendarPopup(True)
        self.stop_at_date_edit.setFixedHeight(_INPUT_H)
        self.stop_at_date_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        _style_spin(self.stop_at_date_edit)

        self.stop_at_time_edit = QTimeEdit()
        self.stop_at_time_edit.setDisplayFormat("HH:mm")
        self.stop_at_time_edit.setTime(QTime(7, 30))
        self.stop_at_time_edit.setFixedHeight(_INPUT_H)
        self.stop_at_time_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        _style_spin(self.stop_at_time_edit)

        for w in (self.stop_at_date_edit, self.stop_at_time_edit):
            w.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            w.installEventFilter(self._wheel_blocker)

        self.stop_at_hint = QLabel("체크 시 종료 시간 설정")
        self.stop_at_hint.setStyleSheet(
            "color: #888; font-size: 11px; background: transparent;"
        )
        self.stop_at_hint.setFixedHeight(_INPUT_H)
        self.stop_at_hint.setMinimumWidth(0)
        self.stop_at_hint.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

        def _toggle_stop_at(checked: bool) -> None:
            self.stop_at_date_edit.setVisible(checked)
            self.stop_at_time_edit.setVisible(checked)
            self.stop_at_hint.setVisible(not checked)

        self.stop_at_check.toggled.connect(_toggle_stop_at)
        stop_row.addWidget(self.stop_at_check)
        stop_row.addWidget(self.stop_at_date_edit)
        stop_row.addWidget(self.stop_at_time_edit)
        stop_row.addWidget(self.stop_at_hint, stretch=1)
        # Initial state: checkbox starts unchecked, so hide editors and show hint.
        self.stop_at_date_edit.setVisible(False)
        self.stop_at_time_edit.setVisible(False)

        stop_with_info = QHBoxLayout()
        stop_with_info.setContentsMargins(0, 0, 0, 0)
        stop_with_info.setSpacing(4)
        stop_with_info.addWidget(_wrap(stop_row), stretch=1)
        stop_with_info.addWidget(_info_btn(_INFO_STOP_AT))
        sess_form.addRow(_label("중단 시간"), _wrap(stop_with_info))

        sess_group.layout().addLayout(sess_form)
        sess_group.layout().addStretch()
        layout.addWidget(sess_group, stretch=2)

        # ── 옵션 ────────────────────────────────────────────────
        opts_group = _group("옵션")
        self.auto_check = QCheckBox("자동 모드")
        self.auto_check.setChecked(True)
        self.auto_check.setVisible(False)
        self.throttle_check = QCheckBox("스로틀 사용 (ccusage 필요)")
        self.no_resume_check = QCheckBox("매 반복마다 새 세션")
        for cb, info in (
            (self.throttle_check,  _INFO_THROTTLE),
            (self.no_resume_check, _INFO_NO_RESUME),
        ):
            cb.setStyleSheet("QCheckBox { color: #ccc; font-size: 12px; }")
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(4)
            row.addWidget(cb)
            row.addStretch()
            row.addWidget(_info_btn(info))
            opts_group.layout().addLayout(row)
        opts_group.layout().addStretch()
        layout.addWidget(opts_group, stretch=1)

        # ── 번역 ────────────────────────────────────────────────
        trans_group = _group("번역")
        self.translate_check = QCheckBox("리포트 자동 번역")
        self.translate_check.setStyleSheet("QCheckBox { color: #ccc; font-size: 12px; }")
        trans_group.layout().addWidget(self.translate_check)

        self.translate_method_combo = QComboBox()
        self.translate_method_combo.addItems(["Google Translate API", "Claude"])
        self.translate_method_combo.setFixedHeight(_INPUT_H)
        self.translate_method_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        _style_combo(self.translate_method_combo)
        self.translate_method_combo.setVisible(False)
        trans_group.layout().addWidget(self.translate_method_combo)

        self.translate_check.toggled.connect(self.translate_method_combo.setVisible)
        trans_group.layout().addStretch()
        layout.addWidget(trans_group, stretch=1)

        self.restore_settings()

        # Start / Stop buttons live here as attributes only — MainWindow
        # reparents them into a fixed footer at the bottom of the sidebar.
        self.start_btn = QPushButton("▶  시작")
        self.start_btn.setFixedHeight(36)
        self.start_btn.setStyleSheet(
            "QPushButton { background: #0e78d5; color: white; border-radius: 4px;"
            "font-size: 13px; font-weight: bold; }"
            "QPushButton:hover { background: #1e88e5; }"
            "QPushButton:disabled { background: #333; color: #666; }"
        )
        self.stop_btn = QPushButton("■  중단")
        self.stop_btn.setFixedHeight(36)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet(
            "QPushButton { background: #444; color: #ccc; border-radius: 4px;"
            "font-size: 13px; }"
            "QPushButton:hover { background: #555; }"
            "QPushButton:disabled { background: #2a2a2a; color: #555; }"
        )

    # ------------------------------------------------------------------ #

    def get_config(self) -> dict:
        stop_at = None
        if self.stop_at_check.isChecked():
            qd = self.stop_at_date_edit.date()
            qt = self.stop_at_time_edit.time()
            stop_at = ddatetime(qd.year(), qd.month(), qd.day(), qt.hour(), qt.minute())

        # Only expose the API key if the latest validation marked it valid —
        # QSettings is the source of truth here (we clear it on invalid).
        validated_key = str(QSettings().value("anthropic_api_key", "") or "")

        return {
            "project_dir":      self.project_dir_edit.text().strip(),
            "prompt":           self.prompt_edit.toPlainText().strip(),
            "model":            self.model_combo.currentText().strip(),
            "budget":           self.budget_spin.value(),
            "max_iter":         self.max_iter_spin.value() or None,
            "max_turns":        self.max_turns_spin.value(),
            "auto":             True,
            "throttle_enabled": self.throttle_check.isChecked(),
            "no_resume":        self.no_resume_check.isChecked(),
            "stop_at":          stop_at,
            "translate_enabled":self.translate_check.isChecked(),
            "translate_method": self.translate_method_combo.currentText(),
            "anthropic_api_key": validated_key,
        }

    def save_settings(self) -> None:
        s = QSettings()
        s.setValue("project_dir",       self.project_dir_edit.text())
        # Persist the user's custom prompt independently from any preset body
        # so switching to "직접 입력" restores their last-typed text.
        s.setValue("prompt",            self._custom_prompt)
        s.setValue("preset",            self.preset_combo.currentData() or "")
        s.setValue("model",             self.model_combo.currentText())
        s.setValue("budget",            self.budget_spin.value())
        s.setValue("max_iter",          self.max_iter_spin.value())
        s.setValue("max_turns",         self.max_turns_spin.value())
        s.setValue("stop_at_enabled",   self.stop_at_check.isChecked())
        d = self.stop_at_date_edit.date()
        t = self.stop_at_time_edit.time()
        s.setValue("stop_at_date",      f"{d.year():04d}-{d.month():02d}-{d.day():02d}")
        s.setValue("stop_at_time",      f"{t.hour():02d}:{t.minute():02d}")
        s.setValue("throttle_enabled",  self.throttle_check.isChecked())
        s.setValue("no_resume",         self.no_resume_check.isChecked())
        s.setValue("translate_enabled", self.translate_check.isChecked())
        s.setValue("translate_method",  self.translate_method_combo.currentText())

    def restore_settings(self) -> None:
        s = QSettings()

        project_dir = s.value("project_dir", "")
        if project_dir:
            self.project_dir_edit.setText(str(project_dir))

        prompt = s.value("prompt", "")
        self._custom_prompt = str(prompt) if prompt else ""

        # Apply saved preset selection if it still exists; otherwise fall back
        # to "직접 입력" with the user's saved custom prompt.
        saved_preset = str(s.value("preset", "") or "")
        idx = self.preset_combo.findData(saved_preset) if saved_preset else 0
        if idx < 0:
            idx = 0
        self._loading_preset = True
        self.preset_combo.setCurrentIndex(idx)
        self._loading_preset = False
        # Trigger the handler manually so the prompt edit reflects the choice
        # even when the index didn't actually change.
        self._on_preset_changed(idx)

        model = s.value("model", "")
        if model:
            idx = self.model_combo.findText(str(model))
            if idx >= 0:
                self.model_combo.setCurrentIndex(idx)
            else:
                self.model_combo.setCurrentText(str(model))

        for attr, key, cast in (
            ("budget_spin",    "budget",    float),
            ("max_iter_spin",  "max_iter",  int),
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

        stop_at_date = s.value("stop_at_date", "")
        if stop_at_date:
            try:
                y, mo, d = str(stop_at_date).split("-")
                self.stop_at_date_edit.setDate(QDate(int(y), int(mo), int(d)))
            except (ValueError, AttributeError):
                pass

        stop_at_time = s.value("stop_at_time", "07:30")
        try:
            h, m = str(stop_at_time).split(":")
            self.stop_at_time_edit.setTime(QTime(int(h), int(m)))
        except (ValueError, AttributeError):
            pass

        for attr, key in (
            ("throttle_check",  "throttle_enabled"),
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
            self, "프로젝트 디렉토리 선택", self.project_dir_edit.text() or ""
        )
        if path:
            self.project_dir_edit.setText(path)

    def set_project_dir_locked(self, locked: bool) -> None:
        """Enable or disable the project directory input and browse button.

        When locked, the user cannot change the project directory. This prevents
        UI desync where the report browser shows a different project than the
        one being processed by an active session.
        """
        self.project_dir_edit.setEnabled(not locked)
        self.browse_btn.setEnabled(not locked)
        if locked:
            self.project_dir_edit.setToolTip(
                "Cannot change project directory while session is running"
            )
            self.browse_btn.setToolTip(
                "Cannot change project directory while session is running"
            )
        else:
            self.project_dir_edit.setToolTip("")
            self.browse_btn.setToolTip("")

    # ------------------------------------------------------------------ #
    #  Preset handling                                                     #
    # ------------------------------------------------------------------ #

    def refresh_presets(self) -> None:
        """Re-scan bundled + user preset directories and rebuild the combo."""
        from ..engine.preset import list_presets

        prev = self.preset_combo.currentData() if self.preset_combo.count() else ""
        self._loading_preset = True
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        # First entry: free-form custom prompt
        self.preset_combo.addItem("직접 입력", "")
        for p in list_presets():
            self.preset_combo.addItem(p.title, p.name)
        # Restore previous selection if still available
        idx = self.preset_combo.findData(prev) if prev else 0
        if idx < 0:
            idx = 0
        self.preset_combo.setCurrentIndex(idx)
        self.preset_combo.blockSignals(False)
        self._loading_preset = False
        self._on_preset_changed(idx)

    def _on_preset_changed(self, _idx: int) -> None:
        """Sync the prompt edit with the currently selected preset."""
        from ..engine.preset import load_preset

        name = self.preset_combo.currentData() or ""
        self._loading_preset = True
        try:
            if not name:
                # "직접 입력" — restore the user's last custom prompt and unlock
                self.prompt_edit.setReadOnly(False)
                self.prompt_edit.setPlainText(self._custom_prompt)
            else:
                preset = load_preset(str(name))
                if preset is None:
                    # Preset disappeared (e.g. user removed file); fall back.
                    self.prompt_edit.setReadOnly(False)
                    self.prompt_edit.setPlainText(self._custom_prompt)
                else:
                    self.prompt_edit.setPlainText(preset.prompt)
                    self.prompt_edit.setReadOnly(True)
        finally:
            self._loading_preset = False

    def _on_prompt_text_changed(self) -> None:
        """When 직접 입력 mode is active, remember the user's typed prompt."""
        if self._loading_preset:
            return
        if not (self.preset_combo.currentData() or ""):
            self._custom_prompt = self.prompt_edit.toPlainText()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _group(title: str) -> QGroupBox:
    g = QGroupBox(title)
    g.setStyleSheet(
        "QGroupBox {"
        "  color: #888; font-size: 10px; font-weight: bold;"
        "  border: 1px solid #333; border-radius: 4px;"
        "  margin-top: 8px; padding-top: 4px;"
        "}"
        "QGroupBox::title { subcontrol-origin: margin; left: 8px; top: -1px; }"
    )
    g.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
    inner = QVBoxLayout()
    inner.setContentsMargins(10, 10, 10, 10)
    inner.setSpacing(6)
    g.setLayout(inner)
    return g


def _form() -> QFormLayout:
    f = QFormLayout()
    f.setContentsMargins(0, 0, 0, 0)
    f.setSpacing(6)
    f.setHorizontalSpacing(8)
    f.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    f.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    return f


def _label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet("color: #888; font-size: 11px;")
    lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return lbl


def _style_input(w: QLineEdit) -> None:
    w.setStyleSheet(
        "QLineEdit { background: #2d2d2d; color: #ccc; border: 1px solid #444;"
        "border-radius: 4px; padding: 3px 6px; font-size: 12px; }"
        "QLineEdit:focus { border-color: #0e78d5; }"
        "QLineEdit:disabled { background: #262626; color: #666; }"
    )


def _style_spin(w: QWidget) -> None:
    w.setStyleSheet(
        "background: #2d2d2d; color: #ccc; border: 1px solid #444;"
        "border-radius: 4px; padding: 2px 4px; font-size: 12px;"
        "QAbstractSpinBox::up-button { width: 0px; image: none; }"
        "QAbstractSpinBox::down-button { width: 0px; image: none; }"
        "QDateEdit::drop-down { width: 18px; background: #2d2d2d;"
        "  border-left: 1px solid #444; }"
    )


def _style_spin_with_arrows(w: QWidget) -> None:
    """Like _style_spin but keeps up/down buttons visible (used for max_iter_spin)."""
    w.setStyleSheet(
        "background: #2d2d2d; color: #ccc; border: 1px solid #444;"
        "border-radius: 4px; padding: 2px 4px; font-size: 12px;"
        "QAbstractSpinBox::up-button { width: 14px; background: #333;"
        "  border-left: 1px solid #444; border-bottom: 1px solid #444; }"
        "QAbstractSpinBox::down-button { width: 14px; background: #333;"
        "  border-left: 1px solid #444; }"
    )


def _style_combo(w: QComboBox) -> None:
    w.setStyleSheet(
        "QComboBox { background: #2d2d2d; color: #ccc; border: 1px solid #444;"
        "border-radius: 4px; padding: 2px 6px; font-size: 12px; }"
        "QComboBox::drop-down { border: none; width: 0px; }"
        "QComboBox::down-arrow { image: none; width: 0; height: 0; }"
        "QComboBox QAbstractItemView { background: #2d2d2d; color: #ccc; }"
    )


def _wrap(layout) -> QWidget:
    w = QWidget()
    w.setStyleSheet("background: transparent;")
    w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    w.setLayout(layout)
    layout.setContentsMargins(0, 0, 0, 0)
    return w


# ---------------------------------------------------------------------------
# (i) info button helpers
# ---------------------------------------------------------------------------

_INFO_MODEL = (
    "사용할 Claude 모델을 선택합니다.\n\n"
    "• claude-opus: 가장 강력하지만 느리고 비용이 높습니다.\n"
    "• claude-sonnet: 성능과 비용의 균형이 잡힌 추천 모델입니다.\n"
    "• claude-haiku: 빠르고 저렴하며 간단한 작업에 적합합니다.\n\n"
    "직접 모델 ID를 입력할 수도 있습니다."
)

_INFO_BUDGET = (
    "스로틀 기능 활성화 시 사용하는 세션당 최대 비용 한도($)입니다.\n\n"
    "현재까지 사용한 비용 비율이 경과 시간 비율의 1.05배를 초과하면\n"
    "잠시 대기 후 재개합니다.\n\n"
    "예: 세션이 40% 경과했을 때 비용이 42% 이상이면 대기합니다."
)

_INFO_MAX_ITER = (
    "플랜을 찾는 최대 반복 횟수입니다.\n\n"
    "• 0: 무제한으로 실행합니다.\n"
    "• 1~N: 해당 횟수만큼 반복 후 자동 종료합니다.\n\n"
    "각 반복마다 Claude가 새 개선 플랜을 하나씩 제안합니다."
)

_INFO_MAX_TURNS = (
    "각 반복에서 Claude와의 최대 대화 턴 수입니다.\n\n"
    "턴 수가 높을수록 복잡한 코드베이스를 더 깊이 분석할 수 있지만\n"
    "비용과 시간이 증가합니다.\n\n"
    "기본값 80은 대부분의 프로젝트에 충분합니다."
)

_INFO_STOP_AT = (
    "지정한 날짜·시간에 세션을 자동으로 중단합니다.\n\n"
    "야간 자동 실행 시 다음 날 아침 시간을 지정해두면\n"
    "원하는 시간에 종료됩니다.\n\n"
    "체크박스를 해제하면 이 기능이 비활성화됩니다."
)

_INFO_THROTTLE = (
    "비용 사용 속도를 자동으로 조절합니다 (ccusage 필요).\n\n"
    "ccusage가 감지한 현재 세션의 시작·종료 시간과\n"
    "이 설정의 예산을 기준으로 속도를 제한합니다.\n\n"
    "설치: brew install ccusage"
)

_INFO_NO_RESUME = (
    "매 반복마다 이전 대화 컨텍스트를 이어가지 않고\n"
    "새 Claude 세션으로 시작합니다.\n\n"
    "기본적으로 세션을 이어가는 것이 더 효율적입니다.\n"
    "컨텍스트가 너무 길어 오류가 발생할 때 활성화하세요."
)


def _info_btn(text: str) -> QPushButton:
    btn = QPushButton("ⓘ")
    btn.setFixedSize(18, 18)
    btn.setStyleSheet(
        "QPushButton { background: #2a2a2a; color: #666; border-radius: 9px;"
        " font-size: 10px; padding: 0; border: 1px solid #444; }"
        "QPushButton:hover { background: #383838; color: #aaa; }"
    )
    btn.setToolTip(text)

    def _show():
        dlg = QMessageBox()
        dlg.setWindowTitle("설명")
        dlg.setText(text)
        dlg.setIcon(QMessageBox.Icon.Information)
        dlg.exec()

    btn.clicked.connect(_show)
    return btn


def _with_info(widget: QWidget, info_text: str) -> QWidget:
    container = QWidget()
    container.setStyleSheet("background: transparent;")
    container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    lay = QHBoxLayout(container)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(4)
    lay.addWidget(widget, stretch=1)
    lay.addWidget(_info_btn(info_text))
    return container
