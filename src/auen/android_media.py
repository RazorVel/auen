"""Opt-in authenticated local bridge for the Android MediaSession companion."""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import re
import shutil
import subprocess
import threading
import time
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlencode, urlparse

from auen.remote import RemoteControlServer

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

ENDPOINT_NAME = "android-media.json"
COMPANION_ACTIVITY = "io.github.razorvel.auen.media/.MainActivity"
COMPANION_RECEIVER = "io.github.razorvel.auen.media/.ConnectionReceiver"
_TOKEN = re.compile(r"[0-9a-f]{64}\Z")


class AndroidMediaBridge:
    """Publish cached metadata without asking the UI or mpv on every phone poll."""

    def __init__(
        self, state_dir: Path, handler: Callable[[str], dict[str, Any]], *,
        seek_handler: Callable[[float, str], dict[str, Any]] | None = None,
    ) -> None:
        self._handler = handler
        self._seek_handler = seek_handler
        self._lock = threading.Lock()
        self._last_seen = 0.0
        self._stop = threading.Event()
        self._connector: threading.Thread | None = None
        self._snapshot: dict[str, Any] = {
            "protocol": 1,
            "state": "stopped",
            "title": "Nothing playing",
            "elapsed_seconds": 0.0,
            "duration_seconds": None,
            "can_next": False,
            "can_previous": False,
            "thumbnail_url": None,
            "media_id": None,
            "can_seek": False,
        }
        self.server = RemoteControlServer(
            state_dir, self._dispatch, tcp=True, endpoint_name=ENDPOINT_NAME,
            parameter_commands={"seek": self._seek},
        )

    def start(self) -> None:
        self.server.start()

    def close(self) -> None:
        # The worker sends shutdown asynchronously. Never delay stopping real audio
        # for an Android activity-manager command (which can take several seconds).
        self._stop.set()
        self.server.close()
        with self._lock:
            self._last_seen = 0.0

    def start_autoconnect(self) -> None:
        """One visible bootstrap per run; subsequent retries never steal focus."""
        if self._connector is not None:
            return
        endpoint = read_media_endpoint(self.server.path.parent)
        self._connector = threading.Thread(
            target=self._connect_loop, args=(endpoint,), name="auen-android-connect", daemon=True,
        )
        self._connector.start()

    def _connect_loop(self, endpoint: tuple[int, str]) -> None:
        try:
            if self._stop.wait(1.0):
                return
            if not self.connected:
                with contextlib.suppress(OSError, RuntimeError):
                    _companion_command(endpoint, automatic=True)
            delay = 5.0
            while not self._stop.wait(delay):
                if not self.connected:
                    with contextlib.suppress(OSError, RuntimeError):
                        _companion_command(endpoint, broadcast="connect")
                delay = min(delay * 2, 30.0)
        finally:
            with contextlib.suppress(OSError, RuntimeError):
                _companion_command(endpoint, broadcast="shutdown")

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._last_seen > 0 and time.monotonic() - self._last_seen < 5.0

    def update(
        self, *, state: str, title: str, elapsed: float = 0.0,
        duration: float | None = None, can_next: bool = False, can_previous: bool = False,
        source_uri: str | None = None,
        can_seek: bool = False,
    ) -> None:
        if state not in {"playing", "paused", "stopped", "buffering"}:
            raise ValueError("invalid media state")
        with self._lock:
            self._snapshot = {
                "protocol": 1,
                "state": state,
                "title": title,
                "elapsed_seconds": max(0.0, elapsed),
                "duration_seconds": duration,
                "can_next": can_next,
                "can_previous": can_previous,
                "thumbnail_url": youtube_thumbnail(source_uri),
                "media_id": media_identity(source_uri) if source_uri else None,
                "can_seek": bool(can_seek and self._seek_handler and source_uri
                                 and duration is not None and math.isfinite(duration)
                                 and duration > 0 and state in {"playing", "paused"}),
            }

    def _seek(self, request: dict[str, Any]) -> dict[str, Any]:
        seconds, media_id = request.get("seconds"), request.get("media_id")
        if (isinstance(seconds, bool) or not isinstance(seconds, (int, float))
                or not 0 <= seconds <= 1_000_000_000 or not math.isfinite(seconds)):
            raise ValueError("invalid seek position")
        with self._lock:
            if (not self._snapshot.get("can_seek") or not isinstance(media_id, str)
                    or media_id != self._snapshot.get("media_id")):
                raise ValueError("seek unavailable or track changed")
        assert self._seek_handler is not None
        return self._seek_handler(float(seconds), media_id)

    def _dispatch(self, command: str) -> dict[str, Any]:
        if command == "status":
            with self._lock:
                self._last_seen = time.monotonic()
                return dict(self._snapshot)
        response = self._handler(command)
        # App actions refresh the snapshot before acknowledging Play/Pause.
        # Return it with the acknowledgement instead of immediately polling a
        # possibly stale pre-command cache and leaving the old button visible.
        with self._lock:
            return {**self._snapshot, **response}


def media_identity(source_uri: str) -> str:
    """Identify stale seek requests without exposing local paths in metadata."""
    return hashlib.sha256(source_uri.encode("utf-8")).hexdigest()


def read_media_endpoint(state_dir: Path) -> tuple[int, str]:
    path = state_dir / ENDPOINT_NAME
    if not path.exists():
        raise RuntimeError("enable Android headphone controls and run auen before pairing")
    if path.stat().st_size > 4096:
        raise ValueError("invalid media endpoint")
    try:
        endpoint = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid media endpoint") from exc
    if not isinstance(endpoint, dict):
        raise ValueError("invalid media endpoint")
    port, token = endpoint.get("port"), endpoint.get("token")
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("invalid media endpoint")
    if not isinstance(token, str) or not _TOKEN.fullmatch(token):
        raise ValueError("invalid media endpoint")
    return port, token


def media_pairing_code(state_dir: Path) -> str:
    """Only disclose credentials in response to the explicit pairing command."""
    port, token = read_media_endpoint(state_dir)
    return "auen://media?" + urlencode({"protocol": 1, "port": port, "token": token})


def youtube_thumbnail(source_uri: str | None) -> str | None:
    """Derive public artwork without another YouTube extraction or login request."""
    if not source_uri:
        return None
    try:
        uri = urlparse(source_uri)
        if uri.scheme not in {"http", "https"} or uri.username or uri.password:
            return None
        host = uri.hostname
        video_id = ""
        if host == "youtu.be":
            video_id = uri.path.removeprefix("/")
        elif host in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}:
            if uri.path == "/watch":
                video_id = parse_qs(uri.query).get("v", [""])[0]
            else:
                parts = uri.path.strip("/").split("/")
                if len(parts) == 2 and parts[0] in {"shorts", "embed", "live"}:
                    video_id = parts[1]
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
    except ValueError:
        pass
    return None


def open_media_companion(state_dir: Path) -> None:
    _companion_command(read_media_endpoint(state_dir))


def _companion_command(
    endpoint: tuple[int, str], *, automatic: bool = False, broadcast: str | None = None,
) -> None:
    port, token = endpoint
    command = shutil.which("am")
    if command is None:
        raise RuntimeError("install termux-am, or paste 'auen media pair' into the companion")
    try:
        args = [command, "start", "-n", COMPANION_ACTIVITY]
        if broadcast is not None:
            args = [command, "broadcast", "-n", COMPANION_RECEIVER,
                    "-a", f"io.github.razorvel.auen.media.{broadcast}"]
        else:
            args += ["--ez", "auto-connect", "true", "--ez", "return-to-termux",
                     "true" if automatic else "false"]
        args += ["--ei", "bridge-port", str(port), "--es", "bridge-token", token]
        result = subprocess.run(
            args,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            text=True, timeout=5.0, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        # Never include the command: it contains the pairing credential.
        raise RuntimeError("Android did not open the companion in time") from exc
    if result.returncode != 0 or "Error" in (result.stderr or ""):
        raise RuntimeError(
            "could not open the companion; install the APK or use 'auen media pair'"
        )
