from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    RateLimitEvent,
    ResultMessage,
    ToolUseBlock,
    query,
)
from pydantic import ValidationError

from .models import DiscoveredPlan
from .tool_summary import summarize_tool

logger = logging.getLogger(__name__)


@dataclass
class DiscoveryResult:
    plan: DiscoveredPlan | None
    cost_usd: float
    total_tokens: int
    session_id: str | None
    model: str | None = None
    num_turns: int = 0


QUERY_TIMEOUT_SECONDS = 30 * 60  # 30 minutes per query


async def discover_plan(
    prompt: str,
    cwd: str | None = None,
    resume_session_id: str | None = None,
    on_activity: Callable[[str], None] | None = None,
    model: str | None = None,
    max_turns: int = 80,
) -> DiscoveryResult:
    """Run a single Claude query to discover one improvement plan."""
    import asyncio

    target_dir = cwd or os.getcwd()

    from .executor import (
        _StderrBuffer,
        _resolve_anthropic_api_key,
        _resolve_cli_path,
        _show_error,
    )

    stderr_buf = _StderrBuffer()
    options = ClaudeAgentOptions(
        allowed_tools=["Read", "Glob", "Grep", "WebSearch"],
        permission_mode="bypassPermissions",
        cwd=target_dir,
        max_turns=max_turns,
        output_format={
            "type": "json_schema",
            "schema": DiscoveredPlan.model_json_schema(),
        },
        system_prompt=(
            "You are in READ-ONLY mode. You may only use Read, Glob, Grep, "
            "and WebSearch. Do NOT modify any files. Your goal is to analyze "
            "the codebase and produce a structured improvement plan."
        ),
        stderr=stderr_buf,
    )

    if model:
        options.model = model

    if resume_session_id:
        options.resume = resume_session_id
    try:
        cli_path = _resolve_cli_path()
        if cli_path:
            options.cli_path = cli_path
    except Exception as e:
        _show_error(
            "Claude CLI 경로 적용 실패",
            "ClaudeAgentOptions에 cli_path를 적용하는 중 오류가 발생했습니다.",
            e,
        )

    try:
        api_key = _resolve_anthropic_api_key()
        if api_key:
            options.env = {**(options.env or {}), "ANTHROPIC_API_KEY": api_key}
    except Exception as e:
        _show_error(
            "Anthropic API Key 적용 실패",
            "ClaudeAgentOptions에 API 키를 적용하는 중 오류가 발생했습니다.",
            e,
        )

    last_result_subtype: str | None = None

    async def _run_query() -> DiscoveryResult:
        nonlocal last_result_subtype
        plan: DiscoveredPlan | None = None
        cost: float = 0.0
        tokens: int = 0
        session_id: str | None = None
        _model: str | None = None
        turns: int = 0

        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                if _model is None:
                    _model = message.model
                has_tool_use = False
                for block in message.content:
                    if isinstance(block, ToolUseBlock):
                        has_tool_use = True
                        if on_activity:
                            detail = summarize_tool(block.name, block.input)
                            on_activity(detail)
                if has_tool_use:
                    turns += 1
                if message.error:
                    raise RuntimeError(f"Claude API error: {message.error}")
            elif isinstance(message, RateLimitEvent):
                if message.rate_limit_info.status == "rejected":
                    raise RuntimeError(
                        f"rate_limit: Rate limit rejected"
                        f" (type={message.rate_limit_info.rate_limit_type},"
                        f" resets_at={message.rate_limit_info.resets_at})"
                    )
            elif isinstance(message, ResultMessage):
                last_result_subtype = message.subtype
                cost = message.total_cost_usd or 0.0
                session_id = message.session_id
                if message.usage:
                    u = message.usage
                    tokens = (
                        u.get("input_tokens", 0)
                        + u.get("output_tokens", 0)
                        + u.get("cache_read_input_tokens", 0)
                        + u.get("cache_creation_input_tokens", 0)
                    )
                if message.subtype == "success" and message.structured_output:
                    try:
                        plan = DiscoveredPlan.model_validate(message.structured_output)
                    except ValidationError as ve:
                        # Log validation error but preserve cost data for tracking
                        logger.warning(
                            "ValidationError parsing structured output: %s. "
                            "Cost will still be tracked. Raw output: %s",
                            ve,
                            message.structured_output,
                        )
                        plan = None

        return DiscoveryResult(
            plan=plan, cost_usd=cost, total_tokens=tokens, session_id=session_id,
            model=_model, num_turns=turns,
        )

    try:
        return await asyncio.wait_for(_run_query(), timeout=QUERY_TIMEOUT_SECONDS)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        raise
    except Exception as e:
        # Give the SDK's detached stderr reader a moment to drain any final
        # lines into stderr_buf before we snapshot it for the error report.
        try:
            await asyncio.sleep(0.2)
        except Exception:
            pass

        # Rate limit errors are handled (wait + retry) by the caller in engine.py.
        # Don't show a popup — just propagate silently.
        err_str = str(e).lower()
        if "rate_limit" in err_str or "rate limit" in err_str:
            raise

        summary = "discover_plan 실행 중 예외가 발생했습니다."
        resolved_cli = getattr(options, "cli_path", None)
        if resolved_cli:
            summary += f"\n\nClaude CLI 경로: {resolved_cli}"
        if model:
            summary += f"\n모델: {model}"
        # The CLI exits with code 1 for non-success ResultMessage subtypes
        # (e.g. error_max_turns). The SDK turns that into an opaque "Command
        # failed" exception with empty stderr — show the actual subtype
        # we captured during iteration instead.
        if last_result_subtype and last_result_subtype != "success":
            summary += (
                f"\n\n실패 원인 (ResultMessage.subtype): {last_result_subtype}"
            )
            if last_result_subtype == "error_max_turns":
                summary += (
                    f"\n→ 최대 턴({max_turns})을 초과했습니다. 환경설정에서 "
                    f"'최대 턴' 값을 늘려보세요."
                )
        stderr_text = stderr_buf.text()
        if stderr_text:
            summary += f"\n\nClaude CLI stderr:\n{stderr_text}"
        elif not last_result_subtype:
            summary += (
                "\n\nClaude CLI stderr: (비어있음 — CLI가 stderr 출력 없이 즉시 종료됨)"
                "\n→ 터미널에서 `claude -v` 와 `claude` 를 직접 실행하여 인증/버전을 확인하세요."
            )
        _show_error("Discovery 쿼리 오류", summary, e)
        raise


