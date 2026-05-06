from __future__ import annotations

import subprocess
from pathlib import Path


def _anthropic_client():
    """Build an Anthropic SDK client using the user's API key when present."""
    import anthropic

    try:
        from .executor import _resolve_anthropic_api_key
        key = _resolve_anthropic_api_key()
    except Exception:
        key = None
    if key:
        return anthropic.Anthropic(api_key=key)
    return anthropic.Anthropic()


def generate_commit_message(plan_title: str, lang: str = "ko") -> str:
    client = _anthropic_client()

    if lang == "ko":
        prompt = (
            f"다음 코드 개선 작업의 제목을 보고 자연스러운 한국어 커밋 메시지를 한 문장으로 작성해줘. "
            f"'fix:', 'feat:' 같은 prefix 없이 담백하게 써줘. 마침표 없이 끝내줘.\n\n"
            f"작업 제목: {plan_title}\n\n"
            f"커밋 메시지만 출력해."
        )
    else:
        prompt = (
            f"Write a concise, natural git commit message in one sentence for the following code improvement task. "
            f"No prefix like 'fix:', 'feat:', etc. Just a plain sentence. No period at the end.\n\n"
            f"Task title: {plan_title}\n\n"
            f"Output only the commit message."
        )

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=100,
        messages=[{"role": "user", "content": prompt}],
    )

    return message.content[0].text.strip()


def generate_batch_commit_message(plan_titles: list[str], lang: str = "ko") -> str:
    """Generate one commit message that covers multiple plan titles."""
    if not plan_titles:
        return ""
    if len(plan_titles) == 1:
        return generate_commit_message(plan_titles[0], lang)

    client = _anthropic_client()
    titles_block = "\n".join(f"- {t}" for t in plan_titles)

    if lang == "ko":
        prompt = (
            f"다음은 한 번에 함께 처리한 여러 코드 개선 작업의 제목 목록이야. "
            f"이 작업들을 묶은 자연스러운 한국어 커밋 메시지를 한 문장으로 작성해줘. "
            f"'fix:', 'feat:' 같은 prefix 없이 담백하게 써줘. 마침표 없이 끝내줘.\n\n"
            f"작업 제목들:\n{titles_block}\n\n"
            f"커밋 메시지만 출력해."
        )
    else:
        prompt = (
            f"Below is a list of code improvement task titles that were handled together. "
            f"Write a single concise, natural git commit message in one sentence covering all of them. "
            f"No prefix like 'fix:', 'feat:', etc. Just a plain sentence. No period at the end.\n\n"
            f"Task titles:\n{titles_block}\n\n"
            f"Output only the commit message."
        )

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=120,
        messages=[{"role": "user", "content": prompt}],
    )

    return message.content[0].text.strip()


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
