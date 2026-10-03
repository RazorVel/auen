"""Bounded playback cache and user-managed offline library index."""

from __future__ import annotations

import hashlib
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from typing import TYPE_CHECKING, Concatenate, ParamSpec, TypeVar, cast

if TYPE_CHECKING:
    from collections.abc import Callable

    from auen.models import Track

P = ParamSpec("P")
R = TypeVar("R")


def _locked(
    method: Callable[Concatenate[CacheManager, P], R],
) -> Callable[Concatenate[CacheManager, P], R]:
    @wraps(method)
    def wrapper(self: CacheManager, *args: P.args, **kwargs: P.kwargs) -> R:
        with self._lock:
            return method(self, *args, **kwargs)

    return cast("Callable[Concatenate[CacheManager, P], R]", wrapper)


@dataclass(frozen=True, slots=True)
class CacheEntry:
    source_uri: str
    track_id: str
    title: str
    path: Path
    size_bytes: int
    last_access_ns: int
    pinned: bool
    duration_seconds: float | None = None
    duration_display: str | None = None


@dataclass(frozen=True, slots=True)
class CacheStats:
    cache_bytes: int
    library_bytes: int
    cached_tracks: int
    library_tracks: int


class CacheManager:
    """Own cached files and evict only unpinned entries by least recent use."""

    def __init__(self, root: Path, *, max_cache_bytes: int = 1024**3) -> None:
        if max_cache_bytes < 0:
            raise ValueError("max_cache_bytes cannot be negative")
        self.root = root.expanduser().resolve()
        self.media_dir = self.root / "media"
        self.max_cache_bytes = max_cache_bytes
        self.media_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            self.root / "cache.sqlite3", timeout=5.0, check_same_thread=False
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA synchronous = FULL")
        self._create_schema()
        self.reconcile()

    def _create_schema(self) -> None:
        with self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS media (
                    source_uri TEXT PRIMARY KEY,
                    track_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    path TEXT NOT NULL UNIQUE,
                    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
                    last_access_ns INTEGER NOT NULL,
                    pinned INTEGER NOT NULL DEFAULT 0 CHECK (pinned IN (0, 1)),
                    duration_seconds REAL,
                    duration_display TEXT
                );
                CREATE INDEX IF NOT EXISTS media_lru
                    ON media(pinned, last_access_ns);
                """
            )
            columns = {
                str(row["name"])
                for row in self._connection.execute("PRAGMA table_info(media)").fetchall()
            }
            if "duration_seconds" not in columns:
                self._connection.execute("ALTER TABLE media ADD COLUMN duration_seconds REAL")
            if "duration_display" not in columns:
                self._connection.execute("ALTER TABLE media ADD COLUMN duration_display TEXT")

    def destination_for(self, track: Track, *, extension: str = ".opus") -> Path:
        """Return a stable, safe destination owned by this cache."""
        if not extension.startswith(".") or not re.fullmatch(r"\.[A-Za-z0-9]{1,10}", extension):
            raise ValueError(f"invalid media extension: {extension}")
        safe_title = re.sub(r"[^\w.-]+", "-", track.title, flags=re.UNICODE).strip("-.")
        if not safe_title:
            safe_title = "track"
        digest = hashlib.sha256(track.uri.encode("utf-8")).hexdigest()[:16]
        return self.media_dir / f"{safe_title[:60]}-{digest}{extension.casefold()}"

    @_locked
    def register(self, track: Track, path: Path, *, pinned: bool = False) -> CacheEntry:
        """Index an existing managed file and enforce the automatic-cache limit."""
        managed_path = self._managed_file(path)
        size = managed_path.stat().st_size
        accessed = time.time_ns()
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO media(
                    source_uri, track_id, title, path, size_bytes, last_access_ns, pinned,
                    duration_seconds, duration_display
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_uri) DO UPDATE SET
                    track_id = excluded.track_id,
                    title = excluded.title,
                    path = excluded.path,
                    size_bytes = excluded.size_bytes,
                    last_access_ns = excluded.last_access_ns,
                    pinned = MAX(media.pinned, excluded.pinned),
                    duration_seconds = COALESCE(excluded.duration_seconds, media.duration_seconds),
                    duration_display = COALESCE(excluded.duration_display, media.duration_display)
                """,
                (
                    track.uri,
                    track.track_id,
                    track.title,
                    str(managed_path),
                    size,
                    accessed,
                    int(pinned),
                    track.duration_seconds,
                    track.duration_display,
                ),
            )
        track.cached_path = managed_path
        self.prune()
        entry = self.get(track.uri, touch=False)
        if entry is None:
            track.cached_path = None
            raise ValueError("file exceeds the automatic cache limit; pin it to keep it")
        return entry

    @_locked
    def get(self, source_uri: str, *, touch: bool = True) -> CacheEntry | None:
        row = self._connection.execute(
            "SELECT * FROM media WHERE source_uri = ?", (source_uri,)
        ).fetchone()
        if row is None:
            return None
        path = Path(row["path"])
        if not path.is_file():
            with self._connection:
                self._connection.execute("DELETE FROM media WHERE source_uri = ?", (source_uri,))
            return None
        if touch:
            accessed = time.time_ns()
            with self._connection:
                self._connection.execute(
                    "UPDATE media SET last_access_ns = ? WHERE source_uri = ?",
                    (accessed, source_uri),
                )
            row = dict(row)
            row["last_access_ns"] = accessed
        return _entry_from_row(row)

    @_locked
    def set_pinned(self, source_uri: str, *, pinned: bool) -> CacheEntry | None:
        """Pin an entry, or unpin it and return None if the cache immediately evicts it."""
        with self._connection:
            cursor = self._connection.execute(
                "UPDATE media SET pinned = ?, last_access_ns = ? WHERE source_uri = ?",
                (int(pinned), time.time_ns(), source_uri),
            )
        if cursor.rowcount == 0:
            raise KeyError(source_uri)
        self.prune()
        return self.get(source_uri, touch=False)

    @_locked
    def remove(self, source_uri: str) -> bool:
        """Explicitly remove one cached or pinned file owned by this manager."""
        entry = self.get(source_uri, touch=False)
        if entry is None:
            return False
        managed_path = self._managed_path(entry.path)
        managed_path.unlink(missing_ok=True)
        with self._connection:
            self._connection.execute("DELETE FROM media WHERE source_uri = ?", (source_uri,))
        return True

    @_locked
    def update_duration(
        self,
        source_uri: str,
        duration_seconds: float,
        duration_display: str,
    ) -> bool:
        """Persist duration discovered locally during playback."""
        with self._connection:
            cursor = self._connection.execute(
                """
                UPDATE media
                SET duration_seconds = ?, duration_display = ?
                WHERE source_uri = ?
                """,
                (duration_seconds, duration_display, source_uri),
            )
        return cursor.rowcount > 0

    @_locked
    def prune(self) -> list[Path]:
        """Evict least-recently-used unpinned files until the cache fits its limit."""
        rows = self._connection.execute(
            "SELECT * FROM media WHERE pinned = 0 ORDER BY last_access_ns, source_uri"
        ).fetchall()
        total = sum(int(row["size_bytes"]) for row in rows)
        removed: list[Path] = []
        for row in rows:
            if total <= self.max_cache_bytes:
                break
            path = self._managed_path(Path(row["path"]))
            path.unlink(missing_ok=True)
            total -= int(row["size_bytes"])
            removed.append(path)
            with self._connection:
                self._connection.execute(
                    "DELETE FROM media WHERE source_uri = ?", (row["source_uri"],)
                )
        return removed

    @_locked
    def list_entries(self, *, pinned: bool | None = None) -> list[CacheEntry]:
        if pinned is None:
            rows = self._connection.execute(
                "SELECT * FROM media ORDER BY pinned DESC, title COLLATE NOCASE"
            ).fetchall()
        else:
            rows = self._connection.execute(
                "SELECT * FROM media WHERE pinned = ? ORDER BY title COLLATE NOCASE",
                (int(pinned),),
            ).fetchall()
        return [_entry_from_row(row) for row in rows if Path(row["path"]).is_file()]

    @_locked
    def stats(self) -> CacheStats:
        row = self._connection.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN pinned = 0 THEN size_bytes ELSE 0 END), 0) cache_bytes,
                COALESCE(SUM(CASE WHEN pinned = 1 THEN size_bytes ELSE 0 END), 0) library_bytes,
                SUM(CASE WHEN pinned = 0 THEN 1 ELSE 0 END) cached_tracks,
                SUM(CASE WHEN pinned = 1 THEN 1 ELSE 0 END) library_tracks
            FROM media
            """
        ).fetchone()
        return CacheStats(
            cache_bytes=int(row["cache_bytes"]),
            library_bytes=int(row["library_bytes"]),
            cached_tracks=int(row["cached_tracks"] or 0),
            library_tracks=int(row["library_tracks"] or 0),
        )

    @_locked
    def reconcile(self) -> int:
        """Drop stale database records while leaving unindexed files untouched."""
        rows = self._connection.execute("SELECT source_uri, path FROM media").fetchall()
        missing = [row["source_uri"] for row in rows if not Path(row["path"]).is_file()]
        with self._connection:
            self._connection.executemany(
                "DELETE FROM media WHERE source_uri = ?", [(source_uri,) for source_uri in missing]
            )
        return len(missing)

    @_locked
    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> CacheManager:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _managed_file(self, path: Path) -> Path:
        managed_path = self._managed_path(path)
        if path.is_symlink() or not managed_path.is_file():
            raise ValueError(f"cache file does not exist or is a symlink: {path}")
        return managed_path

    def _managed_path(self, path: Path) -> Path:
        resolved = path.expanduser().resolve()
        try:
            resolved.relative_to(self.media_dir)
        except ValueError as exc:
            raise ValueError(f"refusing to manage file outside cache: {path}") from exc
        return resolved


def _entry_from_row(row: sqlite3.Row | dict[str, object]) -> CacheEntry:
    return CacheEntry(
        source_uri=str(row["source_uri"]),
        track_id=str(row["track_id"]),
        title=str(row["title"]),
        path=Path(str(row["path"])),
        size_bytes=int(str(row["size_bytes"])),
        last_access_ns=int(str(row["last_access_ns"])),
        pinned=bool(row["pinned"]),
        duration_seconds=(
            float(str(row["duration_seconds"]))
            if row["duration_seconds"] is not None
            else None
        ),
        duration_display=(
            str(row["duration_display"])
            if row["duration_display"] is not None
            else None
        ),
    )
