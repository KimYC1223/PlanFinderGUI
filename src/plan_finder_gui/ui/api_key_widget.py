from __future__ import annotations

from PySide6.QtCore import QObject, QSettings, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


_INPUT_H = 26


def _validate_anthropic_key(key: str) -> bool:
    """Ping /v1/models to verify the API key is accepted by Anthropic."""
    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/models?limit=1",
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return 200 <= resp.status < 300
    except urllib.error.HTTPError:
        return False
    except Exception:
        return False


class _ApiKeyValidator(QObject):
    """Worker that validates an Anthropic API key off the UI thread."""

    finished = Signal(bool, str)  # (is_valid, key_that_was_checked)

    def __init__(self, key: str) -> None:
        super().__init__()
        self._key = key

    def run(self) -> None:
        valid = _validate_anthropic_key(self._key)
        self.finished.emit(valid, self._key)


_INFO_API_KEY = (
    "PlanFinder가 Claude API를 호출할 때 사용할 Anthropic API Key입니다.\n\n"
    "• 비워두거나 유효하지 않으면 로컬에 로그인된 Claude(claude CLI) 정보를\n"
    "  사용하여 동작합니다.\n"
    "• 유효한 키를 입력하면 해당 키를 사용해 Claude를 호출합니다.\n\n"
    "키는 로컬 설정에만 저장됩니다."
)


class ApiKeyEditor(QWidget):
    """Self-contained API key editor with debounced background validation.

    Persists the validated key to QSettings under "anthropic_api_key". The
    rest of the app reads it from QSettings, so this widget owns the full
    lifecycle (input, validation, persistence, status display).
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)

        self.api_key_edit = QLineEdit()
        self.api_key_edit.setPlaceholderText("sk-ant-…")
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setFixedHeight(_INPUT_H)
        self.api_key_edit.setStyleSheet(
            "QLineEdit { background: #2d2d2d; color: #ccc; border: 1px solid #444;"
            "border-radius: 4px; padding: 3px 6px; font-size: 12px; }"
            "QLineEdit:focus { border-color: #0e78d5; }"
        )
        row.addWidget(self.api_key_edit, stretch=1)
        row.addWidget(_info_btn(_INFO_API_KEY))
        outer.addLayout(row)

        self.api_key_status_label = QLabel(
            "현재 로컬에 로그인된 Claude 정보를 사용하여 동작합니다."
        )
        self.api_key_status_label.setWordWrap(True)
        self.api_key_status_label.setStyleSheet(
            "color: #888; font-size: 11px; background: transparent; padding-top: 2px;"
        )
        outer.addWidget(self.api_key_status_label)

        # Debounce key validation so we don't ping the API on every keystroke.
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(600)
        self._timer.timeout.connect(self._start_validation)
        self._validator_thread: QThread | None = None
        self._validator_worker: _ApiKeyValidator | None = None

        self.api_key_edit.textChanged.connect(self._on_text_changed)

        # Pre-populate from saved settings and kick off a background revalidation.
        saved_key = str(QSettings().value("anthropic_api_key", "") or "")
        if saved_key:
            self.api_key_edit.blockSignals(True)
            self.api_key_edit.setText(saved_key)
            self.api_key_edit.blockSignals(False)
            self._set_status(using_user_key=True)
            QTimer.singleShot(0, self._start_validation)

    # ------------------------------------------------------------------ #

    def _on_text_changed(self, _text: str) -> None:
        self._timer.start()

    def _set_status(self, *, using_user_key: bool) -> None:
        if using_user_key:
            self.api_key_status_label.setText(
                "이제 해당 API Key를 사용하여 Claude를 사용하여 동작합니다."
            )
            self.api_key_status_label.setStyleSheet(
                "color: #4ec9b0; font-size: 11px; background: transparent;"
                " padding-top: 2px;"
            )
        else:
            self.api_key_status_label.setText(
                "현재 로컬에 로그인된 Claude 정보를 사용하여 동작합니다."
            )
            self.api_key_status_label.setStyleSheet(
                "color: #888; font-size: 11px; background: transparent;"
                " padding-top: 2px;"
            )

    def _start_validation(self) -> None:
        key = self.api_key_edit.text().strip()
        if not key:
            QSettings().remove("anthropic_api_key")
            self._set_status(using_user_key=False)
            return

        # Cheap format guard: avoid network calls for clearly invalid input.
        if not key.startswith("sk-ant-") or len(key) < 20:
            QSettings().remove("anthropic_api_key")
            self._set_status(using_user_key=False)
            return

        thread = QThread(self)
        worker = _ApiKeyValidator(key)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_validated)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._validator_thread = thread
        self._validator_worker = worker
        thread.start()

    def _on_validated(self, valid: bool, checked_key: str) -> None:
        # Discard stale results when the user has typed more since this
        # validation was kicked off.
        current = self.api_key_edit.text().strip()
        if checked_key != current:
            return

        if valid and current:
            QSettings().setValue("anthropic_api_key", current)
            self._set_status(using_user_key=True)
        else:
            QSettings().remove("anthropic_api_key")
            self._set_status(using_user_key=False)


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
