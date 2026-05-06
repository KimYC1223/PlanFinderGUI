from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSettings


def _bundled_preset_dir() -> Path:
    """Return the package-bundled presets directory.

    Works for both dev (source layout) and PyInstaller frozen builds.
    """
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "presets"  # type: ignore[attr-defined]
    # __file__ = src/plan_finder_gui/engine/preset.py → parents[1] = plan_finder_gui
    return Path(__file__).parents[1] / "presets"


def _user_preset_dir() -> Path | None:
    raw = QSettings().value("preset_dir", "")
    if not raw:
        return None
    p = Path(str(raw)).expanduser()
    return p if p.is_dir() else None


@dataclass
class Preset:
    name: str            # filename stem, used as stable id
    title: str           # H1 heading or stem
    description: str
    tags: list[str]
    prompt: str
    source: Path         # the file the preset was parsed from


def _parse_preset(path: Path) -> Preset | None:
    """Parse a preset .md file. Returns None if the file isn't a valid preset.

    Format (mirroring kajebiii/plan-finder):
        # Title
        ## Description
        ...
        ## Tags
        a, b, c
        ## Prompt
        <prompt body>

    Files without a `## Prompt` section are skipped (not a usable preset).
    """
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None

    def extract_section(heading: str) -> str:
        m = re.search(rf"^## {re.escape(heading)}\s*\n(.*?)(?=\n## |\Z)", text, re.DOTALL | re.MULTILINE)
        return m.group(1).strip() if m else ""

    prompt = extract_section("Prompt")
    if not prompt:
        # Treat the entire file body as the prompt when the user keeps a plain
        # markdown note instead of the structured format. Title falls back to
        # the H1 heading or filename stem.
        prompt = text.strip()

    title_m = re.search(r"^# (.+)$", text, re.MULTILINE)
    title = title_m.group(1).strip() if title_m else path.stem

    description = extract_section("Description")
    tags_raw = extract_section("Tags")
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()]

    return Preset(
        name=path.stem,
        title=title,
        description=description,
        tags=tags,
        prompt=prompt,
        source=path,
    )


def list_presets() -> list[Preset]:
    """Return all presets, with user-dir entries overriding bundled ones by name.

    Order: bundled (alpha) first, then user-only (alpha). User entries that
    share a name with a bundled one replace the bundled entry in place.
    """
    presets: dict[str, Preset] = {}

    bundled = _bundled_preset_dir()
    if bundled.is_dir():
        for f in sorted(bundled.glob("*.md")):
            p = _parse_preset(f)
            if p is not None:
                presets[p.name] = p

    user = _user_preset_dir()
    if user is not None:
        for f in sorted(user.glob("*.md")):
            p = _parse_preset(f)
            if p is not None:
                presets[p.name] = p  # user overrides bundled

    return list(presets.values())


def load_preset(name: str) -> Preset | None:
    for p in list_presets():
        if p.name == name:
            return p
    return None
