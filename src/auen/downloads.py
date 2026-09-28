"""Bounded, deduplicated downloads into the managed cache."""

from __future__ import annotations

import os
import tempfile
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any

from yt_dlp import YoutubeDL  # type: ignore[import-untyped]
from yt_dlp.utils import DownloadError  # type: ignore[import-untyped]

from auen.media.youtube import is_youtube_url
from auen.models import Track, TrackSource

if TYPE_CHECKING:
    from auen.cache import CacheEntry, CacheManager


class DownloadServiceError(RuntimeError):
    """A user-facing media download failure."""


class DownloadManager:
    """Download at most a configured number of distinct tracks concurrently."""

    def __init__(self, cache: CacheManager, *, max_workers: int = 4) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be at least 1")
        self.cache = cache
        self.max_workers = max_workers
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="auen-dl")
        self._lock = threading.RLock()
        self._inflight: dict[str, Future[CacheEntry]] = {}
        self._pin_requests: set[str] = set()
        self._closed = False

    def submit(self, track: Track, *, pinned: bool = False) -> Future[CacheEntry]:
        """Return one shared future per URI, upgrading duplicate requests to pinned."""
        if track.source is not TrackSource.YOUTUBE or not is_youtube_url(track.uri):
            raise ValueError("only YouTube tracks can be downloaded")

        with self._lock:
            if self._closed:
                raise RuntimeError("download manager is closed")
            if pinned:
                self._pin_requests.add(track.uri)

            existing_entry = self.cache.get(track.uri)
            if existing_entry is not None:
                if pinned and not existing_entry.pinned:
                    pinned_entry = self.cache.set_pinned(track.uri, pinned=True)
                    if pinned_entry is not None:
                        existing_entry = pinned_entry
                track.cached_path = existing_entry.path
                return _completed_future(existing_entry)

            existing_future = self._inflight.get(track.uri)
            if existing_future is not None:
                existing_future.add_done_callback(partial(_copy_cached_path, track=track))
                return existing_future

            future = self._executor.submit(self._download_and_register, track)
            self._inflight[track.uri] = future
            future.add_done_callback(partial(self._finished, track.uri))
            return future

    def _download_and_register(self, track: Track) -> CacheEntry:
        temp_root = self.cache.root / "tmp"
        temp_root.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.TemporaryDirectory(prefix="download-", dir=temp_root) as temporary:
                downloaded = self._download_file(track, Path(temporary))
                destination = self.cache.destination_for(track, extension=downloaded.suffix)
                os.replace(downloaded, destination)
                with self._lock:
                    pinned = track.uri in self._pin_requests
                return self.cache.register(track, destination, pinned=pinned)
        except DownloadServiceError:
            raise
        except (OSError, ValueError) as exc:
            raise DownloadServiceError(str(exc)) from exc

    def _download_file(self, track: Track, directory: Path) -> Path:
        output = directory / "media.%(ext)s"
        options: dict[str, Any] = {
            "format": "bestaudio/best",
            "noplaylist": True,
            "outtmpl": str(output),
            "quiet": True,
            "no_warnings": True,
        }
        try:
            with YoutubeDL(options) as ydl:
                ydl.extract_info(track.uri, download=True)
        except DownloadError as exc:
            raise DownloadServiceError(str(exc)) from exc

        files = [
            candidate
            for candidate in directory.iterdir()
            if candidate.is_file() and not candidate.name.endswith((".part", ".ytdl"))
        ]
        if len(files) != 1:
            raise DownloadServiceError("download did not produce exactly one media file")
        return files[0]

    def _finished(self, uri: str, _future: Future[CacheEntry]) -> None:
        with self._lock:
            self._inflight.pop(uri, None)
            self._pin_requests.discard(uri)

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._inflight)

    def close(self, *, wait: bool = True, cancel_pending: bool = False) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._executor.shutdown(wait=wait, cancel_futures=cancel_pending)

    def __enter__(self) -> DownloadManager:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def _completed_future(entry: CacheEntry) -> Future[CacheEntry]:
    future: Future[CacheEntry] = Future()
    future.set_result(entry)
    return future


def _copy_cached_path(future: Future[CacheEntry], track: Track) -> None:
    if future.cancelled() or future.exception() is not None:
        return
    track.cached_path = future.result().path
