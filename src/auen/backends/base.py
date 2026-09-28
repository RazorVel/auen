"""Abstract base class for audio backends."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from auen.models import PlaybackStatus


@dataclass(frozen=True, slots=True)
class BackendCapabilities:
    """Features exposed by a playback backend."""

    streaming: bool
    seeking: bool
    volume: bool
    reports_position: bool


class AudioBackend(ABC):
    """Abstract audio playback backend."""

    @abstractmethod
    def play(self, uri: str) -> None:
        """Start playing from a file path or stream URL."""
        pass

    @abstractmethod
    def pause(self) -> None:
        pass

    @abstractmethod
    def resume(self) -> None:
        pass

    @abstractmethod
    def stop(self) -> None:
        pass

    @abstractmethod
    def get_status(self) -> PlaybackStatus:
        pass

    @abstractmethod
    def set_volume(self, level: int) -> None:
        pass

    @abstractmethod
    def seek(self, seconds: float) -> None:
        """Seek relative to current position. Positive = forward."""
        pass

    @abstractmethod
    def wait_for_end(self, timeout: float | None = None) -> bool:
        """Block until current track ends. Returns True if ended, False on timeout."""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable backend identifier used by configuration and diagnostics."""
        pass

    @property
    @abstractmethod
    def capabilities(self) -> BackendCapabilities:
        """Capabilities used by orchestration and the UI."""
        pass

    @property
    def supports_streaming(self) -> bool:
        return self.capabilities.streaming

    @property
    def supports_seek(self) -> bool:
        return self.capabilities.seeking
