"""Domain models for the auen audio player."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from uuid import uuid4


class TrackSource(Enum):
    LOCAL = auto()
    YOUTUBE = auto()
    URL = auto()


class PlaybackState(Enum):
    STOPPED = auto()
    PLAYING = auto()
    PAUSED = auto()


class RepeatMode(str, Enum):
    """How the player behaves after a track or queue finishes."""

    OFF = "off"
    ALL = "all"
    ONE = "one"


class SessionMode(str, Enum):
    """Remote-media behavior selected when a session starts."""

    ASK = "ask"
    STREAM_ONLY = "stream_only"
    STREAM_AND_CACHE = "stream_and_cache"


class CollectionKind(str, Enum):
    """A browsable group returned by YouTube search."""

    ALBUM = "album"
    PLAYLIST = "playlist"


@dataclass(slots=True)
class Track:
    title: str
    source: TrackSource
    uri: str
    cached_path: Path | None = None
    stream_url: str | None = None
    duration_seconds: float | None = None
    duration_display: str | None = None
    track_id: str = field(default_factory=lambda: uuid4().hex)

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
class HistoryEntry:
    """One unique track in the durable recently played history."""

    track: Track
    last_played_at: datetime
    play_count: int = 1


@dataclass(slots=True, frozen=True)
class SavedPlaylist:
    """A durable user-named ordered collection."""

    playlist_id: int
    name: str
    track_count: int = 0


@dataclass(slots=True)
class MediaCollection:
    title: str
    uri: str
    kind: CollectionKind = CollectionKind.PLAYLIST
    item_count: int | None = None
    collection_id: str = field(default_factory=lambda: uuid4().hex)


SearchItem = Track | MediaCollection


@dataclass(slots=True)
class PlaybackStatus:
    state: PlaybackState
    track: Track | None = None
    elapsed_seconds: float = 0.0
    duration_seconds: float | None = None
    volume: int = 80
