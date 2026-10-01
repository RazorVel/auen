"""Textual application shell for auen."""

from __future__ import annotations

import asyncio
import math
from typing import TYPE_CHECKING, ClassVar

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
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

from auen.backends import detect_backend
from auen.config import AuenConfig
from auen.models import PlaybackState, RepeatMode, SessionMode, Track
from auen.session import AuenSession

if TYPE_CHECKING:
    from textual.binding import BindingType

    from auen.backends.base import AudioBackend


class SearchInput(Input):
    """Search field with conventional select-all behavior."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+a", "select_all", "Select all", show=False, priority=True),
        *Input.BINDINGS,
    ]


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
        self.query_one("#cancel-duplicate", Button).focus()

    @on(Button.Pressed, "#cancel-duplicate")
    def cancel_pressed(self) -> None:
        self.dismiss(False)

    @on(Button.Pressed, "#confirm-duplicate")
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
                yield Select(
                    [("Automatic", "auto"), ("mpv", "mpv"), ("Termux", "termux")],
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
                "Search results", "search-results", str(self.config.search_result_count)
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
        yield Footer()

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
        self.config.search_result_count = self._integer_value("#search-results", "search results")
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
    BINDINGS: ClassVar[list[BindingType]] = [
        ("/", "focus_search", "⌕ Search"),
        ("space", "toggle_playback", "▶/Ⅱ Play"),
        ("n", "next_track", "» Next"),
        ("[", "seek_backward", "← 10s"),
        ("]", "seek_forward", "10s →"),
        ("g", "go_to_time", "↪ Time"),
        ("d", "download_selected", "↓ Offline"),
        ("delete", "remove_queued", "Del Remove"),
        ("f2", "settings", "⚙ Settings"),
        ("f3", "change_theme", "◐ Theme"),
        ("q", "quit", "q Quit"),
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
        self.session.on_playback_error = self._playback_failed
        self.current_session_mode = SessionMode(self.config.session_mode)
        self.search_results: dict[str, Track] = {}
        self._result_order: list[Track] = []
        self._last_saved_position = 0.0

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield SearchInput(placeholder="Search YouTube or paste a YouTube URL…", id="search-bar")
        with Horizontal(id="workspace"):
            with Vertical(classes="pane", id="results-pane"):
                yield Label("⌕ Results · 0", classes="pane-title", id="results-title")
                yield DataTable(id="results", cursor_type="row")
            with Vertical(classes="pane", id="queue-pane"):
                yield Label("≡ Queue · 0", classes="pane-title", id="queue-title")
                yield DataTable(id="queue", cursor_type="row")
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
        results = self.query_one("#results", DataTable)
        results.add_columns("Title", "Duration")
        results.zebra_stripes = True
        queue = self.query_one("#queue", DataTable)
        queue.add_columns("Title", "Source", "Availability")
        queue.zebra_stripes = True
        self._refresh_queue()
        self.set_interval(0.5, self._refresh_playback_status)
        if self.current_session_mode is SessionMode.ASK:
            self.push_screen(SessionModeScreen(), self._session_mode_selected)
        else:
            self._start_player()
        if self.backend_error is not None:
            self.notify(self.backend_error, title="Playback unavailable", severity="warning")

    def on_unmount(self) -> None:
        self.session.close()

    @on(Input.Submitted, "#search-bar")
    def search_submitted(self, event: Input.Submitted) -> None:
        if event.value.strip():
            self.query_one("#results-title", Label).update("⌕ Searching…")
            self.query_one("#results", DataTable).clear()
            self.search_media(event.value)

    @work(exclusive=True, group="youtube-search")
    async def search_media(self, query: str) -> None:
        try:
            tracks = await asyncio.wrap_future(self.session.submit_search(query))
        except (OSError, RuntimeError, ValueError) as exc:
            self.query_one("#results-title", Label).update("⌕ Results · 0")
            self.notify(str(exc), title="Search failed", severity="error")
            return
        self._show_results(tracks)

    def _show_results(self, tracks: list[Track]) -> None:
        table = self.query_one("#results", DataTable)
        table.clear()
        self._result_order = tracks
        self.search_results = {track.track_id: track for track in tracks}
        for track in tracks:
            table.add_row(track.title, track.duration_display or "-", key=track.track_id)
        self.query_one("#results-title", Label).update(f"⌕ Results · {len(tracks)}")
        if not tracks:
            self.notify("No matching videos found", title="Search")
        else:
            table.focus()

    @on(DataTable.RowSelected, "#results")
    def result_selected(self, event: DataTable.RowSelected) -> None:
        track = self.search_results.get(str(event.row_key.value))
        if track is None:
            return
        if any(queued.uri == track.uri for queued in self.session.playlist.queue_list):
            self.push_screen(
                DuplicateQueueScreen(track),
                lambda confirmed: self._duplicate_queue_decided(track, confirmed),
            )
            return
        self._enqueue_track(track)

    def _duplicate_queue_decided(self, track: Track, confirmed: bool | None) -> None:
        if confirmed:
            self._enqueue_track(track)

    def _enqueue_track(self, track: Track) -> None:
        future = self.session.enqueue(track, session_mode=self.current_session_mode)
        self._refresh_queue()
        self.notify(track.title, title="Added to queue")
        if future is not None:
            future.add_done_callback(self._download_finished)

    def _refresh_queue(self) -> None:
        table = self.query_one("#queue", DataTable)
        table.clear()
        for position, track in enumerate(self.session.playlist.queue_list):
            availability = "✓ offline" if track.is_cached else "↗ stream"
            table.add_row(
                track.title,
                track.source.name.casefold(),
                availability,
                key=f"{track.track_id}:{position}",
            )
        self.query_one("#queue-title", Label).update(
            f"≡ Queue · {self.session.playlist.queue_length}"
        )

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

    def _show_now_playing(self, track: Track | None) -> None:
        message = "○ Nothing playing" if track is None else f"▶ {track.title}"
        self.query_one("#now-playing", Static).update(message)
        if track is None:
            self._reset_progress()

    def _refresh_playback_status(self) -> None:
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

    def action_settings(self) -> None:
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
        if self.session.player is not None:
            self.session.player.set_volume(self.config.volume)
        self.session.save()

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
        track = self._result_order[table.cursor_row]
        future = self.session.save_offline(track)
        future.add_done_callback(self._download_finished)
        self.notify(track.title, title="Saving offline")

    def action_remove_queued(self) -> None:
        table = self.query_one("#queue", DataTable)
        if self.session.remove_queued(table.cursor_row) is not None:
            self._refresh_queue()


def run() -> None:
    """Launch the interactive application."""
    config = AuenConfig.load()
    try:
        backend = detect_backend(config.backend)
        backend_error = None
    except (OSError, RuntimeError, ValueError) as exc:
        backend = None
        backend_error = str(exc)
    AuenApp(config, backend=backend, backend_error=backend_error).run()


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
