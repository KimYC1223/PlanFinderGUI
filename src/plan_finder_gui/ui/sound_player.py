from __future__ import annotations

import random
import sys
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtMultimedia import QSoundEffect


def _sound_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "sound"  # type: ignore[attr-defined]
    # __file__ = src/plan_finder_gui/ui/sound_player.py → parents[3] = project root
    return Path(__file__).parents[3] / "sound"


class _SoundPlayer:
    def __init__(self) -> None:
        self._dir = _sound_dir()
        self._fx = QSoundEffect()       # one-shot sounds
        self._loop_fx = QSoundEffect()  # working loop (single instance → no overlap)
        self._loop_active = False
        self._volume: float = 1.0
        self._loop_fx.playingChanged.connect(self._on_loop_playing_changed)

    def _url(self, name: str) -> QUrl:
        return QUrl.fromLocalFile(str(self._dir / name))

    # ------------------------------------------------------------------ #

    def set_volume(self, v: float) -> None:
        self._volume = max(0.0, min(1.0, v))
        self._fx.setVolume(self._volume)
        self._loop_fx.setVolume(self._volume)

    def play(self, name: str) -> None:
        self._fx.setSource(self._url(name))
        self._fx.setVolume(self._volume)
        self._fx.play()

    def play_random(self, *names: str) -> None:
        if names:
            self.play(random.choice(names))

    def start_working_loop(self) -> None:
        self._loop_active = True
        self._play_next_loop()

    def stop_working_loop(self) -> None:
        # Set flag first so the playingChanged callback doesn't reschedule
        self._loop_active = False
        self._loop_fx.stop()

    # ------------------------------------------------------------------ #

    def _play_next_loop(self) -> None:
        if not self._loop_active:
            return
        name = random.choice([
            "edrrep00.wav", "edrrep01.wav", "edrrep02.wav",
            "edrrep03.wav", "edrrep04.wav",
        ])
        self._loop_fx.setSource(self._url(name))
        self._loop_fx.setVolume(self._volume)
        self._loop_fx.play()

    def _on_loop_playing_changed(self) -> None:
        # playingChanged fires on both True (started) and False (stopped).
        # Only schedule the next sound when playback has just ended.
        if not self._loop_fx.isPlaying() and self._loop_active:
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
