"""Dependency-free metadata shared by desktop media-control adapters."""

import hashlib
from dataclasses import dataclass

OBJECT_PATH = "/org/mpris/MediaPlayer2"
NO_TRACK = OBJECT_PATH + "/TrackList/NoTrack"


def desktop_track_identity(track_id: str) -> str:
    """An opaque, path-safe identity; never a file path or signed media URL."""
    return OBJECT_PATH + "/track/" + hashlib.sha256(track_id.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MediaSnapshot:
    state: str = "Stopped"
    track_id: str = NO_TRACK
    title: str = ""
    elapsed: float = 0.0
    duration: float | None = None
    art_url: str | None = None
    volume: float = 0.8
    can_next: bool = False
    can_previous: bool = False
    can_play: bool = False
    can_pause: bool = False
    can_seek: bool = False
