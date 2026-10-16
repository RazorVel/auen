"""Real child-process lifecycle checks, with no network requests."""

import json
import subprocess
import sys
import time
from concurrent.futures import CancelledError, ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from auen.media.extractor import ExtractionError, Extractor, _main


@pytest.mark.parametrize("cancel", [False, True])
def test_stalled_extraction_is_bounded_and_reaps_child(tmp_path: Path, cancel: bool) -> None:
    runner = Extractor()
    launched: list[subprocess.Popen] = []
    original_popen = subprocess.Popen
    entered = tmp_path / "entered"

    def launch(_command, **kwargs):
        if _command[1:3] != ["-m", "auen.media.worker"]:
            return original_popen(_command, **kwargs)
        process = original_popen([
            sys.executable, "-c",
            "import pathlib,sys,time; pathlib.Path(sys.argv[1]).touch(); time.sleep(30)",
            str(entered),
        ], **kwargs)
        launched.append(process)
        return process

    with patch("auen.media.extractor.subprocess.Popen", side_effect=launch):
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(runner.extract, "unused", {}, timeout=2 if cancel else 0.5)
            try:
                deadline = time.monotonic() + 3
                while not entered.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                assert entered.exists()
                if cancel:
                    runner.close()
                with pytest.raises(CancelledError if cancel else ExtractionError):
                    future.result(timeout=3)
                assert len(launched) == 1 and launched[0].poll() is not None
                # Keep unrelated commands real, notably Windows taskkill used
                # by production cleanup; do not turn them into stalled workers.
                subprocess.run([sys.executable, "-c", "pass"], check=True, timeout=3)
                assert len(launched) == 1
            finally:
                runner.close()
        with pytest.raises(CancelledError):
            runner.extract("unused", {})
        assert len(launched) == 1


def test_response_from_owned_process_is_read_and_worker_reaped() -> None:
    original_popen = subprocess.Popen
    launched: list[subprocess.Popen] = []

    def launch(command, **kwargs):
        if command[1:3] != ["-m", "auen.media.worker"]:
            return original_popen(command, **kwargs)
        process = original_popen([
            sys.executable, "-c",
            "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text("
            "'{\"result\":{\"title\":\"local fixture\",\"url\":\"https://example.test/audio\"}}')",
            command[-1],
        ], **kwargs)
        launched.append(process)
        return process

    with patch("auen.media.extractor.subprocess.Popen", side_effect=launch):
        result = Extractor().extract("unused", {})
    assert result["title"] == "local fixture"
    assert launched[0].poll() == 0


def test_worker_limits_retries_and_projects_metadata(tmp_path: Path) -> None:
    request, response = tmp_path / "request", tmp_path / "response"
    request.write_text(json.dumps({
        "target": "unused", "options": {"playlistend": 1}, "download": False,
    }))
    ydl = MagicMock()
    ydl.extract_info.return_value = {
        "title": "list", "formats": ["not needed"],
        "entries": [{"id": "one", "title": "One", "formats": []}, {"id": "two"}],
    }
    with patch("yt_dlp.YoutubeDL") as factory:
        factory.return_value.__enter__.return_value = ydl
        _main(request, response)
    options = factory.call_args.args[0]
    assert options["socket_timeout"] == 10
    assert options["retries"] == options["extractor_retries"] == 1
    assert json.loads(response.read_text()) == {
        "result": {"title": "list", "entries": [{"id": "one", "title": "One"}]},
    }


def test_worker_serializes_error_without_traceback(tmp_path: Path) -> None:
    request, response = tmp_path / "request", tmp_path / "response"
    request.write_text(json.dumps({"target": "unused", "options": {}, "download": False}))
    with patch("yt_dlp.YoutubeDL", side_effect=RuntimeError("offline fixture")):
        _main(request, response)
    assert json.loads(response.read_text()) == {"error": "offline fixture"}


def test_actual_module_entrypoint_without_any_network_call(tmp_path: Path) -> None:
    request, response = tmp_path / "request", tmp_path / "response"
    request.write_text("{}")  # Invalid local request must fail before extraction.
    completed = subprocess.run([
        sys.executable, "-m", "auen.media.worker", str(request), str(response),
    ], capture_output=True, timeout=10, check=False)
    assert completed.returncode == 0
    assert completed.stderr == b""
    assert "error" in json.loads(response.read_text())
