"""Tests for backend-neutral playback orchestration."""

import threading
import time
from collections.abc import Callable, Iterator
from unittest.mock import MagicMock, patch

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
        self.elapsed = 0.0

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
        self.elapsed = max(0.0, self.elapsed + seconds)

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


@pytest.fixture
def navigation_player() -> Iterator[tuple[Playlist, FakeBackend, PlaybackController]]:
    playlist = Playlist()
    backend = FakeBackend()
    player = PlaybackController(playlist, backend)
    try:
        yield playlist, backend, player
    finally:
        player.close()


def start_navigation(
    playlist: Playlist, backend: FakeBackend, player: PlaybackController
) -> tuple[Track, Track, Track]:
    tracks = (make_track("first"), make_track("second"), make_track("third"))
    playlist.add_many(tracks)
    player.start()
    wait_until(lambda: player._ready)
    return tracks


@pytest.mark.parametrize("paused,shuffle", [(False, False), (True, False), (False, True)])
def test_non_quitting_stop_retains_track_and_queue_and_play_restarts(
    navigation_player: tuple[Playlist, FakeBackend, PlaybackController],
    paused: bool, shuffle: bool,
) -> None:
    playlist, backend, player = navigation_player
    first, second, third = start_navigation(playlist, backend, player)
    playlist.shuffle = shuffle
    if paused:
        player.pause()
    backend.elapsed = 32
    player.stop_playback()
    player.stop_playback()
    wait_until(lambda: player.current_track is None)
    assert backend.state is PlaybackState.STOPPED
    assert playlist.queue_list == [first, second, third]
    assert playlist.history_list == []
    assert list(player._back_stack) == []
    assert player.queue_held
    assert player._thread is not None and player._thread.is_alive()
    player.play()
    wait_until(lambda: player._ready)
    assert player.current_track is first
    assert backend.elapsed == 0
    assert backend.state is PlaybackState.PLAYING
    assert playlist.queue_list == [second, third]


def test_stop_during_preparation_never_starts_audio() -> None:
    playlist = Playlist()
    backend = FakeBackend()
    preparing, release = threading.Event(), threading.Event()
    def prepare(track: Track) -> str:
        preparing.set()
        assert release.wait(2)
        return track.uri
    player = PlaybackController(playlist, backend, prepare=prepare)
    track = make_track("first")
    playlist.add(track)
    try:
        player.start()
        assert preparing.wait(2)
        player.stop_playback()
        release.set()
        wait_until(lambda: playlist.queue_list == [track])
        assert backend.played == []
        assert player.current_track is None
        player.play()
        wait_until(lambda: player._ready)
        assert backend.played == [track.uri]
    finally:
        release.set()
        player.close()


def test_failed_stop_does_not_hold_queue(
    navigation_player: tuple[Playlist, FakeBackend, PlaybackController],
) -> None:
    playlist, backend, player = navigation_player
    start_navigation(playlist, backend, player)
    with (
        patch.object(backend, "stop", side_effect=RuntimeError("unavailable")),
        pytest.raises(RuntimeError, match="unavailable"),
    ):
        player.stop_playback()
    assert not player.queue_held
    assert player._ready


@pytest.mark.parametrize("elapsed", [0, 2.99, 3, 30])
def test_previous_restarts_first_track_without_consuming_queue(
    navigation_player: tuple[Playlist, FakeBackend, PlaybackController], elapsed: float
) -> None:
    playlist, backend, player = navigation_player
    first, second, third = start_navigation(playlist, backend, player)
    backend.elapsed = elapsed

    assert player.previous() == "restarted"
    assert backend.seek_calls == [-elapsed]
    assert player.current_track is first
    assert playlist.queue_list == [second, third]
    assert playlist.history_list == []


@pytest.mark.parametrize("elapsed,expected", [(2.99, "previous"), (3, "restarted")])
def test_previous_threshold_and_next_return_to_interrupted_track(
    navigation_player: tuple[Playlist, FakeBackend, PlaybackController],
    elapsed: float,
    expected: str,
) -> None:
    playlist, backend, player = navigation_player
    first, second, third = start_navigation(playlist, backend, player)
    player.skip()
    wait_until(lambda: player.current_track is second and player._ready)
    backend.elapsed = elapsed

    assert player.previous() == expected
    if expected == "restarted":
        assert backend.seek_calls == [-elapsed]
        assert playlist.queue_list == [third]
    else:
        wait_until(lambda: player.current_track is first and player._ready)
        assert playlist.queue_list == [second, third]
        player.skip()
        wait_until(lambda: player.current_track is second and player._ready)
        assert playlist.queue_list == [third]


def test_previous_retraces_actual_shuffle_order(
    navigation_player: tuple[Playlist, FakeBackend, PlaybackController],
) -> None:
    playlist, backend, player = navigation_player
    playlist.shuffle = True
    with patch("auen.playlist.random.randrange", side_effect=lambda count: count - 1):
        first, second, third = start_navigation(playlist, backend, player)
        assert player.current_track is third
        player.skip()
        wait_until(lambda: player.current_track is first and player._ready)
        assert player.previous() == "previous"
        wait_until(lambda: player.current_track is third and player._ready)
        assert playlist.queue_list == [first, second]
        player.skip()
        wait_until(lambda: player.current_track is first and player._ready)
        assert playlist.queue_list == [second]


def test_previous_preserves_paused_state_and_cancels_after_track_hold(
    navigation_player: tuple[Playlist, FakeBackend, PlaybackController],
) -> None:
    playlist, backend, player = navigation_player
    first, second, _ = start_navigation(playlist, backend, player)
    player.skip()
    wait_until(lambda: player.current_track is second and player._ready)
    player.pause()
    player.hold_after_current()

    assert player.previous() == "previous"
    wait_until(lambda: player.current_track is first and player._ready)
    assert backend.state is PlaybackState.PAUSED
    assert not player._hold_after_current.is_set()
    player.play()
    assert backend.state is PlaybackState.PLAYING


def test_previous_handles_multiple_back_steps_and_preserves_forward_order(
    navigation_player: tuple[Playlist, FakeBackend, PlaybackController],
) -> None:
    playlist, backend, player = navigation_player
    first, second, third = start_navigation(playlist, backend, player)
    for track in (second, third):
        player.skip()
        wait_until(lambda track=track: player.current_track is track and player._ready)
    for track in (second, first):
        assert player.previous() == "previous"
        wait_until(lambda track=track: player.current_track is track and player._ready)
    assert playlist.queue_list == [second, third]
    for track in (second, third):
        player.skip()
        wait_until(lambda track=track: player.current_track is track and player._ready)
    assert playlist.queue_list == []


def test_explicit_play_pause_are_idempotent(
    navigation_player: tuple[Playlist, FakeBackend, PlaybackController],
) -> None:
    playlist, backend, player = navigation_player
    first, _, _ = start_navigation(playlist, backend, player)
    player.pause()
    player.pause()
    assert backend.state is PlaybackState.PAUSED
    player.play()
    player.play()
    assert backend.state is PlaybackState.PLAYING
    assert backend.played == [first.uri]


def test_previous_with_no_playback_is_a_noop(
    navigation_player: tuple[Playlist, FakeBackend, PlaybackController],
) -> None:
    _, _, player = navigation_player
    assert player.previous() is None
    player.pause()
    player.play()


def test_manual_next_overrides_repeat_one(
    navigation_player: tuple[Playlist, FakeBackend, PlaybackController],
) -> None:
    playlist, backend, player = navigation_player
    playlist.repeat_mode = RepeatMode.ONE
    first, second, _ = start_navigation(playlist, backend, player)
    backend.ended.set()
    wait_until(lambda: backend.played == [first.uri, first.uri] and player._ready)
    player.skip()
    wait_until(lambda: player.current_track is second and player._ready)


def test_previous_does_not_add_interrupted_track_to_repeat_cycle(
    navigation_player: tuple[Playlist, FakeBackend, PlaybackController],
) -> None:
    playlist, backend, player = navigation_player
    playlist.repeat_mode = RepeatMode.ALL
    first, second, third = start_navigation(playlist, backend, player)
    player.skip()
    wait_until(lambda: player.current_track is second and player._ready)
    assert player.previous() == "previous"
    wait_until(lambda: player.current_track is first and player._ready)
    assert playlist.history_list == [first]
    assert playlist.queue_list == [second, third]


def test_failed_tracks_are_not_previous_targets(
    navigation_player: tuple[Playlist, FakeBackend, PlaybackController],
) -> None:
    playlist, backend, player = navigation_player
    failed = make_track("failed")
    good = make_track("good")

    def prepare(track: Track) -> str:
        if track is failed:
            raise RuntimeError("unavailable")
        return track.uri

    player.prepare = prepare
    playlist.add_many([failed, good])
    player.start()
    wait_until(lambda: player.queue_held)
    player.skip()
    wait_until(lambda: player.current_track is good and player._ready)
    assert player.previous() == "restarted"
    assert backend.played == [good.uri]


def test_previous_failure_preserves_navigation_and_queue(
    navigation_player: tuple[Playlist, FakeBackend, PlaybackController],
) -> None:
    playlist, backend, player = navigation_player
    first, second, third = start_navigation(playlist, backend, player)
    player.skip()
    wait_until(lambda: player.current_track is second and player._ready)
    with (
        patch.object(backend, "stop", side_effect=RuntimeError("stop failed")),
        pytest.raises(RuntimeError, match="stop failed"),
    ):
        player.previous()
    assert list(player._back_stack) == [first]
    assert playlist.queue_list == [third]
    assert player.current_track is second
    assert player.previous() == "previous"
    wait_until(lambda: player.current_track is first and player._ready)


def test_navigation_requests_during_transition_do_not_duplicate_queue(
    navigation_player: tuple[Playlist, FakeBackend, PlaybackController],
) -> None:
    playlist, backend, player = navigation_player
    first, second, third = start_navigation(playlist, backend, player)
    player.skip()
    wait_until(lambda: player.current_track is second and player._ready)
    # Hold the transition lock while sending repeated requests, so the worker
    # cannot begin the requested previous track between those requests.
    with player._control_lock:
        assert player.previous() == "previous"
        assert player.previous() is None
        player.skip()
    wait_until(lambda: player.current_track is first and player._ready)
    assert playlist.queue_list == [second, third]


def test_repeat_one_during_previous_keeps_interrupted_track_waiting(
    navigation_player: tuple[Playlist, FakeBackend, PlaybackController],
) -> None:
    playlist, backend, player = navigation_player
    first, second, third = start_navigation(playlist, backend, player)
    player.skip()
    wait_until(lambda: player.current_track is second and player._ready)
    playlist.repeat_mode = RepeatMode.ONE
    assert player.previous() == "previous"
    wait_until(lambda: player.current_track is first and player._ready)
    played = len(backend.played)
    backend.ended.set()
    wait_until(lambda: len(backend.played) == played + 1 and player._ready)
    assert player.current_track is first
    assert playlist.queue_list == [second, third]
    player.skip()
    wait_until(lambda: player.current_track is second and player._ready)


def test_explicit_pause_during_preparation_is_applied_when_track_starts(
    navigation_player: tuple[Playlist, FakeBackend, PlaybackController],
) -> None:
    playlist, backend, player = navigation_player
    preparing = threading.Event()
    released = threading.Event()

    def prepare(track: Track) -> str:
        preparing.set()
        assert released.wait(2)
        return track.uri

    player.prepare = prepare
    playlist.add(make_track("buffering"))
    player.start()
    try:
        assert preparing.wait(1)
        player.pause()
        player.pause()
    finally:
        released.set()
    wait_until(lambda: player._ready)
    assert backend.state is PlaybackState.PAUSED
    player.play()
    assert backend.state is PlaybackState.PLAYING


def test_explicit_play_can_override_paused_previous_during_transition(
    navigation_player: tuple[Playlist, FakeBackend, PlaybackController],
) -> None:
    playlist, backend, player = navigation_player
    first, second, _ = start_navigation(playlist, backend, player)
    player.skip()
    wait_until(lambda: player.current_track is second and player._ready)
    player.pause()
    with player._control_lock:
        assert player.previous() == "previous"
        player.play()
    wait_until(lambda: player.current_track is first and player._ready)
    assert backend.state is PlaybackState.PLAYING


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


def test_hold_after_current_waits_before_consuming_next_track() -> None:
    playlist = Playlist()
    backend = FakeBackend()
    first = make_track("first")
    second = make_track("second")
    playlist.add_many([first, second])
    player = PlaybackController(playlist, backend)
    player.start()

    wait_until(lambda: backend.played == [first.uri])
    player.hold_after_current()
    backend.ended.set()
    wait_until(lambda: player.queue_held)
    time.sleep(0.05)

    assert backend.played == [first.uri]
    assert playlist.queue_list == [second]

    player.toggle_pause()
    wait_until(lambda: backend.played == [first.uri, second.uri])
    player.close()


def test_skip_cancels_hold_after_current() -> None:
    playlist = Playlist()
    backend = FakeBackend()
    first = make_track("first")
    second = make_track("second")
    playlist.add_many([first, second])
    player = PlaybackController(playlist, backend)
    player.start()

    wait_until(lambda: backend.played == [first.uri])
    player.hold_after_current()
    player.skip()
    wait_until(lambda: backend.played == [first.uri, second.uri])

    assert not player.queue_held
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
    try:
        wait_until(lambda: len(errors) == 1)
        assert errors[0][0] is failed
        assert str(errors[0][1]) == "unavailable"
        assert playlist.queue_list == [failed, good]
        assert playlist.history_list == []
        assert started == []
        assert player.queue_held
        time.sleep(0.3)
        assert len(errors) == 1  # No automatic retry or cascading skips.
        player.skip()
        wait_until(lambda: started == [good])
        assert backend.played == [good.uri]
    finally:
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

    try:
        wait_until(lambda: len(errors) == 1)
        assert errors[0][0] is failed
        assert str(errors[0][1]) == "status unavailable"
        assert playlist.queue_list == [failed, good]
        assert playlist.history_list == []
        assert player.queue_held
        player.play()
        wait_until(lambda: backend.played == [failed.uri, failed.uri])
        assert playlist.queue_list == [good]
    finally:
        player.close()


@pytest.mark.parametrize("repeat", list(RepeatMode))
def test_retry_after_network_recovery_retains_duplicates_and_works_with_shuffle(
    repeat: RepeatMode,
) -> None:
    playlist = Playlist()
    failed, good = make_track("failed"), make_track("good")
    playlist.add_next_many([failed, failed, good])
    playlist.shuffle = True
    playlist.repeat_mode = repeat
    backend = FakeBackend()
    recovered = threading.Event()

    def prepare(track: Track) -> str:
        if not recovered.is_set():
            raise RuntimeError("network unavailable")
        return track.uri

    player = PlaybackController(playlist, backend, prepare=prepare)
    player.start()
    try:
        wait_until(lambda: player.queue_held)
        assert playlist.queue_list == [failed, failed, good]
        recovered.set()
        player.toggle_pause()
        wait_until(lambda: player._ready)
        assert backend.played == [failed.uri]
        assert playlist.queue_list == [failed, good]
    finally:
        player.close()


def test_quit_during_preparation_cancels_and_cannot_start_late_audio() -> None:
    playlist = Playlist()
    track = make_track("preparing")
    playlist.add(track)
    backend = FakeBackend()
    entered, cancelled = threading.Event(), threading.Event()

    def prepare(track: Track) -> str:
        entered.set()
        assert cancelled.wait(2)
        return track.uri

    player = PlaybackController(
        playlist, backend, prepare=prepare, cancel_prepare=cancelled.set,
    )
    player.start()
    try:
        assert entered.wait(2)
        start = time.monotonic()
        player.close()
        assert time.monotonic() - start < 1
        assert backend.played == []
        assert playlist.queue_list == [track]
        assert player.current_track is None
        assert player._thread is not None and not player._thread.is_alive()
    finally:
        cancelled.set()
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
