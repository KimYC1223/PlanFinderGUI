from __future__ import annotations

import os

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class GoogleAuthDialog(QDialog):
    """Shows at startup if Google Translate is selected but no credentials saved."""

    _SETTINGS_KEY = "google_credentials_path"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Google Cloud Credentials")
        self.setMinimumWidth(480)
        self.setStyleSheet(
            "QDialog { background: #1e1e1e; color: #ccc; }"
            "QLabel { color: #ccc; font-size: 12px; }"
            "QLineEdit { background: #2d2d2d; color: #ccc; border: 1px solid #444;"
            "  border-radius: 4px; padding: 4px 8px; font-size: 12px; }"
            "QLineEdit:focus { border-color: #0e78d5; }"
            "QPushButton { background: #333; color: #ccc; border-radius: 4px;"
            "  padding: 4px 12px; font-size: 12px; }"
            "QPushButton:hover { background: #444; }"
        )
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        info = QLabel(
            "To use Google Translate, you need a Google Cloud service account credentials file.\n\n"
            "1. Go to the Google Cloud Console and create a service account.\n"
            "2. Enable the Cloud Translation API.\n"
            "3. Download the JSON credentials file.\n"
            "4. Provide the path to that file below."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #aaa; font-size: 11px; line-height: 1.5;")
        layout.addWidget(info)

        path_label = QLabel("Credentials JSON path:")
        layout.addWidget(path_label)

        path_row = QHBoxLayout()
        self._path_edit = QLineEdit()
        self._path_edit.setPlaceholderText("/path/to/credentials.json")

        # Restore previously saved value if any
        s = QSettings()
        saved = s.value(self._SETTINGS_KEY, "")
        if saved:
            self._path_edit.setText(str(saved))

        browse_btn = QPushButton("Browse…")
        browse_btn.setFixedWidth(80)
        browse_btn.clicked.connect(self._browse)
        path_row.addWidget(self._path_edit)
        path_row.addWidget(browse_btn)
        layout.addLayout(path_row)

        self._error_label = QLabel("")
        self._error_label.setStyleSheet("color: #f44336; font-size: 11px;")
        self._error_label.setVisible(False)
        layout.addWidget(self._error_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setStyleSheet(
            "QPushButton { background: #0e78d5; color: white; border-radius: 4px;"
            "  padding: 4px 16px; font-weight: bold; }"
            "QPushButton:hover { background: #1e88e5; }"
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Google Cloud Credentials JSON",
            self._path_edit.text() or "",
            "JSON files (*.json);;All files (*)",
        )
        if path:
            self._path_edit.setText(path)

    def _on_accept(self) -> None:
        path = self._path_edit.text().strip()
        if not path:
            self._show_error("Please provide a credentials file path.")
            return

        import pathlib
        p = pathlib.Path(path)
        if not p.exists():
            self._show_error("File not found. Please check the path.")
            return
        if not p.is_file():
            self._show_error("Path does not point to a file.")
            return

        # Save to settings and environment
        s = QSettings()
        s.setValue(self._SETTINGS_KEY, path)
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = path
        self.accept()

    def _show_error(self, msg: str) -> None:
        self._error_label.setText(msg)
        self._error_label.setVisible(True)

    # ------------------------------------------------------------------ #
    #  Static helpers                                                      #
    # ------------------------------------------------------------------ #

    @staticmethod
    def load_saved_credentials() -> bool:
        """Load from QSettings if exists. Returns True if found and valid."""
        s = QSettings()
        path = s.value(GoogleAuthDialog._SETTINGS_KEY, "")
        if not path:
            return False

        import pathlib
        p = pathlib.Path(str(path))
        if not p.exists() or not p.is_file():
            return False

        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(p)
        return True

    @staticmethod
    def ensure_credentials(parent: QWidget | None = None) -> bool:
        """Load saved credentials, or show dialog if missing.

        Returns True if credentials are ready.
        """
        if GoogleAuthDialog.load_saved_credentials():
            return True
        dlg = GoogleAuthDialog(parent)
        return dlg.exec() == QDialog.DialogCode.Accepted
