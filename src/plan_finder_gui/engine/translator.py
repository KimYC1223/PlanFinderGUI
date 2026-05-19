from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

from .fileutil import atomic_write


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class TranslationTruncatedError(Exception):
    """Raised when Claude API response is truncated due to max_tokens limit.

    Attributes:
        partial_text: The truncated translation text that was returned.
        file_name: Optional file name being translated (for error messages).
    """

    def __init__(
        self, partial_text: str, file_name: str | None = None, message: str | None = None
    ) -> None:
        self.partial_text = partial_text
        self.file_name = file_name
        if message is None:
            file_info = f" for '{file_name}'" if file_name else ""
            message = (
                f"Translation was truncated{file_info} due to token limit. "
                f"The document may be too large for a single translation. "
                f"Consider using Google Translate for very large documents."
            )
        super().__init__(message)


_logger = logging.getLogger(__name__)


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


def _async_anthropic_client():
    """Build an async Anthropic SDK client using the user's API key when present."""
    import anthropic

    try:
        from .executor import _resolve_anthropic_api_key
        key = _resolve_anthropic_api_key()
    except Exception:
        key = None
    if key:
        return anthropic.AsyncAnthropic(api_key=key)
    return anthropic.AsyncAnthropic()

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
    masked, blocks = _mask_code(text)

    client = _anthropic_client()

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

    # Check if the response was truncated due to token limit
    if message.stop_reason == "max_tokens":
        partial_text = message.content[0].text if message.content else ""
        restored_partial = _unmask_code(partial_text, blocks)
        _logger.warning(
            "Translation truncated due to max_tokens limit. "
            "Input length: %d chars, output length: %d chars. "
            "Consider using Google Translate for large documents.",
            len(text),
            len(partial_text),
        )
        raise TranslationTruncatedError(partial_text=restored_partial)

    translated: str = message.content[0].text
    return _unmask_code(translated, blocks)


# ---------------------------------------------------------------------------
# Async translation functions (non-blocking for event loop)
# ---------------------------------------------------------------------------


async def translate_with_google_async(text: str, target_lang: str = "ko") -> str:
    """Translate text using Google Cloud Translate v2 (async/non-blocking).

    Runs the synchronous Google Cloud client in a thread pool to avoid
    blocking the asyncio event loop.

    Requires GOOGLE_APPLICATION_CREDENTIALS environment variable to be set.
    The google-cloud-translate package must be installed.
    """
    return await asyncio.to_thread(translate_with_google, text, target_lang)


async def translate_with_claude_async(text: str, target_lang: str = "ko") -> str:
    """Translate text using the Anthropic Claude API (Haiku model, async).

    Uses the async Anthropic client to avoid blocking the asyncio event loop.
    Keeps markdown formatting, code blocks, and file paths unchanged.
    """
    masked, blocks = _mask_code(text)

    client = _async_anthropic_client()

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

    message = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=8192,
        system=system_prompt,
        messages=[{"role": "user", "content": masked}],
    )

    # Check if the response was truncated due to token limit
    if message.stop_reason == "max_tokens":
        partial_text = message.content[0].text if message.content else ""
        restored_partial = _unmask_code(partial_text, blocks)
        _logger.warning(
            "Translation truncated due to max_tokens limit. "
            "Input length: %d chars, output length: %d chars. "
            "Consider using Google Translate for large documents.",
            len(text),
            len(partial_text),
        )
        raise TranslationTruncatedError(partial_text=restored_partial)

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

    Uses atomic write (temp file + fsync + os.replace) to prevent corruption
    if the process crashes during the write operation.
    """
    stem = original_path.stem
    translated_name = f"{stem}.{target_lang}.md"
    translated_dir = original_path.parent / "translated"
    translated_dir.mkdir(exist_ok=True)
    translated_path = translated_dir / translated_name
    atomic_write(translated_path, translated_text)
    return translated_path


async def save_translated_async(
    original_path: Path,
    translated_text: str,
    target_lang: str = "ko",
) -> Path:
    """Save translated text to a translated/ subdirectory (async/non-blocking).

    Runs the synchronous file write in a thread pool to avoid blocking
    the asyncio event loop.

    For example, given ``/reports/pending/plan.md`` and ``target_lang="ko"``,
    saves to ``/reports/pending/translated/plan.ko.md`` and returns that path.
    """
    return await asyncio.to_thread(save_translated, original_path, translated_text, target_lang)
