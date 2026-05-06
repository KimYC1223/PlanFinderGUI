from __future__ import annotations

import json
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QGroupBox,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


# ---------------------------------------------------------------------------
# Background worker — runs ccusage in a thread and emits parsed data
# ---------------------------------------------------------------------------

class _Worker(QObject):
    data_ready = Signal(dict)

    def fetch(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        result: dict = {"session": None, "today_cost": 0.0, "today_tokens": 0, "account": None, "error": None}

        # ── ccusage: all blocks ─────────────────────────────────────────────
        try:
            proc = subprocess.run(
                ["ccusage", "blocks", "--json", "--recent", "--offline"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if proc.returncode == 0:
                data = json.loads(proc.stdout)
                today = datetime.now().date()
                for block in data.get("blocks", []):
                    # Parse active session
                    if block.get("isActive"):
                        result["session"] = block

                    # Sum today's usage
                    try:
                        start_str = block.get("startTime", "")
                        dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                        if dt.astimezone().replace(tzinfo=None).date() == today:
                            result["today_cost"] += block.get("costUSD", 0.0)
                            result["today_tokens"] += block.get("totalTokens", 0)
                    except Exception:
                        pass
        except FileNotFoundError:
            result["error"] = "ccusage 미설치"
        except subprocess.TimeoutExpired:
            result["error"] = "ccusage timeout"
        except Exception as e:
            result["error"] = str(e)[:60]

        # ── Account info ────────────────────────────────────────────────────
        result["account"] = _read_account_email()

        self.data_ready.emit(result)


def _read_account_email() -> str | None:
    """Try to read Claude Code account email from credentials file."""
    candidates = [
        Path.home() / ".claude" / ".credentials.json",
        Path.home() / ".claude" / "credentials.json",
        Path.home() / ".config" / "claude" / "credentials.json",
    ]
    for path in candidates:
        try:
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                # common structures
                email = (
                    data.get("emailAddress")
                    or data.get("email")
                    or (data.get("oauthAccount") or {}).get("emailAddress")
                    or (data.get("account") or {}).get("email")
                )
                if email:
                    return str(email)
        except Exception:
            pass
    return None


def _fmt_tokens(tokens: int) -> str:
    if tokens >= 1_000_000:
        return f"{tokens / 1_000_000:.1f}M"
    if tokens >= 1_000:
        return f"{tokens / 1_000:.1f}K"
    return str(tokens)


# ---------------------------------------------------------------------------
# Widget
# ---------------------------------------------------------------------------

class ClaudeSessionPanel(QWidget):
    """Shows current Claude Code session usage info. Refreshes every 2 s."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._worker = _Worker()
        self._worker.data_ready.connect(self._on_data)
        self._fetching = False

        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self._build_ui()

        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()
        self._refresh()

    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        group = QGroupBox("Claude 세션")
        group.setStyleSheet(
            "QGroupBox {"
            "  color: #888; font-size: 10px; font-weight: bold;"
            "  border: 1px solid #333; border-radius: 4px;"
            "  margin-top: 8px; padding-top: 4px;"
            "}"
            "QGroupBox::title { subcontrol-origin: margin; left: 8px; top: -1px; }"
        )
        group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        inner = QVBoxLayout(group)
        inner.setContentsMargins(8, 6, 8, 6)
        inner.setSpacing(2)

        lbl_style = "color: #999; font-size: 11px; background: transparent;"
        val_style = "color: #ccc; font-size: 11px; background: transparent;"
        dim_style = "color: #666; font-size: 10px; background: transparent;"

        self._account_lbl = QLabel("계정: 로딩 중...")
        self._account_lbl.setStyleSheet(val_style)
        inner.addWidget(self._account_lbl)

        sep1 = QLabel()
        sep1.setFixedHeight(1)
        sep1.setStyleSheet("background: #333;")
        inner.addWidget(sep1)

        self._sess_header = QLabel("현재 세션")
        self._sess_header.setStyleSheet(lbl_style)
        inner.addWidget(self._sess_header)

        self._sess_time = QLabel("  로딩 중...")
        self._sess_time.setStyleSheet(dim_style)
        inner.addWidget(self._sess_time)

        self._sess_cost = QLabel("")
        self._sess_cost.setStyleSheet(dim_style)
        inner.addWidget(self._sess_cost)

        self._sess_model = QLabel("")
        self._sess_model.setStyleSheet(dim_style)
        self._sess_model.setWordWrap(True)
        inner.addWidget(self._sess_model)

        sep2 = QLabel()
        sep2.setFixedHeight(1)
        sep2.setStyleSheet("background: #333;")
        inner.addWidget(sep2)

        self._today_header = QLabel("오늘 합계")
        self._today_header.setStyleSheet(lbl_style)
        inner.addWidget(self._today_header)

        self._today_cost = QLabel("  로딩 중...")
        self._today_cost.setStyleSheet(dim_style)
        inner.addWidget(self._today_cost)

        self._today_tokens = QLabel("")
        self._today_tokens.setStyleSheet(dim_style)
        inner.addWidget(self._today_tokens)

        inner.addStretch()

        outer.addWidget(group)

    # ------------------------------------------------------------------ #

    def _refresh(self) -> None:
        if self._fetching:
            return
        self._fetching = True
        self._worker.fetch()

    def showEvent(self, event):  # type: ignore[override]
        # Resume polling whenever the panel becomes visible.
        if not self._timer.isActive():
            self._timer.start()
            self._refresh()
        super().showEvent(event)

    def hideEvent(self, event):  # type: ignore[override]
        # Pause ccusage polling while hidden — no point spawning a subprocess
        # every 2s when nobody can see the result.
        self._timer.stop()
        super().hideEvent(event)

    def _on_data(self, result: dict) -> None:
        self._fetching = False

        # Account
        email = result.get("account")
        self._account_lbl.setText(f"계정: {email}" if email else "계정: —")

        # Active session
        sess = result.get("session")
        if sess:
            try:
                start = datetime.fromisoformat(
                    sess["startTime"].replace("Z", "+00:00")
                ).astimezone().replace(tzinfo=None)
                end = datetime.fromisoformat(
                    sess["endTime"].replace("Z", "+00:00")
                ).astimezone().replace(tzinfo=None)
                now = datetime.now()
                remaining = max(0.0, (end - now).total_seconds())
                self._sess_time.setText(
                    f"  {start.strftime('%H:%M')} ~ {end.strftime('%H:%M')}"
                    f"  ({remaining / 3600:.1f}h 남음)"
                )
            except Exception:
                self._sess_time.setText("  시간: 파싱 오류")

            cost = sess.get("costUSD", 0.0)
            self._sess_cost.setText(f"  비용: ${cost:.2f}")

            models = [m for m in sess.get("models", []) if m != "<synthetic>"]
            model_str = ", ".join(models) if models else "—"
            self._sess_model.setText(f"  모델: {model_str}")
        else:
            err = result.get("error")
            if err:
                self._sess_time.setText(f"  ({err})")
            else:
                self._sess_time.setText("  활성 세션 없음")
            self._sess_cost.setText("")
            self._sess_model.setText("")

        # Today totals
        today_cost = result.get("today_cost", 0.0)
        today_tokens = result.get("today_tokens", 0)
        self._today_cost.setText(f"  비용: ${today_cost:.2f}")
        self._today_tokens.setText(f"  토큰: {_fmt_tokens(today_tokens)}")
