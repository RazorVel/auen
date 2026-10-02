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
        if not shutil.which("mpv"):
            raise RuntimeError("mpv was not found; install mpv or choose another backend")
        return MpvBackend()
    if preference == "termux":
        if not shutil.which("termux-media-player"):
            raise RuntimeError(
                "termux-media-player was not found; install the Termux:API package"
            )
        return TermuxBackend()

    if shutil.which("mpv"):
        return MpvBackend()
    if shutil.which("termux-media-player"):
        return TermuxBackend()

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
