from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


# Common bin directories that PyInstaller .app bundles miss because macOS
# LaunchServices strips the shell PATH when an app is launched from Finder
# or Dock. Listed in priority order.
_FALLBACK_DIRS: tuple[str, ...] = (
    "/opt/homebrew/bin",
    "/opt/homebrew/sbin",
    "/usr/local/bin",
    "/usr/local/sbin",
    "~/.local/bin",
    "~/.bun/bin",
    "~/.npm-global/bin",
    "~/.cargo/bin",
)

# Env vars that user-shell exports but a Finder-launched .app bundle won't
# inherit. PATH is critical for tool lookup; the API keys back the commit
# message generator and Claude/Google translation paths.
_INHERIT_ENV_KEYS: tuple[str, ...] = (
    "PATH",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "OPENAI_API_KEY",
)

_MARK_START = "__PLANFINDER_ENV_START__"
_MARK_END = "__PLANFINDER_ENV_END__"
_KEY_SEP = "__PLANFINDER_KEY__"
_VAL_SEP = "__PLANFINDER_VAL__"
_LOGIN_SHELL_TIMEOUT_SECS = 5.0


def _login_shell_env(keys: tuple[str, ...]) -> dict[str, str] | None:
    """Ask the user's login+interactive shell for the values of `keys`.

    nvm/brew/api-key exports often live in ~/.zshrc, which only runs for
    interactive shells — `-l -i` covers login + interactive init files.
    Markers fence the payload from any banner / prompt output.

    Returns None on failure. Missing keys are simply absent from the result.
    """
    if sys.platform == "win32":
        return None
    shell = os.environ.get("SHELL") or shutil.which("zsh") or shutil.which("bash")
    if not shell:
        return None

    # Use ${VAR} braces — bare $VAR followed by underscore-bearing markers
    # would be treated as a single (undefined) identifier by the shell.
    payload_parts = [f'"{_MARK_START}"']
    for k in keys:
        payload_parts.append(f'"{k}{_KEY_SEP}${{{k}}}{_VAL_SEP}"')
    payload_parts.append(f'"{_MARK_END}"')
    cmd = "printf '%s' " + " ".join(payload_parts)

    try:
        result = subprocess.run(
            [shell, "-l", "-i", "-c", cmd],
            capture_output=True,
            text=True,
            timeout=_LOGIN_SHELL_TIMEOUT_SECS,
            stdin=subprocess.DEVNULL,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None

    m = re.search(
        re.escape(_MARK_START) + r"(.*?)" + re.escape(_MARK_END),
        result.stdout,
        re.DOTALL,
    )
    if not m:
        return None

    out: dict[str, str] = {}
    for entry in m.group(1).split(_VAL_SEP):
        if _KEY_SEP not in entry:
            continue
        key, value = entry.split(_KEY_SEP, 1)
        key = key.strip()
        if not key:
            continue
        if value:
            out[key] = value
    return out


def _existing_dirs(dirs: tuple[str, ...]) -> list[str]:
    out: list[str] = []
    for d in dirs:
        expanded = os.path.expanduser(d)
        if expanded and Path(expanded).is_dir():
            out.append(expanded)
    return out


def ensure_user_path() -> None:
    """Augment os.environ so subprocesses & API calls work in .app bundles.

    macOS .app bundles launched from Finder/Dock inherit the LaunchServices
    environment (roughly /usr/bin:/bin:/usr/sbin:/sbin and no user exports).
    That hides /opt/homebrew/bin and nvm Node bins from PATH and strips
    things like ANTHROPIC_API_KEY that the commit-message generator needs.

    This pulls PATH plus a curated list of API-key style env vars from the
    user's login+interactive shell and merges anything still missing.
    Existing values in os.environ are NOT overwritten.

    Idempotent. No-op on Windows.
    """
    if sys.platform == "win32":
        return

    shell_env = _login_shell_env(_INHERIT_ENV_KEYS) or {}

    # PATH: union of current + shell + static fallbacks, preserving order.
    current_path = os.environ.get("PATH", "")
    parts = current_path.split(os.pathsep) if current_path else []
    seen = set(parts)
    additions: list[str] = []

    shell_path = shell_env.get("PATH")
    if shell_path:
        for p in shell_path.split(os.pathsep):
            if p and p not in seen:
                seen.add(p)
                additions.append(p)

    for p in _existing_dirs(_FALLBACK_DIRS):
        if p not in seen:
            seen.add(p)
            additions.append(p)

    if additions:
        os.environ["PATH"] = os.pathsep.join(parts + additions)

    # Other env vars: only fill in if the parent process didn't already
    # provide them. Never overwrite an existing value.
    for key, value in shell_env.items():
        if key == "PATH":
            continue
        if value and not os.environ.get(key):
            os.environ[key] = value
