"""Run yt-dlp in an owned, cancellable process instead of an unkillable thread."""

from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import CancelledError
from pathlib import Path
from typing import Any

_MAX_RESPONSE = 8 * 1024 * 1024


class ExtractionError(RuntimeError):
    """A bounded extraction failed, timed out, or returned invalid data."""


class Extractor:
    """Isolate network/DNS/library stalls; cancellation also reaps the child."""

    def __init__(self) -> None:
        self.cancelled = threading.Event()
        self._launch_lock = threading.Lock()

    def close(self) -> None:
        with self._launch_lock:
            self.cancelled.set()

    def extract(
        self, target: str, options: dict[str, Any], *, download: bool = False,
        timeout: float = 45.0,
    ) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="auen-extract-") as directory:
            request = Path(directory) / "request.json"
            response = Path(directory) / "response.json"
            request.write_text(json.dumps({
                "target": target, "options": options, "download": download,
            }), encoding="utf-8")
            with self._launch_lock:
                if self.cancelled.is_set():
                    raise CancelledError("YouTube request cancelled")
                process = subprocess.Popen(
                    [sys.executable, "-m", "auen.media.worker", str(request), str(response)],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=os.name != "nt",
                    creationflags=0x08000200 if os.name == "nt" else 0,
                )
            deadline = time.monotonic() + timeout
            try:
                while process.poll() is None:
                    if self.cancelled.wait(0.05):
                        raise CancelledError("YouTube request cancelled")
                    if time.monotonic() >= deadline:
                        raise ExtractionError(
                            "YouTube request timed out. Check your connection/VPN and retry."
                        )
                if self.cancelled.is_set():
                    raise CancelledError("YouTube request cancelled")
                if not response.is_file() or response.stat().st_size > _MAX_RESPONSE:
                    raise ExtractionError("YouTube worker returned no valid response")
                payload = json.loads(response.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    raise ExtractionError("YouTube worker returned invalid data")
                if payload.get("error"):
                    raise ExtractionError(str(payload["error"]))
                result = payload.get("result")
                if process.returncode != 0 or not isinstance(result, dict):
                    raise ExtractionError("YouTube worker failed")
                return result
            except (OSError, ValueError) as exc:
                raise ExtractionError("Could not read the YouTube worker response") from exc
            finally:
                _stop_process(process)


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    """Terminate only our worker tree, including any downloader child processes."""
    if sys.platform != "win32":
        # The worker owns its process group; also remove helpers left by an exit.
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
    elif process.poll() is None:
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=2.0, check=False, creationflags=0x08000000,
            )
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
    if process.poll() is None:
        process.kill()
    process.wait(timeout=2.0)


def _metadata(result: dict[str, Any], *, limit: int) -> dict[str, Any]:
    """Return only the bounded, serializable fields the application consumes."""
    fields = ("id", "title", "url", "webpage_url", "duration", "playlist_count", "album")
    payload = {key: result[key] for key in fields if key in result}
    if "entries" in result:
        from itertools import islice

        payload["entries"] = [
            {key: entry[key] for key in fields if key in entry}
            for entry in islice(result.get("entries") or [], limit)
            if isinstance(entry, dict)
        ]
    return payload


def _main(request: Path, response: Path) -> None:
    from yt_dlp import YoutubeDL  # type: ignore[import-untyped]

    try:
        data = json.loads(request.read_text(encoding="utf-8"))
        options = {
            "socket_timeout": 10, "retries": 1, "extractor_retries": 1,
            "fragment_retries": 1, "noprogress": True, **data["options"],
        }
        with YoutubeDL(options) as ydl:
            result = ydl.extract_info(data["target"], download=data["download"])
            if not isinstance(result, dict):
                raise ExtractionError("YouTube returned an invalid response")
            payload = {"result": _metadata(result, limit=int(options.get("playlistend", 100)))}
        encoded = json.dumps(payload, ensure_ascii=True)
        if len(encoded) > _MAX_RESPONSE:
            raise ExtractionError("YouTube response exceeded the size limit")
    except Exception as exc:
        encoded = json.dumps({"error": str(exc)[:8000]})
    response.write_text(encoded, encoding="utf-8")
