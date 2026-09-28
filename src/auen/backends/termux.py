"""Termux media player backend."""

import subprocess
import threading
import time

from auen.backends.base import AudioBackend, BackendCapabilities
from auen.models import PlaybackState, PlaybackStatus


class TermuxBackend(AudioBackend):
    """Termux media player backend. File paths only, no streaming."""

    def __init__(self) -> None:
        self._current_volume = 80
        self._is_playing = False
        self._end_event = threading.Event()

    def play(self, uri: str) -> None:
        self._end_event.clear()
        self._is_playing = True
        subprocess.run(
            ["termux-media-player", "play", uri],
            capture_output=True,
            check=False,
        )

    def pause(self) -> None:
        self._is_playing = False
        subprocess.run(
            ["termux-media-player", "pause"],
            capture_output=True,
            check=False,
        )

    def resume(self) -> None:
        self._is_playing = True
        subprocess.run(
            ["termux-media-player", "play"],
            capture_output=True,
            check=False,
        )

    def stop(self) -> None:
        self._is_playing = False
        self._end_event.set()
        subprocess.run(
            ["termux-media-player", "stop"],
            capture_output=True,
            check=False,
        )

    def get_status(self) -> PlaybackStatus:
        result = subprocess.run(
            ["termux-media-player", "info"],
            capture_output=True,
            text=True,
            check=False,
        )

        output = result.stdout.strip()
        state = PlaybackState.STOPPED

        if "No track currently!" not in output and output != "":
            state = PlaybackState.PLAYING if self._is_playing else PlaybackState.PAUSED
        else:
            if self._is_playing:
                # If termux says no track but we were playing, track has ended naturally
                self._is_playing = False
                self._end_event.set()

        return PlaybackStatus(
            state=state,
            volume=self._current_volume,
        )

    def set_volume(self, level: int) -> None:
        self._current_volume = max(0, min(100, level))
        # termux-volume stream stream-name volume
        subprocess.run(
            ["termux-volume", "music", str(int(self._current_volume / 100 * 15))],
            capture_output=True,
            check=False,
        )

    def seek(self, seconds: float) -> None:
        pass  # Unsupported in Termux

    def wait_for_end(self, timeout: float | None = None) -> bool:
        """Poll info until track ends, since Termux backend lacks events."""
        start = time.monotonic()
        while not self._end_event.is_set():
            if timeout is not None and (time.monotonic() - start) > timeout:
                return False

            # This triggers the natural end detection if the track finished
            status = self.get_status()
            if status.state == PlaybackState.STOPPED:
                self._end_event.set()
                return True

            time.sleep(1.0)
        return True

    @property
    def name(self) -> str:
        return "termux"

    @property
    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            streaming=False,
            seeking=False,
            volume=True,
            reports_position=False,
        )
