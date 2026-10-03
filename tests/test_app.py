"""Tests for the Textual application shell and settings screen."""

import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from rich.cells import cell_len
from textual.containers import Horizontal
from textual.widgets import Button, DataTable, Footer, Input, Label, Select

from auen.app import (
    AuenApp,
    ClearHistoryScreen,
    DeletePlaylistScreen,
    DuplicateQueueScreen,
    LoadMoreScreen,
    PlaylistNameScreen,
    PlaylistPickerScreen,
    QueuePlaylistScreen,
    SearchInput,
    SessionModeScreen,
    SettingsScreen,
    ThemeScreen,
    _emoji_safety_gutter,
    _format_timestamp,
    _is_termux_environment,
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


def test_run_preserves_ui_error_when_backend_cleanup_also_fails(tmp_path: Path) -> None:
    app = MagicMock()
    app.run.side_effect = RuntimeError("UI crash")
    app.session.close.side_effect = RuntimeError("backend stop timed out")

    with (
        patch("auen.app.AuenConfig.load", return_value=AuenConfig(config_dir=tmp_path)),
        patch("auen.app.detect_backend", return_value=MagicMock()),
        patch("auen.app.AuenApp", return_value=app),
        pytest.raises(RuntimeError, match="UI crash"),
    ):
        run()

    app.session.close.assert_called_once_with()


def test_run_migrates_termux_preference_when_mpv_is_available(tmp_path: Path) -> None:
    config = AuenConfig(config_dir=tmp_path, backend="termux")
    app = MagicMock()

    with (
        patch("auen.app.AuenConfig.load", return_value=config),
        patch("auen.app._is_termux_environment", return_value=True),
        patch("auen.app.shutil.which", return_value="/data/data/com.termux/files/usr/bin/mpv"),
        patch("auen.app.detect_backend", return_value=MagicMock()) as detect,
        patch("auen.app.AuenApp", return_value=app),
    ):
        run()

    assert config.backend == "auto"
    detect.assert_called_once_with("auto")
    app.run.assert_called_once_with()


async def test_unmount_suppresses_backend_cleanup_error(tmp_path: Path) -> None:
    app = make_app(tmp_path, mode=SessionMode.STREAM_ONLY)
    app.session.close = MagicMock(side_effect=RuntimeError("stop timed out"))  # type: ignore[method-assign]

    async with app.run_test():
        pass


async def test_termux_settings_hide_fallback_when_mpv_is_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TERMUX_VERSION", "0.118")
    app = make_app(tmp_path, mode=SessionMode.STREAM_ONLY)

    with patch("auen.app.shutil.which", return_value="/data/data/com.termux/files/usr/bin/mpv"):
        async with app.run_test() as pilot:
            await pilot.press("f2")
            backend = app.screen.query_one("#backend", Select)
            values = {value for _prompt, value in backend._options}

            assert {"auto", "mpv"} <= values
            assert "termux" not in values
            assert not app.screen.query(Footer)


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


async def test_narrow_layout_uses_compact_playback_labels(tmp_path: Path) -> None:
    app = make_app(tmp_path, mode=SessionMode.STREAM_ONLY)

    async with app.run_test(size=(60, 30)):
        assert str(app.query_one("#seek-back", Button).label) == "-10s ["
        assert str(app.query_one("#play-pause", Button).label) == "Play/Pause"
        assert str(app.query_one("#seek-forward", Button).label) == "+10s ]"
        assert str(app.query_one("#jump-time", Button).label) == "Jump g"
        assert str(app.query_one("#next-track", Button).label) == "Next n"


def test_footer_hides_actions_already_shown_as_playback_buttons() -> None:
    bindings = {binding.key: binding for binding in AuenApp.BINDINGS}

    for key in ("space", "n", "[", "]", "g"):
        assert not bindings[key].show
    for key in ("/", "d", "f2", "f3", "q"):
        assert bindings[key].show


def test_saving_unchanged_settings_does_not_resend_volume(tmp_path: Path) -> None:
    app = make_app(tmp_path, mode=SessionMode.STREAM_ONLY)
    player = MagicMock()
    app.session.player = player
    app._settings_volume_before = app.config.volume

    app._settings_closed(True)

    player.set_volume.assert_not_called()


def test_saving_changed_volume_updates_active_player(tmp_path: Path) -> None:
    app = make_app(tmp_path, mode=SessionMode.STREAM_ONLY)
    player = MagicMock()
    app.session.player = player
    app._settings_volume_before = app.config.volume
    app.config.volume = 55

    app._settings_closed(True)

    player.set_volume.assert_called_once_with(55)


def test_termux_environment_disables_directional_control_characters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TERMUX_VERSION", "0.118")

    rendered, _page = _title_cell("Arabic أغنية", 30, 0)

    assert _is_termux_environment()
    assert "\u2066" not in rendered
    assert "\u2069" not in rendered


async def test_termux_environment_marks_main_and_theme_screens_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PREFIX", "/data/data/com.termux/files/usr")
    app = make_app(tmp_path, mode=SessionMode.STREAM_ONLY)

    async with app.run_test(size=(60, 30)) as pilot:
        assert app.screen.has_class("termux-safe")
        assert app.query_one("#results-pane").styles.border_top[0] == "ascii"

        await pilot.press("f3")
        assert isinstance(app.screen, ThemeScreen)
        assert app.screen.has_class("termux-safe")
        assert app.screen.query_one("#theme-dialog").styles.border_top[0] == "ascii"
        assert app.screen.query_one("#theme-list").styles.border_top[0] == ""


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


async def test_queue_deletion_keeps_nearest_row_selected(tmp_path: Path) -> None:
    app = make_app(tmp_path, mode=SessionMode.STREAM_ONLY)
    tracks = [
        Track(title=f"Track {index}", source=TrackSource.LOCAL, uri=f"/{index}.opus")
        for index in range(4)
    ]

    async with app.run_test() as pilot:
        app.session.playlist.add_many(tracks)
        app._refresh_queue()
        queue = app.query_one("#queue", DataTable)
        queue.focus()

        queue.move_cursor(row=1)
        await pilot.press("delete")
        assert app.session.playlist.queue_list == [tracks[0], tracks[2], tracks[3]]
        assert queue.cursor_row == 1

        queue.move_cursor(row=2)
        await pilot.press("delete")
        assert app.session.playlist.queue_list == [tracks[0], tracks[2]]
        assert queue.cursor_row == 1

        await pilot.press("delete", "delete")
        assert app.session.playlist.queue_list == []
        assert queue.row_count == 0


async def test_history_view_restores_previous_results_and_cursor(tmp_path: Path) -> None:
    app = make_app(tmp_path, mode=SessionMode.STREAM_ONLY)
    results = [
        Track(title=f"Result {index}", source=TrackSource.LOCAL, uri=f"/result-{index}.opus")
        for index in range(3)
    ]
    played = Track(
        title="Previously played",
        source=TrackSource.YOUTUBE,
        uri="https://youtube.com/watch?v=played",
        duration_display="3:14",
    )
    app.session.state.record_play(
        played,
        played_at=datetime.now(timezone.utc) - timedelta(minutes=2),
    )

    async with app.run_test() as pilot:
        app._show_results(results, cursor_row=2)
        await pilot.press("h")

        table = app.query_one("#results", DataTable)
        assert "History · 1" in str(app.query_one("#results-title", Label).render())
        assert table.get_cell(f"{played.track_id}:0", "time") == "3:14"
        assert table.get_cell(f"{played.track_id}:0", "plays") == "1"

        await pilot.press("escape")
        assert "Results · 3" in str(app.query_one("#results-title", Label).render())
        assert table.cursor_row == 2
        assert app._result_order == results


async def test_history_supports_play_next_play_now_and_duplicate_confirmation(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path, mode=SessionMode.STREAM_ONLY)
    played = Track(
        title="History track",
        source=TrackSource.YOUTUBE,
        uri="https://youtube.com/watch?v=history",
    )
    app.session.state.record_play(played)

    async with app.run_test() as pilot:
        app.query_one("#results", DataTable).focus()
        await pilot.press("h")
        await pilot.pause()
        assert app.query_one("#results", DataTable).has_focus
        await pilot.press("home")
        assert app.session.playlist.queue_list == [played]

        await pilot.press("enter")
        assert isinstance(app.screen, DuplicateQueueScreen)
        await pilot.click("#confirm-duplicate")
        assert [track.uri for track in app.session.playlist.queue_list] == [played.uri, played.uri]


async def test_history_can_append_track_to_end_of_queue(tmp_path: Path) -> None:
    app = make_app(tmp_path, mode=SessionMode.STREAM_ONLY)
    queued = Track(title="Already queued", source=TrackSource.LOCAL, uri="/queued.opus")
    played = Track(title="History track", source=TrackSource.LOCAL, uri="/history.opus")
    app.session.enqueue(queued)
    app.session.state.record_play(played)

    async with app.run_test() as pilot:
        app.query_one("#results", DataTable).focus()
        await pilot.press("h")
        await pilot.press("a")

        assert app.session.playlist.queue_list == [queued, played]

        await pilot.press("a")
        assert isinstance(app.screen, DuplicateQueueScreen)
        await pilot.click("#confirm-duplicate")
        assert app.session.playlist.queue_list == [queued, played, played]


async def test_history_shortcuts_type_normally_in_search(tmp_path: Path) -> None:
    app = make_app(tmp_path, mode=SessionMode.STREAM_ONLY)

    async with app.run_test() as pilot:
        search = app.query_one("#search-bar", Input)
        search.focus()
        await pilot.press("a", "h", "c", "p", "r", "s")

        assert search.value == "ahcprs"
        assert not app._showing_history

        await pilot.press("ctrl+a", "s")
        assert search.value == "s"


async def test_history_supports_remove_and_confirmed_clear(tmp_path: Path) -> None:
    app = make_app(tmp_path, mode=SessionMode.STREAM_ONLY)
    first = Track(title="First", source=TrackSource.LOCAL, uri="/first.opus")
    second = Track(title="Second", source=TrackSource.LOCAL, uri="/second.opus")
    app.session.state.record_play(first)
    app.session.state.record_play(second)

    async with app.run_test() as pilot:
        app.query_one("#results", DataTable).focus()
        await pilot.press("h")
        await pilot.pause()
        assert app.query_one("#results", DataTable).has_focus
        await pilot.press("delete")
        assert len(app.session.recent_history()) == 1

        await pilot.press("c")
        assert isinstance(app.screen, ClearHistoryScreen)
        await pilot.press("escape")
        assert len(app.session.recent_history()) == 1

        await pilot.press("c")
        await pilot.click("#confirm-clear-history")
        assert app.session.recent_history() == []
        assert app.query_one("#results", DataTable).row_count == 1


async def test_history_columns_remain_contained_when_resized(tmp_path: Path) -> None:
    app = make_app(tmp_path, mode=SessionMode.STREAM_ONLY)
    track = Track(
        title="A deliberately long previously played title with emoji 🔥",
        source=TrackSource.YOUTUBE,
        uri="https://youtube.com/watch?v=history-resize",
        duration_display="1:29:39",
    )
    app.session.state.record_play(track)

    async with app.run_test(size=(100, 30)) as pilot:
        app.query_one("#results", DataTable).focus()
        await pilot.press("h")

        table = app.query_one("#results", DataTable)
        for width, height in ((60, 30), (120, 35), (55, 25), (100, 30)):
            await pilot.resize_terminal(width, height)
            await pilot.pause()

            assert table.ordered_columns[0].width == app._table_title_width(table)
            assert sum(column.get_render_width(table) for column in table.ordered_columns) <= (
                table.size.width - 1
            )
            assert table.get_cell(f"{track.track_id}:0", "time") == "1:29:39"
            assert table.get_cell(f"{track.track_id}:0", "plays") == "1"


async def test_named_playlist_create_rename_delete_and_restore_results(tmp_path: Path) -> None:
    app = make_app(tmp_path, mode=SessionMode.STREAM_ONLY)
    result = Track(title="Search result", source=TrackSource.LOCAL, uri="/result.opus")

    async with app.run_test() as pilot:
        app._show_results([result])
        await pilot.press("p")
        assert "Playlists · 0" in str(app.query_one("#results-title", Label).render())

        await pilot.press("c")
        assert isinstance(app.screen, PlaylistNameScreen)
        app.screen.query_one("#playlist-name-input", Input).value = "Road Trip"
        await pilot.press("enter")
        assert app.session.named_playlists()[0].name == "Road Trip"

        await pilot.press("enter")
        assert "Road Trip · 0" in str(app.query_one("#results-title", Label).render())
        await pilot.press("escape")

        await pilot.press("r")
        assert isinstance(app.screen, PlaylistNameScreen)
        app.screen.query_one("#playlist-name-input", Input).value = "Favorites"
        await pilot.press("enter")
        assert app.session.named_playlists()[0].name == "Favorites"

        await pilot.press("delete")
        assert isinstance(app.screen, DeletePlaylistScreen)
        await pilot.press("escape")
        assert len(app.session.named_playlists()) == 1

        await pilot.press("delete")
        await pilot.click("#confirm-delete-playlist")
        assert app.session.named_playlists() == []

        await pilot.press("escape")
        assert "Results · 1" in str(app.query_one("#results-title", Label).render())
        assert app._result_order == [result]


async def test_add_to_named_playlist_from_results_history_and_queue(tmp_path: Path) -> None:
    app = make_app(tmp_path, mode=SessionMode.STREAM_ONLY)
    playlist = app.session.create_named_playlist("Mix")
    result = Track(title="Result", source=TrackSource.LOCAL, uri="/result.opus")
    history = Track(title="History", source=TrackSource.LOCAL, uri="/history.opus")
    queued = Track(title="Queued", source=TrackSource.LOCAL, uri="/queued.opus")
    app.session.state.record_play(history)
    app.session.enqueue(queued)

    async with app.run_test() as pilot:
        app._show_results([result])
        await pilot.press("s")

        await pilot.press("h")
        await pilot.press("s")

        queue = app.query_one("#queue", DataTable)
        queue.focus()
        await pilot.press("s")

        tracks = app.session.named_playlist_tracks(playlist.playlist_id)
        assert [track.title for track in tracks] == ["Result", "History", "Queued"]


async def test_add_to_playlist_picker_and_duplicate_confirmation(tmp_path: Path) -> None:
    app = make_app(tmp_path, mode=SessionMode.STREAM_ONLY)
    first = app.session.create_named_playlist("First")
    app.session.create_named_playlist("Second")
    track = Track(title="Selected", source=TrackSource.LOCAL, uri="/selected.opus")

    async with app.run_test() as pilot:
        app._show_results([track])
        await pilot.press("s")
        assert isinstance(app.screen, PlaylistPickerScreen)
        await pilot.press("enter")
        assert app.session.named_playlist_tracks(first.playlist_id) == [track]

        await pilot.press("s")
        await pilot.press("enter")
        assert isinstance(app.screen, DuplicateQueueScreen)
        await pilot.press("escape")
        assert len(app.session.named_playlist_tracks(first.playlist_id)) == 1

        await pilot.press("s")
        await pilot.press("enter")
        await pilot.click("#confirm-duplicate")
        assert len(app.session.named_playlist_tracks(first.playlist_id)) == 2


async def test_add_to_playlist_creates_first_playlist_when_none_exist(tmp_path: Path) -> None:
    app = make_app(tmp_path, mode=SessionMode.STREAM_ONLY)
    track = Track(title="First saved track", source=TrackSource.LOCAL, uri="/first.opus")

    async with app.run_test() as pilot:
        app._show_results([track])
        await pilot.press("s")
        assert isinstance(app.screen, PlaylistNameScreen)
        app.screen.query_one("#playlist-name-input", Input).value = "First playlist"
        await pilot.press("enter")

        playlist = app.session.named_playlists()[0]
        assert playlist.name == "First playlist"
        assert app.session.named_playlist_tracks(playlist.playlist_id) == [track]


async def test_named_playlist_tracks_reorder_remove_and_queue_actions(tmp_path: Path) -> None:
    app = make_app(tmp_path, mode=SessionMode.STREAM_ONLY)
    playlist = app.session.create_named_playlist("Ordered")
    tracks = [
        Track(title=f"Track {index}", source=TrackSource.LOCAL, uri=f"/{index}.opus")
        for index in range(3)
    ]
    for track in tracks:
        app.session.add_to_named_playlist(playlist.playlist_id, track)

    async with app.run_test() as pilot:
        app.query_one("#results", DataTable).focus()
        await pilot.press("p")
        await pilot.press("enter")
        table = app.query_one("#results", DataTable)

        table.move_cursor(row=2)
        await pilot.press("shift+up")
        assert app.session.named_playlist_tracks(playlist.playlist_id) == [
            tracks[0],
            tracks[2],
            tracks[1],
        ]

        await pilot.press("delete")
        assert app.session.named_playlist_tracks(playlist.playlist_id) == [
            tracks[0],
            tracks[1],
        ]

        await pilot.press("enter")
        table.move_cursor(row=0)
        await pilot.press("home")
        assert app.session.playlist.queue_list == [tracks[0], tracks[1]]

        table.move_cursor(row=1)
        await pilot.press("a")
        assert isinstance(app.screen, DuplicateQueueScreen)
        await pilot.click("#confirm-duplicate")
        assert app.session.playlist.queue_list == [tracks[0], tracks[1], tracks[1]]


async def test_named_playlists_remain_contained_when_resized(tmp_path: Path) -> None:
    app = make_app(tmp_path, mode=SessionMode.STREAM_ONLY)
    playlist = app.session.create_named_playlist(
        "🔥 A deliberately very long mobile playlist name with mixed عنوان characters"
    )
    track = Track(
        title="A very long playlist track 🚒🔥 with mixed عنوان characters",
        source=TrackSource.YOUTUBE,
        uri="https://youtube.com/watch?v=playlist-resize",
        duration_display="1:29:39",
    )
    app.session.add_to_named_playlist(playlist.playlist_id, track)

    async with app.run_test(size=(100, 30)) as pilot:
        app.query_one("#results", DataTable).focus()
        await pilot.press("p")
        table = app.query_one("#results", DataTable)

        await pilot.resize_terminal(60, 30)
        await pilot.pause()
        narrow_title = str(
            table.get_cell(f"playlist:{playlist.playlist_id}", "title")
        )
        assert "→" in narrow_title

        for width, height in ((120, 35), (55, 25), (200, 35)):
            await pilot.resize_terminal(width, height)
            await pilot.pause()
            assert sum(column.get_render_width(table) for column in table.ordered_columns) <= (
                table.size.width - 1
            )

        wide_title = str(table.get_cell(f"playlist:{playlist.playlist_id}", "title"))
        assert "→" not in wide_title

        await pilot.press("enter")
        assert table.get_cell(f"{track.track_id}:0", "time") == "1:29:39"
        assert sum(column.get_render_width(table) for column in table.ordered_columns) <= (
            table.size.width - 1
        )


async def test_history_and_named_playlist_show_cache_status(tmp_path: Path) -> None:
    app = make_app(tmp_path, mode=SessionMode.STREAM_ONLY)
    cached_file = tmp_path / "cached.opus"
    cached_file.write_bytes(b"audio")
    cached = Track(
        title="Offline",
        source=TrackSource.YOUTUBE,
        uri="https://youtube.com/watch?v=offline-status",
        cached_path=cached_file,
    )
    streaming = Track(
        title="Streaming",
        source=TrackSource.YOUTUBE,
        uri="https://youtube.com/watch?v=stream-status",
    )
    downloading = Track(
        title="Downloading",
        source=TrackSource.YOUTUBE,
        uri="https://youtube.com/watch?v=download-status",
    )
    app.session.state.record_play(streaming)
    app.session.state.record_play(cached)
    app.session.state.record_play(downloading)
    playlist = app.session.create_named_playlist("Status")
    app.session.add_to_named_playlist(playlist.playlist_id, cached)
    app.session.add_to_named_playlist(playlist.playlist_id, downloading)
    app.session.add_to_named_playlist(playlist.playlist_id, streaming)

    with patch.object(
        app.session.downloads,
        "is_active",
        side_effect=lambda uri: uri == downloading.uri,
    ):
        async with app.run_test() as pilot:
            app.query_one("#results", DataTable).focus()
            await pilot.press("h")
            table = app.query_one("#results", DataTable)
            assert table.get_cell(f"{downloading.track_id}:0", "status") == "↓"
            assert table.get_cell(f"{cached.track_id}:1", "status") == "✓"
            assert table.get_cell(f"{streaming.track_id}:2", "status") == "↗"
            assert [column.label.plain for column in table.ordered_columns][-1] == "●"
            assert table.ordered_columns[3].width == 6

            await pilot.press("escape", "p", "enter")
            assert table.get_cell(f"{cached.track_id}:0", "status") == "✓"
            assert table.get_cell(f"{downloading.track_id}:1", "status") == "↓"
            assert table.get_cell(f"{streaming.track_id}:2", "status") == "↗"
            assert sum(
                column.get_render_width(table) for column in table.ordered_columns
            ) <= (table.size.width - 1)


async def test_open_named_playlist_can_append_every_track_in_order(tmp_path: Path) -> None:
    app = make_app(tmp_path, mode=SessionMode.STREAM_ONLY)
    playlist = app.session.create_named_playlist("Whole album")
    first = Track(title="First", source=TrackSource.LOCAL, uri="/first.opus")
    second = Track(title="Second", source=TrackSource.LOCAL, uri="/second.opus")
    app.session.add_to_named_playlist(playlist.playlist_id, first)
    app.session.add_to_named_playlist(playlist.playlist_id, second)
    app.session.add_to_named_playlist(playlist.playlist_id, first)

    async with app.run_test() as pilot:
        app.query_one("#results", DataTable).focus()
        await pilot.press("p", "enter", "e")
        assert isinstance(app.screen, QueuePlaylistScreen)
        await pilot.press("escape")
        assert app.session.playlist.queue_list == []

        await pilot.press("e")
        await pilot.click("#confirm-queue-playlist")
        assert app.session.playlist.queue_list == [first, second, first]
        assert app.query_one("#queue", DataTable).row_count == 3


async def test_context_guide_follows_focused_pane_and_view(tmp_path: Path) -> None:
    app = make_app(tmp_path, mode=SessionMode.STREAM_ONLY)
    app.session.state.record_play(
        Track(title="Played", source=TrackSource.LOCAL, uri="/played.opus")
    )

    async with app.run_test() as pilot:
        results = app.query_one("#results", DataTable)
        results.focus()
        await pilot.pause()
        assert app.query_one("#results-pane").has_class("guide-visible")
        assert not app.query_one("#queue-pane").has_class("guide-visible")
        assert "Enter queue/open" in str(app.query_one("#results-guide").render())

        await pilot.press("tab")
        assert not app.query_one("#results-pane").has_class("guide-visible")
        assert app.query_one("#queue-pane").has_class("guide-visible")

        await pilot.press("tab", "h")
        assert "c clear" in str(app.query_one("#results-guide").render())

        await pilot.press("f2")
        assert "Ctrl+S save" in str(app.screen.query_one("#settings-guide").render())


async def test_playlist_deletion_keeps_nearest_row_selected(tmp_path: Path) -> None:
    app = make_app(tmp_path, mode=SessionMode.STREAM_ONLY)
    playlists = [
        app.session.create_named_playlist(name) for name in ("First", "Second", "Third")
    ]
    tracks = [
        Track(title=f"Track {index}", source=TrackSource.LOCAL, uri=f"/{index}.opus")
        for index in range(3)
    ]
    for track in tracks:
        app.session.add_to_named_playlist(playlists[2].playlist_id, track)

    async with app.run_test() as pilot:
        table = app.query_one("#results", DataTable)
        table.focus()
        await pilot.press("p")
        table.move_cursor(row=1)
        await pilot.press("delete")
        await pilot.click("#confirm-delete-playlist")
        assert table.cursor_row == 1
        selected = app._selected_named_playlist()
        assert selected is not None
        assert selected.playlist_id == playlists[2].playlist_id

        await pilot.press("enter")
        table.move_cursor(row=1)
        await pilot.press("delete")
        assert table.cursor_row == 1
        assert app._selected_named_playlist_track() == tracks[2]

        await pilot.press("delete")
        assert table.cursor_row == 0
        assert app._selected_named_playlist_track() == tracks[0]
