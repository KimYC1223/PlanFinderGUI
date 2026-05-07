from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path


def _resolve_api_key() -> str | None:
    try:
        from .executor import _resolve_anthropic_api_key
        return _resolve_anthropic_api_key()
    except Exception:
        return None


def _build_prompt_single(plan_title: str, lang: str) -> str:
    if lang == "ko":
        return (
            f"다음 코드 개선 작업의 제목을 보고 자연스러운 한국어 커밋 메시지를 한 문장으로 작성해줘. "
            f"'fix:', 'feat:' 같은 prefix 없이 담백하게 써줘. 마침표 없이 끝내줘.\n\n"
            f"작업 제목: {plan_title}\n\n"
            f"커밋 메시지만 출력해."
        )
    return (
        f"Write a concise, natural git commit message in one sentence for the following code improvement task. "
        f"No prefix like 'fix:', 'feat:', etc. Just a plain sentence. No period at the end.\n\n"
        f"Task title: {plan_title}\n\n"
        f"Output only the commit message."
    )


def _build_prompt_batch(plan_titles: list[str], lang: str) -> str:
    titles_block = "\n".join(f"- {t}" for t in plan_titles)
    if lang == "ko":
        return (
            f"다음은 한 번에 함께 처리한 여러 코드 개선 작업의 제목 목록이야. "
            f"이 작업들을 묶은 자연스러운 한국어 커밋 메시지를 한 문장으로 작성해줘. "
            f"'fix:', 'feat:' 같은 prefix 없이 담백하게 써줘. 마침표 없이 끝내줘.\n\n"
            f"작업 제목들:\n{titles_block}\n\n"
            f"커밋 메시지만 출력해."
        )
    return (
        f"Below is a list of code improvement task titles that were handled together. "
        f"Write a single concise, natural git commit message in one sentence covering all of them. "
        f"No prefix like 'fix:', 'feat:', etc. Just a plain sentence. No period at the end.\n\n"
        f"Task titles:\n{titles_block}\n\n"
        f"Output only the commit message."
    )


def _generate_via_sdk(prompt: str, api_key: str, max_tokens: int) -> str:
    """Sync path: use the Anthropic Python SDK with the configured API key."""
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text.strip()


async def _generate_via_cli(prompt: str, cwd: str | None) -> str:
    """Async path: drive the local `claude` CLI through claude_agent_sdk.

    Used when the user hasn't configured an Anthropic API key — the CLI carries
    its own OAuth login so this still works without any credentials in
    QSettings or environment.

    `cwd` should match the discovery/resolve session's cwd (the user's project
    directory). Reusing that path means macOS won't prompt for folder access
    again at commit time — the prompt was already handled at session start.
    """
    from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, query

    from .executor import _StderrBuffer

    stderr_buf = _StderrBuffer()
    options = ClaudeAgentOptions(
        allowed_tools=[],
        permission_mode="bypassPermissions",
        max_turns=1,
        cwd=cwd,
        system_prompt=(
            "You are generating a single git commit message. Output only the "
            "commit message itself — no explanations, no quotes, no prefixes."
        ),
        stderr=stderr_buf,
    )

    try:
        from .executor import _resolve_cli_path
        cli_path = _resolve_cli_path()
        if cli_path:
            options.cli_path = cli_path
    except Exception:
        pass

    parts: list[str] = []
    try:
        async for msg in query(prompt=prompt, options=options):
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    text = getattr(block, "text", None)
                    if text:
                        parts.append(text)
    except Exception as e:
        stderr_text = stderr_buf.text()
        if stderr_text:
            raise RuntimeError(
                f"{e}\n\nClaude CLI stderr:\n{stderr_text}"
            ) from e
        raise
    return "".join(parts).strip()


async def generate_commit_message(
    plan_title: str, lang: str = "ko", cwd: str | None = None
) -> str:
    prompt = _build_prompt_single(plan_title, lang)
    api_key = _resolve_api_key()
    if api_key:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, _generate_via_sdk, prompt, api_key, 100
        )
    return await _generate_via_cli(prompt, cwd)


async def generate_batch_commit_message(
    plan_titles: list[str], lang: str = "ko", cwd: str | None = None
) -> str:
    """Generate one commit message that covers multiple plan titles."""
    if not plan_titles:
        return ""
    if len(plan_titles) == 1:
        return await generate_commit_message(plan_titles[0], lang, cwd)

    prompt = _build_prompt_batch(plan_titles, lang)
    api_key = _resolve_api_key()
    if api_key:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, _generate_via_sdk, prompt, api_key, 120
        )
    return await _generate_via_cli(prompt, cwd)


def git_commit(cwd: str, message: str) -> tuple[bool, str]:
    """Stage all changes and create a git commit. Returns (success, output)."""
    try:
        add_result = subprocess.run(
            ["git", "add", "-A"],
            cwd=cwd,
            capture_output=True,
            text=True,
        )
        if add_result.returncode != 0:
            return False, f"git add 실패: {add_result.stderr.strip()}"

        status_result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=cwd,
            capture_output=True,
        )
        if status_result.returncode == 0:
            return False, "커밋할 변경사항 없음"

        commit_result = subprocess.run(
            ["git", "commit", "-m", message],
            cwd=cwd,
            capture_output=True,
            text=True,
        )
        if commit_result.returncode != 0:
            return False, f"git commit 실패: {commit_result.stderr.strip()}"

        return True, commit_result.stdout.strip()
    except FileNotFoundError:
        return False, "git을 찾을 수 없음"
    except Exception as e:
        return False, str(e)


def extract_title(plan_path: Path) -> str:
    """Extract the plan title from the markdown file's first H1 heading."""
    try:
        for line in plan_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("# "):
                return line[2:].strip()
    except Exception:
        pass
    return ""
