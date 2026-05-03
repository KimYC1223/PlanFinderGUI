from __future__ import annotations

import asyncio
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..engine.engine import run_discovery_loop
from ..engine.throttle import CcusageNotInstalled, SessionThrottle
from .claude_session_panel import ClaudeSessionPanel
from .config_panel import ConfigPanel
from .gui_display import GuiDisplayAdapter
from .log_panel import LogPanel
from .report_browser import ReportBrowser
from .status_bar import StatusBar
from . import sound_player


def _find_translated_helper(original: Path) -> Path | None:
    """Find a sibling translated file like original_stem.XX.md."""
    parent = original.parent
    stem = original.stem
    for f in parent.glob(f"{stem}.*.md"):
        parts = f.stem.rsplit(".", 1)
        if len(parts) == 2 and len(parts[1]) == 2:
            return f
    return None


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self._task: asyncio.Task | None = None
        self._adapter: GuiDisplayAdapter | None = None
        self._session_cost: float = 0.0
        self._is_resolve_session: bool = False

        self.setStyleSheet("QMainWindow { background: #1e1e1e; }")
        self._build_menu()
        self._build_ui()

    def _build_menu(self) -> None:
        bar = self.menuBar()
        bar.setStyleSheet(
            "QMenuBar { background: #1e1e1e; color: #ccc; font-size: 13px; }"
            "QMenuBar::item { padding: 4px 10px; background: transparent; }"
            "QMenuBar::item:selected { background: #2a2d2e; }"
            "QMenu { background: #2d2d2d; color: #ccc; border: 1px solid #444; }"
            "QMenu::item { padding: 6px 20px; }"
            "QMenu::item:selected { background: #094771; color: white; }"
            "QMenu::separator { height: 1px; background: #444; margin: 2px 8px; }"
        )

        app_menu = bar.addMenu("PlanFinder")

        pref_act = QAction("환경설정...", self)
        pref_act.setShortcut("Ctrl+,")
        pref_act.setMenuRole(QAction.MenuRole.PreferencesRole)
        pref_act.triggered.connect(self._open_settings)
        app_menu.addAction(pref_act)

        app_menu.addSeparator()

        quit_act = QAction("종료", self)
        quit_act.setShortcut("Ctrl+Q")
        quit_act.setMenuRole(QAction.MenuRole.QuitRole)
        quit_act.triggered.connect(QApplication.quit)
        app_menu.addAction(quit_act)

    def _open_settings(self) -> None:
        from .settings_dialog import SettingsDialog
        dlg = SettingsDialog(self)
        dlg.exec()

    def _build_ui(self) -> None:
        central = QWidget()
        central.setStyleSheet("background: #1e1e1e;")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Main splitter: left config | right content
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet("QSplitter::handle { background: #333; width: 1px; }")

        # Left panel
        left = QWidget()
        left.setStyleSheet("background: #1e1e1e;")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        self.config_panel = ConfigPanel()
        left_layout.addWidget(self.config_panel, stretch=1)

        # Claude session info panel
        self.claude_session_panel = ClaudeSessionPanel()
        self.claude_session_panel.setContentsMargins(12, 0, 12, 8)
        left_layout.addWidget(self.claude_session_panel)

        self.status_bar_widget = StatusBar()
        left_layout.addWidget(self.status_bar_widget)

        splitter.addWidget(left)

        # Right panel: report browser (top) + log (bottom)
        right = QWidget()
        right.setStyleSheet("background: #252526;")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        right_splitter = QSplitter(Qt.Orientation.Vertical)
        right_splitter.setStyleSheet("QSplitter::handle { background: #333; height: 1px; }")

        self.report_browser = ReportBrowser()
        self.log_panel = LogPanel()

        right_splitter.addWidget(self.report_browser)
        right_splitter.addWidget(self.log_panel)
        right_splitter.setSizes([580, 220])

        right_layout.addWidget(right_splitter)
        splitter.addWidget(right)

        splitter.setSizes([300, 900])
        root.addWidget(splitter)

        # Wire config buttons
        self.config_panel.start_btn.clicked.connect(self.start_session)
        self.config_panel.stop_btn.clicked.connect(self.stop_session)

        # Wire report_browser action signals
        self.report_browser.resolve_requested.connect(self._on_resolve_requested)
        self.report_browser.reject_requested.connect(self._on_reject_requested)
        self.report_browser.restart_requested.connect(self._on_restart_requested)
        self.report_browser.restore_requested.connect(self._on_restore_requested)

        # Update report dir when project dir changes
        self.config_panel.project_dir_edit.textChanged.connect(self._on_project_dir_changed)
        # Trigger once on startup
        QTimer.singleShot(0, lambda: self._on_project_dir_changed(
            self.config_panel.project_dir_edit.text()
        ))

    # ------------------------------------------------------------------ #
    #  Report dir helpers                                                  #
    # ------------------------------------------------------------------ #

    def _get_report_dir(self) -> Path:
        config = self.config_panel.get_config()
        project_name = Path(config["project_dir"]).name if config["project_dir"] else "_unknown"
        return Path.home() / "claude-reports" / project_name

    def _on_project_dir_changed(self, path: str) -> None:
        if path.strip():
            project_name = Path(path.strip()).name
            report_dir = Path.home() / "claude-reports" / project_name
            self.report_browser.set_report_dir(report_dir)

    # ------------------------------------------------------------------ #
    #  Session management                                                  #
    # ------------------------------------------------------------------ #

    def _warn(self, title: str, msg: str) -> None:
        sound_player.play("buzz.wav")
        QMessageBox.warning(self, title, msg)

    def start_session(self) -> None:
        config = self.config_panel.get_config()

        if not config["project_dir"]:
            self._warn("Missing Input", "Please select a project directory.")
            return
        _project_path = Path(config["project_dir"])
        if not _project_path.exists():
            self._warn("Invalid Path", "The specified path does not exist.")
            return
        if not _project_path.is_dir():
            self._warn("Invalid Path", "Please select a directory, not a file.")
            return
        if not config["prompt"]:
            self._warn("Missing Input", "Please enter a prompt.")
            return
        if config.get("stop_at") is not None:
            from datetime import datetime as _dt
            if config["stop_at"] <= _dt.now():
                self._warn("잘못된 중단 시간", "중단 시간이 현재보다 과거입니다.")
                return

        # Handle translation credentials check before starting
        post_save_hook = None
        if config.get("translate_enabled"):
            method = config.get("translate_method", "Google Translate API")
            if "Google" in method:
                from ..ui.google_auth_dialog import GoogleAuthDialog
                if not GoogleAuthDialog.ensure_credentials(self):
                    return  # user cancelled
                from ..engine.translator import save_translated, translate_with_google

                def post_save_hook(filepath: Path) -> None:
                    try:
                        content = filepath.read_text(encoding="utf-8")
                        translated = translate_with_google(content)
                        save_translated(filepath, translated)
                    except Exception as e:
                        self.log_panel.append_log(f"Translation failed: {e}", "warn")
            else:
                from ..engine.translator import save_translated, translate_with_claude

                def post_save_hook(filepath: Path) -> None:
                    try:
                        content = filepath.read_text(encoding="utf-8")
                        translated = translate_with_claude(content)
                        save_translated(filepath, translated)
                    except Exception as e:
                        self.log_panel.append_log(f"Translation failed: {e}", "warn")

        # Reset UI state
        self.status_bar_widget.reset()
        self.status_bar_widget.set_running(True)
        self.log_panel.clear_activity()
        self.report_browser.set_running(True)

        self._session_cost = 0.0
        self._adapter = GuiDisplayAdapter(self)
        self._wire_signals()

        # Build throttle (gracefully disable if ccusage not available)
        throttle = None
        if config["throttle_enabled"]:
            try:
                throttle = SessionThrottle(
                    session_budget=config["budget"],
                    log_fn=self._adapter.log,
                )
            except CcusageNotInstalled as e:
                self.log_panel.append_log(str(e), "warn")
                self.log_panel.append_log("Throttle disabled.", "warn")

        coro = run_discovery_loop(
            plan_prompt=config["prompt"],
            display=self._adapter,
            max_iterations=config["max_iter"],
            cwd=config["project_dir"],
            auto=True,  # always auto
            throttle=throttle,
            throttle_enabled=config["throttle_enabled"] and throttle is not None,
            resume=not config["no_resume"],
            stop_at=config["stop_at"],
            model=config["model"] or None,
            max_turns=config["max_turns"],
            post_save_hook=post_save_hook,
        )

        self._is_resolve_session = False
        sound_player.play("button.wav")
        sound_player.start_working_loop()

        self._task = asyncio.ensure_future(coro)
        self._task.add_done_callback(self._on_task_done)

        self.config_panel.start_btn.setEnabled(False)
        self.config_panel.stop_btn.setEnabled(True)

    def stop_session(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        if self._adapter:
            self._adapter.cancel_pending()

    def _on_task_done(self, task: asyncio.Task) -> None:
        sound_player.stop_working_loop()

        self.config_panel.start_btn.setEnabled(True)
        self.config_panel.stop_btn.setEnabled(False)
        self.status_bar_widget.set_running(False)
        self.log_panel.clear_activity()
        self.report_browser.set_running(False)
        self.report_browser.refresh()

        if task.cancelled():
            sound_player.play("tscrdy00.wav")
            self.log_panel.append_log("Session cancelled.", "warn")
        elif task.exception():
            exc = task.exception()
            sound_player.play("tscrdy00.wav")
            self.log_panel.append_log(f"Session error: {exc}", "error")
        else:
            if self._is_resolve_session:
                sound_player.play("tadupd02.wav")
            else:
                sound_player.play("tscrdy00.wav")
            self.log_panel.append_log("Session completed.", "info")

    def closeEvent(self, event: QCloseEvent) -> None:
        self.config_panel.save_settings()
        self.stop_session()
        event.accept()

    def _on_session_finished(self, approved: int, rejected: int, pending: int) -> None:
        parts = [f"✓ {approved} approved", f"✗ {rejected} rejected"]
        if pending:
            parts.append(f"⏳ {pending} pending")
        self.log_panel.append_log("Session finished: " + ", ".join(parts), "info")

    # ------------------------------------------------------------------ #
    #  Signal wiring                                                       #
    # ------------------------------------------------------------------ #

    def _wire_signals(self) -> None:
        a = self._adapter

        a.log_message.connect(self.log_panel.append_log)
        a.activity_updated.connect(self.log_panel.set_activity)
        a.iteration_started.connect(self.status_bar_widget.set_iteration)
        a.iteration_started.connect(lambda _: self.report_browser.set_running(True))
        a.cost_updated.connect(
            lambda cost, tokens, turns: (
                self.status_bar_widget.update_cost(cost, tokens, turns),
                setattr(self, "_session_cost", cost),
            )
        )

        a.plan_approved.connect(
            lambda plan, fp: (
                self.status_bar_widget.increment_approved(),
                self.log_panel.append_log(f"Approved: {plan.title}", "success"),
                self.log_panel.append_log(f"Saved to: {fp}", "dim"),
            )
        )
        a.plan_rejected.connect(
            lambda plan, reason: (
                self.status_bar_widget.increment_rejected(),
                self.log_panel.append_log(
                    f"Rejected: {plan.title}"
                    + (f" — {reason}" if reason else ""),
                    "reject",
                ),
            )
        )
        a.plan_pending.connect(
            lambda plan, fp: (
                self.log_panel.append_log(f"Pending: {plan.title}", "info"),
                self.log_panel.append_log(f"Saved to: {fp}", "dim"),
            )
        )
        # Refresh tree shortly after a new plan file is saved
        a.plan_pending.connect(
            lambda plan, fp: QTimer.singleShot(100, self.report_browser.refresh)
        )
        a.plan_pending.connect(
            lambda plan, fp: sound_player.play("transmission.wav")
        )

        a.no_more_plans.connect(
            lambda: self.log_panel.append_log(
                "No more improvements found. Codebase looks good!", "success"
            )
        )

        a.session_finished.connect(self._on_session_finished)
        a.error_occurred.connect(
            lambda msg: self.log_panel.append_log(f"Error: {msg}", "error")
        )

    # ------------------------------------------------------------------ #
    #  Report browser action handlers                                      #
    # ------------------------------------------------------------------ #

    def _on_resolve_requested(self, paths: list) -> None:
        """Move pending files to working/, then start a resolve session."""
        report_dir = self._get_report_dir()
        working_dir = report_dir / "working"
        working_dir.mkdir(parents=True, exist_ok=True)

        moved: list[Path] = []
        for p in paths:
            orig = Path(p)
            if orig.exists():
                dest = working_dir / orig.name
                orig.rename(dest)
                moved.append(dest)
                # Also move any translated versions
                trans = _find_translated_helper(orig)
                if trans and trans.exists():
                    trans.rename(working_dir / trans.name)

        self.report_browser.refresh()

        if not moved:
            return

        # Stop current session if running
        self.stop_session()

        config = self.config_panel.get_config()
        self._adapter = GuiDisplayAdapter(self)
        self._wire_signals()

        from ..engine.executor import run_resolve_session

        self._is_resolve_session = True
        sound_player.start_working_loop()

        coro = run_resolve_session(
            plan_paths=moved,
            display=self._adapter,
            cwd=config["project_dir"],
            model=config["model"] or None,
            max_turns=config["max_turns"],
        )
        self._task = asyncio.ensure_future(coro)
        self._task.add_done_callback(self._on_task_done)
        self.config_panel.start_btn.setEnabled(False)
        self.config_panel.stop_btn.setEnabled(True)
        self.report_browser.set_running(True)
        self.status_bar_widget.set_running(True)

    def _on_reject_requested(self, paths: list) -> None:
        """Move pending files to reject/."""
        report_dir = self._get_report_dir()
        reject_dir = report_dir / "reject"
        reject_dir.mkdir(parents=True, exist_ok=True)

        for p in paths:
            orig = Path(p)
            if orig.exists():
                orig.rename(reject_dir / orig.name)
                trans = _find_translated_helper(orig)
                if trans and trans.exists():
                    trans.rename(reject_dir / trans.name)

        self.report_browser.refresh()

    def _on_restart_requested(self, paths: list) -> None:
        """Files are already in working/; start resolve session directly."""
        plan_paths = [Path(p) for p in paths if Path(p).exists()]
        if not plan_paths:
            return

        # Stop current session if running
        self.stop_session()

        config = self.config_panel.get_config()
        self._adapter = GuiDisplayAdapter(self)
        self._wire_signals()

        from ..engine.executor import run_resolve_session

        self._is_resolve_session = True
        sound_player.start_working_loop()

        coro = run_resolve_session(
            plan_paths=plan_paths,
            display=self._adapter,
            cwd=config["project_dir"],
            model=config["model"] or None,
            max_turns=config["max_turns"],
        )
        self._task = asyncio.ensure_future(coro)
        self._task.add_done_callback(self._on_task_done)
        self.config_panel.start_btn.setEnabled(False)
        self.config_panel.stop_btn.setEnabled(True)
        self.report_browser.set_running(True)
        self.status_bar_widget.set_running(True)

    def _on_restore_requested(self, paths: list) -> None:
        """Move rejected files back to pending/."""
        report_dir = self._get_report_dir()
        pending_dir = report_dir / "pending"
        pending_dir.mkdir(parents=True, exist_ok=True)

        for p in paths:
            orig = Path(p)
            if orig.exists():
                orig.rename(pending_dir / orig.name)
                trans = _find_translated_helper(orig)
                if trans and trans.exists():
                    trans.rename(pending_dir / trans.name)

        self.report_browser.refresh()
