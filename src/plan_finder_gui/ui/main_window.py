from __future__ import annotations

import asyncio
from pathlib import Path

from PySide6.QtCore import QSettings, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSplitter,
    QSystemTrayIcon,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..engine.engine import run_discovery_loop
from ..engine.session_manager import Session, SessionManager
from ..engine.throttle import CcusageNotInstalled, SessionThrottle
from .claude_session_panel import ClaudeSessionPanel
from .config_panel import ConfigPanel
from .gui_display import GuiDisplayAdapter
from .log_panel import LogPanel
from .report_browser import ReportBrowser
from .sessions_panel import SessionsPanel
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


def _is_translated_md(path: Path) -> bool:
    """True when filename matches *.XX.md (2-letter language suffix)."""
    parts = path.stem.rsplit(".", 1)
    return len(parts) == 2 and len(parts[1]) == 2


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self._session_manager = SessionManager(self)

        # Set when the user explicitly chose to quit (tray menu / pre-confirmed
        # close). Lets closeEvent skip the "send to tray?" prompt.
        self._force_quit: bool = False

        self.setStyleSheet("QMainWindow { background: #1e1e1e; }")
        self._build_menu()
        self._build_ui()
        self._build_tray()

        self._session_manager.session_registered.connect(self._on_session_registered)
        self._session_manager.session_unregistered.connect(self._on_session_unregistered)

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

        about_act = QAction("About PlanFinder GUI", self)
        about_act.setMenuRole(QAction.MenuRole.AboutRole)
        about_act.triggered.connect(self._show_about)
        app_menu.addAction(about_act)

        app_menu.addSeparator()

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

        # ── View menu ─────────────────────────────────────────────
        view_menu = bar.addMenu("View")

        self._act_show_left = QAction("Info View", self)
        self._act_show_left.setCheckable(True)
        self._act_show_left.setChecked(True)
        self._act_show_left.triggered.connect(self._toggle_left_panel)
        view_menu.addAction(self._act_show_left)

        self._act_show_browser = QAction("트리 & 파일 미리보기", self)
        self._act_show_browser.setCheckable(True)
        self._act_show_browser.setChecked(True)
        self._act_show_browser.triggered.connect(self._toggle_browser_panel)
        view_menu.addAction(self._act_show_browser)

        self._act_show_log = QAction("Logger", self)
        self._act_show_log.setCheckable(True)
        self._act_show_log.setChecked(True)
        self._act_show_log.triggered.connect(self._toggle_log_panel)
        view_menu.addAction(self._act_show_log)

        # ── 옵션 menu ─────────────────────────────────────────────
        options_menu = bar.addMenu("옵션")

        self._act_quiet_hours = QAction("Quiet Hours (22:00~03:00 자동 일시정지)", self)
        self._act_quiet_hours.setCheckable(True)
        self._act_quiet_hours.setChecked(
            QSettings().value("quiet_hours_enabled", True) in (True, "true", "True", "1")
        )
        self._act_quiet_hours.toggled.connect(self._on_quiet_hours_toggled)
        options_menu.addAction(self._act_quiet_hours)

    def _on_quiet_hours_toggled(self, checked: bool) -> None:
        QSettings().setValue("quiet_hours_enabled", checked)

    def _toggle_left_panel(self, checked: bool) -> None:
        if checked:
            self._left.setVisible(True)
            sizes = self._main_splitter.sizes()
            if sizes and sizes[0] == 0:
                total = sum(sizes) or 1300
                self._main_splitter.setSizes([320, max(total - 320, 600)])
        else:
            self._left.setVisible(False)

    def _toggle_browser_panel(self, checked: bool) -> None:
        if checked:
            self.report_browser.setVisible(True)
            sizes = self._right_splitter.sizes()
            if sizes and sizes[0] == 0:
                total = sum(sizes) or 800
                self._right_splitter.setSizes([580, max(total - 580, 100)])
        else:
            self.report_browser.setVisible(False)

    def _toggle_log_panel(self, checked: bool) -> None:
        if checked:
            self.log_panel.setVisible(True)
            sizes = self._right_splitter.sizes()
            if len(sizes) >= 2 and sizes[1] == 0:
                total = sum(sizes) or 800
                self._right_splitter.setSizes([max(total - 220, 100), 220])
        else:
            self.log_panel.setVisible(False)

    def _sync_view_actions(self, *_: object) -> None:
        main = self._main_splitter.sizes()
        if main:
            self._act_show_left.setChecked(main[0] > 0 and self._left.isVisible())
        right = self._right_splitter.sizes()
        if len(right) >= 2:
            self._act_show_browser.setChecked(right[0] > 0 and self.report_browser.isVisible())
            self._act_show_log.setChecked(right[1] > 0 and self.log_panel.isVisible())

    def _open_settings(self) -> None:
        from .settings_dialog import SettingsDialog
        dlg = SettingsDialog(self)
        dlg.exec()
        # Settings may have changed the preset directory — refresh the dropdown.
        if hasattr(self, "config_panel"):
            self.config_panel.refresh_presets()

    def _show_about(self) -> None:
        import sys
        from PySide6.QtGui import QPixmap
        from PySide6.QtWidgets import (
            QDialog, QDialogButtonBox, QLabel, QVBoxLayout,
        )

        sound_player.play_random(
            "tscwht01.wav", "tscwht02.wav", "tscwht03.wav"
        )

        # Resolve icon path (frozen vs dev layout)
        if getattr(sys, "frozen", False):
            icon_path = Path(sys._MEIPASS) / "img" / "scv.webp"  # type: ignore[attr-defined]
        else:
            icon_path = Path(__file__).parents[3] / "img" / "scv.webp"

        # Resolve version from package metadata, with hardcoded fallback
        try:
            from importlib.metadata import version
            ver = version("plan-finder-gui")
        except Exception:
            ver = "0.1.0"

        dlg = QDialog(self)
        dlg.setWindowTitle("About PlanFinder GUI")
        dlg.setFixedWidth(420)
        dlg.setStyleSheet(
            "QDialog { background: #252526; color: #ccc; }"
            "QLabel { color: #ccc; }"
            "QLabel a { color: #4fc3f7; text-decoration: none; }"
            "QPushButton {"
            "  background: #0e639c; color: white;"
            "  border: none; padding: 6px 16px;"
            "}"
            "QPushButton:hover { background: #1177bb; }"
        )
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        if icon_path.exists():
            pix = QPixmap(str(icon_path))
            if not pix.isNull():
                icon_label = QLabel()
                icon_label.setPixmap(
                    pix.scaled(
                        128, 128,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                layout.addWidget(icon_label, alignment=Qt.AlignmentFlag.AlignHCenter)

        title = QLabel("PlanFinder GUI")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #e8e8e8; padding-top: 8px;")
        layout.addWidget(title)

        ver_label = QLabel(f"Version {ver}")
        ver_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ver_label.setStyleSheet("color: #aaa; font-size: 13px; padding-bottom: 6px;")
        layout.addWidget(ver_label)

        desc = QLabel(
            "Claude AI를 활용해 코드베이스를 자동 분석하고<br>"
            "개선 계획(Plan)을 생성하는 크로스플랫폼 데스크톱 앱입니다."
        )
        desc.setTextFormat(Qt.TextFormat.RichText)
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setWordWrap(True)
        desc.setStyleSheet("font-size: 12px; color: #c0c0c0; padding: 4px 0 10px 0;")
        layout.addWidget(desc)

        credits = QLabel(
            'Created by <b>KimYC1223</b><br>'
            'Inspired by <b>kajebiii</b>\'s '
            '<a href="https://github.com/kajebiii/plan-finder">plan-finder</a>'
        )
        credits.setTextFormat(Qt.TextFormat.RichText)
        credits.setOpenExternalLinks(True)
        credits.setAlignment(Qt.AlignmentFlag.AlignCenter)
        credits.setWordWrap(True)
        credits.setStyleSheet(
            "font-size: 12px; color: #b8b8b8;"
            "border-top: 1px solid #3a3a3a; padding-top: 12px; margin-top: 4px;"
        )
        layout.addWidget(credits)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(dlg.accept)
        layout.addWidget(buttons)

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

        # Left panel — header (fixed) | tabs (scrollable) | start/stop (fixed)
        left = QWidget()
        left.setStyleSheet("background: #1e1e1e;")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        # ── Pinned header ─────────────────────────────────────────
        header = QWidget()
        header.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        header.setStyleSheet("background: #1e1e1e;")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(12, 18, 12, 16)
        header_layout.setSpacing(0)
        header_title = QLabel("Plan Finder")
        header_title.setStyleSheet(
            "color: #e8e8e8; font-size: 22px; font-weight: bold;"
        )
        header_layout.addWidget(header_title)
        left_layout.addWidget(header)

        # ── Tabs ──────────────────────────────────────────────────
        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        tabs.setElideMode(Qt.TextElideMode.ElideNone)
        tabs.setUsesScrollButtons(False)
        tabs.tabBar().setExpanding(True)
        tabs.setStyleSheet(
            "QTabWidget::pane { border: none; background: #1e1e1e; }"
            "QTabBar { background: #1e1e1e; }"
            "QTabBar::tab {"
            "  background: #252526; color: #aaa;"
            "  padding: 6px 12px; font-size: 12px;"
            "  border: 1px solid #2c2c2c; border-bottom: none;"
            "}"
            "QTabBar::tab:selected { background: #1e1e1e; color: #e8e8e8; }"
            "QTabBar::tab:hover:!selected { background: #2a2d2e; color: #ccc; }"
        )

        # Tab 1: 검사 정보 ────────────────────────────────────────
        self.config_panel = ConfigPanel()
        tabs.addTab(self.config_panel, "검사 정보")

        # Tab 2: 활성 Claude 정보 ──────────────────────────────────
        active_tab = QWidget()
        active_tab.setStyleSheet("background: #1e1e1e;")
        active_layout = QVBoxLayout(active_tab)
        active_layout.setContentsMargins(0, 0, 0, 0)
        active_layout.setSpacing(0)

        # Live PlanFinder sessions (with CPU sparklines)
        self.sessions_panel = SessionsPanel(self._session_manager)
        self.sessions_panel.setContentsMargins(12, 12, 12, 6)
        active_layout.addWidget(self.sessions_panel)

        # Claude session info panel (ccusage-driven aggregate stats).
        self.claude_session_panel = ClaudeSessionPanel()
        self.claude_session_panel.setContentsMargins(12, 6, 12, 12)
        active_layout.addWidget(self.claude_session_panel, stretch=1)

        self.status_bar_widget = StatusBar()
        active_layout.addWidget(self.status_bar_widget)

        tabs.addTab(active_tab, "활성 Claude 정보")

        left_layout.addWidget(tabs, stretch=1)

        # ── Pinned footer (Start / Stop) ──────────────────────────
        footer = QWidget()
        footer.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        footer.setStyleSheet(
            "background: #1e1e1e; border-top: 1px solid #2c2c2c;"
        )
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(12, 8, 12, 12)
        footer_layout.setSpacing(0)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addWidget(self.config_panel.start_btn)
        btn_row.addWidget(self.config_panel.stop_btn)
        footer_layout.addLayout(btn_row)
        left_layout.addWidget(footer)

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

        splitter.setSizes([320, 980])
        self._left = left
        self._main_splitter = splitter
        self._right_splitter = right_splitter
        splitter.splitterMoved.connect(self._sync_view_actions)
        right_splitter.splitterMoved.connect(self._sync_view_actions)
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
        # Trigger once on startup, then recover any leftover working/ items.
        # Files end up stranded in working/ when a previous resolve session was
        # interrupted (app closed mid-run); restoring them to pending lets the
        # user re-trigger or reject without hunting them down manually.
        QTimer.singleShot(0, self._startup_init)

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

    def _startup_init(self) -> None:
        self._on_project_dir_changed(self.config_panel.project_dir_edit.text())
        self._recover_working_to_pending()

    def _recover_working_to_pending(self) -> None:
        """Restore any files left in working/ back to pending/ on startup."""
        config = self.config_panel.get_config()
        if not config.get("project_dir"):
            return
        report_dir = self._get_report_dir()
        working_dir = report_dir / "working"
        if not working_dir.is_dir():
            return

        pending_dir = report_dir / "pending"
        moved = 0
        skipped: list[str] = []

        for src in sorted(working_dir.glob("*.md")):
            if _is_translated_md(src):
                # Sibling translations move alongside their original below.
                continue
            dest = pending_dir / src.name
            if dest.exists():
                skipped.append(src.name)
                continue
            try:
                pending_dir.mkdir(parents=True, exist_ok=True)
                src.rename(dest)
                moved += 1
            except OSError as e:
                self.log_panel.append_log(
                    f"working → pending 이동 실패: {src.name} ({e})", "warn"
                )
                continue

            stem = src.stem

            # Sibling translation: working/<stem>.<lang>.md
            for trans in working_dir.glob(f"{stem}.*.md"):
                if not _is_translated_md(trans):
                    continue
                trans_dest = pending_dir / trans.name
                if trans_dest.exists():
                    continue
                try:
                    trans.rename(trans_dest)
                except OSError:
                    pass

            # Subdirectory translation: working/translated/<stem>.<lang>.md
            working_trans_dir = working_dir / "translated"
            if working_trans_dir.is_dir():
                for trans in working_trans_dir.glob(f"{stem}.*.md"):
                    if not _is_translated_md(trans):
                        continue
                    pending_trans_dir = pending_dir / "translated"
                    pending_trans_dir.mkdir(parents=True, exist_ok=True)
                    trans_dest = pending_trans_dir / trans.name
                    if trans_dest.exists():
                        continue
                    try:
                        trans.rename(trans_dest)
                    except OSError:
                        pass

        if moved:
            self.log_panel.append_log(
                f"working → pending 복구: {moved}개 파일 이동", "info"
            )
            self.report_browser.refresh()
        if skipped:
            self.log_panel.append_log(
                f"working → pending 건너뜀 (pending에 동일 이름 존재): "
                + ", ".join(skipped[:5])
                + (f" 외 {len(skipped) - 5}개" if len(skipped) > 5 else ""),
                "warn",
            )

    # ------------------------------------------------------------------ #
    #  Session management                                                  #
    # ------------------------------------------------------------------ #

    def _warn(self, title: str, msg: str) -> None:
        sound_player.play("buzz.wav")
        QMessageBox.warning(self, title, msg)

    def _ensure_project_access(self, project_dir: str) -> bool:
        """Validate project dir + pre-trigger macOS folder-access prompt.

        Called from every entry point that spawns a Claude session (Start /
        Resolve / Restart) so the permission dialog is always handled at the
        start of work, not midway through.
        """
        if not project_dir:
            self._warn("Missing Input", "Please select a project directory.")
            return False
        path = Path(project_dir)
        if not path.exists():
            self._warn("Invalid Path", "The specified path does not exist.")
            return False
        if not path.is_dir():
            self._warn("Invalid Path", "Please select a directory, not a file.")
            return False
        try:
            next(iter(path.iterdir()), None)
        except PermissionError:
            self._warn(
                "권한 오류",
                "프로젝트 디렉토리에 접근할 수 없습니다.\n"
                "시스템 설정 → 개인정보 보호 및 보안에서 PlanFinder의 폴더 접근 권한을 허용해주세요.",
            )
            return False
        except OSError as e:
            self._warn("디렉토리 오류", f"프로젝트 디렉토리를 읽을 수 없습니다: {e}")
            return False
        return True

    def start_session(self) -> None:
        from ..engine.executor import _show_error
        try:
            self._start_session_impl()
        except Exception as e:
            _show_error(
                "Start 실패",
                "Start 버튼 처리 중 예외가 발생했습니다.",
                e,
            )

    def _start_session_impl(self) -> None:
        config = self.config_panel.get_config()

        if not self._ensure_project_access(config["project_dir"]):
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

        adapter = GuiDisplayAdapter(self)

        # Build throttle (gracefully disable if ccusage not available)
        throttle = None
        if config["throttle_enabled"]:
            try:
                throttle = SessionThrottle(
                    session_budget=config["budget"],
                    log_fn=adapter.log,
                )
            except CcusageNotInstalled as e:
                self.log_panel.append_log(str(e), "warn")
                self.log_panel.append_log("Throttle disabled.", "warn")

        coro = run_discovery_loop(
            plan_prompt=config["prompt"],
            display=adapter,
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

        self._spawn_session(
            label="Discovery",
            adapter=adapter,
            coro=coro,
            is_resolve=False,
        )

    def stop_session(self) -> None:
        cancelled = self._session_manager.cancel_all()
        for sess in self._session_manager.list():
            sess.adapter.cancel_pending()
        if cancelled:
            self.log_panel.append_log(
                f"Stop 요청: {cancelled}개 세션 취소 중...", "warn"
            )

    def _spawn_session(
        self,
        label: str,
        adapter: GuiDisplayAdapter,
        coro,
        is_resolve: bool,
    ) -> Session:
        sid = self._session_manager.new_id()
        session = Session(sid, label, adapter, parent=self)
        session.is_resolve = is_resolve  # type: ignore[attr-defined]
        self._wire_session_signals(session)
        self._session_manager.register(session)

        session.task = asyncio.ensure_future(coro)
        session.task.add_done_callback(
            lambda t, s=session: self._on_session_task_done(s, t)
        )

        self.log_panel.append_log(f"[{sid}] {label} 세션 시작", "info")
        sound_player.play("button.wav")
        return session

    def _on_session_registered(self, session: Session) -> None:
        # First running session — start the looping audio + status indicator.
        running_count = sum(
            1 for s in self._session_manager.list() if s.state == "running"
        )
        if running_count == 1:
            sound_player.start_working_loop()
            self.status_bar_widget.set_running(True)
            self.report_browser.set_running(True)
            if self._tray is not None:
                self._tray.setIcon(self._tray_icon_running)
        self.config_panel.stop_btn.setEnabled(True)

    def _on_session_unregistered(self, session: Session) -> None:
        if not self._session_manager.any_running():
            sound_player.stop_working_loop()
            self.status_bar_widget.set_running(False)
            self.log_panel.clear_activity()
            self.report_browser.set_running(False)
            self.report_browser.refresh()
            self.config_panel.stop_btn.setEnabled(False)
            if self._tray is not None:
                self._tray.setIcon(self._tray_icon_idle)

    def _on_session_task_done(self, session: Session, task: asyncio.Task) -> None:
        is_resolve = bool(getattr(session, "is_resolve", False))

        if task.cancelled():
            self._session_manager.mark_state(session, "cancelled")
            sound_player.play_random("tscerr00.wav", "tscerr01.wav")
            self.log_panel.append_log(f"[{session.id}] Session cancelled.", "warn")
        elif task.exception():
            exc = task.exception()
            self._session_manager.mark_state(session, "failed")
            sound_player.play("buzz.wav")
            self.log_panel.append_log(
                f"[{session.id}] Session error: {exc}", "error"
            )
            from ..engine.executor import _show_error
            _show_error(
                "세션 비정상 종료",
                f"[{session.id}] 비동기 세션이 예외로 종료되었습니다:\n"
                f"{type(exc).__name__}: {exc}",
                exc,
            )
        else:
            self._session_manager.mark_state(session, "completed")
            if is_resolve:
                sound_player.play("tadupd02.wav")
            else:
                sound_player.play("tscupd00.wav")
            self.log_panel.append_log(f"[{session.id}] Session completed.", "info")

        # Briefly leave the card visible in its terminal state, then drop it.
        QTimer.singleShot(2500, lambda s=session: self._session_manager.unregister(s))

    # ------------------------------------------------------------------ #
    #  System tray                                                         #
    # ------------------------------------------------------------------ #

    _TRAY_ICON_SIZES = (16, 22, 32, 44, 128)

    def _resolve_img_dir(self) -> Path:
        """Return path to the bundled img/ folder (dev vs frozen layout)."""
        import sys
        if getattr(sys, "frozen", False):
            return Path(sys._MEIPASS) / "img"  # type: ignore[attr-defined]
        return Path(__file__).parents[3] / "img"

    def _select_tray_color(self) -> str:
        """Pick 'black' or 'white' icon set based on platform/theme.

        macOS uses the black silhouette as a template mask — the system
        auto-inverts per dark/light mode, so the source color doesn't matter
        much. On Windows/Linux there is no template mode, so we pick the
        color that contrasts with the current taskbar theme.
        """
        import sys
        if sys.platform == "darwin":
            return "black"
        try:
            scheme = QGuiApplication.styleHints().colorScheme()
            if scheme == Qt.ColorScheme.Light:
                return "black"
        except Exception:
            pass
        return "white"

    def _build_tray_icon(self, prefix: str, color: str) -> QIcon:
        """Assemble a multi-resolution QIcon from img/{prefix}_{color}_*.png."""
        base = self._resolve_img_dir()
        icon = QIcon()
        for sz in self._TRAY_ICON_SIZES:
            p = base / f"{prefix}_{color}_{sz}.png"
            if p.exists():
                icon.addFile(str(p), QSize(sz, sz))
        return icon

    def _refresh_tray_icons(self) -> None:
        """Rebuild idle/running icons (e.g. after a color-scheme change)."""
        import sys
        color = self._select_tray_color()
        self._tray_icon_idle    = self._build_tray_icon("idle",    color)
        self._tray_icon_running = self._build_tray_icon("running", color)
        if sys.platform == "darwin":
            self._tray_icon_idle.setIsMask(True)
            self._tray_icon_running.setIsMask(True)
        if self._tray is not None:
            running = self._session_manager.any_running()
            self._tray.setIcon(
                self._tray_icon_running if running else self._tray_icon_idle
            )

    def _build_tray(self) -> None:
        self._tray = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        self._tray = QSystemTrayIcon(self)
        self._tray.setToolTip("PlanFinder")
        self._refresh_tray_icons()

        # Live-update the icon set when the OS theme flips (Qt 6.5+).
        try:
            QGuiApplication.styleHints().colorSchemeChanged.connect(
                lambda _scheme: self._refresh_tray_icons()
            )
        except Exception:
            pass

        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background: #2d2d2d; color: #ccc; border: 1px solid #444; }"
            "QMenu::item { padding: 6px 20px; }"
            "QMenu::item:selected { background: #094771; color: white; }"
            "QMenu::separator { height: 1px; background: #444; margin: 2px 8px; }"
        )
        show_act = menu.addAction("PlanFinder 열기")
        show_act.triggered.connect(self._show_from_tray)
        menu.addSeparator()
        quit_act = menu.addAction("종료")
        quit_act.triggered.connect(self._quit_from_tray)
        self._tray.setContextMenu(menu)

        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        # On macOS the menu bar icon mostly fires Trigger; on Windows users
        # often double-click. Treat both as "toggle window".
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            if self.isVisible() and not self.isMinimized():
                self.hide()
            else:
                self._show_from_tray()

    def _show_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit_from_tray(self) -> None:
        self._force_quit = True
        self.close()

    # ------------------------------------------------------------------ #
    #  Close handling                                                      #
    # ------------------------------------------------------------------ #

    def closeEvent(self, event: QCloseEvent) -> None:
        # macOS native fullscreen + a modal QMessageBox = black screen, because
        # the dialog appears in a different Space while the fullscreen Space is
        # left empty. Exit fullscreen first and re-issue the close after the
        # ~half-second fullscreen-exit animation finishes.
        if self.isFullScreen():
            self.showNormal()
            event.ignore()
            QTimer.singleShot(500, self.close)
            return

        # If the user explicitly chose Quit (tray menu or app menu) we skip
        # the prompt. Otherwise consult the saved preference / ask.
        if not self._force_quit and self._tray is not None:
            action = self._resolve_close_action()
            if action == "minimize":
                self.hide()
                event.ignore()
                return
            if action == "cancel":
                event.ignore()
                return
            # action == "quit" → fall through and tear everything down

        self.config_panel.save_settings()
        self.stop_session()
        if getattr(self, "_tray", None) is not None:
            self._tray.hide()
        event.accept()

    def _resolve_close_action(self) -> str:
        """Return 'minimize' or 'quit'. Asks the user when no preference saved."""
        s = QSettings()
        saved = str(s.value("tray/close_action", "") or "")
        if saved in ("minimize", "quit"):
            return saved
        return self._ask_close_action()

    def _ask_close_action(self) -> str:
        mb = QMessageBox(self)
        mb.setWindowTitle("PlanFinder 닫기")
        mb.setIcon(QMessageBox.Icon.Question)
        mb.setText("창을 어떻게 닫으시겠습니까?")
        mb.setInformativeText(
            "트레이로 보내면 작업이 백그라운드에서 계속 실행됩니다.\n"
            "종료하면 진행 중인 Claude 세션이 모두 중단됩니다."
        )
        mb.setStyleSheet(
            "QMessageBox { background: #252526; color: #ccc; }"
            "QLabel { color: #ccc; }"
            "QPushButton {"
            "  background: #333; color: #ccc; border: 1px solid #444;"
            "  border-radius: 4px; padding: 5px 14px; min-width: 80px;"
            "}"
            "QPushButton:hover { background: #3d3d3d; }"
            "QPushButton:default { background: #0e78d5; color: white; border: none; }"
            "QPushButton:default:hover { background: #1e88e5; }"
        )
        minimize_btn = mb.addButton("트레이로 보내기", QMessageBox.ButtonRole.AcceptRole)
        quit_btn     = mb.addButton("종료",            QMessageBox.ButtonRole.DestructiveRole)
        cancel_btn   = mb.addButton("취소",            QMessageBox.ButtonRole.RejectRole)
        mb.setDefaultButton(minimize_btn)

        remember = QCheckBox("이 선택을 기억하기")
        remember.setStyleSheet("QCheckBox { color: #aaa; }")
        mb.setCheckBox(remember)

        mb.exec()
        clicked = mb.clickedButton()
        if clicked is minimize_btn:
            choice = "minimize"
        elif clicked is quit_btn:
            choice = "quit"
        else:
            return "cancel"

        if remember.isChecked():
            QSettings().setValue("tray/close_action", choice)
        return choice

    def _on_session_finished(
        self, sid: str, approved: int, rejected: int, pending: int
    ) -> None:
        parts = [f"✓ {approved} approved", f"✗ {rejected} rejected"]
        if pending:
            parts.append(f"⏳ {pending} pending")
        self.log_panel.append_log(
            f"[{sid}] Session finished: " + ", ".join(parts), "info"
        )

    # ------------------------------------------------------------------ #
    #  Signal wiring                                                       #
    # ------------------------------------------------------------------ #

    def _wire_session_signals(self, session: Session) -> None:
        a = session.adapter
        sid = session.id
        prefix = f"[{sid}] "

        a.log_message.connect(
            lambda msg, p=prefix: self.log_panel.append_log(p + msg)
        )
        a.activity_updated.connect(
            lambda detail, p=prefix: self.log_panel.set_activity(p + detail)
        )
        a.activity_updated.connect(
            lambda detail, p=prefix: self.log_panel.append_log(
                f"{p}Claude: {detail}", "dim"
            )
        )
        a.iteration_started.connect(
            lambda n, sid=sid: self.status_bar_widget.set_iteration_for(sid, n)
        )
        a.iteration_started.connect(lambda _: self.report_browser.set_running(True))
        a.cost_updated.connect(
            lambda cost, tokens, turns: self.status_bar_widget.update_cost(
                cost, tokens, turns
            )
        )

        a.plan_approved.connect(
            lambda plan, fp, p=prefix: (
                self.status_bar_widget.increment_approved(),
                self.log_panel.append_log(f"{p}Approved: {plan.title}", "success"),
                self.log_panel.append_log(f"{p}Saved to: {fp}", "dim"),
            )
        )
        a.plan_rejected.connect(
            lambda plan, reason, p=prefix: (
                self.status_bar_widget.increment_rejected(),
                self.log_panel.append_log(
                    f"{p}Rejected: {plan.title}"
                    + (f" — {reason}" if reason else ""),
                    "reject",
                ),
            )
        )
        a.plan_pending.connect(
            lambda plan, fp, p=prefix: (
                self.log_panel.append_log(f"{p}Pending: {plan.title}", "info"),
                self.log_panel.append_log(f"{p}Saved to: {fp}", "dim"),
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
            lambda p=prefix: self.log_panel.append_log(
                f"{p}No more improvements found. Codebase looks good!", "success"
            )
        )

        a.session_finished.connect(
            lambda approved, rejected, pending, sid=sid:
                self._on_session_finished(sid, approved, rejected, pending)
        )
        a.error_occurred.connect(
            lambda msg, p=prefix: self.log_panel.append_log(f"{p}Error: {msg}", "error")
        )

    # ------------------------------------------------------------------ #
    #  Report browser action handlers                                      #
    # ------------------------------------------------------------------ #

    def _on_resolve_requested(self, paths: list) -> None:
        """Move pending files to working/, then start a resolve session."""
        from ..engine.executor import _show_error

        config = self.config_panel.get_config()
        if not self._ensure_project_access(config["project_dir"]):
            return

        try:
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
        except Exception as e:
            _show_error(
                "pending → working 이동 실패",
                "파일을 working/ 으로 이동하는 도중 오류가 발생했습니다.",
                e,
            )
            return

        self.report_browser.refresh()

        if not moved:
            return

        try:
            adapter = GuiDisplayAdapter(self)

            from ..engine.executor import run_resolve_session

            label = (
                f"Resolve · 일괄 {len(moved)}개"
                if len(moved) > 1
                else f"Resolve · {moved[0].name}"
            )

            coro = run_resolve_session(
                plan_paths=moved,
                display=adapter,
                cwd=config["project_dir"],
                model=config["model"] or None,
                max_turns=config["max_turns"],
            )
            self._spawn_session(
                label=label,
                adapter=adapter,
                coro=coro,
                is_resolve=True,
            )
        except Exception as e:
            _show_error(
                "Resolve 세션 시작 실패",
                "resolve 세션을 시작하는 도중 오류가 발생했습니다.",
                e,
            )

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
        from ..engine.executor import _show_error, run_resolve_session

        plan_paths = [Path(p) for p in paths if Path(p).exists()]
        if not plan_paths:
            return

        config = self.config_panel.get_config()
        if not self._ensure_project_access(config["project_dir"]):
            return

        try:
            adapter = GuiDisplayAdapter(self)

            label = (
                f"Restart · 일괄 {len(plan_paths)}개"
                if len(plan_paths) > 1
                else f"Restart · {plan_paths[0].name}"
            )

            coro = run_resolve_session(
                plan_paths=plan_paths,
                display=adapter,
                cwd=config["project_dir"],
                model=config["model"] or None,
                max_turns=config["max_turns"],
            )
            self._spawn_session(
                label=label,
                adapter=adapter,
                coro=coro,
                is_resolve=True,
            )
        except Exception as e:
            _show_error(
                "Restart 실패",
                "working/ 에서 다시 시작하는 도중 오류가 발생했습니다.",
                e,
            )

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
