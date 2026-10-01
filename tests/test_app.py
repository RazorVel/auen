"""Tests for the Textual application shell and settings screen."""

import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from rich.cells import cell_len
from textual.containers import Horizontal
from textual.widgets import DataTable, Input, Label

from auen.app import (
    AuenApp,
    DuplicateQueueScreen,
    LoadMoreScreen,
    SearchInput,
    SessionModeScreen,
    SettingsScreen,
    ThemeScreen,
    _emoji_safety_gutter,
    _format_timestamp,
    _merge_search_items,
    _parse_timestamp,
    _stabilize_terminal_emoji,
    _title_cell,
    _title_window,
    run,
)
from auen.cache import CacheManager
from auen.config import AuenConfig
from auen.downloads import DownloadManager
from auen.models import CollectionKind, MediaCollection, SessionMode, Track, TrackSource
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
        assert any(
            "Load more amount" in str(label.render())
            for label in app.screen.query(".setting-row Label")
        )

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
        assert f"{result.track_id}:0" in app.search_results
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


@pytest.mark.parametrize("emoji", ["🌟🔥", "👩‍🎤", "🧑🏽‍🎤", "☕️", "🇮🇩", "1️⃣"])
def test_title_cell_keeps_a_gutter_for_terminal_emoji_widths(emoji: str) -> None:
    title = f"A long title {emoji} that reaches the edge"
    rendered, _page = _title_cell(title, 20, 0)

    assert cell_len(rendered) <= 20 - _emoji_safety_gutter(title)


def test_load_more_merge_preserves_order_and_deduplicates_uris() -> None:
    first = Track(
        title="First",
        source=TrackSource.YOUTUBE,
        uri="https://youtube.com/watch?v=first",
    )
    repeated = Track(
        title="First returned again",
        source=TrackSource.YOUTUBE,
        uri=first.uri,
    )
    second = Track(
        title="Second",
        source=TrackSource.YOUTUBE,
        uri="https://youtube.com/watch?v=second",
    )

    assert _merge_search_items([first], [repeated, second]) == [first, second]


def test_load_more_merge_caps_newly_displayed_rows() -> None:
    existing = [
        Track(
            title=f"Existing {index}",
            source=TrackSource.YOUTUBE,
            uri=f"https://youtube.com/watch?v=existing-{index}",
        )
        for index in range(3)
    ]
    displaced_collection = MediaCollection(
        title="Album",
        uri="https://youtube.com/playlist?list=album",
        collection_id="album",
    )
    incoming = [
        *existing,
        *[
            Track(
                title=f"New {index}",
                source=TrackSource.YOUTUBE,
                uri=f"https://youtube.com/watch?v=new-{index}",
            )
            for index in range(7)
        ],
        displaced_collection,
    ]

    merged = _merge_search_items(
        [*existing, displaced_collection],
        incoming,
        max_items=len(existing) + 1 + 5,
    )

    assert merged[:4] == [*existing, displaced_collection]
    assert len(merged) == len(existing) + 1 + 5


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Fire 🔥❄️", "Fire 🔥❄"),
        ("Singer 👩‍🎤", "Singer 👩🎤"),
        ("Skin 🧑🏽", "Skin 🧑"),
        ("Key 1️⃣", "Key 1"),
    ],
)
def test_terminal_emoji_normalization_removes_unstable_composition(
    value: str, expected: str
) -> None:
    assert _stabilize_terminal_emoji(value) == expected


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
        title=(
            "Salim की Request पर Shreya ने गाया a deliberately long title "
            "that remains pageable even in a full-width phone pane"
        ),
        source=TrackSource.YOUTUBE,
        uri="https://youtube.com/watch?v=unicode",
        duration_display="4:27",
    )

    async with app.run_test(size=(80, 30)) as pilot:
        app._show_results([result])
        table = app.query_one("#results", DataTable)
        row_key = f"{result.track_id}:0"
        first_cell = str(table.get_cell(row_key, "title"))
        first = first_cell.removeprefix("\u2066").removesuffix("\u2069")

        await pilot.press("right")
        second_cell = str(table.get_cell(row_key, "title"))
        second = second_cell.removeprefix("\u2066").removesuffix("\u2069")

        assert first.endswith("→")
        assert second.startswith("←")
        assert second != first
        assert table.get_cell(row_key, "time") == "4:27"
        assert table.scroll_x == 0

        await pilot.press("left")
        assert table.get_cell(row_key, "title") == first_cell

        await pilot.press("right", "tab")
        assert table.get_cell(row_key, "title") == first_cell


async def test_paged_title_resets_when_highlight_moves_to_another_row(tmp_path: Path) -> None:
    app = make_app(tmp_path, mode=SessionMode.STREAM_ONLY)
    tracks = [
        Track(
            title=f"A deliberately long title for result {index} that needs several pages",
            source=TrackSource.YOUTUBE,
            uri=f"https://youtube.com/watch?v=reset-{index}",
        )
        for index in range(2)
    ]

    async with app.run_test(size=(80, 30)) as pilot:
        app._show_results(tracks)
        table = app.query_one("#results", DataTable)
        first_key = f"{tracks[0].track_id}:0"
        first_cell = table.get_cell(first_key, "title")

        await pilot.press("right")
        assert table.get_cell(first_key, "title") != first_cell

        await pilot.press("down")
        assert table.get_cell(first_key, "title") == first_cell


async def test_title_reset_ignores_queue_rows_replaced_by_shuffle(tmp_path: Path) -> None:
    app = make_app(tmp_path, mode=SessionMode.STREAM_ONLY)
    before = Track(title="Before", source=TrackSource.LOCAL, uri="/before.opus")
    after = Track(title="After", source=TrackSource.LOCAL, uri="/after.opus")

    async with app.run_test():
        app.session.playlist.add(before)
        app._refresh_queue()
        queue = app.query_one("#queue", DataTable)

        app.session.playlist.restore([after], [])
        app._reset_title_pages(queue)

        assert queue.row_count == 1


def test_run_closes_session_after_unhandled_ui_error(tmp_path: Path) -> None:
    app = MagicMock()
    app.run.side_effect = RuntimeError("UI crash")

    with (
        patch("auen.app.AuenConfig.load", return_value=AuenConfig(config_dir=tmp_path)),
        patch("auen.app.detect_backend", return_value=MagicMock()),
        patch("auen.app.AuenApp", return_value=app),
        pytest.raises(RuntimeError, match="UI crash"),
    ):
        run()

    app.session.close.assert_called_once_with()


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
        row_key = f"{result.track_id}:0"
        title = str(table.get_cell(row_key, "title"))

        assert title.startswith("\u2066")
        assert title.endswith("\u2069")
        assert table.get_cell(row_key, "time") == "1:48:46"
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
            assert queue.ordered_columns[1].width == app._table_title_width(queue)
            assert sum(
                column.get_render_width(results) for column in results.ordered_columns
            ) <= results.size.width - 1
            assert sum(
                column.get_render_width(queue) for column in queue.ordered_columns
            ) <= queue.size.width - 1


async def test_workspace_stacks_on_narrow_terminals_and_restores_wide_layout(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path, mode=SessionMode.STREAM_ONLY)

    async with app.run_test(size=(120, 30)) as pilot:
        workspace = app.query_one("#workspace", Horizontal)
        results_pane = app.query_one("#results-pane")
        queue_pane = app.query_one("#queue-pane")

        assert not workspace.has_class("narrow")
        assert results_pane.region.y == queue_pane.region.y
        assert results_pane.region.x < queue_pane.region.x

        await pilot.resize_terminal(60, 30)
        await pilot.pause()

        assert workspace.has_class("narrow")
        assert results_pane.region.x == queue_pane.region.x
        assert results_pane.region.y < queue_pane.region.y
        assert results_pane.region.width == queue_pane.region.width
        assert app.query_one("#results", DataTable).size.height >= 5
        assert app.query_one("#queue", DataTable).size.height >= 5

        await pilot.resize_terminal(120, 30)
        await pilot.pause()

        assert not workspace.has_class("narrow")
        assert results_pane.region.y == queue_pane.region.y
        assert results_pane.region.x < queue_pane.region.x


async def test_collection_opens_tracks_and_escape_returns_to_search(tmp_path: Path) -> None:
    app = make_app(tmp_path, mode=SessionMode.STREAM_ONLY)
    collection = MediaCollection(
        title="An album",
        uri="https://youtube.com/playlist?list=album",
        kind=CollectionKind.ALBUM,
        collection_id="album",
    )
    track = Track(
        title="Album track",
        source=TrackSource.YOUTUBE,
        uri="https://youtube.com/watch?v=track",
        duration_display="3:10",
    )
    app.session.youtube.collection_tracks = lambda _collection: [track]  # type: ignore[method-assign]
    before = Track(
        title="Before",
        source=TrackSource.YOUTUBE,
        uri="https://youtube.com/watch?v=before",
    )
    after = Track(
        title="After",
        source=TrackSource.YOUTUBE,
        uri="https://youtube.com/watch?v=after",
    )

    async with app.run_test() as pilot:
        app._show_results([before, collection, after])
        table = app.query_one("#results", DataTable)
        table.move_cursor(row=1)
        assert "◉" in str(table.get_cell("album:1", "title"))

        await pilot.press("enter")
        await app.workers.wait_for_complete()
        assert table.row_count == 1
        assert "An album" in str(app.query_one("#results-title", Label).render())

        await pilot.press("escape")
        assert table.row_count == 3
        assert table.cursor_row == 1
        assert "Results" in str(app.query_one("#results-title", Label).render())
        assert "◉" in str(table.get_cell("album:1", "title"))


async def test_duplicate_result_identities_cannot_crash_table_render(tmp_path: Path) -> None:
    app = make_app(tmp_path, mode=SessionMode.STREAM_ONLY)
    collection = MediaCollection(
        title="Repeated playlist",
        uri="https://youtube.com/playlist?list=repeated",
        collection_id="repeated",
    )

    async with app.run_test():
        app._show_results([collection, collection])
        table = app.query_one("#results", DataTable)

        assert table.row_count == 2
        assert table.get_cell("repeated:0", "time") == "list"
        assert table.get_cell("repeated:1", "time") == "list"


async def test_initial_search_fills_pane_and_load_more_requires_confirmation(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path, mode=SessionMode.STREAM_ONLY)
    requested_limits: list[int] = []

    def search(_query: str, *, limit: int) -> list[Track]:
        requested_limits.append(limit)
        return [
            Track(
                title=f"Result {index}",
                source=TrackSource.YOUTUBE,
                uri=f"https://youtube.com/watch?v={index}",
            )
            for index in range(limit)
        ]

    app.session.youtube.search = search  # type: ignore[method-assign]

    async with app.run_test(size=(80, 30)) as pilot:
        search_input = app.query_one("#search-bar", Input)
        search_input.value = "query"
        search_input.focus()
        expected_initial = app._initial_search_limit()
        await pilot.press("enter")
        await app.workers.wait_for_complete()

        table = app.query_one("#results", DataTable)
        assert requested_limits == [expected_initial]
        assert table.row_count == expected_initial + 1

        table.move_cursor(row=table.row_count - 1)
        await pilot.pause()
        assert requested_limits == [expected_initial]

        await pilot.press("enter")
        assert isinstance(app.screen, LoadMoreScreen)
        assert requested_limits == [expected_initial]

        await pilot.click("#confirm-load-more")
        await app.workers.wait_for_complete()
        assert requested_limits == [expected_initial, expected_initial + 5]
        assert table.row_count == expected_initial + 6


async def test_load_more_preserves_navigation_during_request(tmp_path: Path) -> None:
    app = make_app(tmp_path, mode=SessionMode.STREAM_ONLY)
    tracks = [
        Track(
            title=f"Result {index}",
            source=TrackSource.YOUTUBE,
            uri=f"https://youtube.com/watch?v={index}",
        )
        for index in range(10)
    ]
    started = threading.Event()
    release = threading.Event()

    def slow_search(_query: str, *, limit: int) -> list[Track]:
        started.set()
        release.wait(2)
        return tracks[:limit]

    app.session.youtube.search = slow_search  # type: ignore[method-assign]

    try:
        async with app.run_test() as pilot:
            app._active_query = "query"
            app._search_limit = 5
            app._search_has_more = True
            app._show_results(tracks[:5], has_more=True, cursor_row=5)
            app._load_more_decided(True)
            await pilot.pause()
            assert started.wait(1)

            table = app.query_one("#results", DataTable)
            table.move_cursor(row=2)
            await pilot.pause()
            release.set()
            await app.workers.wait_for_complete()

            assert table.cursor_row == 2
            assert table.row_count == 11
    finally:
        release.set()


async def test_escape_cancels_ui_search_and_ignores_late_result(tmp_path: Path) -> None:
    app = make_app(tmp_path, mode=SessionMode.STREAM_ONLY)
    previous = Track(
        title="Previous result",
        source=TrackSource.YOUTUBE,
        uri="https://youtube.com/watch?v=previous",
    )
    late = Track(
        title="Late result",
        source=TrackSource.YOUTUBE,
        uri="https://youtube.com/watch?v=late",
    )
    started = threading.Event()
    release = threading.Event()

    def slow_search(_query: str, *, limit: int) -> list[Track]:
        del limit
        started.set()
        release.wait(2)
        return [late]

    app.session.youtube.search = slow_search  # type: ignore[method-assign]

    try:
        async with app.run_test() as pilot:
            app._show_results([previous])
            search_input = app.query_one("#search-bar", Input)
            search_input.value = "new query"
            search_input.focus()
            await pilot.press("enter")
            assert started.wait(1)

            await pilot.press("escape")
            table = app.query_one("#results", DataTable)
            assert f"{previous.track_id}:0" in app.search_results

            release.set()
            await app.workers.wait_for_complete()
            assert f"{previous.track_id}:0" in app.search_results
            assert f"{late.track_id}:0" not in app.search_results
            assert table.row_count == 1
    finally:
        release.set()


async def test_empty_search_has_visible_state_and_focuses_queue(tmp_path: Path) -> None:
    app = make_app(tmp_path, mode=SessionMode.STREAM_ONLY)
    app.session.youtube.search = lambda *_args, **_kwargs: []  # type: ignore[method-assign]

    async with app.run_test() as pilot:
        search_input = app.query_one("#search-bar", Input)
        search_input.value = "nothing"
        search_input.focus()
        await pilot.press("enter")
        await app.workers.wait_for_complete()

        results = app.query_one("#results", DataTable)
        assert results.row_count == 1
        assert "No matching" in str(results.get_cell("__state__", "title"))
        assert app.query_one("#queue", DataTable).has_focus


async def test_queue_supports_play_next_reorder_and_play_now(tmp_path: Path) -> None:
    app = make_app(tmp_path, mode=SessionMode.STREAM_ONLY)
    tracks = [
        Track(title=f"Track {index}", source=TrackSource.LOCAL, uri=f"/{index}.opus")
        for index in range(3)
    ]

    async with app.run_test() as pilot:
        app.session.playlist.add_many(tracks)
        app._refresh_queue()
        queue = app.query_one("#queue", DataTable)
        queue.focus()
        queue.move_cursor(row=2)

        await pilot.press("home")
        assert app.session.playlist.queue_list == [tracks[2], tracks[0], tracks[1]]

        await pilot.press("shift+down")
        assert app.session.playlist.queue_list == [tracks[0], tracks[2], tracks[1]]

        queue.move_cursor(row=2)
        await pilot.press("enter")
        assert app.session.playlist.queue_list[0] is tracks[1]
        assert queue.get_cell(f"{tracks[1].track_id}:0", "time") == "-"
        assert queue.get_cell(f"{tracks[1].track_id}:0", "status") == "↗"
