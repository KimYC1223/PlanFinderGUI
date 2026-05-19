from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path


_COMMIT_SYSTEM_PROMPT = (
    "You are generating a single git commit message. Output only the "
    "commit message itself — no explanations, no quotes, no prefixes."
)


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


async def _generate_via_cli_sdk(prompt: str, cwd: str | None) -> str:
    """SDK-based async path: drive the local `claude` CLI through claude_agent_sdk.

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
        system_prompt=_COMMIT_SYSTEM_PROMPT,
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


def _generate_via_cli_subprocess(prompt: str, cwd: str | None) -> str:
    """Sync fallback: invoke `claude --print` directly via subprocess.

    The SDK transport's stderr reader uses TextReceiveStream which decodes
    as UTF-8 and silently drops non-UTF-8 lines via ``except Exception:
    pass``. On Windows that hides the real failure behind a generic
    "Check stderr output for details". This path bypasses the SDK so we
    can capture stderr ourselves and either recover (if the CLI works
    when invoked directly) or surface the real error.
    """
    from .executor import _resolve_cli_path

    cli_path = _resolve_cli_path() or shutil.which("claude")
    if not cli_path:
        raise RuntimeError("claude CLI binary not found on PATH")

    cmd = [
        cli_path,
        "--print",
        "--max-turns", "1",
        "--permission-mode", "bypassPermissions",
        "--system-prompt", _COMMIT_SYSTEM_PROMPT,
        prompt,
    ]

    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
    except FileNotFoundError as e:
        raise RuntimeError(f"claude CLI not executable: {e}") from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError("claude CLI timed out after 60s") from e

    if result.returncode != 0:
        stderr = (result.stderr or "").strip() or "(no stderr output)"
        stdout = (result.stdout or "").strip()
        msg = (
            f"claude CLI exited with code {result.returncode}\n"
            f"stderr:\n{stderr}"
        )
        if stdout:
            msg += f"\n\nstdout:\n{stdout}"
        raise RuntimeError(msg)

    return (result.stdout or "").strip()


async def _generate_via_cli(prompt: str, cwd: str | None) -> str:
    """Generate a commit message via the local Claude CLI.

    Tries the SDK-based async path first; on failure falls back to a
    direct ``subprocess.run`` call. The fallback both recovers (if the
    CLI works when invoked directly) and surfaces the real stderr the
    SDK transport swallowed.
    """
    try:
        return await _generate_via_cli_sdk(prompt, cwd)
    except Exception as sdk_err:
        try:
            result = await asyncio.to_thread(
                _generate_via_cli_subprocess, prompt, cwd
            )
        except Exception as sub_err:
            raise RuntimeError(
                f"SDK path failed: {sdk_err}\n\n"
                f"Direct subprocess fallback also failed: {sub_err}"
            ) from sub_err
        return result


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


def _unstage_changes(cwd: str, files: list[str] | None = None, timeout: float = 10.0) -> bool:
    """Unstage changes via `git reset HEAD`.

    If `files` is provided, only those specific files are unstaged.
    Otherwise, all staged changes are unstaged.

    Returns True if unstaging succeeded, False otherwise.
    Uses a timeout to avoid hanging on corrupted repos.
    """
    try:
        if files:
            cmd = ["git", "reset", "HEAD", "--"] + files
        else:
            cmd = ["git", "reset", "HEAD"]
        reset_result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return reset_result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        return False


def git_commit(
    cwd: str, message: str, files: list[str] | None = None
) -> tuple[bool, str]:
    """Stage changes and create a git commit. Returns (success, output).

    If `files` is provided, only those specific files are staged using
    `git add <file>...`. Otherwise, all changes are staged using `git add -A`.

    If the commit fails after staging, attempts to unstage the changes
    to leave the repository in a clean state.
    """
    staged_by_us = False
    try:
        if files:
            # Stage only the specified files
            if not files:
                return False, "커밋할 변경사항 없음"
            # Use git add for each file - handles added, modified, and deleted files
            add_result = subprocess.run(
                ["git", "add", "--"] + files,
                cwd=cwd,
                capture_output=True,
                text=True,
            )
            if add_result.returncode != 0:
                return False, f"git add 실패: {add_result.stderr.strip()}"
        else:
            # Legacy behavior: stage all changes
            add_result = subprocess.run(
                ["git", "add", "-A"],
                cwd=cwd,
                capture_output=True,
                text=True,
            )
            if add_result.returncode != 0:
                return False, f"git add 실패: {add_result.stderr.strip()}"

        staged_by_us = True

        status_result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=cwd,
            capture_output=True,
        )
        if status_result.returncode == 0:
            # No changes to commit - nothing was actually staged
            staged_by_us = False
            return False, "커밋할 변경사항 없음"

        commit_result = subprocess.run(
            ["git", "commit", "-m", message],
            cwd=cwd,
            capture_output=True,
            text=True,
        )
        if commit_result.returncode != 0:
            stderr = commit_result.stderr.strip()
            # Commit failed - attempt to unstage changes to restore clean state
            if _unstage_changes(cwd, files):
                return False, f"git commit 실패 (변경사항 unstage됨): {stderr}"
            else:
                return False, f"git commit 실패 (unstage도 실패): {stderr}"

        return True, commit_result.stdout.strip()
    except FileNotFoundError:
        # git binary not found - if we staged, try to unstage
        if staged_by_us:
            _unstage_changes(cwd, files)
        return False, "git을 찾을 수 없음"
    except Exception as e:
        # Unexpected error - if we staged, try to unstage
        if staged_by_us:
            _unstage_changes(cwd, files)
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
