"""Tests for the Textual application shell and settings screen."""

from pathlib import Path

import pytest
from textual.widgets import DataTable, Input, Label

from auen.app import (
    AuenApp,
    DuplicateQueueScreen,
    SearchInput,
    SessionModeScreen,
    SettingsScreen,
    _format_timestamp,
    _parse_timestamp,
)
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
        assert results.has_focus
        assert "Results · 1" in str(app.query_one("#results-title", Label).render())

        await pilot.press("enter")
        await pilot.pause()

        queue = app.query_one("#queue", DataTable)
        assert queue.row_count == 1
        assert app.session.playlist.queue_list[0].track_id == result.track_id


async def test_duplicate_search_result_requires_confirmation(tmp_path: Path) -> None:
    app = make_app(tmp_path, mode=SessionMode.STREAM_ONLY)
    result = Track(
        title="Repeat me",
        source=TrackSource.YOUTUBE,
        uri="https://youtube.com/watch?v=repeat",
    )
    app.session.youtube.search = lambda *_args, **_kwargs: [result]  # type: ignore[method-assign]

    async with app.run_test() as pilot:
        search = app.query_one("#search-bar", Input)
        search.value = "repeat"
        search.focus()
        await pilot.press("enter")
        await app.workers.wait_for_complete()

        await pilot.press("enter")
        await pilot.press("enter")
        await pilot.pause()

        queue = app.query_one("#queue", DataTable)
        assert isinstance(app.screen, DuplicateQueueScreen)
        assert queue.row_count == 1

        await pilot.click("#confirm-duplicate")
        await pilot.pause()

        assert queue.row_count == 2
        assert app.session.playlist.queue_list == [result, result]


async def test_duplicate_queue_confirmation_can_be_cancelled(tmp_path: Path) -> None:
    app = make_app(tmp_path, mode=SessionMode.STREAM_ONLY)
    result = Track(
        title="Only once",
        source=TrackSource.YOUTUBE,
        uri="https://youtube.com/watch?v=once",
    )
    app.session.youtube.search = lambda *_args, **_kwargs: [result]  # type: ignore[method-assign]

    async with app.run_test() as pilot:
        search = app.query_one("#search-bar", Input)
        search.value = "once"
        search.focus()
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.press("enter")
        await pilot.press("enter")
        await pilot.pause()

        await pilot.press("escape")
        await pilot.pause()

        assert app.query_one("#queue", DataTable).row_count == 1
        assert app.session.playlist.queue_list == [result]


@pytest.mark.parametrize(
    ("value", "expected"),
    [("90", 90), ("1:30", 90), ("1:02:15", 3735), ("2.5", 2.5)],
)
def test_parse_timestamp(value: str, expected: float) -> None:
    assert _parse_timestamp(value) == expected


@pytest.mark.parametrize("value", ["", "nope", "1:70", "-1", "1:2:3:4", "nan", "inf"])
def test_parse_timestamp_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValueError):
        _parse_timestamp(value)


def test_format_timestamp() -> None:
    assert _format_timestamp(90) == "1:30"
    assert _format_timestamp(3735) == "1:02:15"


async def test_ctrl_a_selects_all_search_text(tmp_path: Path) -> None:
    app = make_app(tmp_path, mode=SessionMode.STREAM_ONLY)

    async with app.run_test() as pilot:
        search = app.query_one("#search-bar", SearchInput)
        search.value = "replace this"
        search.focus()
        await pilot.press("ctrl+a", "x")

        assert search.value == "x"
