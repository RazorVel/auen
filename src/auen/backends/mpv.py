"""Mpv media player backend via JSON IPC."""

import contextlib
import json
import os
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from auen.backends.base import AudioBackend, BackendCapabilities
from auen.models import PlaybackState, PlaybackStatus


class MpvBackend(AudioBackend):
    """mpv backend using JSON IPC socket for control."""

    def __init__(self) -> None:
        self._socket_path = Path(tempfile.gettempdir()) / f"auen-mpv-{os.getpid()}-{id(self)}.sock"
        self._process: subprocess.Popen[bytes] | None = None
        self._lock = threading.Lock()
        self._current_volume = 80
        self._end_event = threading.Event()
        self._is_playing = False

    def play(self, uri: str) -> None:
        with self._lock:
            if self._process:
                self._kill_process()

            self._end_event.clear()

            # Start mpv in idle mode to keep it alive or just play the file
            cmd = [
                "mpv",
                "--no-video",
                "--cache=yes",
                "--cache-pause=yes",
                "--cache-pause-initial=yes",
                "--cache-pause-wait=3",
                "--demuxer-readahead-secs=30",
                f"--input-ipc-server={self._socket_path}",
                "--quiet",
                uri,
            ]
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            # Wait for socket
            start = time.time()
            while not self._socket_path.exists():
                if self._process.poll() is not None:
                    self._process = None
                    raise RuntimeError("mpv exited before its control socket became available")
                if time.time() - start > 5:
                    self._kill_process()
                    raise RuntimeError("mpv socket didn't appear in time.")
                time.sleep(0.1)

            self._is_playing = True

            # Monitor process in background
            process = self._process
            threading.Thread(target=self._monitor_process, args=(process,), daemon=True).start()

            self.set_volume(self._current_volume)

    def _monitor_process(self, process: subprocess.Popen[bytes]) -> None:
        process.wait()
        with self._lock:
            if self._process is process:
                self._process = None
                self._is_playing = False
                self._end_event.set()
                self._remove_socket()

    def _remove_socket(self) -> None:
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
        if not self._socket_path.exists():
            return {"error": "no socket"}

        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(2.0)
                s.connect(str(self._socket_path))
                req = json.dumps({"command": command}) + "\n"
                s.sendall(req.encode("utf-8"))

                data = b""
                max_response_bytes = 1024 * 1024
                while b"\n" not in data:
                    chunk = s.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                    if len(data) > max_response_bytes:
                        raise RuntimeError("mpv IPC response exceeded 1 MiB")

                if not data:
                    return {}

                lines = data.decode("utf-8").splitlines()
                for line in lines:
                    if line.strip():
                        resp = json.loads(line)
                        if "event" not in resp:
                            return dict(resp)
            return {}
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, RuntimeError) as exc:
            return {"error": str(exc)}

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

        # Get volume
        vol_resp = self._send_command(["get_property", "volume"])
        vol_data = vol_resp.get("data")
        vol = self._current_volume if vol_data is None else int(vol_data)
        self._current_volume = vol

        return PlaybackStatus(
            state=state,
            elapsed_seconds=elapsed,
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
