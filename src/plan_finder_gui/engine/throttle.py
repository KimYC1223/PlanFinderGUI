"""Session-aware throttle using cost ($) from ResultMessage.total_cost_usd.

Formula:
  (cumulative_cost / session_budget) * 1.05 < (elapsed / session_duration)

Session timing auto-detected via `ccusage blocks --json`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from collections.abc import Callable
from datetime import datetime

logger = logging.getLogger(__name__)

DEFAULT_SESSION_BUDGET = 40.0  # $40 per session


class CcusageNotInstalled(RuntimeError):
    """ccusage CLI is not installed."""


class NoActiveSession(RuntimeError):
    """ccusage found no active session block."""


def _run_ccusage_subprocess() -> subprocess.CompletedProcess:
    """Run ccusage subprocess (blocking). Called from thread pool.

    Raises FileNotFoundError if ccusage is missing.
    Raises subprocess.TimeoutExpired if timeout exceeded.
    """
    return subprocess.run(
        ["ccusage", "blocks", "--json", "--active"],
        capture_output=True,
        text=True,
        timeout=30,
    )


def _parse_ccusage_result(json_result: subprocess.CompletedProcess) -> dict:
    """Parse ccusage subprocess result into session info dict.

    Raises NoActiveSession if parsing fails or no active block found.
    """
    if json_result.returncode != 0:
        raise NoActiveSession(
            f"ccusage exited with code {json_result.returncode}: {json_result.stderr.strip()[:200]}"
        )

    try:
        data = json.loads(json_result.stdout)
    except json.JSONDecodeError as e:
        raise NoActiveSession(
            f"ccusage returned malformed JSON: {json_result.stdout[:200]}"
        ) from e

    active_block = None
    for block in data.get("blocks", []):
        if block.get("isActive"):
            active_block = block

    if active_block is None:
        raise NoActiveSession("No active session found via ccusage.")

    # Defensive parsing of time fields - ccusage may return unexpected formats
    try:
        start_time_raw = active_block["startTime"]
        end_time_raw = active_block["endTime"]
        start_utc = datetime.fromisoformat(
            start_time_raw.replace("Z", "+00:00")
        )
        end_utc = datetime.fromisoformat(
            end_time_raw.replace("Z", "+00:00")
        )
        session_start = start_utc.astimezone().replace(tzinfo=None)
        session_end = end_utc.astimezone().replace(tzinfo=None)
    except KeyError as e:
        raise NoActiveSession(
            f"ccusage returned active block without required time field: {e}"
        ) from e
    except (TypeError, AttributeError) as e:
        # TypeError/AttributeError if startTime or endTime is None or not a string
        raise NoActiveSession(
            f"ccusage returned active block with invalid time value (null or wrong type): {e}"
        ) from e
    except ValueError as e:
        # ValueError if the date string is malformed
        raise NoActiveSession(
            f"ccusage returned active block with malformed date string: {e}"
        ) from e

    # Defensive parsing of costUSD field - raise if missing, warn if wrong type
    if "costUSD" not in active_block:
        raise NoActiveSession(
            "ccusage returned active block without costUSD field - "
            "ccusage version may be incompatible"
        )

    cost_usd_raw = active_block["costUSD"]
    if isinstance(cost_usd_raw, (int, float)):
        cost_usd = float(cost_usd_raw)
    else:
        logger.warning(
            "ccusage returned costUSD with unexpected type %s (value: %r), "
            "falling back to 0.0. Check ccusage version compatibility.",
            type(cost_usd_raw).__name__,
            cost_usd_raw,
        )
        cost_usd = 0.0

    return {
        "session_start": session_start,
        "session_end": session_end,
        "cost_usd": cost_usd,
        "models": active_block.get("models", []),
    }


async def detect_session_async() -> dict:
    """Async auto-detect current session info from ccusage.

    This function runs the blocking subprocess call in a thread pool
    to avoid blocking the Qt event loop.

    Returns dict with keys:
      session_start: datetime (local)
      session_end: datetime (local)
      cost_usd: float (cost already spent in this session)
      models: list[str] (models used in this session)

    Raises CcusageNotInstalled if ccusage is missing.
    Raises NoActiveSession if no active block found or timeout.
    """
    try:
        json_result = await asyncio.to_thread(_run_ccusage_subprocess)
    except FileNotFoundError:
        raise CcusageNotInstalled(
            "ccusage is required but not installed. Install it with: brew install ccusage"
        )
    except subprocess.TimeoutExpired:
        raise NoActiveSession("ccusage timed out (30s). Skipping session detection.")

    return _parse_ccusage_result(json_result)


def detect_session() -> dict:
    """Synchronous auto-detect current session info from ccusage.

    WARNING: This function blocks the calling thread for up to 30 seconds.
    Prefer detect_session_async() in async contexts.

    Returns dict with keys:
      session_start: datetime (local)
      session_end: datetime (local)
      cost_usd: float (cost already spent in this session)
      models: list[str] (models used in this session)

    Raises CcusageNotInstalled if ccusage is missing.
    Raises NoActiveSession if no active block found.
    """
    try:
        json_result = _run_ccusage_subprocess()
    except FileNotFoundError:
        raise CcusageNotInstalled(
            "ccusage is required but not installed. Install it with: brew install ccusage"
        )
    except subprocess.TimeoutExpired:
        raise NoActiveSession("ccusage timed out (30s). Skipping session detection.")

    return _parse_ccusage_result(json_result)


class SessionThrottle:
    def __init__(
        self,
        session_budget: float = DEFAULT_SESSION_BUDGET,
        log_fn: Callable[[str], None] | None = None,
        *,
        _skip_init: bool = False,
    ) -> None:
        """Initialize SessionThrottle.

        Args:
            session_budget: Budget in USD for the session.
            log_fn: Optional logging callback.
            _skip_init: Internal flag to skip sync init for async factory.
        """
        self.session_budget = session_budget
        self.cumulative_cost: float = 0.0
        self.cumulative_tokens: int = 0
        self.model: str | None = None
        self.session_ready: bool = False
        self.last_error: str | None = None
        self._log = log_fn or (lambda _: None)
        if not _skip_init:
            self._init_session()

    @classmethod
    async def create_async(
        cls,
        session_budget: float = DEFAULT_SESSION_BUDGET,
        log_fn: Callable[[str], None] | None = None,
    ) -> "SessionThrottle":
        """Async factory to create SessionThrottle without blocking.

        Use this instead of __init__ when creating SessionThrottle from
        an async context to avoid blocking the event loop.
        """
        instance = cls(session_budget, log_fn, _skip_init=True)
        await instance._init_session_async()
        return instance

    def _apply_session_info(self, session_info: dict) -> None:
        """Apply session info dict to instance state."""
        self.session_ready = True
        self.session_start = session_info["session_start"]
        self.session_end = session_info["session_end"]
        self.session_duration = self.session_end - self.session_start
        if self.session_duration.total_seconds() <= 0:
            self._log("Session has zero or negative duration — throttle disabled.")
            self.session_ready = False
            return
        self.cumulative_cost = session_info["cost_usd"]
        models = [m for m in session_info.get("models", []) if m != "<synthetic>"]
        if models and self.model is None:
            self.model = models[0]
        self._log(
            f"Session detected via ccusage: "
            f"{self.session_start.strftime('%H:%M')} ~ "
            f"{self.session_end.strftime('%H:%M')}, "
            f"${self.cumulative_cost:.2f}/${self.session_budget:.0f} spent"
        )

    def _init_session(self) -> None:
        """Synchronous session initialization (blocks for up to 30s).

        Catches both NoActiveSession and CcusageNotInstalled to gracefully
        disable throttling rather than crashing the discovery loop.
        """
        try:
            session_info = detect_session()
        except NoActiveSession as e:
            self.session_ready = False
            self.last_error = str(e)
            self._log("No active session yet — throttle disabled until session starts.")
            return
        except CcusageNotInstalled as e:
            self.session_ready = False
            self.last_error = str(e)
            self._log(
                "ccusage became unavailable — throttle disabled. "
                "Check PATH or reinstall ccusage."
            )
            return

        self.last_error = None
        self._apply_session_info(session_info)

    async def _init_session_async(self) -> None:
        """Async session initialization (non-blocking).

        Catches both NoActiveSession and CcusageNotInstalled to gracefully
        disable throttling rather than crashing the discovery loop.
        """
        try:
            session_info = await detect_session_async()
        except NoActiveSession as e:
            self.session_ready = False
            self.last_error = str(e)
            self._log("No active session yet — throttle disabled until session starts.")
            return
        except CcusageNotInstalled as e:
            self.session_ready = False
            self.last_error = str(e)
            self._log(
                "ccusage became unavailable — throttle disabled. "
                "Check PATH or reinstall ccusage."
            )
            return

        self.last_error = None
        self._apply_session_info(session_info)

    def reinit(self) -> None:
        """Re-detect session info synchronously (blocks for up to 30s).

        WARNING: This function blocks the calling thread for up to 30 seconds.
        Prefer reinit_async() in async contexts.
        """
        self._log("Re-detecting session...")
        self.cumulative_cost = 0.0
        self.cumulative_tokens = 0
        self._init_session()

    async def reinit_async(self) -> None:
        """Re-detect session info asynchronously (non-blocking)."""
        self._log("Re-detecting session...")
        self.cumulative_cost = 0.0
        self.cumulative_tokens = 0
        await self._init_session_async()

    def add_usage(self, cost_usd: float, tokens: int, model: str | None = None) -> None:
        self.cumulative_cost += cost_usd
        self.cumulative_tokens += tokens
        if model and self.model is None:
            self.model = model

    def _elapsed_ratio(self) -> float:
        now = datetime.now()
        elapsed = (now - self.session_start).total_seconds()
        total = self.session_duration.total_seconds()
        if total <= 0:
            return 1.0
        return max(0.0, min(1.0, elapsed / total))

    def _usage_ratio(self) -> float:
        if self.session_budget <= 0:
            return 0.0
        return self.cumulative_cost / self.session_budget

    def is_allowed(self) -> bool:
        if not self.session_ready:
            return True
        return self._usage_ratio() * 1.05 < self._elapsed_ratio()

    def seconds_until_allowed(self) -> float:
        usage = self._usage_ratio()
        if usage <= 0:
            return 0.0
        total_secs = self.session_duration.total_seconds()
        elapsed_secs = (datetime.now() - self.session_start).total_seconds()
        needed_elapsed = usage * 1.05 * total_secs
        remaining = max(0.0, needed_elapsed - elapsed_secs)
        time_until_session_end = max(0.0, total_secs - elapsed_secs)
        return min(remaining, time_until_session_end)

    async def wait_if_needed(self) -> None:
        import asyncio

        while not self.is_allowed():
            wait = self.seconds_until_allowed()
            if wait <= 0:
                break
            wait += 30  # buffer to avoid re-triggering
            from datetime import datetime

            now_str = datetime.now().strftime("%H:%M:%S")
            self._log(
                f"[{now_str}] Throttling: cost {self._usage_ratio():.0%} * 1.05 "
                f"> time {self._elapsed_ratio():.0%}. "
                f"Waiting {wait / 60:.1f} min..."
            )
            await asyncio.sleep(wait)
            self._log("Throttle wait done, resuming...")

    def status_line(self) -> str:
        if not self.session_ready:
            model_str = f" | Model: {self.model}" if self.model else ""
            return f"No active session — throttle disabled{model_str}"

        usage = self._usage_ratio()
        elapsed = self._elapsed_ratio()
        pace = usage * 1.05
        margin = elapsed - pace

        if margin > 0.15:
            indicator = "Plenty"
        elif margin > 0.05:
            indicator = "OK"
        elif margin > 0:
            indicator = "Tight"
        else:
            indicator = "Over budget"

        remaining_hours = (
            self.session_duration.total_seconds() * (1 - elapsed) / 3600
        )

        model_str = f" | Model: {self.model}" if self.model else ""

        return (
            f"Cost: ${self.cumulative_cost:.2f}/"
            f"${self.session_budget:.0f} "
            f"({usage:.0%}) | "
            f"Session: {elapsed:.0%} ({remaining_hours:.1f}h left) | "
            f"{indicator} (pace {pace:.0%} vs time {elapsed:.0%})"
            f"{model_str}"
        )
