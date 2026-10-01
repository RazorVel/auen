"""Tests for YouTube search and stream resolution."""

from unittest.mock import MagicMock, patch

import pytest
from yt_dlp.utils import DownloadError

from auen.media.youtube import YouTubeService, YouTubeServiceError, is_youtube_url
from auen.models import Track, TrackSource


def test_youtube_url_validation() -> None:
    assert is_youtube_url("https://www.youtube.com/watch?v=abc")
    assert is_youtube_url("https://music.youtube.com/watch?v=abc")
    assert is_youtube_url("https://youtu.be/abc")
    assert not is_youtube_url("https://example.com/watch?v=abc")
    assert not is_youtube_url("not a url")


def test_search_returns_selectable_tracks() -> None:
    service = YouTubeService()
    response = {
        "entries": [
            {"id": "abc", "title": "First", "duration": 65},
            {
                "id": "def",
                "title": "Second",
                "duration": 3661,
                "webpage_url": "https://www.youtube.com/watch?v=def",
            },
            None,
        ]
    }

    with patch.object(service, "_extract", return_value=response) as extract:
        tracks = service.search("test query", limit=3)

    extract.assert_called_once_with("ytsearch3:test query", flat=True)
    assert [track.title for track in tracks] == ["First", "Second"]
    assert tracks[0].uri == "https://www.youtube.com/watch?v=abc"
    assert tracks[0].duration_display == "1:05"
    assert tracks[1].duration_display == "1:01:01"


def test_resolve_populates_direct_stream_metadata() -> None:
    service = YouTubeService()
    track = Track(
        title="Search title",
        source=TrackSource.YOUTUBE,
        uri="https://youtu.be/abc",
    )
    response = {"title": "Canonical title", "url": "https://media.example/audio", "duration": 90}

    with patch.object(service, "_extract", return_value=response):
        resolved = service.resolve(track)

    assert resolved is track
    assert track.title == "Canonical title"
    assert track.stream_url == "https://media.example/audio"
    assert track.duration_display == "1:30"


def test_resolve_rejects_non_youtube_track() -> None:
    service = YouTubeService()
    track = Track(title="Local", source=TrackSource.LOCAL, uri="/music/local.mp3")

    with pytest.raises(ValueError, match="not a YouTube"):
        service.resolve(track)


def test_resolve_requires_playable_stream() -> None:
    service = YouTubeService()
    track = Track(
        title="Missing",
        source=TrackSource.YOUTUBE,
        uri="https://youtube.com/watch?v=missing",
    )

    with (
        patch.object(service, "_extract", return_value={"title": "Missing"}),
        pytest.raises(YouTubeServiceError, match="playable"),
    ):
        service.resolve(track)


def test_bot_challenge_has_concise_actionable_error() -> None:
    service = YouTubeService()
    extractor = MagicMock()
    extractor.extract_info.side_effect = DownloadError(
        "ERROR: [youtube] abc: Sign in to confirm you\u2019re not a bot. Use --cookies."
    )

    with (
        patch("auen.media.youtube.YoutubeDL") as youtube_dl,
        pytest.raises(YouTubeServiceError, match="requires sign-in") as raised,
    ):
        youtube_dl.return_value.__enter__.return_value = extractor
        service.search("blocked")

    assert "ERROR:" not in str(raised.value)
