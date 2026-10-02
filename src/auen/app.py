"""Textual application shell for auen."""

from __future__ import annotations

import asyncio
import contextlib
import math
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, ClassVar

from rich.cells import cell_len, chop_cells
from textual import events, on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    OptionList,
    ProgressBar,
    Select,
    Static,
    Switch,
)
from textual.widgets.data_table import CellDoesNotExist

from auen.backends import detect_backend
from auen.config import AuenConfig
from auen.models import (
    CollectionKind,
    HistoryEntry,
    MediaCollection,
    PlaybackState,
    RepeatMode,
    SearchItem,
    SessionMode,
    Track,
)
from auen.session import AuenSession

_LOAD_MORE_KEY = "__load_more__"
_STATE_KEY = "__state__"

if TYPE_CHECKING:
    from collections.abc import Sequence

    from textual.binding import BindingType

    from auen.backends.base import AudioBackend


class SearchInput(Input):
    """Search field with conventional select-all behavior."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+a", "select_all", "Select all", show=False, priority=True),
        Binding("escape", "app.leave_search", "Leave search", show=False),
        *Input.BINDINGS,
    ]


class TrackTable(DataTable[object]):
    """Track table whose horizontal arrows page titles rather than scroll columns."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("shift+up", "priority_up", "Move up", show=False),
        Binding("shift+down", "priority_down", "Move down", show=False),
        Binding("escape", "back", "Back", show=False),
    ]

    class TitlePageRequested(Message):
        def __init__(self, table: TrackTable, delta: int) -> None:
            self.table = table
            self.delta = delta
            super().__init__()

    class ViewportResized(Message):
        def __init__(self, table: TrackTable) -> None:
            self.table = table
            super().__init__()

    class QueueMoveRequested(Message):
        def __init__(self, table: TrackTable, delta: int) -> None:
            self.table = table
            self.delta = delta
            super().__init__()

    class QueuePlayNextRequested(Message):
        def __init__(self, table: TrackTable) -> None:
            self.table = table
            super().__init__()

    class ResultsBackRequested(Message):
        pass

    def action_cursor_left(self) -> None:
        self.post_message(self.TitlePageRequested(self, -1))

    def action_cursor_right(self) -> None:
        self.post_message(self.TitlePageRequested(self, 1))

    def on_resize(self, _event: events.Resize) -> None:
        self.post_message(self.ViewportResized(self))

    def action_priority_up(self) -> None:
        if self.id == "queue":
            self.post_message(self.QueueMoveRequested(self, -1))
        else:
            self.action_cursor_up()

    def action_priority_down(self) -> None:
        if self.id == "queue":
            self.post_message(self.QueueMoveRequested(self, 1))
        else:
            self.action_cursor_down()

    def action_scroll_home(self) -> None:
        if self.id == "queue" or self.has_class("history-view"):
            self.post_message(self.QueuePlayNextRequested(self))
        else:
            super().action_scroll_home()

    def action_back(self) -> None:
        self.post_message(self.ResultsBackRequested())


@dataclass(slots=True)
class ResultsViewState:
    items: list[SearchItem]
    heading: str
    cursor_row: int
    query: str | None
    limit: int
    has_more: bool
    history_entries: list[HistoryEntry] | None


class SessionModeScreen(ModalScreen[SessionMode]):
    """Ask how remote media should be handled for this session."""

    CSS = """
    SessionModeScreen {
        align: center middle;
        background: $background 70%;
    }
    #session-dialog {
        width: 64;
        height: auto;
        padding: 1 2;
        border: round $accent;
        background: $surface;
    }
    SessionModeScreen.termux-safe #session-dialog {
        border: ascii $accent;
    }
    #session-dialog Button {
        width: 1fr;
        margin-top: 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="session-dialog"):
            yield Label("Choose playback behavior", classes="dialog-title")
            yield Static(
                "Stream directly without retaining media, or keep a managed copy "
                "for later offline playback. You can change this during the session."
            )
            with Horizontal():
                yield Button("Stream only", id="stream-only")
                yield Button("Stream + cache", id="stream-cache", variant="primary")

    def on_mount(self) -> None:
        self.set_class(_is_termux_environment(), "termux-safe")

    @on(Button.Pressed)
    def select_mode(self, event: Button.Pressed) -> None:
        if event.button.id == "stream-only":
            self.dismiss(SessionMode.STREAM_ONLY)
        elif event.button.id == "stream-cache":
            self.dismiss(SessionMode.STREAM_AND_CACHE)


class DuplicateQueueScreen(ModalScreen[bool]):
    """Confirm intentionally adding another occurrence of a queued track."""

    BINDINGS: ClassVar[list[BindingType]] = [("escape", "cancel", "Cancel")]

    CSS = """
    DuplicateQueueScreen {
        align: center middle;
        background: $background 70%;
    }
    #duplicate-dialog {
        width: 64;
        height: auto;
        padding: 1 2;
        border: round $warning;
        background: $surface;
    }
    #duplicate-actions {
        height: auto;
        margin-top: 1;
        align-horizontal: right;
    }
    #duplicate-actions Button {
        margin-left: 1;
    }
    DuplicateQueueScreen.termux-safe #duplicate-dialog {
        border: ascii $warning;
    }
    """

    def __init__(self, track: Track) -> None:
        super().__init__()
        self.track = track

    def compose(self) -> ComposeResult:
        with Vertical(id="duplicate-dialog"):
            yield Label("Already in queue", classes="dialog-title")
            yield Static(f"“{self.track.title}” is already queued. Add it again?")
            with Horizontal(id="duplicate-actions"):
                yield Button("Cancel", id="cancel-duplicate", variant="default")
                yield Button("Add again", id="confirm-duplicate", variant="warning")

    def on_mount(self) -> None:
        self.set_class(_is_termux_environment(), "termux-safe")
        self.query_one("#cancel-duplicate", Button).focus()

    @on(Button.Pressed, "#cancel-duplicate")
    def cancel_pressed(self) -> None:
        self.dismiss(False)

    @on(Button.Pressed, "#confirm-duplicate")
    def confirm_pressed(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class LoadMoreScreen(ModalScreen[bool]):
    """Confirm the only interaction that fetches another search page."""

    BINDINGS: ClassVar[list[BindingType]] = [("escape", "cancel", "Cancel")]

    CSS = """
    LoadMoreScreen {
        align: center middle;
        background: $background 70%;
    }
    #load-more-dialog {
        width: 56;
        height: auto;
        padding: 1 2;
        border: round $accent;
        background: $surface;
    }
    #load-more-actions {
        height: auto;
        margin-top: 1;
        align-horizontal: right;
    }
    #load-more-actions Button {
        margin-left: 1;
    }
    LoadMoreScreen.termux-safe #load-more-dialog {
        border: ascii $accent;
    }
    """

    def __init__(self, count: int) -> None:
        super().__init__()
        self.count = count

    def compose(self) -> ComposeResult:
        with Vertical(id="load-more-dialog"):
            yield Label("Load more results?", classes="dialog-title")
            yield Static(f"Fetch up to {self.count} additional YouTube results?")
            with Horizontal(id="load-more-actions"):
                yield Button("Cancel", id="cancel-load-more")
                yield Button("Load more", id="confirm-load-more", variant="primary")

    def on_mount(self) -> None:
        self.set_class(_is_termux_environment(), "termux-safe")
        self.query_one("#cancel-load-more", Button).focus()

    @on(Button.Pressed, "#cancel-load-more")
    def cancel_pressed(self) -> None:
        self.dismiss(False)

    @on(Button.Pressed, "#confirm-load-more")
    def confirm_pressed(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class ClearHistoryScreen(ModalScreen[bool]):
    """Confirm removal of the entire recently played history."""

    BINDINGS: ClassVar[list[BindingType]] = [("escape", "cancel", "Cancel")]

    CSS = """
    ClearHistoryScreen {
        align: center middle;
        background: $background 70%;
    }
    #clear-history-dialog {
        width: 56;
        height: auto;
        padding: 1 2;
        border: round $warning;
        background: $surface;
    }
    #clear-history-actions {
        height: auto;
        margin-top: 1;
        align-horizontal: right;
    }
    #clear-history-actions Button {
        margin-left: 1;
    }
    ClearHistoryScreen.termux-safe #clear-history-dialog {
        border: ascii $warning;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="clear-history-dialog"):
            yield Label("Clear recently played?", classes="dialog-title")
            yield Static("This removes play counts and timestamps, but keeps queued tracks.")
            with Horizontal(id="clear-history-actions"):
                yield Button("Cancel", id="cancel-clear-history")
                yield Button("Clear history", id="confirm-clear-history", variant="warning")

    def on_mount(self) -> None:
        self.set_class(_is_termux_environment(), "termux-safe")
        self.query_one("#cancel-clear-history", Button).focus()

    @on(Button.Pressed, "#cancel-clear-history")
    def cancel_pressed(self) -> None:
        self.dismiss(False)

    @on(Button.Pressed, "#confirm-clear-history")
    def confirm_pressed(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class ThemeScreen(ModalScreen[str | None]):
    """Preview installed Textual themes and save only explicit selection."""

    BINDINGS: ClassVar[list[BindingType]] = [("escape", "cancel", "Restore theme")]

    CSS = """
    ThemeScreen {
        align: center middle;
        background: $background 70%;
    }
    #theme-dialog {
        width: 54;
        height: 80%;
        padding: 1 2;
        border: round $accent;
        background: $surface;
    }
    #theme-help {
        height: 2;
        color: $text-muted;
    }
    #theme-list {
        height: 1fr;
    }
    ThemeScreen.termux-safe #theme-dialog {
        border: ascii $accent;
    }
    ThemeScreen.termux-safe #theme-list {
        border: none;
    }
    """

    def __init__(self, config: AuenConfig, themes: list[str]) -> None:
        super().__init__()
        self.config = config
        self.themes = themes
        self.original_theme = config.theme

    def compose(self) -> ComposeResult:
        with Vertical(id="theme-dialog"):
            yield Label("Theme preview", classes="dialog-title")
            yield Static("↑/↓ preview  ·  Enter save  ·  Esc restore", id="theme-help")
            yield OptionList(*self.themes, id="theme-list")

    def on_mount(self) -> None:
        self.set_class(_is_termux_environment(), "termux-safe")
        options = self.query_one("#theme-list", OptionList)
        if self.original_theme in self.themes:
            options.highlighted = self.themes.index(self.original_theme)
        options.focus()

    @on(OptionList.OptionHighlighted, "#theme-list")
    def preview_theme(self, event: OptionList.OptionHighlighted) -> None:
        self.app.theme = self.themes[event.option_index]

    @on(OptionList.OptionSelected, "#theme-list")
    def save_theme(self, event: OptionList.OptionSelected) -> None:
        selected = self.themes[event.option_index]
        self.config.theme = selected
        try:
            self.config.save()
        except (OSError, ValueError) as exc:
            self.notify(str(exc), title="Theme not saved", severity="error")
            return
        self.dismiss(selected)

    def action_cancel(self) -> None:
        self.app.theme = self.original_theme
        self.dismiss(None)


class SeekScreen(ModalScreen[float | None]):
    """Prompt for an absolute playback position."""

    BINDINGS: ClassVar[list[BindingType]] = [("escape", "cancel", "Cancel")]

    CSS = """
    SeekScreen {
        align: center middle;
        background: $background 70%;
    }
    #seek-dialog {
        width: 54;
        height: auto;
        padding: 1 2;
        border: round $accent;
        background: $surface;
    }
    #seek-time {
        margin-top: 1;
    }
    SeekScreen.termux-safe #seek-dialog {
        border: ascii $accent;
    }
    """

    def __init__(self, duration_seconds: float | None) -> None:
        super().__init__()
        self.duration_seconds = duration_seconds

    def compose(self) -> ComposeResult:
        limit = (
            f" Track length: {_format_timestamp(self.duration_seconds)}."
            if self.duration_seconds is not None
            else ""
        )
        with Vertical(id="seek-dialog"):
            yield Label("Go to time", classes="dialog-title")
            yield Static(f"Enter seconds, mm:ss, or hh:mm:ss.{limit}")
            yield Input(placeholder="Example: 90 or 1:30", id="seek-time")

    def on_mount(self) -> None:
        self.set_class(_is_termux_environment(), "termux-safe")
        self.query_one("#seek-time", Input).focus()

    @on(Input.Submitted, "#seek-time")
    def submit_time(self, event: Input.Submitted) -> None:
        try:
            seconds = _parse_timestamp(event.value)
        except ValueError as exc:
            self.notify(str(exc), title="Invalid time", severity="error")
            return
        if self.duration_seconds is not None and seconds > self.duration_seconds:
            self.notify("Time is past the end of this track", severity="error")
            return
        self.dismiss(seconds)

    def action_cancel(self) -> None:
        self.dismiss(None)


class SettingsScreen(Screen[bool]):
    """Keyboard-friendly settings editor shared with the CLI configuration."""

    BINDINGS: ClassVar[list[BindingType]] = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+s", "save", "Save"),
    ]

    CSS = """
    SettingsScreen {
        layout: vertical;
    }
    #settings-title {
        padding: 1 2;
        text-style: bold;
        background: $panel;
    }
    #settings-form {
        padding: 1 2;
    }
    .setting-row {
        height: auto;
        min-height: 3;
        margin-bottom: 1;
    }
    .setting-row Label {
        width: 28;
        padding-top: 1;
    }
    .setting-row Input, .setting-row Select {
        width: 1fr;
    }
    .setting-row Switch {
        width: auto;
        margin-top: 1;
    }
    #settings-actions {
        height: auto;
        dock: bottom;
        padding: 1 2;
        align-horizontal: right;
        background: $panel;
    }
    #settings-actions Button {
        margin-left: 1;
    }
    """

    def __init__(self, config: AuenConfig) -> None:
        super().__init__()
        self.config = config

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("Settings", id="settings-title")
        with VerticalScroll(id="settings-form"):
            with Horizontal(classes="setting-row"):
                yield Label("Playback backend")
                backend_options = [("Automatic (mpv preferred)", "auto"), ("mpv", "mpv")]
                if not (_is_termux_environment() and shutil.which("mpv")):
                    backend_options.append(("Termux:API fallback (no seek)", "termux"))
                yield Select(
                    backend_options,
                    value=self.config.backend,
                    id="backend",
                )
            with Horizontal(classes="setting-row"):
                yield Label("Session startup behavior")
                yield Select(
                    [
                        ("Ask every session", SessionMode.ASK.value),
                        ("Stream only", SessionMode.STREAM_ONLY.value),
                        ("Stream and cache", SessionMode.STREAM_AND_CACHE.value),
                    ],
                    value=self.config.session_mode,
                    id="session-mode",
                )
            with Horizontal(classes="setting-row"):
                yield Label("Repeat")
                yield Select(
                    [
                        ("Off", RepeatMode.OFF.value),
                        ("All", RepeatMode.ALL.value),
                        ("One", RepeatMode.ONE.value),
                    ],
                    value=self.config.repeat_mode,
                    id="repeat-mode",
                )
            yield from self._input_row("Volume (0-100)", "volume", str(self.config.volume))
            yield from self._input_row(
                "Load more amount", "search-results", str(self.config.search_result_count)
            )
            yield from self._input_row(
                "Recently played limit", "history-limit", str(self.config.history_limit)
            )
            yield from self._input_row(
                "Cache limit (MiB)",
                "cache-limit",
                str(self.config.cache_max_bytes // 1024**2),
            )
            yield from self._input_row(
                "Concurrent downloads",
                "download-workers",
                str(self.config.max_download_threads),
            )
            yield from self._switch_row("Shuffle by default", "shuffle", self.config.shuffle)
            yield from self._switch_row(
                "Restore interrupted session", "restore-session", self.config.restore_session
            )
            yield from self._switch_row(
                "Scan folders recursively", "scan-recursive", self.config.scan_recursive
            )
        with Horizontal(id="settings-actions"):
            yield Button("Cancel", id="cancel")
            yield Button("Save", id="save", variant="primary")

    @staticmethod
    def _input_row(label: str, widget_id: str, value: str) -> ComposeResult:
        with Horizontal(classes="setting-row"):
            yield Label(label)
            yield Input(value=value, id=widget_id)

    @staticmethod
    def _switch_row(label: str, widget_id: str, value: bool) -> ComposeResult:
        with Horizontal(classes="setting-row"):
            yield Label(label)
            yield Switch(value=value, id=widget_id)

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_save(self) -> None:
        try:
            self._apply_form()
            path = self.config.save()
        except (OSError, ValueError) as exc:
            self.notify(str(exc), title="Settings not saved", severity="error")
            return

        self.notify(f"Saved to {path}", title="Settings saved")
        self.dismiss(True)

    @on(Button.Pressed, "#cancel")
    def cancel_pressed(self) -> None:
        self.action_cancel()

    @on(Button.Pressed, "#save")
    def save_pressed(self) -> None:
        self.action_save()

    def _apply_form(self) -> None:
        self.config.backend = str(self.query_one("#backend", Select).value)
        self.config.session_mode = str(self.query_one("#session-mode", Select).value)
        self.config.repeat_mode = str(self.query_one("#repeat-mode", Select).value)
        self.config.volume = self._integer_value("#volume", "volume")
        self.config.search_result_count = self._integer_value(
            "#search-results", "load more amount"
        )
        self.config.history_limit = self._integer_value(
            "#history-limit", "recently played limit"
        )
        cache_mebibytes = self._integer_value("#cache-limit", "cache limit")
        self.config.cache_max_bytes = cache_mebibytes * 1024**2
        self.config.max_download_threads = self._integer_value(
            "#download-workers", "concurrent downloads"
        )
        self.config.shuffle = self.query_one("#shuffle", Switch).value
        self.config.restore_session = self.query_one("#restore-session", Switch).value
        self.config.scan_recursive = self.query_one("#scan-recursive", Switch).value
        self.config.validate()

    def _integer_value(self, selector: str, label: str) -> int:
        raw = self.query_one(selector, Input).value
        try:
            return int(raw)
        except ValueError as exc:
            raise ValueError(f"{label} must be a whole number") from exc


class AuenApp(App[None]):
    """Main auen terminal application."""

    TITLE = "auen"
    SUB_TITLE = "terminal audio"
    NARROW_BREAKPOINT = 88
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("/", "focus_search", "⌕ Search"),
        Binding("space", "toggle_playback", "▶/Ⅱ Play", show=False),
        Binding("n", "next_track", "» Next", show=False),
        Binding("[", "seek_backward", "← 10s", show=False),
        Binding("]", "seek_forward", "10s →", show=False),
        Binding("g", "go_to_time", "↪ Time", show=False),
        Binding("h", "show_history", "◷ History"),
        Binding("a", "enqueue_history", "Add history track", show=False),
        Binding("c", "clear_history", "Clear history", show=False),
        Binding("d", "download_selected", "↓ Offline"),
        Binding("delete", "remove_queued", "Del Remove"),
        Binding("f2", "settings", "⚙ Settings"),
        Binding("f3", "change_theme", "◐ Theme"),
        Binding("q", "quit", "q Quit"),
    ]

    CSS = """
    #search-bar {
        dock: top;
        margin: 1 2 0 2;
    }
    #workspace {
        height: 1fr;
        margin: 1 2;
    }
    .pane {
        width: 1fr;
        height: 1fr;
        border: round $panel-lighten-2;
        padding: 1;
    }
    #queue-pane {
        margin-left: 1;
    }
    #workspace.narrow {
        layout: vertical;
        margin: 0 1;
    }
    #workspace.narrow .pane {
        width: 1fr;
        height: 1fr;
        padding: 0 1;
    }
    #workspace.narrow .pane-title {
        margin-bottom: 0;
    }
    #workspace.narrow #queue-pane {
        margin-left: 0;
        margin-top: 0;
    }
    Screen.termux-safe .pane {
        border: ascii $panel-lighten-2;
    }
    .pane-title {
        text-style: bold;
        margin-bottom: 1;
        color: $accent;
    }
    DataTable {
        height: 1fr;
        background: $surface;
    }
    #playback-status {
        dock: bottom;
        height: 5;
        padding: 0 2;
        background: $panel;
    }
    #now-playing {
        height: 2;
        padding-top: 1;
    }
    #progress-row {
        height: 1;
    }
    #playback-progress {
        width: 1fr;
        height: 1;
    }
    #playback-time {
        width: 18;
        height: 1;
        text-align: right;
    }
    #playback-controls {
        height: 1;
        align-horizontal: center;
    }
    .playback-control {
        width: 1fr;
        min-width: 7;
        height: 1;
        border: none;
        padding: 0 1;
        color: $text-muted;
        background: transparent;
    }
    .playback-control:focus, .playback-control:hover {
        color: $text;
        background: $boost;
        text-style: bold;
    }
    """

    def __init__(
        self,
        config: AuenConfig | None = None,
        *,
        session: AuenSession | None = None,
        backend: AudioBackend | None = None,
        backend_error: str | None = None,
    ) -> None:
        super().__init__()
        self.config = config or AuenConfig.load()
        if self.config.theme in self.available_themes:
            self.theme = self.config.theme
        else:
            self.config.theme = self.theme
        self.session = session or AuenSession(self.config)
        self.backend = backend
        self.backend_error = backend_error
        self.session.on_track_changed = self._playback_track_changed
        self.session.on_history_changed = self._playback_history_changed
        self.session.on_playback_error = self._playback_failed
        self.current_session_mode = SessionMode(self.config.session_mode)
        self.search_results: dict[str, SearchItem] = {}
        self._result_order: list[SearchItem] = []
        self._results_heading = "Results"
        self._showing_history = False
        self._history_entries: list[HistoryEntry] = []
        self._history_return: ResultsViewState | None = None
        self._results_parent: ResultsViewState | None = None
        self._search_restore: ResultsViewState | None = None
        self._active_query: str | None = None
        self._search_limit = 0
        self._search_has_more = False
        self._search_generation = 0
        self._search_loading = False
        self._title_pages: dict[tuple[str, str], int] = {}
        self._last_saved_position = 0.0
        self._settings_backend_before = self.config.backend
        self._settings_mode_before = self.config.session_mode
        self._settings_volume_before = self.config.volume

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield SearchInput(placeholder="Search YouTube or paste a YouTube URL…", id="search-bar")
        with Horizontal(id="workspace"):
            with Vertical(classes="pane", id="results-pane"):
                yield Label("⌕ Results · 0", classes="pane-title", id="results-title")
                yield TrackTable(id="results", cursor_type="row")
            with Vertical(classes="pane", id="queue-pane"):
                yield Label("≡ Queue · 0", classes="pane-title", id="queue-title")
                yield TrackTable(id="queue", cursor_type="row")
        with Vertical(id="playback-status"):
            yield Static("○ Nothing playing", id="now-playing")
            with Horizontal(id="progress-row"):
                yield ProgressBar(
                    total=1,
                    show_percentage=False,
                    show_eta=False,
                    id="playback-progress",
                )
                yield Static("0:00 / --:--", id="playback-time")
            with Horizontal(id="playback-controls"):
                yield Button("← 10s  [", id="seek-back", classes="playback-control", compact=True)
                yield Button(
                    "␣ Play/Pause", id="play-pause", classes="playback-control", compact=True
                )
                yield Button(
                    "10s →  ]", id="seek-forward", classes="playback-control", compact=True
                )
                yield Button("↪ Jump  g", id="jump-time", classes="playback-control", compact=True)
                yield Button(
                    "» Next  n", id="next-track", classes="playback-control", compact=True
                )
        yield Footer()

    def on_mount(self) -> None:
        self.screen.set_class(_is_termux_environment(), "termux-safe")
        self._apply_responsive_layout(self.size.width)
        results = self.query_one("#results", DataTable)
        results.cell_padding = 0
        self._configure_results_columns(history=False)
        results.zebra_stripes = True
        queue = self.query_one("#queue", DataTable)
        queue.cell_padding = 0
        queue.add_column("#", width=3, key="position")
        queue.add_column("Title", width=10, key="title")
        queue.add_column("Time", width=7, key="time")
        queue.add_column("●", width=1, key="status")
        queue.zebra_stripes = True
        self.call_after_refresh(self._sync_table_widths)
        self._refresh_queue()
        self.set_interval(0.5, self._refresh_playback_status)
        if self.current_session_mode is SessionMode.ASK:
            self.push_screen(SessionModeScreen(), self._session_mode_selected)
        else:
            self._start_player()
        if self.backend_error is not None:
            self.notify(self.backend_error, title="Playback unavailable", severity="warning")

    def on_resize(self, event: events.Resize) -> None:
        self._apply_responsive_layout(event.size.width)
        self.call_after_refresh(self._sync_table_widths)

    def _apply_responsive_layout(self, width: int) -> None:
        workspace = self.query_one("#workspace", Horizontal)
        narrow = width < self.NARROW_BREAKPOINT
        workspace.set_class(narrow, "narrow")
        labels = (
            {
                "#seek-back": "-10s [",
                "#play-pause": "Play/Pause",
                "#seek-forward": "+10s ]",
                "#jump-time": "Jump g",
                "#next-track": "Next n",
            }
            if narrow or _is_termux_environment()
            else {
                "#seek-back": "← 10s  [",
                "#play-pause": "␣ Play/Pause",
                "#seek-forward": "10s →  ]",
                "#jump-time": "↪ Jump  g",
                "#next-track": "» Next  n",
            }
        )
        for selector, label in labels.items():
            self.query_one(selector, Button).label = label

    def on_unmount(self) -> None:
        with contextlib.suppress(Exception):
            self.session.close()

    @on(Input.Submitted, "#search-bar")
    def search_submitted(self, event: Input.Submitted) -> None:
        query = event.value.strip()
        if not query:
            return
        self._search_restore = self._capture_results_state()
        self._history_return = None
        self._results_parent = None
        self._active_query = query
        self._search_limit = self._initial_search_limit()
        self._search_generation += 1
        self._search_loading = True
        self._show_search_state("Searching…")
        self.search_media(query, self._search_limit, self._search_generation)

    @on(TrackTable.TitlePageRequested)
    def title_page_requested(self, event: TrackTable.TitlePageRequested) -> None:
        self._shift_title(event.table, event.delta)

    @on(TrackTable.ViewportResized)
    def table_viewport_resized(self, event: TrackTable.ViewportResized) -> None:
        self._sync_table_width(event.table)

    @on(TrackTable.QueueMoveRequested)
    def queue_move_requested(self, event: TrackTable.QueueMoveRequested) -> None:
        new_row = self.session.move_queued(event.table.cursor_row, event.delta)
        if new_row is None:
            return
        self._refresh_queue()
        event.table.move_cursor(row=new_row)

    @on(TrackTable.QueuePlayNextRequested)
    def queue_play_next_requested(self, event: TrackTable.QueuePlayNextRequested) -> None:
        if event.table.id == "results" and self._showing_history:
            entry = self._selected_history_entry()
            if entry is not None:
                self._request_history_queue(entry.track, play_now=False, append=False)
            return
        track = self.session.prioritize_queued(event.table.cursor_row)
        if track is None:
            return
        self._refresh_queue()
        event.table.move_cursor(row=0)
        self.notify(track.title, title="Playing next")

    @on(TrackTable.ResultsBackRequested)
    def results_back_requested(self) -> None:
        if self._showing_history:
            self._leave_history()
            return
        if self._results_parent is None:
            return
        self._search_generation += 1
        self._search_loading = False
        parent = self._results_parent
        self._results_parent = None
        self._restore_results_state(parent)

    @on(events.DescendantBlur)
    def reset_title_after_table_blur(self, event: events.DescendantBlur) -> None:
        if isinstance(event.widget, TrackTable):
            self._reset_title_pages(event.widget)

    @on(DataTable.RowHighlighted)
    def reset_title_after_row_change(self, event: DataTable.RowHighlighted) -> None:
        if isinstance(event.data_table, TrackTable):
            self._reset_title_pages(event.data_table)

    @work(exclusive=True, group="youtube-search")
    async def search_media(
        self,
        query: str,
        limit: int,
        generation: int,
        *,
        previous_count: int = 0,
        cursor_row: int = 0,
        existing_items: Sequence[SearchItem] = (),
        max_display_count: int | None = None,
    ) -> None:
        try:
            items = await asyncio.wrap_future(self.session.submit_search(query, limit=limit))
        except (OSError, RuntimeError, ValueError) as exc:
            if generation != self._search_generation:
                return
            self._search_loading = False
            if previous_count:
                self.query_one("#results-title", Label).update(f"⌕ Results · {previous_count}")
            else:
                self._show_search_state("Search failed — press / to try again")
            self.notify(str(exc), title="Search failed", severity="error")
            return
        if generation != self._search_generation:
            return
        self._search_loading = False
        self._search_restore = None
        self._search_limit = limit
        if previous_count:
            # The user may continue navigating while the network request is
            # running. Preserve the row selected at render time, rather than
            # the row that was selected when Load more was confirmed.
            cursor_row = self.query_one("#results", DataTable).cursor_row
        displayed_items = _merge_search_items(
            existing_items,
            items,
            max_items=max_display_count,
        )
        grew = len(displayed_items) > previous_count
        self._search_has_more = grew and len(items) >= limit and limit < 100
        self._show_results(
            displayed_items,
            has_more=self._search_has_more,
            cursor_row=cursor_row,
        )

    def _show_results(
        self,
        items: Sequence[SearchItem],
        *,
        heading: str = "Results",
        has_more: bool = False,
        cursor_row: int = 0,
    ) -> None:
        table = self.query_one("#results", DataTable)
        self._configure_results_columns(history=False)
        table.clear()
        self._showing_history = False
        self._history_entries = []
        self._title_pages = {
            key: page for key, page in self._title_pages.items() if key[0] != "results"
        }
        self._result_order = list(items)
        self._results_heading = heading
        self.search_results = {
            _result_row_key(item, position): item for position, item in enumerate(items)
        }
        title_width = self._table_title_width(table)
        for position, item in enumerate(items):
            table.add_row(
                _title_cell(_result_title(item), title_width, 0)[0],
                _result_detail(item),
                key=_result_row_key(item, position),
            )
        if has_more:
            table.add_row("Load more…", "Enter", key=_LOAD_MORE_KEY)
        self.query_one("#results-title", Label).update(f"⌕ {heading} · {len(items)}")
        self._sync_table_width(table)
        if not items:
            table.add_row("No matching videos found", "", key=_STATE_KEY)
            self.query_one("#queue", DataTable).focus()
        else:
            table.focus()
            table.move_cursor(row=min(max(0, cursor_row), table.row_count - 1))

    def _show_history(
        self,
        entries: Sequence[HistoryEntry] | None = None,
        *,
        cursor_row: int = 0,
    ) -> None:
        history = list(self.session.recent_history() if entries is None else entries)
        table = self.query_one("#results", DataTable)
        self._configure_results_columns(history=True)
        table.clear()
        self._title_pages = {
            key: page for key, page in self._title_pages.items() if key[0] != "results"
        }
        self._showing_history = True
        self._history_entries = history
        self._result_order = [entry.track for entry in history]
        self._results_heading = "History"
        self.search_results = {
            _result_row_key(entry.track, position): entry.track
            for position, entry in enumerate(history)
        }
        self._active_query = None
        self._search_limit = 0
        self._search_has_more = False
        title_width = self._table_title_width(table)
        for position, entry in enumerate(history):
            table.add_row(
                _title_cell(entry.track.title, title_width, 0)[0],
                entry.track.duration_display or "-",
                _history_time(entry.last_played_at),
                str(entry.play_count),
                key=_result_row_key(entry.track, position),
            )
        self.query_one("#results-title", Label).update(f"◷ History · {len(history)}")
        if not history:
            table.add_row("No recently played tracks", "", "", "", key=_STATE_KEY)
        table.add_class("history-view")
        self._sync_table_width(table)
        table.focus()
        table.move_cursor(row=min(max(0, cursor_row), table.row_count - 1))

    def _configure_results_columns(self, *, history: bool) -> None:
        table = self.query_one("#results", DataTable)
        wanted = 4 if history else 2
        if len(table.ordered_columns) == wanted:
            table.set_class(history, "history-view")
            return
        table.clear(columns=True)
        table.add_column("Title", width=10, key="title")
        table.add_column("Time", width=7, key="time")
        if history:
            table.add_column("Last", width=10, key="last")
            table.add_column("Plays", width=5, key="plays")
        table.set_class(history, "history-view")

    @on(DataTable.RowSelected, "#results")
    def result_selected(self, event: DataTable.RowSelected) -> None:
        if self._showing_history:
            entry = self._selected_history_entry()
            if entry is not None:
                self._request_history_queue(entry.track, play_now=True, append=False)
            return
        if str(event.row_key.value) == _LOAD_MORE_KEY:
            self.push_screen(
                LoadMoreScreen(self.config.search_result_count),
                self._load_more_decided,
            )
            return
        item = self.search_results.get(str(event.row_key.value))
        if item is None:
            return
        if isinstance(item, MediaCollection):
            parent = self._capture_results_state()
            self._results_parent = parent
            self._search_generation += 1
            generation = self._search_generation
            self._search_loading = True
            self.query_one("#results-title", Label).update(f"⌕ Opening {item.title}…")
            self.open_collection(item, parent, generation)
            return
        track = item
        if any(queued.uri == track.uri for queued in self.session.playlist.queue_list):
            self.push_screen(
                DuplicateQueueScreen(track),
                lambda confirmed: self._duplicate_queue_decided(track, confirmed),
            )
            return
        self._enqueue_track(track)

    @work(exclusive=True, group="youtube-search")
    async def open_collection(
        self,
        collection: MediaCollection,
        parent: ResultsViewState,
        generation: int,
    ) -> None:
        try:
            tracks = await asyncio.wrap_future(self.session.submit_collection(collection))
        except (OSError, RuntimeError, ValueError) as exc:
            if generation != self._search_generation:
                return
            self._search_loading = False
            self._results_parent = None
            self._restore_results_state(parent)
            self.notify(str(exc), title="Could not open collection", severity="error")
            return
        if generation != self._search_generation:
            return
        self._search_loading = False
        self._active_query = None
        self._search_limit = 0
        self._search_has_more = False
        symbol = "◉" if collection.kind is CollectionKind.ALBUM else "≡"
        self._show_results(tracks, heading=f"{symbol} {collection.title}")

    def _load_more_decided(self, confirmed: bool | None) -> None:
        if not confirmed or self._active_query is None or not self._search_has_more:
            return
        previous_count = len(self._result_order)
        new_limit = min(100, self._search_limit + self.config.search_result_count)
        if new_limit <= self._search_limit:
            return
        cursor_row = self.query_one("#results", DataTable).cursor_row
        self._search_generation += 1
        self._search_loading = True
        self.query_one("#results-title", Label).update(f"⌕ Loading more… · {previous_count}")
        self.search_media(
            self._active_query,
            new_limit,
            self._search_generation,
            previous_count=previous_count,
            cursor_row=cursor_row,
            existing_items=tuple(self._result_order),
            max_display_count=previous_count + self.config.search_result_count,
        )

    def _capture_results_state(self) -> ResultsViewState:
        table = self.query_one("#results", DataTable)
        return ResultsViewState(
            items=list(self._result_order),
            heading=self._results_heading,
            cursor_row=max(0, table.cursor_row),
            query=self._active_query,
            limit=self._search_limit,
            has_more=self._search_has_more,
            history_entries=list(self._history_entries) if self._showing_history else None,
        )

    def _restore_results_state(self, state: ResultsViewState) -> None:
        if state.history_entries is not None:
            self._show_history(state.history_entries, cursor_row=state.cursor_row)
            return
        self._active_query = state.query
        self._search_limit = state.limit
        self._search_has_more = state.has_more
        self._show_results(
            state.items,
            heading=state.heading,
            has_more=state.has_more,
            cursor_row=state.cursor_row,
        )

    def _initial_search_limit(self) -> int:
        table = self.query_one("#results", DataTable)
        return min(50, max(1, table.size.height - 1))

    def _show_search_state(self, message: str) -> None:
        table = self.query_one("#results", DataTable)
        self._configure_results_columns(history=False)
        table.clear()
        self._showing_history = False
        self._history_entries = []
        self._result_order = []
        self.search_results = {}
        self._results_heading = "Results"
        table.add_row(message, "", key=_STATE_KEY)
        self.query_one("#results-title", Label).update("⌕ Results")
        self._sync_table_width(table)

    def _duplicate_queue_decided(self, track: Track, confirmed: bool | None) -> None:
        if confirmed:
            self._enqueue_track(track)

    def _enqueue_track(self, track: Track) -> None:
        future = self.session.enqueue(track, session_mode=self.current_session_mode)
        self._refresh_queue()
        self.notify(track.title, title="Added to queue")
        if future is not None:
            future.add_done_callback(self._download_finished)

    def _request_history_queue(self, track: Track, *, play_now: bool, append: bool) -> None:
        if any(queued.uri == track.uri for queued in self.session.playlist.queue_list):
            self.push_screen(
                DuplicateQueueScreen(track),
                lambda confirmed: self._history_duplicate_decided(
                    track, play_now, append, confirmed
                ),
            )
            return
        self._queue_history_track(track, play_now=play_now, append=append)

    def _history_duplicate_decided(
        self,
        track: Track,
        play_now: bool,
        append: bool,
        confirmed: bool | None,
    ) -> None:
        if confirmed:
            self._queue_history_track(track, play_now=play_now, append=append)

    def _queue_history_track(self, track: Track, *, play_now: bool, append: bool) -> None:
        if append:
            future = self.session.enqueue(track, session_mode=self.current_session_mode)
        else:
            future = self.session.enqueue_next(track, session_mode=self.current_session_mode)
        if play_now and self.session.player is not None and self.session.current_track is not None:
            self.session.player.skip()
        self._refresh_queue()
        title = "Added to queue" if append else "Playing now" if play_now else "Playing next"
        self.notify(track.title, title=title)
        if future is not None:
            future.add_done_callback(self._download_finished)

    @on(DataTable.RowSelected, "#queue")
    def queue_selected(self, event: DataTable.RowSelected) -> None:
        row = event.cursor_row
        was_playing = self.session.current_track is not None
        track = self.session.play_queued_now(row)
        if track is None:
            return
        self._refresh_queue()
        self.notify(
            track.title,
            title="Playing now" if was_playing else "Moved to front",
        )

    def _refresh_queue(self) -> None:
        table = self.query_one("#queue", DataTable)
        table.clear()
        self._title_pages = {
            key: page for key, page in self._title_pages.items() if key[0] != "queue"
        }
        title_width = self._table_title_width(table)
        for position, track in enumerate(self.session.playlist.queue_list):
            if track.is_cached:
                availability = "✓"
            elif self.session.downloads.is_active(track.uri):
                availability = "↓"
            else:
                availability = "↗"
            table.add_row(
                str(position + 1),
                _title_cell(track.title, title_width, 0)[0],
                track.duration_display or "-",
                availability,
                key=f"{track.track_id}:{position}",
            )
        self.query_one("#queue-title", Label).update(
            f"≡ Queue · {self.session.playlist.queue_length}"
        )

    def _shift_title(self, table: DataTable[object], delta: int) -> None:
        row = table.cursor_row
        if row < 0:
            return
        if table.id == "results":
            if row >= len(self._result_order):
                return
            item = self._result_order[row]
            title = _result_title(item)
            row_key = _result_row_key(item, row)
        else:
            queue = self.session.playlist.queue_list
            if row >= len(queue):
                return
            track = queue[row]
            title = track.title
            row_key = f"{track.track_id}:{row}"

        page_key = (table.id or "", row_key)
        requested = self._title_pages.get(page_key, 0) + delta
        rendered, page = _title_cell(title, self._table_title_width(table), requested)
        self._title_pages[page_key] = page
        self._update_title_cell(table, row_key, rendered)

    def _table_title_width(self, table: DataTable[object]) -> int:
        # Leave one cell for Textual's vertical scrollbar in addition to the
        # fixed metadata columns. Otherwise the scrollbar obscures the final
        # duration digit when the pane has enough rows to scroll.
        reserved = (25 if self._showing_history else 9) if table.id == "results" else 13
        return max(6, table.size.width - reserved)

    def _reset_title_pages(self, table: DataTable[object]) -> None:
        table_id = table.id or ""
        self._title_pages = {
            key: page for key, page in self._title_pages.items() if key[0] != table_id
        }
        table.scroll_x = 0
        title_width = self._table_title_width(table)
        if table_id == "results":
            rows = (
                (_result_row_key(item, position), _result_title(item))
                for position, item in enumerate(self._result_order)
            )
        else:
            rows = (
                (f"{track.track_id}:{position}", track.title)
                for position, track in enumerate(self.session.playlist.queue_list)
            )
        for row_key, title in rows:
            self._update_title_cell(
                table,
                row_key,
                _title_cell(title, title_width, 0)[0],
            )

    def _sync_table_widths(self) -> None:
        """Give titles the remaining pane width after compact metadata columns."""
        self._sync_table_width(self.query_one("#results", TrackTable))
        self._sync_table_width(self.query_one("#queue", TrackTable))

    def _sync_table_width(self, table: DataTable[object]) -> None:
        if not table.ordered_columns:
            return
        title_column = 0 if table.id == "results" else 1
        table.ordered_columns[title_column].width = self._table_title_width(table)
        table.refresh(layout=True)

        if table.id == "results":
            for row, item in enumerate(self._result_order):
                if row >= table.row_count:
                    break
                row_key = _result_row_key(item, row)
                page_key = ("results", row_key)
                rendered, page = _title_cell(
                    _result_title(item),
                    self._table_title_width(table),
                    self._title_pages.get(page_key, 0),
                )
                self._title_pages[page_key] = page
                self._update_title_cell(table, row_key, rendered)
            return

        for row, track in enumerate(self.session.playlist.queue_list):
            if row >= table.row_count:
                break
            row_key = f"{track.track_id}:{row}"
            page_key = ("queue", row_key)
            rendered, page = _title_cell(
                track.title,
                self._table_title_width(table),
                self._title_pages.get(page_key, 0),
            )
            self._title_pages[page_key] = page
            self._update_title_cell(table, row_key, rendered)

    @staticmethod
    def _update_title_cell(table: DataTable[object], row_key: str, value: str) -> bool:
        """Ignore title updates for a table snapshot already being replaced."""
        try:
            table.update_cell(row_key, "title", value, update_width=False)
        except CellDoesNotExist:
            return False
        return True

    def _download_finished(self, future: object) -> None:
        try:
            exception = future.exception()  # type: ignore[attr-defined]
        except Exception:
            return
        if not self.is_running:
            return
        if exception is None:
            self.call_from_thread(self._refresh_queue)
            self.call_from_thread(self.notify, "Media is available offline", title="Download")
        else:
            self.call_from_thread(
                self.notify,
                str(exception),
                title="Download failed",
                severity="error",
            )

    def _session_mode_selected(self, mode: SessionMode | None) -> None:
        if mode is not None:
            self.current_session_mode = mode
            self.session.set_session_mode(mode)
            self._start_player()
            self.notify(
                "Streaming only" if mode is SessionMode.STREAM_ONLY else "Offline cache enabled",
                title="Session mode",
            )

    def _start_player(self) -> None:
        if self.backend is None:
            return
        try:
            self.session.start_playback(
                self.backend,
                session_mode=self.current_session_mode,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            self.notify(str(exc), title="Playback unavailable", severity="error")

    def _playback_track_changed(self, track: Track | None) -> None:
        if not self.is_running:
            return
        self.call_from_thread(self._show_now_playing, track)
        self.call_from_thread(self._refresh_queue)

    def _playback_history_changed(self) -> None:
        if self.is_running:
            self.call_from_thread(self._refresh_history_if_visible)

    def _refresh_history_if_visible(self) -> None:
        if self._showing_history:
            cursor_row = self.query_one("#results", DataTable).cursor_row
            self._show_history(cursor_row=max(0, cursor_row))

    def _show_now_playing(self, track: Track | None) -> None:
        message = "○ Nothing playing" if track is None else f"▶ {track.title}"
        self.query_one("#now-playing", Static).update(message)
        if track is None:
            self._reset_progress()

    def _refresh_playback_status(self) -> None:
        # A timer tick may already be queued while Textual is removing the
        # screen during shutdown. Avoid querying widgets after that point.
        if not self.query("#playback-time"):
            return
        player = self.session.player
        track = self.session.current_track
        if player is None or track is None:
            self._reset_progress()
            return
        try:
            status = player.status
        except (OSError, RuntimeError, ValueError):
            return

        elapsed = max(0.0, status.elapsed_seconds)
        state_symbol = "Ⅱ" if status.state is PlaybackState.PAUSED else "▶"
        self.query_one("#now-playing", Static).update(f"{state_symbol} {track.title}")
        duration = track.duration_seconds
        total = max(1.0, duration or 1.0)
        self.query_one("#playback-progress", ProgressBar).update(
            total=total,
            progress=min(elapsed, total),
        )
        duration_text = _format_timestamp(duration) if duration is not None else "--:--"
        self.query_one("#playback-time", Static).update(
            f"{_format_timestamp(elapsed)} / {duration_text}"
        )
        self.session.elapsed_seconds = elapsed
        if abs(elapsed - self._last_saved_position) >= 5.0:
            self.session.save()
            self._last_saved_position = elapsed

    def _reset_progress(self) -> None:
        self.query_one("#playback-progress", ProgressBar).update(total=1, progress=0)
        self.query_one("#playback-time", Static).update("0:00 / --:--")
        self._last_saved_position = 0.0

    def _playback_failed(self, track: Track, error: Exception) -> None:
        if self.is_running:
            self.call_from_thread(
                self.notify,
                str(error),
                title=f"Could not play {track.title}",
                severity="error",
            )

    def action_focus_search(self) -> None:
        self.query_one("#search-bar", Input).focus()

    def action_show_history(self) -> None:
        if self._showing_history:
            self._leave_history()
            return
        self._history_return = self._capture_results_state()
        self._search_generation += 1
        self._search_loading = False
        self._show_history()
        self.notify(
            "Enter play now · Home play next · a add · Del remove · c clear · Esc back",
            title="Recently played",
        )

    def action_enqueue_history(self) -> None:
        if not self._showing_history or not self.query_one("#results", DataTable).has_focus:
            return
        entry = self._selected_history_entry()
        if entry is not None:
            self._request_history_queue(entry.track, play_now=False, append=True)

    def _leave_history(self) -> None:
        state = self._history_return
        self._history_return = None
        if state is None:
            self._show_results([])
            return
        self._restore_results_state(state)

    def action_clear_history(self) -> None:
        if not self._showing_history or not self._history_entries:
            return
        self.push_screen(ClearHistoryScreen(), self._clear_history_decided)

    def _clear_history_decided(self, confirmed: bool | None) -> None:
        if not confirmed:
            return
        self.session.clear_recent_history()
        self._show_history()
        self.notify("Recently played history was cleared", title="History")

    def _selected_history_entry(self) -> HistoryEntry | None:
        row = self.query_one("#results", DataTable).cursor_row
        if not 0 <= row < len(self._history_entries):
            return None
        return self._history_entries[row]

    def action_leave_search(self) -> None:
        if self._search_loading:
            self._search_generation += 1
            self._search_loading = False
            if self._search_restore is not None:
                restore = self._search_restore
                self._search_restore = None
                self._restore_results_state(restore)
                self.notify("The pending result was ignored", title="Search cancelled")
                return
            self._show_search_state("Search cancelled")
        results = self.query_one("#results", DataTable)
        target = results if self._result_order else self.query_one("#queue", DataTable)
        target.focus()

    def action_focus_next(self) -> None:
        if self.screen.id != "_default":
            super().action_focus_next()
            return
        results = self.query_one("#results", DataTable)
        queue = self.query_one("#queue", DataTable)
        (queue if results.has_focus else results).focus()

    def action_focus_previous(self) -> None:
        self.action_focus_next()

    def action_settings(self) -> None:
        self._settings_backend_before = self.config.backend
        self._settings_mode_before = self.config.session_mode
        self._settings_volume_before = self.config.volume
        self.push_screen(SettingsScreen(self.config), self._settings_closed)

    def action_change_theme(self) -> None:
        self.push_screen(
            ThemeScreen(self.config, sorted(self.available_themes)),
            self._theme_selected,
        )

    def _theme_selected(self, theme: str | None) -> None:
        if theme is not None:
            self.notify(theme, title="Theme saved")

    def _settings_closed(self, saved: bool | None) -> None:
        if not saved:
            return
        self.session.playlist.shuffle = self.config.shuffle
        self.session.playlist.repeat_mode = RepeatMode(self.config.repeat_mode)
        self.session.cache.max_cache_bytes = self.config.cache_max_bytes
        self.session.cache.prune()
        self.session.prune_recent_history()
        if (
            self.session.player is not None
            and self.config.volume != self._settings_volume_before
        ):
            self.session.player.set_volume(self.config.volume)
        self.session.save()
        restart_changes: list[str] = []
        if self.config.backend != self._settings_backend_before:
            restart_changes.append("backend")
        if self.config.session_mode != self._settings_mode_before:
            restart_changes.append("startup mode")
        if restart_changes:
            self.notify(
                f"Restart auen to apply: {', '.join(restart_changes)}",
                title="Restart required",
                severity="warning",
            )

    def action_toggle_playback(self) -> None:
        if self.session.player is not None:
            self.session.player.toggle_pause()

    @on(Button.Pressed, "#play-pause")
    def playback_button_pressed(self) -> None:
        self.action_toggle_playback()

    def action_next_track(self) -> None:
        if self.session.player is not None:
            self.session.player.skip()

    @on(Button.Pressed, "#next-track")
    def next_button_pressed(self) -> None:
        self.action_next_track()

    def action_seek_backward(self) -> None:
        self._seek(-10.0)

    @on(Button.Pressed, "#seek-back")
    def seek_back_button_pressed(self) -> None:
        self.action_seek_backward()

    def action_seek_forward(self) -> None:
        self._seek(10.0)

    @on(Button.Pressed, "#seek-forward")
    def seek_forward_button_pressed(self) -> None:
        self.action_seek_forward()

    def action_go_to_time(self) -> None:
        player = self.session.player
        track = self.session.current_track
        if player is None or track is None:
            self.notify("Nothing is playing", title="Go to time", severity="warning")
            return
        if not player.backend.supports_seek:
            self.notify(
                f"{player.backend.name} does not support seeking",
                title="Go to time",
                severity="warning",
            )
            return
        self.push_screen(SeekScreen(track.duration_seconds), self._seek_to)

    @on(Button.Pressed, "#jump-time")
    def jump_button_pressed(self) -> None:
        self.action_go_to_time()

    def _seek_to(self, seconds: float | None) -> None:
        if seconds is None or self.session.player is None:
            return
        try:
            self.session.player.seek_to(seconds)
        except (RuntimeError, ValueError) as exc:
            self.notify(str(exc), title="Seek unavailable", severity="warning")

    def _seek(self, seconds: float) -> None:
        if self.session.player is None:
            return
        try:
            self.session.player.seek(seconds)
        except RuntimeError as exc:
            self.notify(str(exc), title="Seek unavailable", severity="warning")

    def action_download_selected(self) -> None:
        table = self.query_one("#results", DataTable)
        if not 0 <= table.cursor_row < len(self._result_order):
            return
        item = self._result_order[table.cursor_row]
        if isinstance(item, MediaCollection):
            self.notify("Open the collection and select a track", title="Save offline")
            return
        track = item
        future = self.session.save_offline(track)
        future.add_done_callback(self._download_finished)
        self.notify(track.title, title="Saving offline")

    def action_remove_queued(self) -> None:
        results = self.query_one("#results", DataTable)
        if self._showing_history and results.has_focus:
            entry = self._selected_history_entry()
            if entry is None:
                return
            cursor_row = results.cursor_row
            if self.session.remove_recent_history(entry.track.uri):
                self._show_history(cursor_row=max(0, cursor_row))
                self.notify(entry.track.title, title="Removed from history")
            return
        table = self.query_one("#queue", DataTable)
        if table.has_focus and self.session.remove_queued(table.cursor_row) is not None:
            self._refresh_queue()


def run() -> None:
    """Launch the interactive application."""
    config = AuenConfig.load()
    if config.backend == "termux" and _is_termux_environment() and shutil.which("mpv"):
        # v0.1.0 exposed the limited Termux:API backend directly. Prefer the
        # richer native mpv package once it becomes available.
        config.backend = "auto"
        with contextlib.suppress(OSError, ValueError):
            config.save()
    try:
        backend = detect_backend(config.backend)
        backend_error = None
    except (OSError, RuntimeError, ValueError) as exc:
        backend = None
        backend_error = str(exc)
    app = AuenApp(config, backend=backend, backend_error=backend_error)
    try:
        app.run()
    finally:
        # Textual may not dispatch Unmount after an unhandled UI exception.
        # Always stop playback and owned workers before returning to the shell.
        with contextlib.suppress(Exception):
            app.session.close()


def _parse_timestamp(value: str) -> float:
    """Parse seconds, mm:ss, or hh:mm:ss into non-negative seconds."""
    parts = value.strip().split(":")
    if not value.strip() or len(parts) > 3:
        raise ValueError("Enter seconds, mm:ss, or hh:mm:ss")
    try:
        numbers = [float(part) for part in parts]
    except ValueError as exc:
        raise ValueError("Time must contain only numbers and colons") from exc
    if any(not math.isfinite(number) for number in numbers):
        raise ValueError("Time must be a finite number")
    if any(number < 0 for number in numbers):
        raise ValueError("Time cannot be negative")
    if len(numbers) > 1 and any(number >= 60 for number in numbers[1:]):
        raise ValueError("Minutes and seconds must be below 60")
    seconds = 0.0
    for number in numbers:
        seconds = seconds * 60 + number
    return seconds


def _format_timestamp(seconds: float | None) -> str:
    total = max(0, int(seconds or 0))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _history_time(value: datetime) -> str:
    """Format a history timestamp compactly in the terminal's local timezone."""
    local = value.astimezone()
    now = datetime.now().astimezone()
    if local.date() == now.date():
        return local.strftime("%H:%M")
    if local.year == now.year:
        return local.strftime("%b %d")
    return local.strftime("%Y-%m-%d")


def _title_window(value: str, width: int, page: int) -> tuple[str, int]:
    """Return one display-cell-safe page of a title and its clamped page index."""
    if width < 1:
        return "", 0
    if cell_len(value) <= width:
        return value, 0
    if width == 1:
        return "…", 0
    chunks = chop_cells(value, max(1, width - 2))
    selected = min(max(0, page), len(chunks) - 1)
    left = "←" if selected else ""
    right = "→" if selected < len(chunks) - 1 else ""
    return f"{left}{chunks[selected].rstrip()}{right}", selected


def _title_cell(value: str, width: int, page: int) -> tuple[str, int]:
    """Render a title with a terminal-safe, emoji-aware right gutter."""
    value = _stabilize_terminal_emoji(value)
    rendered, selected = _title_window(
        value,
        max(1, width - _emoji_safety_gutter(value)),
        page,
    )
    return (
        rendered if _is_termux_environment() else _isolate_ltr(rendered),
        selected,
    )


def _stabilize_terminal_emoji(value: str) -> str:
    """Remove emoji composition controls whose terminal widths are inconsistent."""
    return "".join(
        character
        for character in value
        if character not in {"\ufe0e", "\ufe0f", "\u200d", "\u20e3"}
        and not "\U0001f3fb" <= character <= "\U0001f3ff"
    )


def _emoji_safety_gutter(value: str) -> int:
    """Allow for terminals disagreeing with Unicode's emoji cell widths."""
    emoji_codepoints = sum(
        1
        for character in value
        if "\U0001f000" <= character <= "\U0001faff"
        or "\u2600" <= character <= "\u27bf"
    )
    return 2 + min(6, emoji_codepoints)


def _result_id(item: SearchItem) -> str:
    return item.track_id if isinstance(item, Track) else item.collection_id


def _result_row_key(item: SearchItem, position: int) -> str:
    """Return a display-unique key even when an extractor repeats an item."""
    return f"{_result_id(item)}:{position}"


def _merge_search_items(
    existing: Sequence[SearchItem],
    incoming: Sequence[SearchItem],
    *,
    max_items: int | None = None,
) -> list[SearchItem]:
    """Preserve displayed order and append only newly discovered media."""
    merged: list[SearchItem] = []
    seen: set[str] = set()
    for item in (*existing, *incoming):
        identity = item.uri
        if identity in seen:
            continue
        seen.add(identity)
        merged.append(item)
        if max_items is not None and len(merged) >= max_items:
            break
    return merged


def _result_title(item: SearchItem) -> str:
    if isinstance(item, Track):
        return f"♪ {item.title}"
    symbol = "◉" if item.kind is CollectionKind.ALBUM else "≡"
    return f"{symbol} {item.title}"


def _result_detail(item: SearchItem) -> str:
    if isinstance(item, Track):
        return item.duration_display or "-"
    if item.item_count is not None:
        return f"{item.item_count} trk"
    return "album" if item.kind is CollectionKind.ALBUM else "list"


def _isolate_ltr(value: str) -> str:
    """Keep bidirectional title text from reordering adjacent table columns."""
    return f"\N{LEFT-TO-RIGHT ISOLATE}{value}\N{POP DIRECTIONAL ISOLATE}"


def _is_termux_environment() -> bool:
    """Detect Termux without depending on optional Termux:API commands."""
    prefix = os.environ.get("PREFIX", "")
    return "TERMUX_VERSION" in os.environ or prefix.startswith("/data/data/com.termux/")
