"""YouTube-only search and stream resolution through yt-dlp."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from yt_dlp import YoutubeDL  # type: ignore[import-untyped]
from yt_dlp.utils import DownloadError  # type: ignore[import-untyped]

from auen.models import Track, TrackSource

_YOUTUBE_HOSTS = {"youtube.com", "youtu.be"}


class YouTubeServiceError(RuntimeError):
    """A user-facing YouTube search or resolution failure."""


class YouTubeService:
    """Search YouTube and resolve selected results without downloading media."""

    def search(self, query: str, *, limit: int = 5) -> list[Track]:
        query = query.strip()
        if not query:
            return []
        if limit < 1:
            raise ValueError("search limit must be at least 1")

        payload = self._extract(f"ytsearch{limit}:{query}", flat=True)
        entries = payload.get("entries") or []
        tracks: list[Track] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            video_id = entry.get("id")
            webpage_url = entry.get("webpage_url") or entry.get("url")
            if webpage_url and not str(webpage_url).startswith(("http://", "https://")):
                webpage_url = None
            uri = webpage_url or (
                f"https://www.youtube.com/watch?v={video_id}" if video_id else None
            )
            title = entry.get("title")
            if not uri or not title:
                continue
            duration = _duration(entry.get("duration"))
            tracks.append(
                Track(
                    title=str(title),
                    source=TrackSource.YOUTUBE,
                    uri=str(uri),
                    duration_seconds=duration,
                    duration_display=_format_duration(duration),
                )
            )
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

    def _extract(self, target: str, *, flat: bool) -> dict[str, Any]:
        options: dict[str, Any] = {
            "extract_flat": flat,
            "format": "bestaudio/best",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
        }
        try:
            with YoutubeDL(options) as ydl:
                result = ydl.extract_info(target, download=False)
        except DownloadError as exc:
            raise YouTubeServiceError(str(exc)) from exc
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
