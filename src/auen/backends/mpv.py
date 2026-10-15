"""Mpv media player backend via JSON IPC."""

import contextlib
import json
import os
import re
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from auen.backends.base import AudioBackend, BackendCapabilities
from auen.backends.windows_pipe import WindowsPipe
from auen.models import PlaybackState, PlaybackStatus


class MpvBackend(AudioBackend):
    """mpv backend using JSON IPC socket for control."""

    def __init__(self) -> None:
        self._windows = os.name == "nt"
        self._socket_path = Path(tempfile.gettempdir()) / f"auen-mpv-{os.getpid()}-{id(self)}.sock"
        self._pipe_name = rf"\\.\pipe\auen-mpv-{os.getpid()}-{id(self)}"
        self._process: subprocess.Popen[bytes] | None = None
        self._lock = threading.Lock()
        self._current_volume = 80
        self._end_event = threading.Event()
        self._is_playing = False
        self._windows_media_option: bool | None = None

    def play(self, uri: str) -> None:
        with self._lock:
            if self._process:
                self._kill_process()

            self._end_event.clear()

            # Start mpv in idle mode to keep it alive or just play the file
            cmd = [
                "mpv",
                *self._windows_input_options(),
                "--no-video",
                "--cache=yes",
                "--cache-pause=yes",
                "--cache-pause-initial=yes",
                "--cache-pause-wait=3",
                "--demuxer-readahead-secs=30",
                f"--input-ipc-server={self._pipe_name if self._windows else self._socket_path}",
                "--quiet",
                "--",
                uri,
            ]
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=0x08000000 if self._windows else 0,
            )

            # Wait for socket
            start = time.monotonic()
            while not self._ipc_ready():
                if self._process.poll() is not None:
                    self._process = None
                    raise RuntimeError("mpv exited before its control socket became available")
                if time.monotonic() - start > 5:
                    self._kill_process()
                    raise RuntimeError("mpv socket didn't appear in time.")
                time.sleep(0.1)

            self._is_playing = True

            # Monitor process in background
            process = self._process
            threading.Thread(target=self._monitor_process, args=(process,), daemon=True).start()

            self.set_volume(self._current_volume)

    def _windows_input_options(self) -> list[str]:
        if not self._windows:
            return []
        if self._windows_media_option is None:
            try:
                probe = subprocess.run(
                    ["mpv", "--no-config", "--list-options"], stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, text=True, errors="replace", check=False,
                    timeout=2.0, creationflags=0x08000000,
                )
                self._windows_media_option = probe.returncode == 0 and bool(re.search(
                    r"(?m)^\s*--media-controls(?:[=\s]|$)", probe.stdout,
                ))
            except (OSError, subprocess.TimeoutExpired):
                self._windows_media_option = False
        # Auen owns the media session and Queue, not its one-track mpv child.
        # Older mpv builds have no SMTC flag: never pass an unsupported option.
        return ["--input-media-keys=no", *(
            ["--media-controls=no"] if self._windows_media_option else []
        )]

    def _ipc_ready(self) -> bool:
        if not self._windows:
            return self._socket_path.exists()
        try:
            with WindowsPipe(self._pipe_name):
                return True
        except OSError:
            return False

    def _monitor_process(self, process: subprocess.Popen[bytes]) -> None:
        process.wait()
        with self._lock:
            if self._process is process:
                self._process = None
                self._is_playing = False
                self._end_event.set()
                self._remove_socket()

    def _remove_socket(self) -> None:
        if self._windows:
            return
        if self._socket_path.exists():
            with contextlib.suppress(OSError):
                self._socket_path.unlink()

    def _kill_process(self) -> None:
        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None

        self._remove_socket()

    def _send_command(self, command: list[Any]) -> dict[str, Any]:
        if not self._windows and not self._socket_path.exists():
            return {"error": "no socket"}

        try:
            if self._windows:
                with WindowsPipe(self._pipe_name) as pipe:
                    return self._exchange_command(pipe, command)
            family = getattr(socket, "AF_UNIX", None)
            if family is None:
                raise RuntimeError("Unix IPC is unavailable on this platform")
            with socket.socket(family, socket.SOCK_STREAM) as s:
                s.settimeout(2.0)
                s.connect(str(self._socket_path))
                return self._exchange_command(s, command)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, RuntimeError) as exc:
            return {"error": str(exc)}

    @staticmethod
    def _exchange_command(
        connection: socket.socket | WindowsPipe, command: list[Any]
    ) -> dict[str, Any]:
        connection.sendall((json.dumps({"command": command}) + "\n").encode("utf-8"))
        data = bytearray()
        total = 0
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            chunk = connection.recv(4096)
            if not chunk:
                return {}
            data.extend(chunk)
            total += len(chunk)
            if total > 1024 * 1024:
                raise RuntimeError("mpv IPC response exceeded 1 MiB")
            while b"\n" in data:
                line, _, remainder = data.partition(b"\n")
                data = bytearray(remainder)
                if line.strip():
                    response = json.loads(line.decode("utf-8"))
                    if not isinstance(response, dict):
                        raise RuntimeError("mpv IPC response must be a JSON object")
                    if "event" not in response:
                        return response
        raise TimeoutError("mpv control channel did not respond in time")

    def pause(self) -> None:
        if self._process:
            self._send_command(["set_property", "pause", True])
            self._is_playing = False

    def resume(self) -> None:
        if self._process:
            self._send_command(["set_property", "pause", False])
            self._is_playing = True

    def stop(self) -> None:
        with self._lock:
            self._kill_process()
            self._is_playing = False
            self._end_event.set()

    def get_status(self) -> PlaybackStatus:
        if not self._process or self._process.poll() is not None:
            return PlaybackStatus(state=PlaybackState.STOPPED, volume=self._current_volume)

        # Get pause state
        pause_resp = self._send_command(["get_property", "pause"])
        is_paused = pause_resp.get("data", False)

        state = PlaybackState.PAUSED if is_paused else PlaybackState.PLAYING

        # Get elapsed time
        time_resp = self._send_command(["get_property", "time-pos"])
        elapsed = float(time_resp.get("data", 0.0) or 0.0)

        duration_resp = self._send_command(["get_property", "duration"])
        duration_data = duration_resp.get("data")
        duration = float(duration_data) if duration_data is not None else None

        # Get volume
        vol_resp = self._send_command(["get_property", "volume"])
        vol_data = vol_resp.get("data")
        vol = self._current_volume if vol_data is None else int(vol_data)
        self._current_volume = vol

        return PlaybackStatus(
            state=state,
            elapsed_seconds=elapsed,
            duration_seconds=duration,
            volume=vol,
        )

    def set_volume(self, level: int) -> None:
        self._current_volume = max(0, min(100, level))
        if self._process:
            self._send_command(["set_property", "volume", self._current_volume])

    def seek(self, seconds: float) -> None:
        if self._process:
            self._send_command(["seek", seconds, "relative"])

    def wait_for_end(self, timeout: float | None = None) -> bool:
        return self._end_event.wait(timeout)

    @property
    def name(self) -> str:
        return "mpv"

    @property
    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            streaming=True,
            seeking=True,
            volume=True,
            reports_position=True,
        )
