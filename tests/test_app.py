"""Tests for the Textual application shell and settings screen."""

from pathlib import Path

import pytest
from rich.cells import cell_len
from textual.widgets import DataTable, Input, Label

from auen.app import (
    AuenApp,
    DuplicateQueueScreen,
    SearchInput,
    SessionModeScreen,
    SettingsScreen,
    ThemeScreen,
    _format_timestamp,
    _parse_timestamp,
    _title_window,
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


def test_title_window_pages_by_terminal_cell_width_for_unicode() -> None:
    value = "Salim की Request पर Shreya ने गाया"
    first, first_page = _title_window(value, 18, 0)
    second, second_page = _title_window(value, 18, 1)

    assert first.endswith("→")
    assert second.startswith("←")
    assert first_page == 0
    assert second_page == 1
    assert cell_len(first) <= 18
    assert cell_len(second) <= 18
    assert _title_window("Short title", 18, 4) == ("Short title", 0)


async def test_theme_preview_escape_restores_original(tmp_path: Path) -> None:
    app = make_app(tmp_path, mode=SessionMode.STREAM_ONLY)

    async with app.run_test() as pilot:
        original = app.theme
        await pilot.press("f3")
        assert isinstance(app.screen, ThemeScreen)
        await pilot.press("down")
        assert app.theme != original

        await pilot.press("escape")
        assert app.theme == original
        assert app.config.theme == original


async def test_theme_preview_enter_saves_selection(tmp_path: Path) -> None:
    app = make_app(tmp_path, mode=SessionMode.STREAM_ONLY)

    async with app.run_test() as pilot:
        await pilot.press("f3")
        await pilot.press("down", "enter")
        await pilot.pause()

        assert not isinstance(app.screen, ThemeScreen)
        assert app.config.theme == app.theme
        assert (tmp_path / "config.toml").exists()


async def test_ctrl_a_selects_all_search_text(tmp_path: Path) -> None:
    app = make_app(tmp_path, mode=SessionMode.STREAM_ONLY)

    async with app.run_test() as pilot:
        search = app.query_one("#search-bar", SearchInput)
        search.value = "replace this"
        search.focus()
        await pilot.press("ctrl+a", "x")

        assert search.value == "x"


async def test_main_tab_cycle_skips_search_and_playback_buttons(tmp_path: Path) -> None:
    app = make_app(tmp_path, mode=SessionMode.STREAM_ONLY)

    async with app.run_test() as pilot:
        search = app.query_one("#search-bar", SearchInput)
        results = app.query_one("#results", DataTable)
        queue = app.query_one("#queue", DataTable)
        search.focus()

        await pilot.press("tab")
        assert results.has_focus
        await pilot.press("tab")
        assert queue.has_focus
        await pilot.press("tab")
        assert results.has_focus


async def test_escape_leaves_search_for_main_tables(tmp_path: Path) -> None:
    app = make_app(tmp_path, mode=SessionMode.STREAM_ONLY)

    async with app.run_test() as pilot:
        search = app.query_one("#search-bar", SearchInput)
        search.focus()
        await pilot.press("escape")

        assert app.query_one("#queue", DataTable).has_focus


async def test_left_and_right_page_selected_title_without_hiding_time(tmp_path: Path) -> None:
    app = make_app(tmp_path, mode=SessionMode.STREAM_ONLY)
    result = Track(
        title="Salim की Request पर Shreya ने गाया a deliberately long title",
        source=TrackSource.YOUTUBE,
        uri="https://youtube.com/watch?v=unicode",
        duration_display="4:27",
    )

    async with app.run_test(size=(80, 30)) as pilot:
        app._show_results([result])
        table = app.query_one("#results", DataTable)
        first_cell = str(table.get_cell(result.track_id, "title"))
        first = first_cell.removeprefix("\u2066").removesuffix("\u2069")

        await pilot.press("right")
        second_cell = str(table.get_cell(result.track_id, "title"))
        second = second_cell.removeprefix("\u2066").removesuffix("\u2069")

        assert first.endswith("→")
        assert second.startswith("←")
        assert second != first
        assert table.get_cell(result.track_id, "time") == "4:27"
        assert table.scroll_x == 0

        await pilot.press("left")
        assert table.get_cell(result.track_id, "title") == first_cell

        await pilot.press("right", "tab")
        assert table.get_cell(result.track_id, "title") == first_cell


async def test_arabic_title_is_directionally_isolated_from_time(tmp_path: Path) -> None:
    app = make_app(tmp_path, mode=SessionMode.STREAM_ONLY)
    result = Track(
        title="أغنية عربية طويلة للاختبار",
        source=TrackSource.YOUTUBE,
        uri="https://youtube.com/watch?v=rtl",
        duration_display="1:48:46",
    )

    async with app.run_test(size=(80, 30)):
        app._show_results([result])
        table = app.query_one("#results", DataTable)
        title = str(table.get_cell(result.track_id, "title"))

        assert title.startswith("\u2066")
        assert title.endswith("\u2069")
        assert table.get_cell(result.track_id, "time") == "1:48:46"
        assert table.ordered_columns[1].width == 7


async def test_table_columns_refresh_at_each_resized_width(tmp_path: Path) -> None:
    app = make_app(tmp_path, mode=SessionMode.STREAM_ONLY)
    result = Track(
        title="A long title whose visible window follows the current table width",
        source=TrackSource.YOUTUBE,
        uri="https://youtube.com/watch?v=resize",
        duration_display="3:21",
    )

    async with app.run_test(size=(100, 30)) as pilot:
        app._show_results([result])
        results = app.query_one("#results", DataTable)
        queue = app.query_one("#queue", DataTable)

        for width, height in ((70, 25), (120, 35), (55, 20), (100, 30)):
            await pilot.resize_terminal(width, height)
            await pilot.pause()

            assert results.ordered_columns[0].width == app._table_title_width(results)
            assert queue.ordered_columns[0].width == app._table_title_width(queue)
