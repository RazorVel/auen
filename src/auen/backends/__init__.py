"""Audio backends for auen."""

import shutil

from auen.backends.base import AudioBackend, BackendCapabilities
from auen.backends.mpv import MpvBackend
from auen.backends.termux import TermuxBackend


def detect_backend(preference: str = "auto") -> AudioBackend:
    """Pick the best available backend for the current environment."""
    if preference not in {"auto", "mpv", "termux"}:
        raise ValueError(f"Unsupported audio backend: {preference}")

    if preference == "mpv":
        return MpvBackend()
    if preference == "termux":
        return TermuxBackend()

    if shutil.which("termux-media-player"):
        return TermuxBackend()
    if shutil.which("mpv"):
        return MpvBackend()

    raise RuntimeError(
        "No supported audio backend found. "
        "Install mpv (desktop) or ensure termux-media-player is available (Termux)."
    )


__all__ = [
    "AudioBackend",
    "BackendCapabilities",
    "MpvBackend",
    "TermuxBackend",
    "detect_backend",
]
