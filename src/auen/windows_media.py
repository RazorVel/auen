"""Optional Windows SMTC adapter. mpv remains the only audio player."""

from __future__ import annotations

import asyncio
import contextlib
import math
import time
from datetime import timedelta
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING, Any

from auen.desktop_media import NO_TRACK, MediaSnapshot
from auen.windows_window import HiddenMediaWindow

if TYPE_CHECKING:
    from collections.abc import Callable

WINDOWS_MEDIA_PACKAGES = (
    "winrt-Windows.Foundation", "winrt-Windows.Media", "winrt-Windows.Media.Interop",
    "winrt-Windows.Storage.Streams",
)


def missing_windows_media_packages() -> list[str]:
    """Doctor checks installation only; do not activate a native media session."""
    missing = []
    for package in WINDOWS_MEDIA_PACKAGES:
        try:
            version(package)
        except PackageNotFoundError:
            missing.append(package)
    return missing


class _WinRTSession:
    """Narrow dynamic boundary to the optional, Windows-only PyWinRT projections."""

    def __init__(self, hwnd: int, button: Callable[[str], None],
                 seek: Callable[[float], None]) -> None:
        self.foundation = import_module("winrt.windows.foundation")
        self.media = import_module("winrt.windows.media")
        self.streams = import_module("winrt.windows.storage.streams")
        interop = import_module("winrt.windows.media.interop")
        self.controls: Any = interop.get_for_window(hwnd)
        self._tokens: list[tuple[str, Any]] = []
        self._metadata: tuple[str, str, str | None] | None = None
        self._last: MediaSnapshot | None = None
        self._timeline_at = 0.0
        buttons = self.media.SystemMediaTransportControlsButton
        actions = {buttons.PLAY: "play", buttons.PAUSE: "pause", buttons.NEXT: "next",
                   buttons.PREVIOUS: "previous", buttons.STOP: "stop"}

        def on_button(_sender: Any, args: Any) -> None:
            action = actions.get(args.button)
            if action is not None:
                button(action)

        def on_seek(_sender: Any, args: Any) -> None:
            seek(args.requested_playback_position.total_seconds())

        try:
            token = self.controls.add_button_pressed(on_button)
            self._tokens.append(("remove_button_pressed", token))
            token = self.controls.add_playback_position_change_requested(on_seek)
            self._tokens.append(("remove_playback_position_change_requested", token))
            self.controls.playback_rate = 1.0
        except Exception:
            self.close()
            raise

    def update(self, snapshot: MediaSnapshot) -> None:
        controls = self.controls
        controls.is_play_enabled = snapshot.can_play
        controls.is_pause_enabled = snapshot.can_pause
        controls.is_next_enabled = snapshot.can_next
        controls.is_previous_enabled = snapshot.can_previous
        controls.is_stop_enabled = snapshot.can_pause
        controls.is_enabled = snapshot.can_play or snapshot.can_pause
        status = self.media.MediaPlaybackStatus
        controls.playback_status = {"Playing": status.PLAYING, "Paused": status.PAUSED}.get(
            snapshot.state, status.STOPPED,
        )
        metadata = (snapshot.track_id, snapshot.title, snapshot.art_url)
        if metadata != self._metadata:
            updater = controls.display_updater
            updater.clear_all()  # Never retain the previous track's thumbnail.
            updater.type = self.media.MediaPlaybackType.MUSIC
            if snapshot.track_id != NO_TRACK:
                updater.music_properties.title = snapshot.title
                updater.app_media_id = snapshot.track_id
                if snapshot.art_url:
                    updater.thumbnail = self.streams.RandomAccessStreamReference.create_from_uri(
                        self.foundation.Uri(snapshot.art_url),
                    )
            updater.update()
            self._metadata = metadata
        now = time.monotonic()
        previous = self._last
        timeline_changed = previous is None or (
            snapshot.track_id, snapshot.state, snapshot.duration, snapshot.can_seek
        ) != (previous.track_id, previous.state, previous.duration, previous.can_seek)
        jump = previous is not None and abs(
            snapshot.elapsed - previous.elapsed
            - ((now - self._timeline_at) if previous.state == "Playing" else 0)
        ) > 1.0
        if timeline_changed or jump or now - self._timeline_at >= 5:
            timeline = self.media.SystemMediaTransportControlsTimelineProperties()
            duration = snapshot.duration
            end = duration if duration is not None and math.isfinite(duration) else 0.0
            end = min(1_000_000_000.0, max(0.0, end))
            elapsed = snapshot.elapsed if math.isfinite(snapshot.elapsed) else 0.0
            timeline.start_time = timedelta(0)
            timeline.end_time = timedelta(seconds=end)
            timeline.position = timedelta(seconds=min(end, max(0.0, elapsed)))
            timeline.min_seek_time = timedelta(0)
            timeline.max_seek_time = timedelta(seconds=end if snapshot.can_seek else 0)
            controls.update_timeline_properties(timeline)
            self._last = snapshot
            self._timeline_at = now

    def close(self) -> None:
        for method, token in self._tokens:
            with contextlib.suppress(Exception):
                getattr(self.controls, method)(token)
        self._tokens.clear()
        with contextlib.suppress(Exception):
            self.controls.is_enabled = False
            self.controls.playback_status = self.media.MediaPlaybackStatus.CLOSED
            self.controls.display_updater.clear_all()
            self.controls.display_updater.update()


class WindowsMediaControls:
    """Forward native events to the UI loop without blocking Windows callbacks."""

    def __init__(self, command: Callable[[str], Any], seek: Callable[[float, str], Any],
                 error: Callable[[str], None]) -> None:
        self._command, self._seek, self._error = command, seek, error
        self._loop = asyncio.get_running_loop()
        self._window: HiddenMediaWindow | None = None
        self._session: _WinRTSession | None = None
        self._closed = False
        self.snapshot = MediaSnapshot()

    def start(self) -> None:
        try:
            self._window = HiddenMediaWindow()
            self._session = _WinRTSession(self._window.handle, self._button, self._position)
            self._session.update(self.snapshot)
        except Exception:
            self.close()
            raise

    def update(self, snapshot: MediaSnapshot) -> None:
        if self._closed:
            return
        self.snapshot = snapshot
        if self._session is not None:
            try:
                self._session.update(snapshot)
            except Exception:
                self._fail("Could not update Windows media controls. Playback still works.")

    def pump(self) -> None:
        if not self._closed and self._window is not None:
            try:
                self._window.pump()
            except Exception:
                self._fail("Windows media controls stopped responding. Playback still works.")

    def _schedule(self, callback: Callable[..., None], *args: Any) -> None:
        if not self._closed:
            with contextlib.suppress(RuntimeError):  # Event loop may already be closing.
                self._loop.call_soon_threadsafe(callback, *args)

    def _button(self, command: str) -> None:
        self._schedule(self._dispatch, command)

    def _dispatch(self, command: str) -> None:
        if self._closed:
            return
        allowed = {"play": self.snapshot.can_play, "pause": self.snapshot.can_pause,
                   "next": self.snapshot.can_next, "previous": self.snapshot.can_previous,
                   "stop": self.snapshot.can_pause}
        if allowed.get(command, False):
            try:
                self._command(command)
            except (OSError, RuntimeError, ValueError):
                self._error("Playback command unavailable; ordinary playback still works.")

    def _position(self, seconds: float) -> None:
        self._schedule(self._dispatch_seek, seconds, self.snapshot.track_id)

    def _dispatch_seek(self, seconds: float, identity: str) -> None:
        snapshot = self.snapshot
        if (self._closed or not snapshot.can_seek or snapshot.track_id != identity
                or identity == NO_TRACK or not math.isfinite(seconds) or seconds < 0
                or snapshot.duration is None or seconds > snapshot.duration):
            return
        try:
            self._seek(seconds, identity)
        except (OSError, RuntimeError, ValueError):
            self._error("Seek unavailable or track changed; ordinary playback still works.")

    def _fail(self, message: str) -> None:
        self.close()
        self._error(message)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._session is not None:
            with contextlib.suppress(Exception):
                self._session.close()
            self._session = None
        if self._window is not None:
            with contextlib.suppress(Exception):
                self._window.close()
            self._window = None
