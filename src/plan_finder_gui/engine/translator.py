from __future__ import annotations

from pathlib import Path


def translate_with_google(text: str, target_lang: str = "ko") -> str:
    """Translate text using Google Cloud Translate v2.

    Requires GOOGLE_APPLICATION_CREDENTIALS environment variable to be set.
    The google-cloud-translate package must be installed.
    """
    # Import lazily to avoid ImportError if not installed
    from google.cloud import translate_v2 as translate  # type: ignore[import]

    client = translate.Client()
    result = client.translate(text, target_language=target_lang)
    translated: str = result["translatedText"]
    return translated


def translate_with_claude(text: str, target_lang: str = "ko") -> str:
    """Translate text using the Anthropic Claude API (Haiku model).

    Keeps markdown formatting, code blocks, and file paths unchanged.
    """
    import anthropic

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
        f"- Keep ALL code blocks unchanged (do not translate code inside ```...``` blocks)\n"
        f"- Keep ALL file paths unchanged (e.g. src/foo/bar.py)\n"
        f"- Keep ALL inline code unchanged (text inside backticks)\n"
        f"- Only output the translated text, nothing else"
    )

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=8192,
        system=system_prompt,
        messages=[
            {
                "role": "user",
                "content": text,
            }
        ],
    )

    translated: str = message.content[0].text
    return translated


def save_translated(
    original_path: Path,
    translated_text: str,
    target_lang: str = "ko",
) -> Path:
    """Save translated text alongside the original file.

    For example, given ``/reports/pending/plan.md`` and ``target_lang="ko"``,
    saves to ``/reports/pending/plan.ko.md`` and returns that path.
    """
    stem = original_path.stem  # e.g. "plan"
    translated_name = f"{stem}.{target_lang}.md"
    translated_path = original_path.parent / translated_name
    translated_path.write_text(translated_text, encoding="utf-8")
    return translated_path
