"""Backend-neutral playback lifecycle and queue orchestration."""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING

from auen.models import PlaybackState, PlaybackStatus, Track

if TYPE_CHECKING:
    from auen.backends.base import AudioBackend
    from auen.playlist import Playlist

TrackPreparer = Callable[[Track], str]
TrackCallback = Callable[[Track | None], None]
TrackStartedCallback = Callable[[Track], None]
ErrorCallback = Callable[[Track, Exception], None]


class PlaybackController:
    """Consume a playlist on one bounded worker and control the active backend."""

    def __init__(
        self,
        playlist: Playlist,
        backend: AudioBackend,
        *,
        prepare: TrackPreparer | None = None,
        on_track_changed: TrackCallback | None = None,
        on_track_started: TrackStartedCallback | None = None,
        on_error: ErrorCallback | None = None,
    ) -> None:
        self.playlist = playlist
        self.backend = backend
        self.prepare = prepare or (lambda track: track.playable_uri)
        self.on_track_changed = on_track_changed
        self.on_track_started = on_track_started
        self.on_error = on_error
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._current_track: Track | None = None
        self._skip_requested = threading.Event()
        self._playback_enabled = threading.Event()
        self._playback_enabled.set()
        self._hold_after_current = threading.Event()

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="auen-player",
                daemon=True,
            )
            self._thread.start()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            if not self._playback_enabled.wait(timeout=0.2):
                continue
            track = self.playlist.next(timeout=0.2)
            if track is None:
                continue

            try:
                uri = self.prepare(track)
                if not uri:
                    raise ValueError("track preparation returned no playable media")
                self._set_current(track)
                self._skip_requested.clear()
                self.backend.play(uri)
                self.backend.set_volume(self.status.volume)
                if self.on_track_started is not None:
                    self.on_track_started(track)
            except Exception as exc:
                self.playlist.mark_played(track)
                self._report_error(track, exc)
                self._set_current(None)
                continue

            ended = False
            playback_error: Exception | None = None
            while not self._stop_event.is_set():
                try:
                    if self.backend.wait_for_end(timeout=0.25):
                        ended = True
                        break
                except Exception as exc:
                    playback_error = exc
                    break

            if self._stop_event.is_set():
                break
            if playback_error is not None:
                with contextlib.suppress(Exception):
                    self.backend.stop()
                self.playlist.mark_played(track)
                self._report_error(track, playback_error)
                self._set_current(None)
                self._apply_pending_hold()
                continue
            if ended or self._skip_requested.is_set():
                self.playlist.complete(track)
            self._set_current(None)
            if ended and not self._skip_requested.is_set():
                self._apply_pending_hold()

    @property
    def current_track(self) -> Track | None:
        with self._lock:
            return self._current_track

    @property
    def status(self) -> PlaybackStatus:
        status = self.backend.get_status()
        status.track = self.current_track
        return status

    def pause(self) -> None:
        if self.current_track is not None:
            self.backend.pause()

    def resume(self) -> None:
        if self.current_track is not None:
            self.backend.resume()
        else:
            self._playback_enabled.set()

    def toggle_pause(self) -> None:
        if self.current_track is None and not self._playback_enabled.is_set():
            self.resume()
            return
        status = self.status
        if status.state is PlaybackState.PAUSED:
            self.resume()
        elif status.state is PlaybackState.PLAYING:
            self.pause()

    def skip(self) -> None:
        self._hold_after_current.clear()
        self._playback_enabled.set()
        if self.current_track is not None:
            self._skip_requested.set()
            self.backend.stop()

    def hold_after_current(self) -> None:
        """Finish the active track, then wait before consuming the queue."""
        if self.current_track is None:
            raise RuntimeError("nothing is playing")
        self._hold_after_current.set()

    def cancel_hold_after_current(self) -> None:
        self._hold_after_current.clear()

    @property
    def queue_held(self) -> bool:
        return not self._playback_enabled.is_set()

    def _apply_pending_hold(self) -> None:
        if self._hold_after_current.is_set():
            self._hold_after_current.clear()
            self._playback_enabled.clear()

    def seek(self, seconds: float) -> None:
        if not self.backend.supports_seek:
            raise RuntimeError(f"{self.backend.name} does not support seeking")
        self.backend.seek(seconds)

    def seek_to(self, seconds: float) -> None:
        """Seek to an absolute position using the backend's relative seek support."""
        if seconds < 0:
            raise ValueError("seek position cannot be negative")
        if not self.backend.supports_seek:
            raise RuntimeError(f"{self.backend.name} does not support seeking")
        if not self.backend.capabilities.reports_position:
            raise RuntimeError(f"{self.backend.name} cannot report playback position")
        self.backend.seek(seconds - self.backend.get_status().elapsed_seconds)

    def set_volume(self, level: int) -> None:
        if not 0 <= level <= 100:
            raise ValueError("volume must be between 0 and 100")
        self.backend.set_volume(level)

    def close(self, *, timeout: float = 3.0) -> None:
        self._stop_event.set()
        stop_error: Exception | None = None
        try:
            self.backend.stop()
        except Exception as exc:
            stop_error = exc
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
            if thread.is_alive():
                raise RuntimeError("playback worker did not stop in time")
        self._set_current(None)
        if stop_error is not None:
            raise stop_error

    def _set_current(self, track: Track | None) -> None:
        with self._lock:
            self._current_track = track
        if self.on_track_changed is not None:
            self.on_track_changed(track)

    def _report_error(self, track: Track, error: Exception) -> None:
        if self.on_error is not None:
            self.on_error(track, error)
