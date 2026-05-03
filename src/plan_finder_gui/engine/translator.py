from __future__ import annotations

import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Code-block masking helpers
# ---------------------------------------------------------------------------

# Matches fenced code blocks (``` ... ```) — multiline, non-greedy.
_FENCE_RE = re.compile(r"```[\s\S]*?```", re.MULTILINE)
# Matches inline code (`...`) — single line only.
_INLINE_RE = re.compile(r"`[^`\n]+`")
# Matches placeholders that survived (or were slightly modified by) translation.
_PLACEHOLDER_RE = re.compile(r"\{\{\{\s*(\d+)\s*\}\}\}")


def _mask_code(text: str) -> tuple[str, list[str]]:
    """Replace code blocks / inline code with {{{N}}} placeholders.

    Fenced blocks are extracted first so their contents don't get
    processed again by the inline-code pass.

    Returns (masked_text, ordered list of extracted snippets).
    """
    blocks: list[str] = []

    def _replace(m: re.Match) -> str:
        idx = len(blocks)
        blocks.append(m.group(0))
        return f"{{{{{{{idx}}}}}}}"  # {{{N}}}

    result = _FENCE_RE.sub(_replace, text)
    result = _INLINE_RE.sub(_replace, result)
    return result, blocks


def _unmask_code(text: str, blocks: list[str]) -> str:
    """Restore {{{N}}} placeholders with their original code snippets."""

    def _replace(m: re.Match) -> str:
        idx = int(m.group(1))
        return blocks[idx] if idx < len(blocks) else m.group(0)

    return _PLACEHOLDER_RE.sub(_replace, text)


# ---------------------------------------------------------------------------
# Translation functions
# ---------------------------------------------------------------------------

def translate_with_google(text: str, target_lang: str = "ko") -> str:
    """Translate text using Google Cloud Translate v2.

    Requires GOOGLE_APPLICATION_CREDENTIALS environment variable to be set.
    The google-cloud-translate package must be installed.
    """
    from google.cloud import translate_v2 as translate  # type: ignore[import]

    masked, blocks = _mask_code(text)

    client = translate.Client()
    # format_="text" prevents Google from treating markdown syntax as HTML,
    # which would otherwise collapse \n\n paragraph breaks.
    result = client.translate(masked, target_language=target_lang, format_="text")
    translated: str = result["translatedText"]
    # Normalize line endings (API may return \r\n on some platforms)
    translated = translated.replace("\r\n", "\n").replace("\r", "\n")

    return _unmask_code(translated, blocks)


def translate_with_claude(text: str, target_lang: str = "ko") -> str:
    """Translate text using the Anthropic Claude API (Haiku model).

    Keeps markdown formatting, code blocks, and file paths unchanged.
    """
    import anthropic

    masked, blocks = _mask_code(text)

    client = anthropic.Anthropic()

    lang_names = {
        "ko": "Korean",
        "ja": "Japanese",
        "zh": "Chinese (Simplified)",
        "fr": "French",
        "de": "German",
        "es": "Spanish",
        "pt": "Portuguese",
        "ru": "Russian",
    }
    lang_name = lang_names.get(target_lang, target_lang)

    system_prompt = (
        f"You are a professional technical translator. "
        f"Translate the following markdown document to {lang_name}. "
        f"Rules:\n"
        f"- Keep ALL markdown formatting intact (headings, bullet points, bold, italic, etc.)\n"
        f"- Placeholders like {{{{0}}}}, {{{{1}}}}, etc. represent code blocks — output them EXACTLY as-is, do NOT translate or modify them.\n"
        f"- Keep ALL file paths unchanged (e.g. src/foo/bar.py)\n"
        f"- Only output the translated text, nothing else"
    )

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=8192,
        system=system_prompt,
        messages=[{"role": "user", "content": masked}],
    )

    translated: str = message.content[0].text
    return _unmask_code(translated, blocks)


# ---------------------------------------------------------------------------
# File saving
# ---------------------------------------------------------------------------

def save_translated(
    original_path: Path,
    translated_text: str,
    target_lang: str = "ko",
) -> Path:
    """Save translated text to a translated/ subdirectory beside the original.

    For example, given ``/reports/pending/plan.md`` and ``target_lang="ko"``,
    saves to ``/reports/pending/translated/plan.ko.md`` and returns that path.
    """
    stem = original_path.stem
    translated_name = f"{stem}.{target_lang}.md"
    translated_dir = original_path.parent / "translated"
    translated_dir.mkdir(exist_ok=True)
    translated_path = translated_dir / translated_name
    translated_path.write_text(translated_text, encoding="utf-8")
    return translated_path
