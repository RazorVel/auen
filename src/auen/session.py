"""Application-level coordination for media, queue, cache, and recovery state."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from auen.cache import CacheEntry, CacheManager
from auen.downloads import DownloadManager
from auen.media.youtube import YouTubeService, is_youtube_url
from auen.models import (
    HistoryEntry,
    MediaCollection,
    RepeatMode,
    SavedPlaylist,
    SearchItem,
    SessionMode,
    Track,
    TrackSource,
)
from auen.player import PlaybackController
from auen.playlist import Playlist
from auen.state import SessionSnapshot, StateStore

if TYPE_CHECKING:
    from collections.abc import Callable
    from concurrent.futures import Future

    from auen.backends.base import AudioBackend
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
        self.state.prune_recent_history(config.history_limit)
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
        self._auto_cache_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="auen-auto-cache"
        )
        self.playlist = Playlist()
        self.current_track: Track | None = None
        self.elapsed_seconds = 0.0
        self.player: PlaybackController | None = None
        self.session_mode = SessionMode(config.session_mode)
        self.on_track_changed: Callable[[Track | None], None] | None = None
        self.on_history_changed: Callable[[], None] | None = None
        self.on_playback_error: Callable[[Track, Exception], None] | None = None
        self._temporary_uris: set[str] = set()
        self._closed = False

        self.playlist.shuffle = config.shuffle
        self.playlist.repeat_mode = RepeatMode(config.repeat_mode)
        if config.restore_session:
            self._restore()

    def search(self, query_or_url: str, *, limit: int | None = None) -> list[SearchItem]:
        value = query_or_url.strip()
        if not value:
            return []
        if is_youtube_url(value):
            return [self.youtube.from_url(value)]
        return self.youtube.search(
            value,
            limit=self.config.search_result_count if limit is None else limit,
        )

    def submit_search(
        self, query_or_url: str, *, limit: int | None = None
    ) -> Future[list[SearchItem]]:
        """Run one search outside the UI thread on an executor owned by this session."""
        return self._search_executor.submit(self.search, query_or_url, limit=limit)

    def submit_collection(self, collection: MediaCollection) -> Future[list[Track]]:
        """Load a collection only after the user explicitly opens it."""
        return self._search_executor.submit(self.youtube.collection_tracks, collection)

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
            return self._auto_cache_executor.submit(self._cache_queued_track, track)
        return None

    def enqueue_next(
        self,
        track: Track,
        *,
        session_mode: SessionMode = SessionMode.STREAM_ONLY,
    ) -> Future[CacheEntry] | None:
        """Place a track at the front of the queue and persist it."""
        cached = self.cache.get(track.uri)
        if cached is not None:
            track.cached_path = cached.path
        self.playlist.add_next(track)
        self.save()
        if session_mode is SessionMode.STREAM_AND_CACHE and not track.is_cached:
            return self._auto_cache_executor.submit(self._cache_queued_track, track)
        return None

    def enqueue_many(
        self,
        tracks: list[Track],
        *,
        session_mode: SessionMode = SessionMode.STREAM_ONLY,
    ) -> list[Future[CacheEntry]]:
        """Append tracks in order, persisting once and scheduling bounded caching."""
        pending: list[Track] = []
        for track in tracks:
            cached = self.cache.get(track.uri)
            if cached is not None:
                track.cached_path = cached.path
            elif session_mode is SessionMode.STREAM_AND_CACHE:
                pending.append(track)
        self.playlist.add_many(tracks)
        self.save()
        return [
            self._auto_cache_executor.submit(self._cache_queued_track, track)
            for track in pending
        ]

    def recent_history(self) -> list[HistoryEntry]:
        return self.state.load_recent_history(limit=self.config.history_limit)

    def remove_recent_history(self, uri: str) -> bool:
        return self.state.remove_recent_history(uri)

    def clear_recent_history(self) -> None:
        self.state.clear_recent_history()

    def prune_recent_history(self) -> None:
        self.state.prune_recent_history(self.config.history_limit)

    def create_named_playlist(self, name: str) -> SavedPlaylist:
        return self.state.create_named_playlist(name)

    def named_playlists(self) -> list[SavedPlaylist]:
        return self.state.list_named_playlists()

    def rename_named_playlist(self, playlist_id: int, name: str) -> bool:
        return self.state.rename_named_playlist(playlist_id, name)

    def delete_named_playlist(self, playlist_id: int) -> bool:
        return self.state.delete_named_playlist(playlist_id)

    def named_playlist_tracks(self, playlist_id: int) -> list[Track]:
        return self.state.load_named_playlist_tracks(playlist_id)

    def add_to_named_playlist(self, playlist_id: int, track: Track) -> int:
        return self.state.add_named_playlist_track(playlist_id, track)

    def remove_from_named_playlist(self, playlist_id: int, position: int) -> Track | None:
        return self.state.remove_named_playlist_track(playlist_id, position)

    def move_named_playlist_track(
        self,
        playlist_id: int,
        position: int,
        delta: int,
    ) -> int | None:
        return self.state.move_named_playlist_track(playlist_id, position, delta)

    def _cache_queued_track(self, track: Track) -> CacheEntry:
        """Serialize automatic caching so it cannot saturate playback bandwidth."""
        return self.downloads.submit(track).result()

    def set_session_mode(self, mode: SessionMode) -> None:
        """Set remote-media behavior for the rest of this running session."""
        if mode is SessionMode.ASK:
            raise ValueError("a concrete session mode is required")
        self.session_mode = mode

    def start_playback(
        self,
        backend: AudioBackend,
        *,
        session_mode: SessionMode | None = None,
    ) -> PlaybackController:
        """Start the single playback worker after startup choices are known."""
        if session_mode is not None:
            self.set_session_mode(session_mode)
        if self.session_mode is SessionMode.ASK:
            raise RuntimeError("choose a session mode before starting playback")
        if self.player is not None:
            return self.player

        self.player = PlaybackController(
            self.playlist,
            backend,
            prepare=self._prepare_track,
            on_track_changed=self._track_changed,
            on_track_started=self._track_started,
            on_error=self._playback_error,
        )
        self.player.set_volume(self.config.volume)
        self.player.start()
        return self.player

    def save_offline(self, track: Track) -> Future[CacheEntry]:
        return self.downloads.submit(track, pinned=True)

    def remove_queued(self, index: int) -> Track | None:
        removed = self.playlist.remove(index)
        if removed is not None:
            self.save()
        return removed

    def prioritize_queued(self, index: int) -> Track | None:
        prioritized = self.playlist.jump(index)
        if prioritized is not None:
            self.save()
        return prioritized

    def move_queued(self, index: int, delta: int) -> int | None:
        new_index = self.playlist.move(index, delta)
        if new_index is not None:
            self.save()
        return new_index

    def play_queued_now(self, index: int) -> Track | None:
        track = self.prioritize_queued(index)
        if track is not None and self.player is not None and self.current_track is not None:
            self.player.skip()
        return track

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
        queue = snapshot.queue
        if snapshot.current_track is not None:
            queue = [snapshot.current_track, *queue]
        self.playlist.restore(queue, snapshot.history)
        self.playlist.shuffle = snapshot.shuffle
        self.playlist.repeat_mode = snapshot.repeat_mode
        self.current_track = None
        self.elapsed_seconds = 0.0

    def _prepare_track(self, track: Track) -> str:
        cached = self.cache.get(track.uri)
        if cached is not None:
            track.cached_path = cached.path
            return str(cached.path)
        if track.source is TrackSource.LOCAL:
            return track.playable_uri
        if self.player is None:
            raise RuntimeError("playback is not initialized")
        if self.player.backend.supports_streaming:
            return self.youtube.resolve(track).playable_uri

        entry = self.downloads.submit(track, pinned=False).result()
        track.cached_path = entry.path
        if self.session_mode is SessionMode.STREAM_ONLY:
            self._temporary_uris.add(track.uri)
        return str(entry.path)

    def _track_changed(self, track: Track | None) -> None:
        previous = self.current_track
        self.current_track = track
        self.elapsed_seconds = 0.0
        if previous is not None and previous.uri in self._temporary_uris:
            self.cache.remove(previous.uri)
            previous.cached_path = None
            self._temporary_uris.discard(previous.uri)
        self.save()
        if self.on_track_changed is not None:
            self.on_track_changed(track)

    def _track_started(self, track: Track) -> None:
        self.state.record_play(track, limit=self.config.history_limit)
        if self.on_history_changed is not None:
            self.on_history_changed()

    def _playback_error(self, track: Track, error: Exception) -> None:
        self.save()
        if self.on_playback_error is not None:
            self.on_playback_error(track, error)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        first_error: Exception | None = None

        def cleanup(action: Callable[[], object]) -> None:
            nonlocal first_error
            try:
                action()
            except Exception as exc:
                if first_error is None:
                    first_error = exc

        if self.player is not None:
            cleanup(self.player.close)
        cleanup(self.save)
        cleanup(lambda: self._search_executor.shutdown(wait=True, cancel_futures=True))
        cleanup(lambda: self._auto_cache_executor.shutdown(wait=True, cancel_futures=True))
        cleanup(lambda: self.downloads.close(wait=True, cancel_pending=True))
        cleanup(self.cache.close)
        cleanup(self.state.close)
        if first_error is not None:
            raise first_error

    def __enter__(self) -> AuenSession:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
