"""Application-level coordination for media, queue, cache, and recovery state."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from auen.cache import CacheEntry, CacheManager
from auen.downloads import DownloadManager
from auen.media.youtube import YouTubeService, is_youtube_url
from auen.models import RepeatMode, SessionMode, Track
from auen.playlist import Playlist
from auen.state import SessionSnapshot, StateStore

if TYPE_CHECKING:
    from concurrent.futures import Future

    from auen.config import AuenConfig


class AuenSession:
    """Keep UI actions thin and persist every meaningful queue mutation."""

    def __init__(
        self,
        config: AuenConfig,
        *,
        state: StateStore | None = None,
        cache: CacheManager | None = None,
        downloads: DownloadManager | None = None,
        youtube: YouTubeService | None = None,
    ) -> None:
        self.config = config
        self.state = state or StateStore(config.state_dir / "state.sqlite3")
        self.cache = cache or CacheManager(
            config.cache_dir,
            max_cache_bytes=config.cache_max_bytes,
        )
        self.downloads = downloads or DownloadManager(
            self.cache,
            max_workers=config.max_download_threads,
        )
        self.youtube = youtube or YouTubeService()
        self._search_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="auen-search")
        self.playlist = Playlist()
        self.current_track: Track | None = None
        self.elapsed_seconds = 0.0

        self.playlist.shuffle = config.shuffle
        self.playlist.repeat_mode = RepeatMode(config.repeat_mode)
        if config.restore_session:
            self._restore()

    def search(self, query_or_url: str) -> list[Track]:
        value = query_or_url.strip()
        if not value:
            return []
        if is_youtube_url(value):
            return [self.youtube.from_url(value)]
        return self.youtube.search(value, limit=self.config.search_result_count)

    def submit_search(self, query_or_url: str) -> Future[list[Track]]:
        """Run one search outside the UI thread on an executor owned by this session."""
        return self._search_executor.submit(self.search, query_or_url)

    def enqueue(
        self,
        track: Track,
        *,
        session_mode: SessionMode = SessionMode.STREAM_ONLY,
    ) -> Future[CacheEntry] | None:
        cached = self.cache.get(track.uri)
        if cached is not None:
            track.cached_path = cached.path
        self.playlist.add(track)
        self.save()
        if session_mode is SessionMode.STREAM_AND_CACHE and not track.is_cached:
            return self.downloads.submit(track)
        return None

    def save_offline(self, track: Track) -> Future[CacheEntry]:
        return self.downloads.submit(track, pinned=True)

    def remove_queued(self, index: int) -> Track | None:
        removed = self.playlist.remove(index)
        if removed is not None:
            self.save()
        return removed

    def save(self) -> None:
        self.state.save(
            SessionSnapshot(
                queue=self.playlist.queue_list,
                history=self.playlist.history_list,
                current_track=self.current_track,
                elapsed_seconds=self.elapsed_seconds,
                shuffle=self.playlist.shuffle,
                repeat_mode=self.playlist.repeat_mode,
            )
        )

    def _restore(self) -> None:
        snapshot = self.state.load()
        self.playlist.restore(snapshot.queue, snapshot.history)
        self.playlist.shuffle = snapshot.shuffle
        self.playlist.repeat_mode = snapshot.repeat_mode
        self.current_track = snapshot.current_track
        self.elapsed_seconds = snapshot.elapsed_seconds

    def close(self) -> None:
        self.save()
        self._search_executor.shutdown(wait=True, cancel_futures=True)
        self.downloads.close(wait=True, cancel_pending=True)
        self.cache.close()
        self.state.close()

    def __enter__(self) -> AuenSession:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
