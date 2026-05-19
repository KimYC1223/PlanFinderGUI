"""Crisp, color-tintable SVG icon loader.

Qt's SVG renderer ignores ``currentColor``, so we load the SVG bytes,
substitute the literal token ``currentColor`` with the requested color,
and render to a high-DPI QPixmap. The result is a QIcon that looks the
same on macOS and Windows (no Segoe UI Symbol fallback).
"""
from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer


def _icons_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "img" / "icons"  # type: ignore[attr-defined]
    return Path(__file__).parents[3] / "img" / "icons"


@lru_cache(maxsize=64)
def _svg_bytes(name: str, color: str) -> bytes:
    path = _icons_dir() / f"{name}.svg"
    raw = path.read_text(encoding="utf-8")
    return raw.replace("currentColor", color).encode("utf-8")


@lru_cache(maxsize=64)
def load_icon(name: str, color: str = "#ffffff", size: int = 32) -> QIcon:
    """Return a QIcon for ``img/icons/{name}.svg`` recolored to ``color``."""
    renderer = QSvgRenderer(QByteArray(_svg_bytes(name, color)))
    icon = QIcon()
    for s in (size, size * 2):
        pm = QPixmap(s, s)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        renderer.render(painter)
        painter.end()
        icon.addPixmap(pm)
    return icon
