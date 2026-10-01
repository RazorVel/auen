"""Tests for application-level media and recovery coordination."""

import threading
import time
from collections.abc import Callable
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import MagicMock

from auen.backends.base import AudioBackend, BackendCapabilities
from auen.cache import CacheManager
from auen.config import AuenConfig
from auen.downloads import DownloadManager
from auen.models import PlaybackState, PlaybackStatus, SessionMode, Track, TrackSource
from auen.session import AuenSession
from auen.state import StateStore


def make_dependencies(tmp_path: Path) -> tuple[StateStore, CacheManager, DownloadManager]:
    state = StateStore(tmp_path / "state.sqlite3")
    cache = CacheManager(tmp_path / "cache", max_cache_bytes=100)
    return state, cache, DownloadManager(cache, max_workers=1)


def make_track(title: str) -> Track:
    return Track(
        title=title,
        source=TrackSource.YOUTUBE,
        uri=f"https://youtube.com/watch?v={title}",
    )


class FakeBackend(AudioBackend):
    def __init__(self) -> None:
        self.played: list[str] = []
        self.ended = threading.Event()
        self.state = PlaybackState.STOPPED
        self.volume = 80

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
        self.ended.set()

    def get_status(self) -> PlaybackStatus:
        return PlaybackStatus(state=self.state, volume=self.volume)

    def set_volume(self, level: int) -> None:
        self.volume = level

    def seek(self, _seconds: float) -> None:
        pass

    def wait_for_end(self, timeout: float | None = None) -> bool:
        return self.ended.wait(timeout)

    @property
    def name(self) -> str:
        return "fake"

    @property
    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(True, True, True, True)


def wait_until(predicate: Callable[[], bool], *, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("condition was not reached in time")
        time.sleep(0.01)


def test_search_delegates_query_and_youtube_url(tmp_path: Path) -> None:
    state, cache, downloads = make_dependencies(tmp_path)
    youtube = MagicMock()
    youtube.search.return_value = [make_track("result")]
    youtube.from_url.return_value = make_track("url")
    config = AuenConfig(config_dir=tmp_path, cache_dir=tmp_path / "cache")

    with AuenSession(
        config, state=state, cache=cache, downloads=downloads, youtube=youtube
    ) as session:
        assert session.search("query")[0].title == "result"
        assert session.search("more", limit=12)[0].title == "result"
        assert session.search("https://youtu.be/url")[0].title == "url"

    assert youtube.search.call_args_list == [
        (("query",), {"limit": 5}),
        (("more",), {"limit": 12}),
    ]
    youtube.from_url.assert_called_once_with("https://youtu.be/url")


def test_enqueue_is_immediately_persisted_and_restored(tmp_path: Path) -> None:
    config = AuenConfig(config_dir=tmp_path, cache_dir=tmp_path / "cache")
    state, cache, downloads = make_dependencies(tmp_path)
    track = make_track("queued")
    session = AuenSession(config, state=state, cache=cache, downloads=downloads)
    session.enqueue(track)
    session.close()

    restored_state, restored_cache, restored_downloads = make_dependencies(tmp_path)
    with AuenSession(
        config,
        state=restored_state,
        cache=restored_cache,
        downloads=restored_downloads,
    ) as restored:
        assert [item.track_id for item in restored.playlist.queue_list] == [track.track_id]


def test_cache_mode_schedules_background_download(tmp_path: Path) -> None:
    state, cache, downloads = make_dependencies(tmp_path)
    youtube = MagicMock()
    config = AuenConfig(config_dir=tmp_path, cache_dir=tmp_path / "cache")
    track = make_track("download")
    downloads.submit = MagicMock(return_value=MagicMock())  # type: ignore[method-assign]

    with AuenSession(
        config, state=state, cache=cache, downloads=downloads, youtube=youtube
    ) as session:
        future = session.enqueue(track, session_mode=SessionMode.STREAM_AND_CACHE)
        assert future is not None
        future.result(timeout=1)

    downloads.submit.assert_called_once_with(track)


def test_automatic_queue_caching_is_serialized(tmp_path: Path) -> None:
    state, cache, downloads = make_dependencies(tmp_path)
    config = AuenConfig(config_dir=tmp_path, cache_dir=tmp_path / "cache")
    first_download: Future[object] = Future()
    second_download: Future[object] = Future()
    downloads.submit = MagicMock(  # type: ignore[method-assign]
        side_effect=[first_download, second_download]
    )

    with AuenSession(config, state=state, cache=cache, downloads=downloads) as session:
        first = session.enqueue(make_track("first"), session_mode=SessionMode.STREAM_AND_CACHE)
        second = session.enqueue(make_track("second"), session_mode=SessionMode.STREAM_AND_CACHE)
        assert first is not None
        assert second is not None
        wait_until(lambda: downloads.submit.call_count == 1)

        first_download.set_result(MagicMock())
        wait_until(lambda: downloads.submit.call_count == 2)
        second_download.set_result(MagicMock())
        first.result(timeout=1)
        second.result(timeout=1)


def test_playback_changes_are_persisted_from_worker_thread(tmp_path: Path) -> None:
    state, cache, downloads = make_dependencies(tmp_path)
    config = AuenConfig(
        config_dir=tmp_path,
        cache_dir=tmp_path / "cache",
        session_mode=SessionMode.STREAM_ONLY.value,
    )
    track = Track(title="local", source=TrackSource.LOCAL, uri="/music/local.opus")
    backend = FakeBackend()

    with AuenSession(config, state=state, cache=cache, downloads=downloads) as session:
        session.enqueue(track)
        session.start_playback(backend)
        wait_until(lambda: backend.played == [track.uri])
        assert session.current_track is track

        backend.ended.set()
        wait_until(lambda: session.playlist.history_list == [track])
        wait_until(lambda: session.current_track is None)
        snapshot = session.state.load()

        assert snapshot.current_track is None
        assert [item.track_id for item in snapshot.history] == [track.track_id]
