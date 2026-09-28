"""Thread-safe track queue with history, shuffle, and loop."""

import random
import threading
from collections import deque
from collections.abc import Iterable

from auen.models import RepeatMode, Track


class Playlist:
    """Thread-safe track queue with history, shuffle, and loop."""

    def __init__(self) -> None:
        self._queue: deque[Track] = deque()
        self._history: list[Track] = []
        self._lock = threading.Lock()
        self._available = threading.Event()
        self.shuffle = False
        self.repeat_mode = RepeatMode.OFF

    def add(self, track: Track) -> None:
        with self._lock:
            self._queue.append(track)
            self._available.set()

    def add_many(self, tracks: Iterable[Track]) -> None:
        with self._lock:
            for track in tracks:
                self._queue.append(track)
            if self._queue:
                self._available.set()

    def next(self, timeout: float | None = None) -> Track | None:
        """Block until a track is available or timeout. Returns None on timeout."""
        if not self._available.wait(timeout):
            return None

        with self._lock:
            if not self._queue:
                self._available.clear()
                return None

            if self.shuffle and len(self._queue) > 1:
                # Pick random track from queue (except head unless we have to,
                # but simple random choice from entire queue is fine here)
                idx = random.randrange(len(self._queue))
                # Swap it to the front so we can popleft
                self._queue[0], self._queue[idx] = self._queue[idx], self._queue[0]

            track = self._queue.popleft()

            if not self._queue:
                self._available.clear()

            return track

    def peek(self) -> Track | None:
        with self._lock:
            if not self._queue:
                return None
            return self._queue[0]

    def skip(self) -> Track | None:
        """Remove and return the current head without waiting."""
        with self._lock:
            if not self._queue:
                return None

            track = self._queue.popleft()
            if not self._queue:
                self._available.clear()
            return track

    def remove(self, index: int) -> Track | None:
        with self._lock:
            if index < 0 or index >= len(self._queue):
                return None

            # Since deque doesn't support pop(index), we do it manually
            # O(N) is fine for a music queue
            track = self._queue[index]
            del self._queue[index]

            if not self._queue:
                self._available.clear()
            return track

    def jump(self, index: int) -> Track | None:
        """Move track at index to head and return it."""
        with self._lock:
            if index < 0 or index >= len(self._queue):
                return None

            track = self._queue[index]
            del self._queue[index]
            self._queue.appendleft(track)
            return track

    def mark_played(self, track: Track) -> None:
        """Move a track to history."""
        with self._lock:
            self._history.append(track)

    def complete(self, track: Track) -> None:
        """Record a finished track and apply the active repeat behavior atomically."""
        with self._lock:
            self._history.append(track)

            if self.repeat_mode is RepeatMode.ONE:
                self._queue.appendleft(track)
                self._available.set()
            elif self.repeat_mode is RepeatMode.ALL and not self._queue:
                self._queue.extend(self._history)
                self._history.clear()
                self._available.set()

    def recycle(self) -> None:
        """If loop is on, move history back to queue."""
        with self._lock:
            if self.repeat_mode is RepeatMode.ALL and self._history:
                self._queue.extend(self._history)
                self._history.clear()
                self._available.set()

    def clear(self) -> None:
        with self._lock:
            self._queue.clear()
            self._available.clear()

    def clear_history(self) -> None:
        with self._lock:
            self._history.clear()

    def restore(self, queue: Iterable[Track], history: Iterable[Track]) -> None:
        """Atomically replace queue and history from a persisted session."""
        with self._lock:
            self._queue = deque(queue)
            self._history = list(history)
            if self._queue:
                self._available.set()
            else:
                self._available.clear()

    @property
    def queue_list(self) -> list[Track]:
        with self._lock:
            return list(self._queue)

    @property
    def history_list(self) -> list[Track]:
        with self._lock:
            return list(self._history)

    @property
    def queue_length(self) -> int:
        with self._lock:
            return len(self._queue)

    @property
    def history_length(self) -> int:
        with self._lock:
            return len(self._history)
