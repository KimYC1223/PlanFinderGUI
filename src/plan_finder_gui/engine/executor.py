from __future__ import annotations

import asyncio
import glob
import os
import shutil
import traceback
from pathlib import Path


def _show_error(title: str, summary: str, exc: BaseException | None = None) -> None:
    """Show a critical QMessageBox in the main thread, including traceback."""
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
        if exc is not None:
            tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            body = f"{summary}\n\n{tb}"
        else:
            body = summary
        # If we're not on the GUI thread for any reason, fall back to print.
        if QApplication.instance() is None:
            print(f"[{title}] {body}")
            return
        box = QMessageBox()
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle(title)
        box.setText(summary)
        box.setDetailedText(body)
        box.exec()
    except Exception:
        # Last resort: never let the dialog itself crash the session.
        print(f"[{title}] {summary}")
        if exc is not None:
            traceback.print_exception(type(exc), exc, exc.__traceback__)


class _StderrBuffer:
    """Capture stderr lines from the Claude CLI subprocess.

    The SDK only pipes stderr when ``ClaudeAgentOptions.stderr`` is set;
    without a callback, ``ProcessError`` surfaces as
    ``stderr="Check stderr output for details"`` and the real failure is
    invisible. We attach this buffer so callers can append the captured
    text to their error reports.
    """

    _MAX_LINES = 400

    def __init__(self) -> None:
        self._lines: list[str] = []

    def __call__(self, line: str) -> None:
        if len(self._lines) < self._MAX_LINES:
            self._lines.append(line)
        elif len(self._lines) == self._MAX_LINES:
            self._lines.append("... (stderr truncated)")

    def text(self) -> str:
        return "\n".join(self._lines)


def _move_to_reviewed(plan_path: Path) -> Path:
    """Move a plan file from working/ to reviewed/. Returns the new path."""
    try:
        reviewed_dir = plan_path.parent.parent / "reviewed"
        reviewed_dir.mkdir(parents=True, exist_ok=True)
        dest = reviewed_dir / plan_path.name
        plan_path.rename(dest)

        # Move any translated versions alongside
        trans_dir = plan_path.parent / "translated"
        if trans_dir.is_dir():
            dest_trans_dir = reviewed_dir / "translated"
            dest_trans_dir.mkdir(exist_ok=True)
            stem = plan_path.stem
            for trans_file in trans_dir.glob(f"{stem}.*.md"):
                trans_file.rename(dest_trans_dir / trans_file.name)

        return dest
    except Exception as e:
        _show_error(
            "리뷰 폴더 이동 실패",
            f"working → reviewed 이동 중 오류:\n{plan_path}",
            e,
        )
        raise


def _get_work_lang() -> str:
    """Read the user's chosen work language. Falls back to legacy commit_lang."""
    try:
        from PySide6.QtCore import QSettings
        s = QSettings()
        return s.value("work_lang", s.value("commit_lang", "ko")) or "ko"
    except Exception:
        return "ko"


def _language_instruction(lang: str) -> str:
    """Return a prompt fragment telling Claude which language to use for comments/messages."""
    if lang == "en":
        return (
            "When writing code comments, docstrings, or commit messages, "
            "use English."
        )
    return (
        "코드 주석, 독스트링, 커밋 메시지를 작성할 때는 한국어로 작성하세요. "
        "단, 코드 식별자(변수명, 함수명 등)는 영어로 유지하세요."
    )


def _is_auto_commit_enabled() -> bool:
    try:
        from PySide6.QtCore import QSettings
        v = QSettings().value("auto_commit", False)
        return v in (True, "true", "True", "1")
    except Exception:
        return False


def _is_batch_resolve_enabled() -> bool:
    try:
        from PySide6.QtCore import QSettings
        v = QSettings().value("batch_resolve", False)
        return v in (True, "true", "True", "1")
    except Exception:
        return False


async def _maybe_auto_commit(plan_path: Path, cwd: str, display) -> None:
    try:
        if not _is_auto_commit_enabled():
            display.log("자동 커밋: 비활성화 상태 (환경설정에서 켤 수 있음)")
            return

        lang = _get_work_lang()

        from .committer import extract_title, generate_commit_message, git_commit

        title = extract_title(plan_path)
        if not title:
            display.log("자동 커밋: 플랜 제목을 읽을 수 없어 건너뜀")
            return

        api_key = _resolve_anthropic_api_key()
        if api_key:
            display.log(f"커밋 메시지 생성 중... ({lang}, Anthropic API 사용)")
        else:
            display.log(f"커밋 메시지 생성 중... ({lang}, 로컬 Claude CLI 사용)")
        try:
            commit_msg = await generate_commit_message(title, lang, cwd)
        except Exception as e:
            display.log(
                f"커밋 메시지 생성 실패, 플랜 제목으로 대체: {e}"
            )
            commit_msg = title
        display.log(f"커밋 메시지: {commit_msg}")

        display.log("git add + commit 실행 중...")
        loop = asyncio.get_event_loop()
        success, output = await loop.run_in_executor(None, git_commit, cwd, commit_msg)
        if success:
            display.log(f"커밋 완료: {commit_msg}")
        else:
            display.log(f"커밋 건너뜀: {output}")
    except Exception as e:
        _show_error(
            "자동 커밋 실패",
            f"자동 커밋 처리 중 오류 (플랜: {plan_path.name}):",
            e,
        )


async def _maybe_auto_commit_batch(plan_paths: list[Path], cwd: str, display) -> None:
    try:
        if not _is_auto_commit_enabled():
            display.log("자동 커밋: 비활성화 상태 (환경설정에서 켤 수 있음)")
            return

        lang = _get_work_lang()

        from .committer import (
            extract_title,
            generate_batch_commit_message,
            git_commit,
        )

        titles: list[str] = []
        for p in plan_paths:
            t = extract_title(p)
            if t:
                titles.append(t)

        if not titles:
            display.log("자동 커밋: 플랜 제목을 읽을 수 없어 건너뜀")
            return

        api_key = _resolve_anthropic_api_key()
        if api_key:
            display.log(f"커밋 메시지 생성 중... ({lang}, {len(titles)}개 묶음, Anthropic API 사용)")
        else:
            display.log(f"커밋 메시지 생성 중... ({lang}, {len(titles)}개 묶음, 로컬 Claude CLI 사용)")
        try:
            commit_msg = await generate_batch_commit_message(titles, lang, cwd)
        except Exception as e:
            display.log(
                f"커밋 메시지 생성 실패, 플랜 제목으로 대체: {e}"
            )
            commit_msg = "\n\n".join(f"- {t}" for t in titles)
        display.log(f"커밋 메시지: {commit_msg}")

        display.log("git add + commit 실행 중...")
        loop = asyncio.get_event_loop()
        success, output = await loop.run_in_executor(None, git_commit, cwd, commit_msg)
        if success:
            display.log(f"커밋 완료: {commit_msg}")
        else:
            display.log(f"커밋 건너뜀: {output}")
    except Exception as e:
        _show_error(
            "자동 커밋 실패",
            f"일괄 자동 커밋 처리 중 오류 ({len(plan_paths)}개 플랜):",
            e,
        )


def _resolve_anthropic_api_key() -> str | None:
    """Return the user-provided Anthropic API key, or None to use local login."""
    try:
        from PySide6.QtCore import QSettings
        raw = QSettings().value("anthropic_api_key", "")
        key = (raw or "").strip() if isinstance(raw, str) else ""
        return key or None
    except Exception:
        return None


def _resolve_cli_path() -> str | None:
    """Return the claude CLI path to use, or None to let the SDK use its default."""
    try:
        from PySide6.QtCore import QSettings
        raw = QSettings().value("claude_cli_path", "")
        saved = (raw or "").strip() if isinstance(raw, str) else ""
        if saved:
            return saved

        if shutil.which("claude"):
            return None  # already on PATH, let SDK find it

        # nvm fallback
        for match in sorted(glob.glob(os.path.expanduser("~/.nvm/versions/node/*/bin/claude"))):
            return match  # return highest lexicographic (latest node version last)

        return None
    except Exception as e:
        _show_error(
            "Claude CLI 경로 해석 실패",
            "Claude CLI 경로를 찾는 도중 오류가 발생했습니다.",
            e,
        )
        return None


def _build_claude_options(cwd: str, model: str | None, max_turns: int):
    from claude_agent_sdk import ClaudeAgentOptions

    stderr_buf = _StderrBuffer()
    options = ClaudeAgentOptions(
        allowed_tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
        permission_mode="default",
        cwd=cwd,
        max_turns=max_turns,
        stderr=stderr_buf,
    )
    if model:
        options.model = model

    cli_path = _resolve_cli_path()
    if cli_path:
        options.cli_path = cli_path

    api_key = _resolve_anthropic_api_key()
    if api_key:
        options.env = {**(options.env or {}), "ANTHROPIC_API_KEY": api_key}
    return options, stderr_buf


async def run_resolve_session(
    plan_paths: list[Path],
    display,  # DisplayInterface
    cwd: str,
    model: str | None = None,
    max_turns: int = 80,
) -> None:
    """Read each plan file and ask Claude to implement it with write access.

    When the `batch_resolve` setting is on and there is more than one plan,
    all plans are sent to a single Claude session and (if auto-commit is
    enabled) committed together as one git commit.
    """
    try:
        from claude_agent_sdk import (
            AssistantMessage,
            ClaudeAgentOptions,  # noqa: F401  (used inside helpers)
            ResultMessage,
            ToolUseBlock,
            query,
        )
    except Exception as e:
        _show_error(
            "Claude SDK 로드 실패",
            "claude_agent_sdk를 import 하는 중 오류가 발생했습니다.",
            e,
        )
        return

    if _is_batch_resolve_enabled() and len(plan_paths) > 1:
        await _run_resolve_session_batched(
            plan_paths=plan_paths,
            display=display,
            cwd=cwd,
            model=model,
            max_turns=max_turns,
            AssistantMessage=AssistantMessage,
            ResultMessage=ResultMessage,
            ToolUseBlock=ToolUseBlock,
            query=query,
        )
        return

    for plan_path in plan_paths:
        if not plan_path.exists():
            display.on_error(f"Plan file not found: {plan_path}")
            continue

        try:
            content = plan_path.read_text(encoding="utf-8")
        except Exception as e:
            _show_error(
                "플랜 파일 읽기 실패",
                f"파일을 읽지 못했습니다: {plan_path}",
                e,
            )
            continue

        lang_instruction = _language_instruction(_get_work_lang())
        prompt = (
            f"Please implement the following improvement plan for the codebase at {cwd}.\n"
            f"Make the actual code changes described in the Implementation Steps section.\n\n"
            f"{lang_instruction}\n\n"
            f"{content}"
        )

        try:
            options, stderr_buf = _build_claude_options(cwd, model, max_turns)
        except Exception as e:
            _show_error(
                "ClaudeAgentOptions 구성 실패",
                "옵션 객체를 만드는 중 오류가 발생했습니다.",
                e,
            )
            return

        display.log(f"Resolving: {plan_path.name}")

        try:
            from .tool_summary import summarize_tool

            async for message in query(prompt=prompt, options=options):
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, ToolUseBlock):
                            detail = summarize_tool(block.name, block.input)
                            on_activity = getattr(display, "on_activity", None)
                            if callable(on_activity):
                                on_activity(detail)
                elif isinstance(message, ResultMessage):
                    if message.subtype == "success":
                        try:
                            plan_path = _move_to_reviewed(plan_path)
                        except Exception:
                            continue
                        display.log(f"Resolved: {plan_path.name}")
                        await _maybe_auto_commit(plan_path, cwd, display)
                    else:
                        display.on_error(f"Failed to resolve: {plan_path.name}")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            try:
                await asyncio.sleep(0.2)
            except Exception:
                pass
            summary = f"플랜 처리 중 오류 (파일: {plan_path.name}):"
            stderr_text = stderr_buf.text()
            if stderr_text:
                summary += f"\n\nClaude CLI stderr:\n{stderr_text}"
            else:
                summary += (
                    "\n\nClaude CLI stderr: (비어있음 — CLI가 stderr 출력 없이 즉시 종료됨)"
                    "\n→ 터미널에서 `claude -v` 와 `claude` 를 직접 실행하여 인증/버전을 확인하세요."
                )
            _show_error("Resolve 세션 오류", summary, e)
            display.on_error(f"Error resolving {plan_path.name}: {e}")


async def _run_resolve_session_batched(
    plan_paths: list[Path],
    display,
    cwd: str,
    model: str | None,
    max_turns: int,
    *,
    AssistantMessage,
    ResultMessage,
    ToolUseBlock,
    query,
) -> None:
    """Send all checked plans to a single Claude session and commit together."""
    valid: list[tuple[Path, str]] = []
    for plan_path in plan_paths:
        if not plan_path.exists():
            display.on_error(f"Plan file not found: {plan_path}")
            continue
        try:
            content = plan_path.read_text(encoding="utf-8")
        except Exception as e:
            _show_error(
                "플랜 파일 읽기 실패",
                f"파일을 읽지 못했습니다: {plan_path}",
                e,
            )
            continue
        valid.append((plan_path, content))

    if not valid:
        return

    lang_instruction = _language_instruction(_get_work_lang())

    sections = []
    for idx, (path, content) in enumerate(valid, start=1):
        sections.append(
            f"===== Plan {idx}/{len(valid)} — {path.name} =====\n\n{content}"
        )

    plans_block = "\n\n".join(sections)
    prompt = (
        f"Please implement ALL of the following {len(valid)} improvement plans for the codebase at {cwd}.\n"
        f"Treat each plan as a separate task and make the actual code changes described in each "
        f"plan's Implementation Steps section. Do not skip any plan.\n\n"
        f"{lang_instruction}\n\n"
        f"{plans_block}"
    )

    try:
        options, stderr_buf = _build_claude_options(cwd, model, max_turns)
    except Exception as e:
        _show_error(
            "ClaudeAgentOptions 구성 실패",
            "옵션 객체를 만드는 중 오류가 발생했습니다.",
            e,
        )
        return

    names = ", ".join(p.name for p, _ in valid)
    display.log(f"Resolving (일괄, {len(valid)}개): {names}")

    try:
        from .tool_summary import summarize_tool

        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, ToolUseBlock):
                        detail = summarize_tool(block.name, block.input)
                        on_activity = getattr(display, "on_activity", None)
                        if callable(on_activity):
                            on_activity(detail)
            elif isinstance(message, ResultMessage):
                if message.subtype == "success":
                    moved: list[Path] = []
                    for path, _ in valid:
                        try:
                            moved.append(_move_to_reviewed(path))
                        except Exception:
                            continue
                    if moved:
                        display.log(
                            f"Resolved (일괄): {', '.join(p.name for p in moved)}"
                        )
                        await _maybe_auto_commit_batch(moved, cwd, display)
                else:
                    display.on_error(
                        f"Failed to resolve batch ({len(valid)} plans): {names}"
                    )
    except asyncio.CancelledError:
        raise
    except Exception as e:
        try:
            await asyncio.sleep(0.2)
        except Exception:
            pass
        summary = f"일괄 플랜 처리 중 오류 ({len(valid)}개):"
        stderr_text = stderr_buf.text()
        if stderr_text:
            summary += f"\n\nClaude CLI stderr:\n{stderr_text}"
        else:
            summary += (
                "\n\nClaude CLI stderr: (비어있음 — CLI가 stderr 출력 없이 즉시 종료됨)"
                "\n→ 터미널에서 `claude -v` 와 `claude` 를 직접 실행하여 인증/버전을 확인하세요."
            )
        _show_error("Resolve 세션 오류", summary, e)
        display.on_error(f"Error resolving batch: {e}")
