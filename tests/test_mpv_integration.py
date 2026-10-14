"""Exercise the native mpv IPC transport without requiring a sound device."""

import shutil
import subprocess
import time
import wave
from pathlib import Path
from unittest.mock import patch

import pytest

from auen.backends.mpv import MpvBackend
from auen.models import PlaybackState


@pytest.mark.skipif(shutil.which("mpv") is None, reason="mpv is not installed")
def test_native_mpv_playback_controls_and_shutdown(tmp_path: Path) -> None:
    audio = tmp_path / "song with spaces.wav"
    with wave.open(str(audio), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8000)
        output.writeframes(b"\0\0" * 8000 * 30)
    original_popen = subprocess.Popen

    def silent_mpv(command: list[str], **kwargs: object) -> subprocess.Popen:
        return original_popen([*command[:1], "--ao=null", *command[1:]], **kwargs)

    backend = MpvBackend()
    with patch("auen.backends.mpv.subprocess.Popen", side_effect=silent_mpv):
        try:
            backend.play(str(audio))
            deadline = time.monotonic() + 5
            while backend.get_status().duration_seconds is None and time.monotonic() < deadline:
                time.sleep(0.05)
            assert backend.get_status().duration_seconds == pytest.approx(30)
            backend.pause()
            assert backend.get_status().state is PlaybackState.PAUSED
            backend.seek(5)
            assert backend.get_status().elapsed_seconds >= 4.5
            backend.set_volume(37)
            assert backend.get_status().volume == 37
            backend.resume()
            assert backend.get_status().state is PlaybackState.PLAYING
        finally:
            backend.stop()
    assert backend.get_status().state is PlaybackState.STOPPED
    assert backend.wait_for_end(timeout=1)
