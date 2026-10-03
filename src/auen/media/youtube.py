"""YouTube-only search and stream resolution through yt-dlp."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote_plus, urlparse

from yt_dlp import YoutubeDL  # type: ignore[import-untyped]
from yt_dlp.utils import DownloadError  # type: ignore[import-untyped]

from auen.models import CollectionKind, MediaCollection, SearchItem, Track, TrackSource
from auen.youtube_policy import YouTubeCooldownError, YouTubeRequestGate

_YOUTUBE_HOSTS = {"youtube.com", "youtu.be"}


class YouTubeServiceError(RuntimeError):
    """A user-facing YouTube search or resolution failure."""


class YouTubeService:
    """Search YouTube and resolve selected results without downloading media."""

    def __init__(self, *, request_gate: YouTubeRequestGate | None = None) -> None:
        self.request_gate = request_gate or YouTubeRequestGate()

    def search(self, query: str, *, limit: int = 5) -> list[SearchItem]:
        query = query.strip()
        if not query:
            return []
        if limit < 1:
            raise ValueError("search limit must be at least 1")

        fetch_limit = min(100, max(15, limit * 3))
        target = f"https://www.youtube.com/results?search_query={quote_plus(query)}"
        payload = self._extract(target, flat=True, limit=fetch_limit)
        entries = payload.get("entries") or []
        items: list[SearchItem] = []
        seen: set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            collection = _collection(entry)
            if collection is not None:
                if collection.uri not in seen:
                    seen.add(collection.uri)
                    items.append(collection)
                continue
            track = _track(entry)
            if track is not None and track.uri not in seen:
                seen.add(track.uri)
                items.append(track)
        return _limit_mixed_results(items, limit)

    def collection_tracks(self, collection: MediaCollection, *, limit: int = 100) -> list[Track]:
        """Return a bounded, flat list of selectable tracks from a collection."""
        payload = self._extract(collection.uri, flat=True, limit=limit)
        tracks: list[Track] = []
        for entry in payload.get("entries") or []:
            if not isinstance(entry, dict):
                continue
            track = _track(entry)
            if track is not None:
                tracks.append(track)
        collection.item_count = len(tracks)
        return tracks

    def from_url(self, url: str) -> Track:
        """Validate and resolve one YouTube URL into a playable track."""
        if not is_youtube_url(url):
            raise ValueError("only YouTube URLs are supported")
        track = Track(title="YouTube", source=TrackSource.YOUTUBE, uri=url)
        return self.resolve(track)

    def resolve(self, track: Track) -> Track:
        """Populate a YouTube track with a short-lived direct audio stream URL."""
        if track.source is not TrackSource.YOUTUBE or not is_youtube_url(track.uri):
            raise ValueError("track is not a YouTube video")

        payload = self._extract(track.uri, flat=False)
        stream_url = payload.get("url")
        if not stream_url:
            raise YouTubeServiceError("YouTube did not return a playable audio stream")

        duration = _duration(payload.get("duration"))
        track.title = str(payload.get("title") or track.title)
        track.stream_url = str(stream_url)
        track.duration_seconds = duration
        track.duration_display = _format_duration(duration)
        return track

    def _extract(self, target: str, *, flat: bool, limit: int | None = None) -> dict[str, Any]:
        options: dict[str, Any] = {
            "extract_flat": flat,
            "format": "bestaudio/best",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
        }
        if limit is not None:
            options["playlistend"] = limit
        try:
            self.request_gate.wait_turn()
            with YoutubeDL(options) as ydl:
                result = ydl.extract_info(target, download=False)
        except YouTubeCooldownError as exc:
            raise YouTubeServiceError(str(exc)) from exc
        except DownloadError as exc:
            if is_temporary_youtube_block(exc):
                remaining = self.request_gate.block()
                raise YouTubeServiceError(youtube_blocked_message(remaining)) from exc
            raise YouTubeServiceError(youtube_error_message(exc)) from exc
        if not isinstance(result, dict):
            raise YouTubeServiceError("YouTube returned an invalid response")
        return result


def is_youtube_url(value: str) -> bool:
    try:
        parsed = urlparse(value.strip())
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").casefold().removeprefix("www.")
    return host in _YOUTUBE_HOSTS or host.endswith(".youtube.com")


def _collection(entry: dict[str, Any]) -> MediaCollection | None:
    uri = str(entry.get("webpage_url") or entry.get("url") or "")
    identifier = str(entry.get("id") or "")
    if "/playlist?" not in uri:
        return None
    title = entry.get("title")
    if not title:
        return None
    kind = (
        CollectionKind.ALBUM
        if identifier.startswith("OLAK5uy") or entry.get("album")
        else CollectionKind.PLAYLIST
    )
    count = entry.get("playlist_count")
    return MediaCollection(
        title=str(title),
        uri=uri,
        kind=kind,
        item_count=int(count) if isinstance(count, int) else None,
        collection_id=identifier or uri,
    )


def _track(entry: dict[str, Any]) -> Track | None:
    video_id = entry.get("id")
    uri = entry.get("webpage_url") or entry.get("url")
    if uri and not str(uri).startswith(("http://", "https://")):
        uri = None
    uri = uri or (f"https://www.youtube.com/watch?v={video_id}" if video_id else None)
    title = entry.get("title")
    if not uri or not title or not is_youtube_url(str(uri)):
        return None
    duration = _duration(entry.get("duration"))
    return Track(
        title=str(title),
        source=TrackSource.YOUTUBE,
        uri=str(uri),
        duration_seconds=duration,
        duration_display=_format_duration(duration),
    )


def _limit_mixed_results(items: list[SearchItem], limit: int) -> list[SearchItem]:
    selected = items[:limit]
    if any(isinstance(item, MediaCollection) for item in selected):
        return selected
    collection = next((item for item in items[limit:] if isinstance(item, MediaCollection)), None)
    if collection is not None and selected:
        selected[-1] = collection
    return selected


def _duration(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _format_duration(seconds: float | None) -> str | None:
    if seconds is None:
        return None
    total = max(0, round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def is_temporary_youtube_block(error: BaseException | str) -> bool:
    """Return whether yt-dlp reported an anonymous-access or rate-limit block."""
    message = str(error).casefold()
    return any(
        marker in message
        for marker in (
            "sign in to confirm you\u2019re not a bot",
            "sign in to confirm you're not a bot",
            "http error 429",
            "too many requests",
        )
    )


def youtube_error_message(error: BaseException | str) -> str:
    """Remove terminal escape sequences from an otherwise useful yt-dlp error."""
    return re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", str(error)).strip()


def youtube_blocked_message(remaining: int) -> str:
    minutes, seconds = divmod(max(0, remaining), 60)
    wait = f"{minutes}:{seconds:02d}" if minutes else f"{seconds}s"
    return (
        "YouTube temporarily blocked anonymous access. "
        f"auen paused new YouTube requests for {wait}; use Offline media or try later."
    )
