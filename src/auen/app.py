"""Textual application shell for auen."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, ClassVar

from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    Select,
    Static,
    Switch,
)

from auen.config import AuenConfig
from auen.models import RepeatMode, SessionMode, Track
from auen.session import AuenSession

if TYPE_CHECKING:
    from textual.binding import BindingType


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
        self.config.search_result_count = self._integer_value(
            "#search-results", "search results"
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
    BINDINGS: ClassVar[list[BindingType]] = [
        ("/", "focus_search", "Search"),
        ("d", "download_selected", "Save offline"),
        ("delete", "remove_queued", "Remove queued"),
        ("f2", "settings", "Settings"),
        ("q", "quit", "Quit"),
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
    }
    DataTable {
        height: 1fr;
    }
    #now-playing {
        dock: bottom;
        height: 3;
        padding: 1 2;
        background: $panel;
    }
    """

    def __init__(
        self,
        config: AuenConfig | None = None,
        *,
        session: AuenSession | None = None,
    ) -> None:
        super().__init__()
        self.config = config or AuenConfig.load()
        self.session = session or AuenSession(self.config)
        self.current_session_mode = SessionMode(self.config.session_mode)
        self.search_results: dict[str, Track] = {}
        self._result_order: list[Track] = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Input(placeholder="Search YouTube or paste a YouTube URL…", id="search-bar")
        with Horizontal(id="workspace"):
            with Vertical(classes="pane", id="results-pane"):
                yield Label("Search results", classes="pane-title")
                yield DataTable(id="results", cursor_type="row")
            with Vertical(classes="pane", id="queue-pane"):
                yield Label("Queue", classes="pane-title")
                yield DataTable(id="queue", cursor_type="row")
        yield Static("Nothing playing", id="now-playing")
        yield Footer()

    def on_mount(self) -> None:
        results = self.query_one("#results", DataTable)
        results.add_columns("Title", "Duration")
        queue = self.query_one("#queue", DataTable)
        queue.add_columns("Title", "Source", "Availability")
        self._refresh_queue()
        if self.current_session_mode is SessionMode.ASK:
            self.push_screen(SessionModeScreen(), self._session_mode_selected)

    def on_unmount(self) -> None:
        self.session.close()

    @on(Input.Submitted, "#search-bar")
    def search_submitted(self, event: Input.Submitted) -> None:
        if event.value.strip():
            self.search_media(event.value)

    @work(exclusive=True, group="youtube-search")
    async def search_media(self, query: str) -> None:
        try:
            tracks = await asyncio.wrap_future(self.session.submit_search(query))
        except (OSError, RuntimeError, ValueError) as exc:
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
        if not tracks:
            self.notify("No matching videos found", title="Search")

    @on(DataTable.RowSelected, "#results")
    def result_selected(self, event: DataTable.RowSelected) -> None:
        track = self.search_results.get(str(event.row_key.value))
        if track is None:
            return
        future = self.session.enqueue(track, session_mode=self.current_session_mode)
        self._refresh_queue()
        self.notify(track.title, title="Added to queue")
        if future is not None:
            future.add_done_callback(self._download_finished)

    def _refresh_queue(self) -> None:
        table = self.query_one("#queue", DataTable)
        table.clear()
        for track in self.session.playlist.queue_list:
            availability = "offline" if track.is_cached else "stream"
            table.add_row(
                track.title,
                track.source.name.casefold(),
                availability,
                key=track.track_id,
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
            self.notify(
                "Streaming only" if mode is SessionMode.STREAM_ONLY else "Offline cache enabled",
                title="Session mode",
            )

    def action_focus_search(self) -> None:
        self.query_one("#search-bar", Input).focus()

    def action_settings(self) -> None:
        self.push_screen(SettingsScreen(self.config), self._settings_closed)

    def _settings_closed(self, saved: bool | None) -> None:
        if not saved:
            return
        self.session.playlist.shuffle = self.config.shuffle
        self.session.playlist.repeat_mode = RepeatMode(self.config.repeat_mode)
        self.session.cache.max_cache_bytes = self.config.cache_max_bytes
        self.session.cache.prune()
        self.session.save()

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
    AuenApp().run()
