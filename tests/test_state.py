"""Tests for crash-safe session persistence."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from auen.models import RepeatMode, Track, TrackSource
from auen.state import SessionSnapshot, StateStore


def make_track(title: str, source: TrackSource = TrackSource.LOCAL) -> Track:
    return Track(title=title, source=source, uri=f"/{title}.opus")


def test_empty_store_loads_empty_session(tmp_path: Path) -> None:
    with StateStore(tmp_path / "state.sqlite3") as store:
        snapshot = store.load()

    assert snapshot.queue == []
    assert snapshot.history == []
    assert snapshot.current_track is None
    assert snapshot.repeat_mode is RepeatMode.OFF


def test_session_round_trip_preserves_track_identity_and_order(tmp_path: Path) -> None:
    first = make_track("first")
    second = Track(
        title="second",
        source=TrackSource.YOUTUBE,
        uri="https://www.youtube.com/watch?v=example",
        cached_path=tmp_path / "second.opus",
        stream_url="https://stream.example/audio",
        duration_seconds=123.5,
        duration_display="2:03",
    )
    snapshot = SessionSnapshot(
        queue=[first, second],
        history=[make_track("played")],
        current_track=second,
        elapsed_seconds=42.25,
        shuffle=True,
        repeat_mode=RepeatMode.ALL,
    )

    with StateStore(tmp_path / "state.sqlite3") as store:
        store.save(snapshot)
        restored = store.load()

    assert [track.track_id for track in restored.queue] == [first.track_id, second.track_id]
    assert [track.title for track in restored.queue] == ["first", "second"]
    assert restored.current_track is not None
    assert restored.current_track.track_id == second.track_id
    assert restored.current_track.cached_path == tmp_path / "second.opus"
    assert restored.elapsed_seconds == 42.25
    assert restored.shuffle is True
    assert restored.repeat_mode is RepeatMode.ALL


def test_clear_removes_only_saved_session(tmp_path: Path) -> None:
    database = tmp_path / "state.sqlite3"
    with StateStore(database) as store:
        store.save(SessionSnapshot(queue=[make_track("queued")]))
        store.clear()
        restored = store.load()

    assert database.exists()
    assert restored.queue == []


def test_recent_history_deduplicates_counts_orders_and_prunes(tmp_path: Path) -> None:
    base = datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc)
    first = make_track("first")
    second = make_track("second")
    third = make_track("third")

    with StateStore(tmp_path / "state.sqlite3") as store:
        store.record_play(first, played_at=base, limit=2)
        store.record_play(second, played_at=base + timedelta(minutes=1), limit=2)
        store.record_play(first, played_at=base + timedelta(minutes=2), limit=2)
        store.record_play(third, played_at=base + timedelta(minutes=3), limit=2)
        history = store.load_recent_history()

    assert [entry.track.title for entry in history] == ["third", "first"]
    assert history[1].play_count == 2
    assert history[1].last_played_at == base + timedelta(minutes=2)


def test_recent_history_survives_session_clear_and_supports_removal(tmp_path: Path) -> None:
    track = make_track("played")

    with StateStore(tmp_path / "state.sqlite3") as store:
        store.record_play(track)
        store.save(SessionSnapshot(queue=[make_track("queued")]))
        store.clear()

        assert [entry.track.uri for entry in store.load_recent_history()] == [track.uri]
        assert store.remove_recent_history(track.uri)
        assert not store.remove_recent_history(track.uri)

        store.record_play(track)
        store.clear_recent_history()
        assert store.load_recent_history() == []
