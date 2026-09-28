"""Safe and deterministic discovery of local audio files."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from auen.models import Track, TrackSource

if TYPE_CHECKING:
    from pathlib import Path

SUPPORTED_AUDIO_EXTENSIONS = frozenset(
    {".aac", ".flac", ".m4a", ".mp3", ".oga", ".ogg", ".opus", ".wav", ".webm"}
)


@dataclass(slots=True)
class LocalDiscovery:
    """Tracks found at a local path and files intentionally skipped."""

    tracks: list[Track] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)


def discover_local(path: Path, *, recursive: bool = True) -> LocalDiscovery:
    """Discover supported audio without following symlinks or hidden directories."""
    path = path.expanduser()
    if not path.exists():
        raise FileNotFoundError(path)

    if path.is_symlink():
        return LocalDiscovery(skipped=[path])

    if path.is_file():
        if _is_supported(path):
            return LocalDiscovery(tracks=[_track_from_path(path)])
        return LocalDiscovery(skipped=[path])

    if not path.is_dir():
        raise ValueError(f"not a regular file or directory: {path}")

    candidates = path.rglob("*") if recursive else path.iterdir()
    supported: list[Path] = []
    skipped: list[Path] = []
    for candidate in candidates:
        relative = candidate.relative_to(path)
        if any(part.startswith(".") for part in relative.parts):
            continue
        if candidate.is_symlink():
            skipped.append(candidate)
            continue
        if not candidate.is_file():
            continue
        if _is_supported(candidate):
            supported.append(candidate)
        else:
            skipped.append(candidate)

    supported.sort(key=lambda item: _natural_key(item.relative_to(path).as_posix()))
    skipped.sort(key=lambda item: _natural_key(item.relative_to(path).as_posix()))
    return LocalDiscovery(
        tracks=[_track_from_path(item) for item in supported],
        skipped=skipped,
    )


def _is_supported(path: Path) -> bool:
    return path.suffix.casefold() in SUPPORTED_AUDIO_EXTENSIONS


def _track_from_path(path: Path) -> Track:
    absolute_path = path.resolve()
    return Track(
        title=path.stem,
        source=TrackSource.LOCAL,
        uri=str(absolute_path),
    )


def _natural_key(value: str) -> tuple[tuple[int, int | str], ...]:
    parts: list[tuple[int, int | str]] = []
    for part in re.split(r"(\d+)", value.casefold()):
        if part.isdigit():
            parts.append((0, int(part)))
        else:
            parts.append((1, part))
    return tuple(parts)
