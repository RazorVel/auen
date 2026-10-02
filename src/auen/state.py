"""Crash-safe persistence for queue, history, and interrupted playback."""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from platformdirs import user_state_dir

from auen.models import HistoryEntry, RepeatMode, Track, TrackSource


@dataclass(slots=True)
class SessionSnapshot:
    """The minimum state needed to recover an interrupted session."""

    queue: list[Track] = field(default_factory=list)
    history: list[Track] = field(default_factory=list)
    current_track: Track | None = None
    elapsed_seconds: float = 0.0
    shuffle: bool = False
    repeat_mode: RepeatMode = RepeatMode.OFF


class StateStore:
    """Transactional SQLite store for rapidly changing application state."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path(user_state_dir("auen")) / "state.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.path, timeout=5.0, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA synchronous = FULL")
        self._create_schema()

    def _create_schema(self) -> None:
        with self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS session (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    current_track TEXT,
                    elapsed_seconds REAL NOT NULL DEFAULT 0,
                    shuffle INTEGER NOT NULL DEFAULT 0,
                    repeat_mode TEXT NOT NULL DEFAULT 'off',
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS queue_items (
                    position INTEGER PRIMARY KEY,
                    track TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS history_items (
                    position INTEGER PRIMARY KEY,
                    track TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS recent_plays (
                    uri TEXT PRIMARY KEY,
                    track TEXT NOT NULL,
                    last_played_at TEXT NOT NULL,
                    play_count INTEGER NOT NULL DEFAULT 1
                );

                PRAGMA user_version = 2;
                """
            )

    def record_play(
        self,
        track: Track,
        *,
        limit: int = 500,
        played_at: datetime | None = None,
    ) -> None:
        """Upsert a track in recent history and prune the oldest unique entries."""
        if limit < 1:
            raise ValueError("history limit must be at least 1")
        timestamp = played_at or datetime.now(timezone.utc)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        encoded_timestamp = timestamp.astimezone(timezone.utc).isoformat()
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO recent_plays(uri, track, last_played_at, play_count)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(uri) DO UPDATE SET
                    track = excluded.track,
                    last_played_at = excluded.last_played_at,
                    play_count = recent_plays.play_count + 1
                """,
                (track.uri, _encode_track(track), encoded_timestamp),
            )
            self._prune_recent_history(limit)

    def load_recent_history(self, *, limit: int = 500) -> list[HistoryEntry]:
        """Return unique tracks ordered from most to least recently played."""
        if limit < 1:
            return []
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT track, last_played_at, play_count
                FROM recent_plays
                ORDER BY last_played_at DESC, uri
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            HistoryEntry(
                track=_decode_track(row["track"]),
                last_played_at=datetime.fromisoformat(row["last_played_at"]),
                play_count=int(row["play_count"]),
            )
            for row in rows
        ]

    def remove_recent_history(self, uri: str) -> bool:
        """Remove one track from recent history."""
        with self._lock, self._connection:
            cursor = self._connection.execute("DELETE FROM recent_plays WHERE uri = ?", (uri,))
        return cursor.rowcount > 0

    def clear_recent_history(self) -> None:
        """Remove all user-facing playback history without changing the queue."""
        with self._lock, self._connection:
            self._connection.execute("DELETE FROM recent_plays")

    def prune_recent_history(self, limit: int) -> None:
        """Apply a new history size limit immediately."""
        if limit < 1:
            raise ValueError("history limit must be at least 1")
        with self._lock, self._connection:
            self._prune_recent_history(limit)

    def _prune_recent_history(self, limit: int) -> None:
        self._connection.execute(
            """
            DELETE FROM recent_plays
            WHERE uri NOT IN (
                SELECT uri FROM recent_plays
                ORDER BY last_played_at DESC, uri
                LIMIT ?
            )
            """,
            (limit,),
        )

    def save(self, snapshot: SessionSnapshot) -> None:
        """Replace the saved session in one durable transaction."""
        with self._lock, self._connection:
            self._connection.execute("DELETE FROM queue_items")
            self._connection.executemany(
                "INSERT INTO queue_items(position, track) VALUES (?, ?)",
                [
                    (position, _encode_track(track))
                    for position, track in enumerate(snapshot.queue)
                ],
            )
            self._connection.execute("DELETE FROM history_items")
            self._connection.executemany(
                "INSERT INTO history_items(position, track) VALUES (?, ?)",
                [
                    (position, _encode_track(track))
                    for position, track in enumerate(snapshot.history)
                ],
            )
            current_track = (
                _encode_track(snapshot.current_track)
                if snapshot.current_track is not None
                else None
            )
            self._connection.execute(
                """
                INSERT INTO session(
                    id, current_track, elapsed_seconds, shuffle, repeat_mode, updated_at
                ) VALUES (1, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    current_track = excluded.current_track,
                    elapsed_seconds = excluded.elapsed_seconds,
                    shuffle = excluded.shuffle,
                    repeat_mode = excluded.repeat_mode,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    current_track,
                    max(0.0, snapshot.elapsed_seconds),
                    int(snapshot.shuffle),
                    snapshot.repeat_mode.value,
                ),
            )

    def load(self) -> SessionSnapshot:
        """Load the last complete snapshot, or an empty session on first use."""
        with self._lock:
            row = self._connection.execute("SELECT * FROM session WHERE id = 1").fetchone()
            if row is None:
                return SessionSnapshot()

            queue = [
                _decode_track(item["track"])
                for item in self._connection.execute(
                    "SELECT track FROM queue_items ORDER BY position"
                ).fetchall()
            ]
            history = [
                _decode_track(item["track"])
                for item in self._connection.execute(
                    "SELECT track FROM history_items ORDER BY position"
                ).fetchall()
            ]
            current_track = _decode_track(row["current_track"]) if row["current_track"] else None

        return SessionSnapshot(
            queue=queue,
            history=history,
            current_track=current_track,
            elapsed_seconds=float(row["elapsed_seconds"]),
            shuffle=bool(row["shuffle"]),
            repeat_mode=RepeatMode(row["repeat_mode"]),
        )

    def clear(self) -> None:
        """Forget session recovery data without touching settings or media."""
        with self._lock, self._connection:
            self._connection.execute("DELETE FROM session")
            self._connection.execute("DELETE FROM queue_items")
            self._connection.execute("DELETE FROM history_items")

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> StateStore:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def _encode_track(track: Track) -> str:
    data = {
        "track_id": track.track_id,
        "title": track.title,
        "source": track.source.name,
        "uri": track.uri,
        "cached_path": str(track.cached_path) if track.cached_path is not None else None,
        "stream_url": track.stream_url,
        "duration_seconds": track.duration_seconds,
        "duration_display": track.duration_display,
    }
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _decode_track(payload: str) -> Track:
    data: dict[str, Any] = json.loads(payload)
    cached_path = Path(data["cached_path"]) if data.get("cached_path") else None
    return Track(
        title=str(data["title"]),
        source=TrackSource[str(data["source"])],
        uri=str(data["uri"]),
        cached_path=cached_path,
        stream_url=data.get("stream_url"),
        duration_seconds=data.get("duration_seconds"),
        duration_display=data.get("duration_display"),
        track_id=str(data["track_id"]),
    )
