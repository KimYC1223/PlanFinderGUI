from __future__ import annotations

import random
import sys
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer


def _sound_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "sound"  # type: ignore[attr-defined]
    # __file__ = src/plan_finder_gui/ui/sound_player.py → parents[3] = project root
    return Path(__file__).parents[3] / "sound"


_LOOP_NAMES = (
    "edrrep00.wav",
    "edrrep01.wav",
    "edrrep02.wav",
    "edrrep03.wav",
    "edrrep04.wav",
)


class _SoundPlayer:
    def __init__(self) -> None:
        self._dir = _sound_dir()
        self._volume: float = 1.0
        self._loop_active = False

        # Single-shot effects.
        self._fx_audio = QAudioOutput()
        self._fx_audio.setVolume(self._volume)
        self._fx = QMediaPlayer()
        self._fx.setAudioOutput(self._fx_audio)

        # Background loop.
        self._loop_audio = QAudioOutput()
        self._loop_audio.setVolume(self._volume)
        self._loop = QMediaPlayer()
        self._loop.setAudioOutput(self._loop_audio)
        self._loop.mediaStatusChanged.connect(self._on_loop_status)

    def _url(self, name: str) -> QUrl:
        return QUrl.fromLocalFile(str(self._dir / name))

    # ------------------------------------------------------------------ #

    def set_volume(self, v: float) -> None:
        self._volume = max(0.0, min(1.0, v))
        self._fx_audio.setVolume(self._volume)
        self._loop_audio.setVolume(self._volume)

    def play(self, name: str) -> None:
        self._fx.stop()
        self._fx.setSource(self._url(name))
        self._fx.play()

    def play_random(self, *names: str) -> None:
        if names:
            self.play(random.choice(names))

    def start_working_loop(self) -> None:
        self._loop_active = True
        self._play_next_loop()

    def stop_working_loop(self) -> None:
        self._loop_active = False
        self._loop.stop()

    # ------------------------------------------------------------------ #

    def _play_next_loop(self) -> None:
        if not self._loop_active:
            return
        self._loop.setSource(self._url(random.choice(_LOOP_NAMES)))
        self._loop.play()

    def _on_loop_status(self, status: QMediaPlayer.MediaStatus) -> None:
        if status == QMediaPlayer.MediaStatus.EndOfMedia and self._loop_active:
            QTimer.singleShot(200, self._play_next_loop)


# Module-level singleton — imported after QApplication is constructed (safe).
_player = _SoundPlayer()


def play(name: str) -> None:
    _player.play(name)


def play_random(*names: str) -> None:
    _player.play_random(*names)


def start_working_loop() -> None:
    _player.start_working_loop()


def stop_working_loop() -> None:
    _player.stop_working_loop()


def set_volume(v: float) -> None:
    _player.set_volume(v)
