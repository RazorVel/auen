"""Tests for application-level media and recovery coordination."""

from pathlib import Path
from unittest.mock import MagicMock

from auen.cache import CacheManager
from auen.config import AuenConfig
from auen.downloads import DownloadManager
from auen.models import SessionMode, Track, TrackSource
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
        assert session.search("https://youtu.be/url")[0].title == "url"

    youtube.search.assert_called_once_with("query", limit=5)
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
    downloads.submit.assert_called_once_with(track)
