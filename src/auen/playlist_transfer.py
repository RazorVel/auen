"""Versioned, offline track-list transfer without machine-specific cache paths."""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlsplit

from auen.models import Track, TrackSource

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

FORMAT = "auen-playlist"
BUNDLE_FORMAT = "auen-playlists"
VERSION = 1
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TRACKS = 10_000


def track_source_key(track: Track) -> tuple[str, str]:
    """Compare YouTube video identities, including short and alternate URL forms."""
    if track.source is TrackSource.YOUTUBE:
        parsed = urlsplit(track.uri)
        host = (parsed.hostname or "").casefold()
        video_id = None
        if host == "youtu.be":
            video_id = parsed.path.strip("/").split("/")[0]
        elif host in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}:
            if parsed.path == "/watch":
                video_id = parse_qs(parsed.query).get("v", [None])[0]
            else:
                parts = parsed.path.strip("/").split("/")
                if len(parts) == 2 and parts[0] in {"shorts", "embed", "live"}:
                    video_id = parts[1]
        if video_id:
            return ("youtube", video_id)
    return (track.source.name.lower(), track.uri)


@dataclass(frozen=True)
class PlaylistDocument:
    name: str
    tracks: list[Track]


def export_playlist(name: str, tracks: Sequence[Track], destination: Path) -> Path:
    """Write a new UTF-8 JSON file; never overwrite an existing file."""
    document = {"format": FORMAT, "version": VERSION, **_playlist_payload(name, tracks)}
    return _write_document(document, destination)


def export_playlists(playlists: Sequence[PlaylistDocument], destination: Path) -> Path:
    """Export multiple named playlists into one track-list bundle."""
    document = {
        "format": BUNDLE_FORMAT,
        "version": VERSION,
        "playlists": [_playlist_payload(item.name, item.tracks) for item in playlists],
    }
    return _write_document(document, destination)


def _playlist_payload(name: str, tracks: Sequence[Track]) -> dict[str, Any]:
    return {
        "name": name,
        "tracks": [
            {
                "title": track.title,
                "source": track.source.name.lower(),
                "uri": track.uri,
                "duration_seconds": track.duration_seconds,
                "duration_display": track.duration_display,
            }
            for track in tracks
        ],
    }


def _write_document(document: dict[str, Any], destination: Path) -> Path:
    _decode_playlists(document)
    encoded = json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if len(encoded.encode("utf-8")) > MAX_FILE_BYTES:
        raise ValueError("playlist file exceeds 10 MiB")
    destination = destination.expanduser()
    with destination.open("x", encoding="utf-8", newline="\n") as output:
        try:
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        except BaseException:
            output.close()
            destination.unlink(missing_ok=True)
            raise
    return destination


def read_playlist(source: Path) -> PlaylistDocument:
    playlists = read_playlists(source)
    if len(playlists) != 1:
        raise ValueError("expected one playlist; this file contains a playlist bundle")
    return playlists[0]


def read_playlists(source: Path) -> list[PlaylistDocument]:
    """Validate the complete file before any persistent state is modified."""
    with source.expanduser().open("rb") as input_file:
        data = input_file.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("playlist file exceeds 10 MiB")
    try:
        document = json.loads(data.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("playlist file must contain valid UTF-8 JSON") from exc
    return _decode_playlists(document)


def _decode_playlists(value: Any) -> list[PlaylistDocument]:
    if not isinstance(value, dict) or value.get("format") not in {FORMAT, BUNDLE_FORMAT}:
        raise ValueError("not an auen playlist file")
    if type(value.get("version")) is not int or value["version"] != VERSION:
        raise ValueError("unsupported playlist format version")
    if value["format"] == FORMAT:
        return [_decode_document(value)]
    items = value.get("playlists")
    if not isinstance(items, list) or len(items) > 1000:
        raise ValueError("playlists must be a list of at most 1000 entries")
    result = []
    names: set[str] = set()
    for index, item in enumerate(items, start=1):
        try:
            document = _decode_document(item)
        except ValueError as exc:
            raise ValueError(f"playlist {index}: {exc}") from exc
        normalized = " ".join(document.name.split()).casefold()
        if normalized in names:
            raise ValueError(f"duplicate playlist name in file: {document.name}")
        names.add(normalized)
        result.append(document)
    return result


def _text(value: Any, label: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError(f"invalid {label}")
    return value


def _decode_document(value: Any) -> PlaylistDocument:
    if not isinstance(value, dict):
        raise ValueError("playlist entry must be an object")
    name = _text(value.get("name"), "playlist name", 80).strip()
    items = value.get("tracks")
    if not isinstance(items, list) or len(items) > MAX_TRACKS:
        raise ValueError("tracks must be a list of at most 10000 entries")
    tracks = []
    for index, item in enumerate(items, start=1):
        try:
            tracks.append(_decode_track(item))
        except ValueError as exc:
            raise ValueError(f"track {index}: {exc}") from exc
    return PlaylistDocument(name, tracks)


def _decode_track(value: Any) -> Track:
    if not isinstance(value, dict):
        raise ValueError("entry must be an object")
    title = _text(value.get("title"), "title", 8192)
    uri = _text(value.get("uri"), "URI", 16384)
    try:
        source = TrackSource[value["source"].upper()]
    except (KeyError, AttributeError, TypeError) as exc:
        raise ValueError("invalid track source") from exc
    if source is not TrackSource.LOCAL:
        parsed = urlsplit(uri)
        if parsed.scheme not in {"https", "http"} or not parsed.hostname:
            raise ValueError("remote URI must be an HTTP or HTTPS URL")
    duration = value.get("duration_seconds")
    if duration is not None and (
        type(duration) not in {int, float}
        or not 0 <= duration <= 315360000
        or not math.isfinite(duration)
    ):
        raise ValueError("invalid duration")
    display = value.get("duration_display")
    if display is not None:
        display = _text(display, "duration display", 32)
    return Track(
        title=title,
        source=source,
        uri=uri,
        duration_seconds=duration,
        duration_display=display,
    )
