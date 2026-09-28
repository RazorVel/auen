"""Tests for the Textual application shell and settings screen."""

from pathlib import Path

from textual.widgets import DataTable, Input

from auen.app import AuenApp, SessionModeScreen, SettingsScreen
from auen.cache import CacheManager
from auen.config import AuenConfig
from auen.downloads import DownloadManager
from auen.models import SessionMode, Track, TrackSource
from auen.session import AuenSession
from auen.state import StateStore


def make_app(tmp_path: Path, *, mode: SessionMode) -> AuenApp:
    config = AuenConfig(
        config_dir=tmp_path,
        cache_dir=tmp_path / "cache",
        state_dir=tmp_path / "state",
        session_mode=mode.value,
    )
    state = StateStore(config.state_dir / "state.sqlite3")
    cache = CacheManager(config.cache_dir)
    downloads = DownloadManager(cache, max_workers=1)
    return AuenApp(
        config,
        session=AuenSession(config, state=state, cache=cache, downloads=downloads),
    )


async def test_startup_asks_for_session_mode(tmp_path: Path) -> None:
    app = make_app(tmp_path, mode=SessionMode.ASK)

    async with app.run_test() as pilot:
        assert isinstance(app.screen, SessionModeScreen)
        await pilot.click("#stream-only")
        await pilot.pause()

        assert app.current_session_mode is SessionMode.STREAM_ONLY


async def test_settings_screen_saves_to_shared_config(tmp_path: Path) -> None:
    app = make_app(tmp_path, mode=SessionMode.STREAM_ONLY)

    async with app.run_test() as pilot:
        await pilot.press("f2")
        await pilot.pause()
        assert isinstance(app.screen, SettingsScreen)

        volume = app.screen.query_one("#volume")
        volume.value = "61"
        await pilot.click("#save")
        await pilot.pause()

        assert app.config.volume == 61
        assert (tmp_path / "config.toml").exists()


async def test_search_result_can_be_selected_into_durable_queue(tmp_path: Path) -> None:
    app = make_app(tmp_path, mode=SessionMode.STREAM_ONLY)
    result = Track(
        title="Found track",
        source=TrackSource.YOUTUBE,
        uri="https://youtube.com/watch?v=found",
        duration_display="3:21",
    )
    app.session.youtube.search = lambda *_args, **_kwargs: [result]  # type: ignore[method-assign]

    async with app.run_test() as pilot:
        search = app.query_one("#search-bar", Input)
        search.value = "found"
        search.focus()
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        results = app.query_one("#results", DataTable)
        assert results.row_count == 1

        results.focus()
        await pilot.press("enter")
        await pilot.pause()

        queue = app.query_one("#queue", DataTable)
        assert queue.row_count == 1
        assert app.session.playlist.queue_list[0].track_id == result.track_id
