"""Exercise the native mpv IPC transport without requiring a sound device."""

import shutil
import subprocess
import threading
import time
import wave
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import pytest

from auen.backends.mpv import MpvBackend
from auen.models import PlaybackState, Track, TrackSource
from auen.player import PlaybackController
from auen.playlist import Playlist


@pytest.mark.skipif(shutil.which("mpv") is None, reason="mpv is not installed")
def test_native_rejected_stream_holds_queue_and_offline_skip_recovers(tmp_path: Path) -> None:
    class Rejected(BaseHTTPRequestHandler):
        def do_GET(self):
            time.sleep(0.2)
            self.send_error(403)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Rejected)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    audio = tmp_path / "offline.wav"
    with wave.open(str(audio), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8000)
        output.writeframes(b"\0\0" * 8000 * 30)
    failed = Track(
        title="Rejected", source=TrackSource.URL,
        uri=f"http://127.0.0.1:{server.server_port}/rejected",
    )
    offline = Track(title="Offline", source=TrackSource.LOCAL, uri=str(audio))
    playlist = Playlist()
    playlist.add_many([failed, offline])
    backend = MpvBackend()
    player = PlaybackController(playlist, backend)
    original_popen = subprocess.Popen

    def silent_mpv(command, **kwargs):
        return original_popen([*command[:1], "--ao=null", *command[1:]], **kwargs)

    try:
        with patch("auen.backends.mpv.subprocess.Popen", side_effect=silent_mpv):
            player.start()
            deadline = time.monotonic() + 5
            while not player.failure_held and time.monotonic() < deadline:
                time.sleep(0.02)
            assert player.failure_held
            assert playlist.queue_list == [failed, offline]
            assert playlist.history_list == []
            player.skip()
            deadline = time.monotonic() + 5
            while not player._ready and time.monotonic() < deadline:
                time.sleep(0.02)
            assert player.current_track is offline and player._ready
    finally:
        player.close()
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=1)


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


@pytest.mark.skipif(shutil.which("mpv") is None, reason="mpv is not installed")
def test_native_mpv_previous_restart_pause_and_forward_return(tmp_path: Path) -> None:
    tracks: list[Track] = []
    for name in ("first", "second", "third"):
        audio = tmp_path / f"{name}.wav"
        with wave.open(str(audio), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(8000)
            output.writeframes(b"\0\0" * 8000 * 30)
        tracks.append(Track(title=name, source=TrackSource.LOCAL, uri=str(audio)))
    original_popen = subprocess.Popen

    def silent_mpv(command: list[str], **kwargs: object) -> subprocess.Popen:
        return original_popen([*command[:1], "--ao=null", *command[1:]], **kwargs)

    def wait_for(predicate: Callable[[], bool]) -> None:
        deadline = time.monotonic() + 5
        while not predicate():
            if time.monotonic() > deadline:
                raise AssertionError("native playback transition timed out")
            time.sleep(0.05)

    playlist = Playlist()
    playlist.add_many(tracks)
    backend = MpvBackend()
    player = PlaybackController(playlist, backend)
    with patch("auen.backends.mpv.subprocess.Popen", side_effect=silent_mpv):
        try:
            player.start()
            wait_for(lambda: player.current_track is tracks[0] and player._ready)
            player.pause()
            player.seek(5)
            wait_for(lambda: player.status.elapsed_seconds >= 4.5)
            assert player.previous() == "restarted"
            assert player.status.elapsed_seconds < 1
            assert player.status.state is PlaybackState.PAUSED
            player.skip()
            wait_for(lambda: player.current_track is tracks[1] and player._ready)
            player.pause()
            assert player.previous() == "previous"
            wait_for(lambda: player.current_track is tracks[0] and player._ready)
            assert player.status.state is PlaybackState.PAUSED
            assert playlist.queue_list == tracks[1:]
            player.play()
            player.skip()
            wait_for(lambda: player.current_track is tracks[1] and player._ready)
            assert playlist.queue_list == [tracks[2]]
            player.stop_playback()
            wait_for(lambda: player.current_track is None)
            assert backend.get_status().state is PlaybackState.STOPPED
            assert playlist.queue_list == [tracks[1], tracks[2]]
            player.play()
            wait_for(lambda: player.current_track is tracks[1] and player._ready)
            assert player.status.elapsed_seconds < 1
            assert player.status.state is PlaybackState.PLAYING
        finally:
            player.close()
    assert backend.get_status().state is PlaybackState.STOPPED
