from __future__ import annotations

import asyncio
from pathlib import Path

from .discovery import discover_plan
from .display_interface import DisplayInterface
from .prompts import build_prompt
from .reporter import save_plan, scan_existing_plans
from .state import StateManager
from .throttle import SessionThrottle


QUIET_START = 22  # 22:00
QUIET_END = 3     # 03:00

_RATE_LIMIT_PATTERNS = [
    "hit your limit",
    "rate limit",
    "rate_limit",
    "overloaded",
]

MAX_CONSECUTIVE_ERRORS = 3


def _is_rate_limit_error(err_msg: str) -> bool:
    lower = err_msg.lower()
    return any(p in lower for p in _RATE_LIMIT_PATTERNS)


def _is_retriable_error(err_msg: str) -> bool:
    lower = err_msg.lower()
    return (
        "exit code 1" in lower
        or "command failed" in lower
        or "connection" in lower
        or "timeout" in lower
    )


def _quiet_hours_enabled() -> bool:
    """Read the user's Quiet Hours toggle from QSettings (default: enabled)."""
    try:
        from PySide6.QtCore import QSettings
        v = QSettings().value("quiet_hours_enabled", True)
    except Exception:
        return True
    return v in (True, "true", "True", "1")


async def _wait_if_quiet_hours(display: DisplayInterface) -> None:
    """Sleep until quiet hours (22:00~03:00) are over (when enabled)."""
    from datetime import datetime, timedelta

    if not _quiet_hours_enabled():
        return

    now = datetime.now()
    hour = now.hour

    if hour >= QUIET_START or hour < QUIET_END:
        wake = now.replace(hour=QUIET_END, minute=0, second=0, microsecond=0)
        if hour >= QUIET_START:
            wake += timedelta(days=1)
        wait_secs = (wake - now).total_seconds()
        display.log(
            f"Quiet hours (22:00~03:00). "
            f"Sleeping until {wake.strftime('%H:%M')} "
            f"({wait_secs / 60:.0f} min)..."
        )
        await asyncio.sleep(wait_secs)
        display.log("Quiet hours over, resuming...")


async def _wait_for_next_session(
    display: DisplayInterface, throttle: SessionThrottle | None
) -> None:
    """Wait until the current session ends, then return."""
    from datetime import datetime

    if throttle and throttle.session_ready:
        now = datetime.now()
        remaining = (throttle.session_end - now).total_seconds()
        if remaining > 0:
            display.log(
                f"Session ends at {throttle.session_end.strftime('%H:%M')}. "
                f"Waiting {remaining / 60:.0f} min..."
            )
            await asyncio.sleep(remaining + 60)
            return

    display.log("Waiting 5 min before retrying...")
    await asyncio.sleep(300)


async def run_discovery_loop(
    plan_prompt: str,
    display: DisplayInterface,
    max_iterations: int | None = None,
    report_dir: Path | None = None,
    cwd: str | None = None,
    auto: bool = False,
    throttle: SessionThrottle | None = None,
    throttle_enabled: bool = False,
    resume: bool = True,
    stop_at: object | None = None,  # datetime.time
    model: str | None = None,
    max_turns: int = 80,
    post_save_hook=None,  # Callable[[Path], Awaitable[None]] | Callable[[Path], None] | None
) -> None:
    """Main discovery loop.

    When auto=False (interactive):
      find plan -> show -> user approves/rejects -> repeat

    When auto=True (unattended):
      find plan -> save to pending/ -> repeat
    """
    import os

    effective_cwd = cwd or os.getcwd()
    project_name = Path(effective_cwd).name

    if report_dir is None:
        report_dir = Path.home() / "claude-reports" / project_name

    state_mgr = StateManager(report_dir)
    state_mgr.load()

    if state_mgr.load_error:
        backup_info = f" Backup created at {state_mgr.backup_path}" if state_mgr.backup_path else ""
        display.on_error(
            f"State file was corrupted.{backup_info} Rejection history has been reset."
        )

    from datetime import datetime as _dt

    iteration = 0
    session_approved = 0
    session_rejected = 0
    session_pending = 0
    session_id: str | None = None
    session_start_time = _dt.now()
    consecutive_errors = 0

    stop_at_datetime = None
    if stop_at:
        # stop_at is now a full datetime object
        stop_at_datetime = stop_at
        display.log(f"세션 중단 예정: {stop_at.strftime('%Y-%m-%d %H:%M')}")

    try:
        while True:
            iteration += 1

            if max_iterations and iteration > max_iterations:
                display.log(f"Reached max iterations ({max_iterations}). Stopping.")
                break

            if stop_at_datetime and _dt.now() >= stop_at_datetime:
                display.log(f"중단 시간 도달 ({stop_at_datetime.strftime('%Y-%m-%d %H:%M')}). 중단.")
                break

            await _wait_if_quiet_hours(display)

            if throttle and throttle.session_ready:
                from datetime import datetime
                if datetime.now() > throttle.session_end:
                    display.log("Session expired, re-detecting...")
                    await throttle.reinit_async()

            if throttle_enabled and throttle:
                await throttle.wait_if_needed()

            display.on_iteration_start(iteration)
            if throttle:
                display.log(throttle.status_line())
            if session_id and resume:
                display.log(f"Resuming session {session_id[:8]}...")

            existing_plans = scan_existing_plans(report_dir)

            if session_id and resume:
                new_plans = [
                    r for r in state_mgr.state.rejected_plans
                    if r.rejected_at > session_start_time
                ]
                prompt = build_prompt(plan_prompt, new_plans, existing_plans)
            else:
                prompt = build_prompt(
                    plan_prompt, state_mgr.state.rejected_plans, existing_plans
                )

            resume_id = session_id if resume else None

            try:
                result = await discover_plan(
                    prompt=prompt,
                    cwd=effective_cwd,
                    resume_session_id=resume_id,
                    on_activity=display.on_activity,
                    model=model,
                    max_turns=max_turns,
                )
            except asyncio.TimeoutError:
                display.on_error("Query timed out (30 min). Resetting session and retrying...")
                session_id = None
                session_start_time = _dt.now()
                iteration -= 1
                continue
            except asyncio.CancelledError:
                raise
            except Exception as e:
                err_msg = str(e)
                if _is_rate_limit_error(err_msg):
                    display.on_error("Rate limit reached. Waiting for next session...")
                    await _wait_for_next_session(display, throttle)
                    session_id = None
                    session_start_time = _dt.now()
                    if throttle:
                        await throttle.reinit_async()
                    consecutive_errors = 0
                    iteration -= 1
                    continue
                if "prompt is too long" in err_msg.lower() or "maximum buffer size" in err_msg.lower():
                    display.log("Session context too large. Resetting session and retrying...")
                    session_id = None
                    session_start_time = _dt.now()
                    iteration -= 1
                    continue
                if _is_retriable_error(err_msg):
                    consecutive_errors += 1
                    display.on_error(
                        f"Error (attempt {consecutive_errors}/{MAX_CONSECUTIVE_ERRORS}): "
                        f"{err_msg[:120]}"
                    )
                    if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                        display.on_error(
                            "Too many consecutive errors. "
                            "Treating as rate limit and waiting for next session..."
                        )
                        await _wait_for_next_session(display, throttle)
                        session_id = None
                        session_start_time = _dt.now()
                        if throttle:
                            await throttle.reinit_async()
                        consecutive_errors = 0
                        iteration -= 1
                        continue
                    display.log("Resetting session and retrying in 30s...")
                    await asyncio.sleep(30)
                    session_id = None
                    session_start_time = _dt.now()
                    iteration -= 1
                    continue
                display.on_error(f"Unexpected error: {err_msg[:200]}")
                display.log("Stopping gracefully.")
                break

            consecutive_errors = 0

            if result.session_id:
                session_id = result.session_id

            display.on_iteration_cost(result.cost_usd, result.total_tokens, result.num_turns)

            if throttle:
                throttle.add_usage(result.cost_usd, result.total_tokens, result.model)

            if result.plan is None:
                display.log("Failed to get structured output from Claude. Retrying...")
                iteration -= 1
                continue

            if result.plan.found_nothing:
                display.on_no_more_plans()
                break

            if auto:
                # Update state first (atomic write) so duplicate-detection works
                # even if the file write fails or process crashes between operations
                state_mgr.add_pending(result.plan)
                filepath = save_plan(result.plan, iteration, report_dir, pending=True)
                if post_save_hook:
                    try:
                        if asyncio.iscoroutinefunction(post_save_hook):
                            await post_save_hook(filepath)
                        else:
                            post_save_hook(filepath)
                    except Exception:
                        pass
                session_pending += 1
                display.on_plan_pending(result.plan, filepath)
            else:
                current_plan = result.plan
                while True:
                    action, feedback = await display.request_approval(current_plan, iteration)

                    if action == "approve":
                        # Update state first (atomic write) so duplicate-detection works
                        # even if the file write fails or process crashes between operations
                        state_mgr.record_approval(current_plan)
                        filepath = save_plan(current_plan, iteration, report_dir)
                        session_approved += 1
                        display.on_plan_approved(current_plan, filepath)
                        break
                    elif action == "reject":
                        state_mgr.add_rejection(current_plan, feedback)
                        session_rejected += 1
                        display.on_plan_rejected(current_plan, feedback)
                        break
                    else:  # revise
                        display.log("Sending feedback to Claude...")
                        revision_prompt = (
                            f"I have feedback on the plan you just proposed "
                            f"(\"{current_plan.title}\"):\n\n"
                            f"{feedback}\n\n"
                            f"Please revise the plan based on this feedback, "
                            f"or propose a completely different plan if the "
                            f"feedback invalidates the original idea."
                        )
                        try:
                            revision = await discover_plan(
                                prompt=revision_prompt,
                                cwd=effective_cwd,
                                resume_session_id=session_id,
                                on_activity=display.on_activity,
                                model=model,
                                max_turns=max_turns,
                            )
                        except asyncio.CancelledError:
                            raise
                        except Exception as e:
                            err_msg = str(e)
                            if _is_rate_limit_error(err_msg) or _is_retriable_error(err_msg):
                                display.on_error(f"Error during revision: {err_msg[:120]}")
                                # Save original plan as pending so it's not lost
                                try:
                                    state_mgr.add_pending(current_plan)
                                    filepath = save_plan(
                                        current_plan, iteration, report_dir, pending=True
                                    )
                                    session_pending += 1
                                    display.log(
                                        "Original plan saved as pending due to revision error."
                                    )
                                    display.on_plan_pending(current_plan, filepath)
                                except Exception as save_err:
                                    display.on_error(
                                        f"Failed to save original plan: {save_err}"
                                    )
                                display.log("Waiting for next session...")
                                await _wait_for_next_session(display, throttle)
                                session_id = None
                                session_start_time = _dt.now()
                                if throttle:
                                    await throttle.reinit_async()
                                break
                            display.on_error(f"Unexpected error during revision: {err_msg[:200]}")
                            # Save original plan as pending so it's not lost
                            try:
                                state_mgr.add_pending(current_plan)
                                filepath = save_plan(
                                    current_plan, iteration, report_dir, pending=True
                                )
                                session_pending += 1
                                display.log(
                                    "Original plan saved as pending due to revision error."
                                )
                                display.on_plan_pending(current_plan, filepath)
                            except Exception as save_err:
                                display.on_error(
                                    f"Failed to save original plan: {save_err}"
                                )
                            break

                        if revision.session_id:
                            session_id = revision.session_id
                        if throttle:
                            throttle.add_usage(
                                revision.cost_usd, revision.total_tokens, revision.model
                            )
                        display.on_iteration_cost(
                            revision.cost_usd, revision.total_tokens, revision.num_turns
                        )

                        if revision.plan and not revision.plan.found_nothing:
                            current_plan = revision.plan
                            # loop back → request_approval called again with revised plan
                        else:
                            display.on_error("Revision failed to produce a plan.")
                            # Save original plan as pending so it's not lost
                            try:
                                state_mgr.add_pending(current_plan)
                                filepath = save_plan(
                                    current_plan, iteration, report_dir, pending=True
                                )
                                session_pending += 1
                                display.log(
                                    "Original plan saved as pending due to revision failure."
                                )
                                display.on_plan_pending(current_plan, filepath)
                            except Exception as save_err:
                                display.on_error(
                                    f"Failed to save original plan: {save_err}"
                                )
                            break

    except (KeyboardInterrupt, asyncio.CancelledError):
        display.log("Stopped by user.")
    finally:
        display.on_session_finished(session_approved, session_rejected, session_pending)
