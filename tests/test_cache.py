"""Tests for bounded cache and offline-library behavior."""

from pathlib import Path

import pytest

from auen.cache import CacheManager
from auen.models import Track, TrackSource


def make_track(title: str) -> Track:
    return Track(
        title=title,
        source=TrackSource.YOUTUBE,
        uri=f"https://youtube.com/watch?v={title}",
    )


def write_media(path: Path, size: int) -> None:
    path.write_bytes(b"x" * size)


def test_destination_is_stable_and_sanitized(tmp_path: Path) -> None:
    track = make_track("../../An awkward / title")
    with CacheManager(tmp_path) as cache:
        first = cache.destination_for(track)
        second = cache.destination_for(track)

    assert first == second
    assert first.parent == (tmp_path / "media").resolve()
    assert ".." not in first.name
    assert first.suffix == ".opus"


def test_register_and_lookup_sets_cached_track_path(tmp_path: Path) -> None:
    track = make_track("saved")
    with CacheManager(tmp_path, max_cache_bytes=100) as cache:
        destination = cache.destination_for(track)
        write_media(destination, 10)
        entry = cache.register(track, destination)
        restored = cache.get(track.uri)

    assert track.cached_path == destination
    assert entry.size_bytes == 10
    assert restored is not None
    assert restored.path == destination


def test_prune_evicts_least_recent_unpinned_file(tmp_path: Path) -> None:
    first = make_track("first")
    second = make_track("second")
    with CacheManager(tmp_path, max_cache_bytes=10) as cache:
        first_path = cache.destination_for(first)
        write_media(first_path, 6)
        cache.register(first, first_path)

        second_path = cache.destination_for(second)
        write_media(second_path, 6)
        cache.register(second, second_path)

        assert cache.get(first.uri, touch=False) is None
        assert cache.get(second.uri, touch=False) is not None

    assert not first_path.exists()
    assert second_path.exists()


def test_pinned_library_is_not_counted_or_evicted(tmp_path: Path) -> None:
    library_track = make_track("library")
    cached_track = make_track("cached")
    with CacheManager(tmp_path, max_cache_bytes=5) as cache:
        library_path = cache.destination_for(library_track)
        write_media(library_path, 20)
        cache.register(library_track, library_path, pinned=True)

        cached_path = cache.destination_for(cached_track)
        write_media(cached_path, 5)
        cache.register(cached_track, cached_path)

        stats = cache.stats()

    assert library_path.exists()
    assert cached_path.exists()
    assert stats.library_bytes == 20
    assert stats.cache_bytes == 5
    assert stats.library_tracks == 1


def test_unpinning_can_make_entry_eligible_for_eviction(tmp_path: Path) -> None:
    track = make_track("large")
    with CacheManager(tmp_path, max_cache_bytes=5) as cache:
        path = cache.destination_for(track)
        write_media(path, 10)
        cache.register(track, path, pinned=True)

        assert cache.set_pinned(track.uri, pinned=False) is None

        assert cache.get(track.uri, touch=False) is None

    assert not path.exists()


def test_refuses_to_manage_or_delete_outside_files(tmp_path: Path) -> None:
    outside = tmp_path / "outside.opus"
    write_media(outside, 5)
    track = make_track("outside")

    with (
        CacheManager(tmp_path / "cache") as cache,
        pytest.raises(ValueError, match="outside cache"),
    ):
        cache.register(track, outside)

    assert outside.exists()


def test_explicit_remove_deletes_managed_file(tmp_path: Path) -> None:
    track = make_track("remove")
    with CacheManager(tmp_path) as cache:
        path = cache.destination_for(track)
        write_media(path, 5)
        cache.register(track, path, pinned=True)

        assert cache.remove(track.uri) is True
        assert cache.remove(track.uri) is False

    assert not path.exists()


def test_reconcile_drops_missing_records(tmp_path: Path) -> None:
    track = make_track("missing")
    with CacheManager(tmp_path) as cache:
        path = cache.destination_for(track)
        write_media(path, 5)
        cache.register(track, path)
        path.unlink()

        assert cache.reconcile() == 1
        assert cache.list_entries() == []
