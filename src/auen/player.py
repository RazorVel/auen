"""Backend-neutral playback lifecycle and queue orchestration."""

from __future__ import annotations

import contextlib
import threading
from collections import deque
from collections.abc import Callable
from typing import TYPE_CHECKING, Literal

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
        cancel_prepare: Callable[[], None] | None = None,
    ) -> None:
        self.playlist = playlist
        self.backend = backend
        self.prepare = prepare or (lambda track: track.playable_uri)
        self.on_track_changed = on_track_changed
        self.on_track_started = on_track_started
        self.on_error = on_error
        self.cancel_prepare = cancel_prepare
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._current_track: Track | None = None
        self._skip_requested = threading.Event()
        self._playback_enabled = threading.Event()
        self._playback_enabled.set()
        self._hold_after_current = threading.Event()
        self._control_lock = threading.RLock()
        self._ready = False
        # This is navigation history, not the deduplicated Recently Played list
        # or the queue's repeat-cycle history. Only successful plays enter it.
        self._back_stack: deque[Track] = deque(maxlen=100)
        self._previous_target: Track | None = None
        self._desired_paused = False
        self._stop_playback_requested = False
        self._failed_track: Track | None = None
        self._volume = 80

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
                self._set_current(track)
                uri = self.prepare(track)
                if not uri:
                    raise ValueError("track preparation returned no playable media")
                with self._control_lock:
                    stopped = (
                        self._stop_event.is_set() or self._stop_playback_requested
                        or not self._playback_enabled.is_set()
                    )
                    if stopped:
                        self._stop_playback_requested = False
                        self.playlist.add_next(track)
                    else:
                        self._skip_requested.clear()
                if stopped:
                    self._set_current(None)
                    continue
                # Backend startup may take seconds. Keep the control lock free
                # so Pause/Stop during preparation never blocks the UI loop.
                self.backend.play(uri)
                self.backend.set_volume(self._volume)
                with self._control_lock:
                    stopped = self._stop_event.is_set() or self._stop_playback_requested
                    if stopped:
                        self.backend.stop()
                    else:
                        if self._desired_paused:
                            self.backend.pause()
                        self._ready = True
                if not stopped and self.on_track_started is not None:
                    self.on_track_started(track)
            except Exception as exc:
                self._hold_failed_track(track, exc)
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
                self.playlist.add_next(track)
                break
            with self._control_lock:
                self._ready = False
                previous_target = self._previous_target
                self._previous_target = None
                skipped = self._skip_requested.is_set()
                if skipped:
                    playback_error = None
                stopped = self._stop_playback_requested
                self._stop_playback_requested = False
                if stopped:
                    self.playlist.add_next_many(
                        [previous_target, track] if previous_target is not None else [track]
                    )
                elif previous_target is not None:
                    # Queue the interrupted track behind the previous one, so
                    # Next returns to it even with shuffle enabled.
                    self.playlist.add_next_many([previous_target, track])
                elif playback_error is None:
                    if ended or skipped:
                        self.playlist.complete(track, skipped=skipped)
                    self._back_stack.append(track)
            if stopped or previous_target is not None:
                self._set_current(None)
                continue
            if playback_error is not None:
                self._hold_failed_track(track, playback_error)
                continue
            self._set_current(None)
            if ended and not skipped:
                self._apply_pending_hold()

    def _hold_failed_track(self, track: Track, error: Exception) -> None:
        with contextlib.suppress(Exception):
            self.backend.stop()
        with self._control_lock:
            self._ready = False
            self.playlist.add_next(track)
            intentional_stop = self._stop_playback_requested or self._stop_event.is_set()
            self._failed_track = None if intentional_stop else track
            self._playback_enabled.clear()
            self._hold_after_current.clear()
        # Persist a queue containing the failed track, not both current + queued.
        self._set_current(None)
        if not intentional_stop:
            self._report_error(track, error)

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
        with self._control_lock:
            self._desired_paused = True
            if self._ready:
                self.backend.pause()

    def resume(self) -> None:
        with self._control_lock:
            self._failed_track = None
            self._desired_paused = False
            if self.current_track is None:
                self._stop_playback_requested = False
            if self._ready:
                self.backend.resume()
            self._playback_enabled.set()

    def play(self) -> None:
        """Explicit Play is idempotent: resume, or release a held queue."""
        self.resume()

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
        with self._control_lock:
            if self._failed_track is not None:
                for index, track in enumerate(self.playlist.queue_list):
                    if track is self._failed_track:
                        self.playlist.remove(index)
                        break
                self._failed_track = None
            self._hold_after_current.clear()
            self._playback_enabled.set()
            if self._previous_target is None:
                self._desired_paused = False
            if self._ready:
                self._skip_requested.set()
                self.backend.stop()
                self._ready = False

    def previous(self) -> Literal["restarted", "previous"] | None:
        """Restart after three seconds, otherwise retrace actual playback order."""
        with self._control_lock:
            if not self._ready:
                return None
            status = self.status
            if status.elapsed_seconds >= 3.0 or not self._back_stack:
                self.seek_to(0)
                result: Literal["restarted", "previous"] = "restarted"
            else:
                target = self._back_stack.pop()
                self._previous_target = target
                self._desired_paused = status.state is PlaybackState.PAUSED
                self._skip_requested.set()
                try:
                    self.backend.stop()
                except Exception:
                    self._previous_target = None
                    self._back_stack.append(target)
                    self._skip_requested.clear()
                    raise
                self._ready = False
                result = "previous"
            self._hold_after_current.clear()
            self._playback_enabled.set()
            return result

    def hold_after_current(self) -> None:
        """Finish the active track, then wait before consuming the queue."""
        if self.current_track is None:
            raise RuntimeError("nothing is playing")
        self._hold_after_current.set()

    def stop_playback(self) -> None:
        """Stop without quitting; retain the interrupted track first for Play."""
        with self._control_lock:
            if not self._playback_enabled.is_set() and self._stop_playback_requested:
                return
            if self._ready:
                # If the backend refuses Stop, do not leave the queue held while
                # the current audio is still running.
                self.backend.stop()
            self._stop_playback_requested = True
            self._hold_after_current.clear()
            self._playback_enabled.clear()
            self._desired_paused = False
            self._ready = False

    def cancel_hold_after_current(self) -> None:
        self._hold_after_current.clear()

    @property
    def queue_held(self) -> bool:
        return not self._playback_enabled.is_set()

    @property
    def failure_held(self) -> bool:
        with self._control_lock:
            return self._failed_track is not None and self.queue_held

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
        self._volume = level

    def close(self, *, timeout: float = 3.0) -> None:
        self._stop_event.set()
        if self.cancel_prepare is not None:
            self.cancel_prepare()
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
        with self._control_lock:
            self._ready = False
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
