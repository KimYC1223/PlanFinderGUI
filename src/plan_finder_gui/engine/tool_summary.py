from __future__ import annotations


def short_path(path: str) -> str:
    """Shorten a path to its last 2 components."""
    parts = path.replace("\\", "/").split("/")
    if len(parts) > 2:
        return "/".join(parts[-2:])
    return path


def summarize_tool(name: str, inp: dict) -> str:
    """Create a short human-readable summary of a tool call."""
    if name == "Read":
        return f"Reading {short_path(inp.get('file_path', ''))}"
    if name == "Write":
        return f"Writing {short_path(inp.get('file_path', ''))}"
    if name == "Edit":
        return f"Editing {short_path(inp.get('file_path', ''))}"
    if name == "Glob":
        return f"Searching {inp.get('pattern', '')}"
    if name == "Grep":
        pattern = inp.get("pattern", "")
        path = inp.get("path", "")
        suffix = f" in {short_path(path)}" if path else ""
        return f"Grep '{pattern}'{suffix}"
    if name == "Bash":
        cmd = inp.get("command", "")
        if len(cmd) > 60:
            cmd = cmd[:57] + "..."
        return f"$ {cmd}"
    return f"{name}(...)"
