"""Domain models for the auen audio player."""

from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path


class TrackSource(Enum):
    LOCAL = auto()
    YOUTUBE = auto()
    URL = auto()


class PlaybackState(Enum):
    STOPPED = auto()
    PLAYING = auto()
    PAUSED = auto()


@dataclass(slots=True)
class Track:
    title: str
    source: TrackSource
    uri: str
    cached_path: Path | None = None
    stream_url: str | None = None
    duration_seconds: float | None = None
    duration_display: str | None = None

    @property
    def is_cached(self) -> bool:
        """Return True if the track is downloaded and the file exists on disk."""
        return self.cached_path is not None and self.cached_path.exists()

    @property
    def playable_uri(self) -> str:
        """Best URI to play right now: cached file > stream URL > original URI."""
        if self.is_cached and self.cached_path is not None:
            return str(self.cached_path)
        if self.stream_url is not None:
            return self.stream_url
        return self.uri


@dataclass(slots=True)
class PlaybackStatus:
    state: PlaybackState
    track: Track | None = None
    elapsed_seconds: float = 0.0
    volume: int = 80
