from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    ToolUseBlock,
    query,
)

from .models import DiscoveredPlan
from .tool_summary import summarize_tool


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

    async def _run_query() -> DiscoveryResult:
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
            elif isinstance(message, ResultMessage):
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
                    plan = DiscoveredPlan.model_validate(message.structured_output)

        return DiscoveryResult(
            plan=plan, cost_usd=cost, total_tokens=tokens, session_id=session_id,
            model=_model, num_turns=turns,
        )

    try:
        return await asyncio.wait_for(_run_query(), timeout=QUERY_TIMEOUT_SECONDS)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        raise
    except Exception as e:
        summary = "discover_plan 실행 중 예외가 발생했습니다."
        stderr_text = stderr_buf.text()
        if stderr_text:
            summary += f"\n\nClaude CLI stderr:\n{stderr_text}"
        _show_error("Discovery 쿼리 오류", summary, e)
        raise


