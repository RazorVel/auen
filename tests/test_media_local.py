"""Tests for local media discovery."""

from pathlib import Path

import pytest

from auen.media.local import discover_local
from auen.models import TrackSource


def test_discovers_supported_files_recursively_in_natural_order(tmp_path: Path) -> None:
    album = tmp_path / "Album"
    album.mkdir()
    (album / "track10.mp3").touch()
    (album / "track2.FLAC").touch()
    (tmp_path / "intro.opus").touch()
    (tmp_path / "cover.jpg").touch()

    result = discover_local(tmp_path)

    assert [track.title for track in result.tracks] == ["track2", "track10", "intro"]
    assert all(track.source is TrackSource.LOCAL for track in result.tracks)
    assert result.skipped == [tmp_path / "cover.jpg"]


def test_non_recursive_scan_only_returns_direct_children(tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "nested.mp3").touch()
    (tmp_path / "direct.wav").touch()

    result = discover_local(tmp_path, recursive=False)

    assert [track.title for track in result.tracks] == ["direct"]


def test_hidden_content_and_symlinks_are_not_followed(tmp_path: Path) -> None:
    hidden = tmp_path / ".private"
    hidden.mkdir()
    (hidden / "secret.mp3").touch()
    real = tmp_path / "real.mp3"
    real.touch()
    link = tmp_path / "linked.mp3"
    link.symlink_to(real)

    result = discover_local(tmp_path)

    assert [track.title for track in result.tracks] == ["real"]
    assert link in result.skipped


def test_single_unsupported_file_is_reported_as_skipped(tmp_path: Path) -> None:
    image = tmp_path / "cover.png"
    image.touch()

    result = discover_local(image)

    assert result.tracks == []
    assert result.skipped == [image]


def test_missing_path_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        discover_local(tmp_path / "missing")
