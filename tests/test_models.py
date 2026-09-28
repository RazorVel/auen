"""Tests for the models module."""

from pathlib import Path

from auen.models import PlaybackState, PlaybackStatus, Track, TrackSource


def test_track_playable_uri_prefers_cache(tmp_path: Path) -> None:
    cached_file = tmp_path / "test.opus"
    cached_file.touch()

    track = Track(
        title="Test",
        source=TrackSource.YOUTUBE,
        uri="https://youtube.com/watch?v=123",
        cached_path=cached_file,
        stream_url="https://stream.url",
    )
    assert track.is_cached is True
    assert track.playable_uri == str(cached_file)


def test_track_playable_uri_falls_back_to_stream() -> None:
    track = Track(
        title="Test",
        source=TrackSource.YOUTUBE,
        uri="https://youtube.com/watch?v=123",
        stream_url="https://stream.url",
    )
    assert track.is_cached is False
    assert track.playable_uri == "https://stream.url"


def test_track_playable_uri_falls_back_to_original() -> None:
    track = Track(
        title="Test",
        source=TrackSource.LOCAL,
        uri="/path/to/file.opus",
    )
    assert track.is_cached is False
    assert track.playable_uri == "/path/to/file.opus"


def test_track_source_enum() -> None:
    assert TrackSource.LOCAL.name == "LOCAL"
    assert TrackSource.YOUTUBE.name == "YOUTUBE"
    assert TrackSource.URL.name == "URL"


def test_playback_status() -> None:
    status = PlaybackStatus(state=PlaybackState.PLAYING, volume=50)
    assert status.state == PlaybackState.PLAYING
    assert status.volume == 50
    assert status.track is None
    assert status.elapsed_seconds == 0.0
