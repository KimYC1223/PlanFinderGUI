"""File utilities for atomic writes and safe file operations."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write(file_path: Path, content: str, encoding: str = "utf-8") -> None:
    """Write content to file atomically to prevent corruption on crash.

    This function writes to a temporary file first, flushes to disk, then
    atomically replaces the target file. This ensures the file is never
    left in a partially-written state if the process crashes or power is lost.

    Args:
        file_path: The target file path to write to.
        content: The text content to write.
        encoding: The text encoding to use (default: utf-8).

    Raises:
        OSError: If the write operation fails.

    Note:
        On some network filesystems, os.replace() may not be truly atomic.
        The temp file is created in the same directory as the target to ensure
        they are on the same filesystem (required for atomic os.replace).
    """
    temp_fd = None
    temp_path = None
    try:
        # Create temp file in the same directory to ensure same filesystem
        # (required for atomic os.replace)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        temp_fd, temp_path = tempfile.mkstemp(
            dir=file_path.parent,
            prefix=".atomic_tmp_",
            suffix=file_path.suffix or ".tmp",
        )
        # Write content to temp file
        with os.fdopen(temp_fd, "w", encoding=encoding) as f:
            temp_fd = None  # fdopen takes ownership, prevent double-close
            f.write(content)
            f.flush()
            os.fsync(f.fileno())

        # Atomically replace target file (atomic on POSIX and Windows)
        os.replace(temp_path, file_path)
        temp_path = None  # Success, prevent cleanup

    except Exception:
        # Clean up temp file on any failure
        if temp_fd is not None:
            try:
                os.close(temp_fd)
            except OSError:
                pass
        if temp_path is not None:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
        raise
