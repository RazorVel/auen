"""Tests for YouTube search and stream resolution."""

from unittest.mock import MagicMock, patch

import pytest
from yt_dlp.utils import DownloadError

from auen.media.youtube import (
    YouTubeService,
    YouTubeServiceError,
    is_temporary_youtube_block,
    is_youtube_url,
    youtube_error_message,
)
from auen.models import CollectionKind, MediaCollection, Track, TrackSource
from auen.youtube_policy import YouTubeRequestGate


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

    extract.assert_called_once_with(
        "https://www.youtube.com/results?search_query=test+query",
        flat=True,
        limit=15,
    )
    assert [track.title for track in tracks] == ["First", "Second"]
    assert tracks[0].uri == "https://www.youtube.com/watch?v=abc"
    assert tracks[0].duration_display == "1:05"
    assert tracks[1].duration_display == "1:01:01"


def test_search_includes_a_collection_with_a_type_symbol_model() -> None:
    service = YouTubeService()
    response = {
        "entries": [
            {"id": f"v{index}", "title": f"Track {index}", "duration": 60} for index in range(6)
        ]
        + [
            {
                "id": "PLmix",
                "title": "Someone's mix",
                "url": "https://www.youtube.com/playlist?list=PLmix",
                "ie_key": "YoutubeTab",
            }
        ]
    }

    with patch.object(service, "_extract", return_value=response):
        items = service.search("mix", limit=5)

    assert len(items) == 5
    assert isinstance(items[-1], MediaCollection)
    assert items[-1].kind is CollectionKind.PLAYLIST


def test_search_deduplicates_repeated_video_and_collection_uris() -> None:
    service = YouTubeService()
    response = {
        "entries": [
            {"id": "same", "title": "First copy", "duration": 60},
            {"id": "same", "title": "Second copy", "duration": 60},
            {
                "id": "PLsame",
                "title": "Playlist copy one",
                "url": "https://www.youtube.com/playlist?list=PLsame",
            },
            {
                "id": "PLsame",
                "title": "Playlist copy two",
                "url": "https://www.youtube.com/playlist?list=PLsame",
            },
        ]
    }

    with patch.object(service, "_extract", return_value=response):
        items = service.search("duplicates", limit=5)

    assert len(items) == 2
    assert [item.uri for item in items] == [
        "https://www.youtube.com/watch?v=same",
        "https://www.youtube.com/playlist?list=PLsame",
    ]


def test_official_album_playlist_is_classified_as_album() -> None:
    service = YouTubeService()
    response = {
        "entries": [
            {
                "id": "OLAK5uy_album",
                "title": "Official album",
                "url": "https://www.youtube.com/playlist?list=OLAK5uy_album",
            }
        ]
    }

    with patch.object(service, "_extract", return_value=response):
        items = service.search("album", limit=5)

    assert isinstance(items[0], MediaCollection)
    assert items[0].kind is CollectionKind.ALBUM


def test_collection_tracks_are_bounded_and_selectable() -> None:
    service = YouTubeService()
    collection = MediaCollection(
        title="A mix",
        uri="https://www.youtube.com/playlist?list=PLmix",
    )
    response = {
        "entries": [
            {"id": "abc", "title": "First", "duration": 65},
            {"id": "def", "title": "Second", "duration": 90},
        ]
    }

    with patch.object(service, "_extract", return_value=response) as extract:
        tracks = service.collection_tracks(collection)

    extract.assert_called_once_with(collection.uri, flat=True, limit=100)
    assert [track.title for track in tracks] == ["First", "Second"]
    assert collection.item_count == 2


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
    service = YouTubeService(
        request_gate=YouTubeRequestGate(
            minimum_interval_seconds=0,
            cooldown_seconds=120,
        )
    )
    extractor = MagicMock()
    extractor.extract_info.side_effect = DownloadError(
        "ERROR: [youtube] abc: Sign in to confirm you\u2019re not a bot. Use --cookies."
    )

    with (
        patch("auen.media.youtube.YoutubeDL") as youtube_dl,
        pytest.raises(YouTubeServiceError, match="temporarily blocked") as raised,
    ):
        youtube_dl.return_value.__enter__.return_value = extractor
        service.search("blocked")

    assert "ERROR:" not in str(raised.value)
    assert service.request_gate.remaining_seconds > 0

    with pytest.raises(YouTubeServiceError, match="cooling down"):
        service.search("blocked again")
    assert extractor.extract_info.call_count == 1


@pytest.mark.parametrize(
    "message",
    [
        "ERROR: HTTP Error 429: Too Many Requests",
        "ERROR: Sign in to confirm you're not a bot",
    ],
)
def test_temporary_block_detection(message: str) -> None:
    assert is_temporary_youtube_block(message)


def test_generic_youtube_error_removes_terminal_escape_sequences() -> None:
    assert youtube_error_message("\x1b[0;31mERROR:\x1b[0m unavailable") == (
        "ERROR: unavailable"
    )
