"""Tests for bounded and deduplicated download orchestration."""

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from yt_dlp.utils import DownloadError

from auen.cache import CacheManager
from auen.downloads import DownloadManager, DownloadServiceError
from auen.models import Track, TrackSource
from auen.youtube_policy import YouTubeRequestGate


def make_track(title: str) -> Track:
    return Track(
        title=title,
        source=TrackSource.YOUTUBE,
        uri=f"https://youtube.com/watch?v={title}",
    )


def fake_download(track: Track, directory: Path) -> Path:
    path = directory / f"{track.title}.webm"
    path.write_bytes(track.title.encode("utf-8"))
    return path


def test_download_registers_track_in_cache(tmp_path: Path) -> None:
    track = make_track("saved")
    with (
        CacheManager(tmp_path, max_cache_bytes=100) as cache,
        DownloadManager(cache, max_workers=1) as downloads,
        patch.object(downloads, "_download_file", side_effect=fake_download),
    ):
        entry = downloads.submit(track).result(timeout=2)

    assert entry.path.exists()
    assert entry.path.suffix == ".webm"
    assert track.cached_path == entry.path


def test_duplicate_requests_share_one_download_and_upgrade_to_pinned(tmp_path: Path) -> None:
    first = make_track("same")
    second = make_track("same")
    release = threading.Event()
    calls = 0

    def blocked_download(track: Track, directory: Path) -> Path:
        nonlocal calls
        calls += 1
        assert release.wait(timeout=2)
        return fake_download(track, directory)

    with (
        CacheManager(tmp_path, max_cache_bytes=100) as cache,
        DownloadManager(cache, max_workers=1) as downloads,
        patch.object(downloads, "_download_file", side_effect=blocked_download),
    ):
        first_future = downloads.submit(first)
        second_future = downloads.submit(second, pinned=True)
        assert first_future is second_future
        release.set()
        entry = first_future.result(timeout=2)

    assert calls == 1
    assert entry.pinned is True
    assert second.cached_path == entry.path


def test_worker_pool_bounds_concurrency(tmp_path: Path) -> None:
    lock = threading.Lock()
    active = 0
    peak = 0

    def measured_download(track: Track, directory: Path) -> Path:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.05)
        result = fake_download(track, directory)
        with lock:
            active -= 1
        return result

    tracks = [make_track(f"track-{index}") for index in range(6)]
    with (
        CacheManager(tmp_path, max_cache_bytes=1000) as cache,
        DownloadManager(cache, max_workers=2) as downloads,
        patch.object(downloads, "_download_file", side_effect=measured_download),
    ):
        futures = [downloads.submit(track) for track in tracks]
        entries = [future.result(timeout=3) for future in futures]

    assert len(entries) == 6
    assert peak == 2


def test_cached_request_finishes_without_new_download(tmp_path: Path) -> None:
    track = make_track("existing")
    with CacheManager(tmp_path, max_cache_bytes=100) as cache:
        path = cache.destination_for(track)
        path.write_bytes(b"cached")
        cache.register(track, path)

        with (
            DownloadManager(cache) as downloads,
            patch.object(downloads, "_download_file") as download_file,
        ):
            entry = downloads.submit(track, pinned=True).result(timeout=1)

    download_file.assert_not_called()
    assert entry.pinned is True


def test_failed_download_can_be_retried(tmp_path: Path) -> None:
    track = make_track("retry")
    with (
        CacheManager(tmp_path, max_cache_bytes=100) as cache,
        DownloadManager(cache, max_workers=1) as downloads,
        patch.object(
            downloads,
            "_download_file",
            side_effect=[DownloadServiceError("network failed"), fake_download(track, tmp_path)],
        ),
    ):
        with pytest.raises(DownloadServiceError, match="network failed"):
            downloads.submit(track).result(timeout=2)
        while downloads.active_count:
            time.sleep(0.01)
        entry = downloads.submit(track).result(timeout=2)

    assert entry.path.exists()


def test_rejects_non_youtube_tracks(tmp_path: Path) -> None:
    local = Track(title="local", source=TrackSource.LOCAL, uri="/music/local.mp3")
    with (
        CacheManager(tmp_path) as cache,
        DownloadManager(cache) as downloads,
        pytest.raises(ValueError, match="only YouTube"),
    ):
        downloads.submit(local)


def test_download_prefers_android_compatible_audio(tmp_path: Path) -> None:
    track = make_track("compatible")
    extractor = MagicMock()
    extractor.extract_info.side_effect = lambda *_args, **_kwargs: (
        tmp_path / "media.m4a"
    ).write_bytes(b"audio")

    with (
        CacheManager(tmp_path / "cache") as cache,
        DownloadManager(cache) as downloads,
        patch("auen.downloads.YoutubeDL") as youtube_dl,
    ):
        youtube_dl.return_value.__enter__.return_value = extractor
        downloaded = downloads._download_file(track, tmp_path)

    options = youtube_dl.call_args.args[0]
    assert options["format"].startswith("bestaudio[ext=m4a]/")
    assert downloaded.suffix == ".m4a"


def test_download_block_starts_shared_cooldown(tmp_path: Path) -> None:
    track = make_track("blocked")
    gate = YouTubeRequestGate(minimum_interval_seconds=0, cooldown_seconds=120)
    extractor = MagicMock()
    extractor.extract_info.side_effect = DownloadError(
        "ERROR: HTTP Error 429: Too Many Requests"
    )

    with (
        CacheManager(tmp_path / "cache") as cache,
        DownloadManager(cache, request_gate=gate) as downloads,
        patch("auen.downloads.YoutubeDL") as youtube_dl,
    ):
        youtube_dl.return_value.__enter__.return_value = extractor
        with pytest.raises(DownloadServiceError, match="temporarily blocked"):
            downloads._download_file(track, tmp_path)
        with pytest.raises(DownloadServiceError, match="cooling down"):
            downloads._download_file(track, tmp_path)

    assert extractor.extract_info.call_count == 1
