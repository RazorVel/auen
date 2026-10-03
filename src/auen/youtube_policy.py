"""Shared pacing and cooldown policy for anonymous YouTube operations."""

from __future__ import annotations

import math
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


class YouTubeCooldownError(RuntimeError):
    """Raised before a request while anonymous YouTube access is cooling down."""


class YouTubeRequestGate:
    """Space request starts and stop retries briefly after an access block."""

    def __init__(
        self,
        *,
        minimum_interval_seconds: float = 1.25,
        cooldown_seconds: float = 120.0,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if minimum_interval_seconds < 0:
            raise ValueError("minimum request interval cannot be negative")
        if cooldown_seconds < 0:
            raise ValueError("YouTube cooldown cannot be negative")
        self.minimum_interval_seconds = minimum_interval_seconds
        self.cooldown_seconds = cooldown_seconds
        self._clock = clock
        self._sleeper = sleeper
        self._lock = threading.RLock()
        self._last_started: float | None = None
        self._cooldown_until = 0.0

    @property
    def remaining_seconds(self) -> int:
        with self._lock:
            return max(0, math.ceil(self._cooldown_until - self._clock()))

    def wait_turn(self) -> None:
        """Wait for request spacing, or fail fast during a block cooldown."""
        with self._lock:
            remaining = self.remaining_seconds
            if remaining:
                raise YouTubeCooldownError(
                    "YouTube anonymous access is cooling down. "
                    f"Try again in {_format_wait(remaining)} or use Offline media."
                )
            now = self._clock()
            if self._last_started is not None:
                delay = self.minimum_interval_seconds - (now - self._last_started)
                if delay > 0:
                    self._sleeper(delay)
                    now = self._clock()
            self._last_started = now

    def block(self) -> int:
        """Begin or extend the temporary anonymous-access cooldown."""
        with self._lock:
            self._cooldown_until = max(
                self._cooldown_until,
                self._clock() + self.cooldown_seconds,
            )
            return self.remaining_seconds


def _format_wait(seconds: int) -> str:
    minutes, remainder = divmod(max(0, seconds), 60)
    if minutes:
        return f"{minutes}:{remainder:02d}"
    return f"{remainder}s"
