from __future__ import annotations

from datetime import datetime as ddatetime

from PySide6.QtCore import QDate, QPoint, QSettings, Qt, QTime
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
        self.setMinimumWidth(260)
        self.setMaximumWidth(380)
        self.setStyleSheet("background: #1e1e1e;")

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
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(12, 12, 12, 8)
        layout.setSpacing(12)
        scroll.setWidget(inner)

        # ── 타이틀 ──────────────────────────────────────────────
        title = QLabel("Plan Finder")
        title.setStyleSheet(
            "color: #e8e8e8; font-size: 16px; font-weight: bold; padding: 4px 0;"
        )
        layout.addWidget(title)

        # ── 프로젝트 ─────────────────────────────────────────────
        proj_group = _group("프로젝트")
        proj_form = _form()

        dir_row = QHBoxLayout()
        dir_row.setSpacing(4)
        self.project_dir_edit = QLineEdit()
        self.project_dir_edit.setPlaceholderText("/경로/프로젝트")
        self.project_dir_edit.setFixedHeight(_INPUT_H)
        _style_input(self.project_dir_edit)
        browse_btn = QPushButton("…")
        browse_btn.setFixedWidth(28)
        browse_btn.setFixedHeight(_INPUT_H)
        browse_btn.setStyleSheet(
            "QPushButton { background: #333; color: #ccc; border-radius: 3px; }"
            "QPushButton:hover { background: #444; }"
        )
        browse_btn.clicked.connect(self._browse_project)
        dir_row.addWidget(self.project_dir_edit)
        dir_row.addWidget(browse_btn)

        proj_form.addRow(_label("디렉토리"), _wrap(dir_row))
        proj_group.layout().addLayout(proj_form)
        layout.addWidget(proj_group)

        # ── 프롬프트 ─────────────────────────────────────────────
        prompt_group = _group("프롬프트")
        self.prompt_edit = QTextEdit()
        self.prompt_edit.setPlaceholderText(
            "예: 버그 찾기, 에러 처리 개선, 타입 힌트 추가…"
        )
        self.prompt_edit.setMinimumHeight(80)
        self.prompt_edit.setMaximumHeight(140)
        self.prompt_edit.setStyleSheet(
            "QTextEdit { background: #2d2d2d; color: #ccc; border: 1px solid #444;"
            "border-radius: 4px; padding: 4px 6px; font-size: 12px; }"
        )
        prompt_group.layout().addWidget(self.prompt_edit)
        layout.addWidget(prompt_group)

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
        self.budget_spin.setValue(40.0)
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
        self.stop_at_date_edit.setEnabled(False)
        self.stop_at_date_edit.setFixedHeight(_INPUT_H)
        self.stop_at_date_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        _style_spin(self.stop_at_date_edit)

        self.stop_at_time_edit = QTimeEdit()
        self.stop_at_time_edit.setDisplayFormat("HH:mm")
        self.stop_at_time_edit.setTime(QTime(7, 30))
        self.stop_at_time_edit.setEnabled(False)
        self.stop_at_time_edit.setFixedHeight(_INPUT_H)
        self.stop_at_time_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        _style_spin(self.stop_at_time_edit)

        def _toggle_stop_at(checked: bool) -> None:
            self.stop_at_date_edit.setEnabled(checked)
            self.stop_at_time_edit.setEnabled(checked)

        self.stop_at_check.toggled.connect(_toggle_stop_at)
        stop_row.addWidget(self.stop_at_check)
        stop_row.addWidget(self.stop_at_date_edit)
        stop_row.addWidget(self.stop_at_time_edit)

        stop_with_info = QHBoxLayout()
        stop_with_info.setContentsMargins(0, 0, 0, 0)
        stop_with_info.setSpacing(4)
        stop_with_info.addWidget(_wrap(stop_row), stretch=1)
        stop_with_info.addWidget(_info_btn(_INFO_STOP_AT))
        sess_form.addRow(_label("중단 시간"), _wrap(stop_with_info))

        sess_group.layout().addLayout(sess_form)
        layout.addWidget(sess_group)

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
        layout.addWidget(opts_group)

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
        layout.addWidget(trans_group)

        layout.addStretch()

        self.restore_settings()

        # ── 시작 / 중단 버튼 ──────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
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
        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.stop_btn)

        btn_container = QWidget()
        btn_container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        btn_container.setStyleSheet("background: #1e1e1e;")
        bc_layout = QVBoxLayout(btn_container)
        bc_layout.setContentsMargins(12, 8, 12, 12)
        bc_layout.setSpacing(0)
        bc_layout.addLayout(btn_row)
        outer.addWidget(btn_container)

    # ------------------------------------------------------------------ #

    def get_config(self) -> dict:
        stop_at = None
        if self.stop_at_check.isChecked():
            qd = self.stop_at_date_edit.date()
            qt = self.stop_at_time_edit.time()
            stop_at = ddatetime(qd.year(), qd.month(), qd.day(), qt.hour(), qt.minute())

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
        }

    def save_settings(self) -> None:
        s = QSettings()
        s.setValue("project_dir",       self.project_dir_edit.text())
        s.setValue("prompt",            self.prompt_edit.toPlainText())
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
        if prompt:
            self.prompt_edit.setPlainText(str(prompt))

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
    inner = QVBoxLayout()
    inner.setContentsMargins(8, 8, 8, 8)
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
