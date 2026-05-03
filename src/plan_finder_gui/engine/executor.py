from __future__ import annotations

import asyncio
from pathlib import Path


async def run_resolve_session(
    plan_paths: list[Path],
    display,  # DisplayInterface
    cwd: str,
    model: str | None = None,
    max_turns: int = 80,
) -> None:
    """Read each plan file and ask Claude to implement it with write access."""
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ResultMessage,
        ToolUseBlock,
        query,
    )

    for plan_path in plan_paths:
        if not plan_path.exists():
            display.on_error(f"Plan file not found: {plan_path}")
            continue

        content = plan_path.read_text(encoding="utf-8")
        prompt = (
            f"Please implement the following improvement plan for the codebase at {cwd}.\n"
            f"Make the actual code changes described in the Implementation Steps section.\n\n"
            f"{content}"
        )

        options = ClaudeAgentOptions(
            allowed_tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
            permission_mode="default",
            cwd=cwd,
            max_turns=max_turns,
        )
        if model:
            options.model = model

        display.log(f"Resolving: {plan_path.name}")

        try:
            async for message in query(prompt=prompt, options=options):
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, ToolUseBlock):
                            pass  # could emit activity
                elif isinstance(message, ResultMessage):
                    if message.subtype == "success":
                        display.log(f"Resolved: {plan_path.name}")
                    else:
                        display.on_error(f"Failed to resolve: {plan_path.name}")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            display.on_error(f"Error resolving {plan_path.name}: {e}")
