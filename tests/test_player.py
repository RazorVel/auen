"""Tests for backend-neutral playback orchestration."""

import threading
import time
from collections.abc import Callable
from unittest.mock import MagicMock

import pytest

from auen.backends.base import AudioBackend, BackendCapabilities
from auen.models import PlaybackState, PlaybackStatus, RepeatMode, Track, TrackSource
from auen.player import PlaybackController
from auen.playlist import Playlist


class FakeBackend(AudioBackend):
    def __init__(self) -> None:
        self.played: list[str] = []
        self.state = PlaybackState.STOPPED
        self.volume = 80
        self.ended = threading.Event()
        self.stopped = threading.Event()
        self.seek_calls: list[float] = []
        self.elapsed = 0.0

    def play(self, uri: str) -> None:
        self.played.append(uri)
        self.state = PlaybackState.PLAYING
        self.ended.clear()

    def pause(self) -> None:
        self.state = PlaybackState.PAUSED

    def resume(self) -> None:
        self.state = PlaybackState.PLAYING

    def stop(self) -> None:
        self.state = PlaybackState.STOPPED
        self.stopped.set()
        self.ended.set()

    def get_status(self) -> PlaybackStatus:
        return PlaybackStatus(
            state=self.state,
            volume=self.volume,
            elapsed_seconds=self.elapsed,
        )

    def set_volume(self, level: int) -> None:
        self.volume = level

    def seek(self, seconds: float) -> None:
        self.seek_calls.append(seconds)

    def wait_for_end(self, timeout: float | None = None) -> bool:
        return self.ended.wait(timeout)

    @property
    def name(self) -> str:
        return "fake"

    @property
    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(True, True, True, True)


class OneWaitFailureBackend(FakeBackend):
    def __init__(self) -> None:
        super().__init__()
        self.failed_once = False

    def wait_for_end(self, timeout: float | None = None) -> bool:
        if not self.failed_once:
            self.failed_once = True
            raise RuntimeError("status unavailable")
        return super().wait_for_end(timeout)


def make_track(title: str) -> Track:
    return Track(title=title, source=TrackSource.LOCAL, uri=f"/{title}.opus")


def wait_until(predicate: Callable[[], bool], *, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("condition was not reached in time")
        time.sleep(0.01)


def test_plays_queued_track_and_records_completion() -> None:
    playlist = Playlist()
    backend = FakeBackend()
    track = make_track("first")
    playlist.add(track)
    player = PlaybackController(playlist, backend)
    player.start()

    wait_until(lambda: backend.played == [track.uri])
    assert player.status.track == track
    backend.ended.set()
    wait_until(lambda: playlist.history_list == [track])
    player.close()


def test_skip_advances_to_next_track() -> None:
    playlist = Playlist()
    backend = FakeBackend()
    first = make_track("first")
    second = make_track("second")
    playlist.add_many([first, second])
    player = PlaybackController(playlist, backend)
    player.start()

    wait_until(lambda: backend.played == [first.uri])
    player.skip()
    wait_until(lambda: backend.played == [first.uri, second.uri])

    assert playlist.history_list == [first]
    player.close()


def test_play_next_insertion_continues_with_existing_queue() -> None:
    playlist = Playlist()
    backend = FakeBackend()
    current = make_track("current")
    queued = make_track("already-queued")
    library = make_track("from-library")
    playlist.add_many([current, queued])
    player = PlaybackController(playlist, backend)
    player.start()

    wait_until(lambda: backend.played == [current.uri])
    playlist.add_next(library)
    player.skip()
    wait_until(lambda: backend.played == [current.uri, library.uri])
    backend.ended.set()
    wait_until(lambda: backend.played == [current.uri, library.uri, queued.uri])

    player.close()


def test_repeat_one_requeues_completed_track() -> None:
    playlist = Playlist()
    playlist.repeat_mode = RepeatMode.ONE
    backend = FakeBackend()
    track = make_track("repeat")
    playlist.add(track)
    player = PlaybackController(playlist, backend)
    player.start()

    wait_until(lambda: backend.played == [track.uri])
    backend.ended.set()
    wait_until(lambda: len(backend.played) == 2)

    assert backend.played == [track.uri, track.uri]
    player.close()


def test_pause_resume_seek_and_volume_controls() -> None:
    playlist = Playlist()
    backend = FakeBackend()
    playlist.add(make_track("controls"))
    player = PlaybackController(playlist, backend)
    player.start()
    wait_until(lambda: backend.state is PlaybackState.PLAYING)

    player.toggle_pause()
    assert backend.state is PlaybackState.PAUSED
    player.toggle_pause()
    assert backend.state is PlaybackState.PLAYING
    player.seek(15)
    backend.elapsed = 12
    player.seek_to(42)
    player.set_volume(42)

    assert backend.seek_calls == [15, 30]
    assert backend.volume == 42
    player.close()


def test_preparation_error_is_reported_without_killing_worker() -> None:
    playlist = Playlist()
    backend = FakeBackend()
    errors: list[tuple[Track, Exception]] = []
    started: list[Track] = []
    failed = make_track("failed")
    good = make_track("good")
    playlist.add_many([failed, good])

    def prepare(track: Track) -> str:
        if track is failed:
            raise RuntimeError("unavailable")
        return track.uri

    player = PlaybackController(
        playlist,
        backend,
        prepare=prepare,
        on_track_started=started.append,
        on_error=lambda track, error: errors.append((track, error)),
    )
    player.start()
    wait_until(lambda: backend.played == [good.uri])

    assert errors[0][0] is failed
    assert str(errors[0][1]) == "unavailable"
    assert playlist.history_list == [failed]
    assert started == [good]
    player.close()


def test_status_error_is_reported_without_killing_worker() -> None:
    playlist = Playlist()
    backend = OneWaitFailureBackend()
    errors: list[tuple[Track, Exception]] = []
    failed = make_track("failed-status")
    good = make_track("good-after-status")
    playlist.add_many([failed, good])
    player = PlaybackController(
        playlist,
        backend,
        on_error=lambda track, error: errors.append((track, error)),
    )
    player.start()

    wait_until(lambda: backend.played == [failed.uri, good.uri])

    assert errors[0][0] is failed
    assert str(errors[0][1]) == "status unavailable"
    assert playlist.history_list == [failed]
    player.close()


def test_rejects_invalid_volume() -> None:
    player = PlaybackController(Playlist(), FakeBackend())
    with pytest.raises(ValueError, match="between 0 and 100"):
        player.set_volume(101)


def test_rejects_negative_absolute_seek() -> None:
    player = PlaybackController(Playlist(), FakeBackend())
    with pytest.raises(ValueError, match="negative"):
        player.seek_to(-1)


def test_close_reports_backend_stop_error_after_clearing_current_track() -> None:
    backend = FakeBackend()
    player = PlaybackController(Playlist(), backend)
    player._current_track = make_track("active")
    backend.stop = MagicMock(side_effect=RuntimeError("stop failed"))  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="stop failed"):
        player.close()

    assert player.current_track is None
