"""Termux media player backend."""

import re
import shutil
import subprocess
import threading
import time

from auen.backends.base import AudioBackend, BackendCapabilities
from auen.models import PlaybackState, PlaybackStatus


class TermuxBackend(AudioBackend):
    """Termux media player backend. File paths only, no streaming."""

    def __init__(
        self,
        *,
        command_timeout: float = 5.0,
        volume_available: bool | None = None,
    ) -> None:
        if command_timeout <= 0:
            raise ValueError("command timeout must be positive")
        self._command_timeout = command_timeout
        self._volume_available = (
            shutil.which("termux-volume") is not None
            if volume_available is None
            else volume_available
        )
        self._current_volume = 80
        self._is_playing = False
        self._end_event = threading.Event()

    def play(self, uri: str) -> None:
        self._end_event.clear()
        self._run("termux-media-player", "play", uri)
        self._is_playing = True

    def pause(self) -> None:
        self._run("termux-media-player", "pause")
        self._is_playing = False

    def resume(self) -> None:
        self._run("termux-media-player", "play")
        self._is_playing = True

    def stop(self) -> None:
        self._is_playing = False
        self._end_event.set()
        self._run("termux-media-player", "stop")

    def get_status(self) -> PlaybackStatus:
        result = self._run("termux-media-player", "info")
        output = result.stdout.strip()
        if "No track currently!" in output or not output:
            self._is_playing = False
            self._end_event.set()
            return PlaybackStatus(
                state=PlaybackState.STOPPED,
                volume=self._current_volume,
            )

        state = (
            PlaybackState.PAUSED if "Status: Paused" in output else PlaybackState.PLAYING
        )
        self._is_playing = state is PlaybackState.PLAYING
        elapsed = 0.0
        position = re.search(r"Current Position:\s*([0-9:]+)\s*/", output)
        if position is not None:
            elapsed = _parse_time(position.group(1))

        return PlaybackStatus(
            state=state,
            elapsed_seconds=elapsed,
            volume=self._current_volume,
        )

    def set_volume(self, level: int) -> None:
        self._current_volume = max(0, min(100, level))
        if not self._volume_available:
            return
        self._run(
            "termux-volume",
            "music",
            str(round(self._current_volume / 100 * 15)),
        )

    def seek(self, seconds: float) -> None:
        pass  # Unsupported in Termux

    def wait_for_end(self, timeout: float | None = None) -> bool:
        """Poll info until track ends, since Termux backend lacks events."""
        deadline = None if timeout is None else time.monotonic() + timeout
        while not self._end_event.is_set():
            status = self.get_status()
            if status.state == PlaybackState.STOPPED:
                self._end_event.set()
                return True
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._end_event.wait(min(0.2, remaining))
            else:
                self._end_event.wait(0.2)
        return True

    def _run(self, *command: str) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                list(command),
                capture_output=True,
                text=True,
                check=False,
                timeout=self._command_timeout,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"{command[0]} was not found; install the Termux:API package"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"{command[0]} did not respond in time") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            suffix = f": {detail}" if detail else f" (exit {result.returncode})"
            raise RuntimeError(f"{command[0]} failed{suffix}")
        return result

    @property
    def name(self) -> str:
        return "termux"

    @property
    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            streaming=False,
            seeking=False,
            volume=self._volume_available,
            reports_position=True,
        )


def _parse_time(value: str) -> float:
    total = 0
    for part in value.split(":"):
        total = total * 60 + int(part)
    return float(total)
