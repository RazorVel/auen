"""Tests for mpv backend."""

import os
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from auen.backends import detect_backend
from auen.backends.mpv import MpvBackend
from auen.backends.termux import TermuxBackend
from auen.models import PlaybackState


@patch("subprocess.Popen")
@patch("pathlib.Path.exists")
@patch("threading.Thread")
@patch("auen.backends.mpv.MpvBackend._send_command", return_value={"error": "success"})
def test_mpv_play_starts_process(
    _mock_command: MagicMock, mock_thread: MagicMock, mock_exists: MagicMock, mock_popen: MagicMock
) -> None:
    backend = MpvBackend()
    backend._windows = False

    # Simulate socket exists after wait
    mock_exists.return_value = True
    mock_popen.return_value.poll.return_value = None

    backend.play("http://stream")

    mock_popen.assert_called_once()
    args = mock_popen.call_args[0][0]
    assert args[0] == "mpv"
    assert "http://stream" in args
    assert "--cache=yes" in args
    assert "--cache-pause-initial=yes" in args
    assert "--cache-pause-wait=3" in args
    assert "--demuxer-readahead-secs=30" in args
    assert backend._is_playing is True
    mock_thread.assert_called_once()


@patch("socket.socket")
@patch("pathlib.Path.exists")
@pytest.mark.skipif(os.name == "nt", reason="Unix socket command transport")
def test_mpv_pause_resume(mock_exists: MagicMock, mock_socket: MagicMock) -> None:
    backend = MpvBackend()
    backend._process = MagicMock()
    mock_exists.return_value = True

    mock_sock_inst = MagicMock()
    mock_socket.return_value.__enter__.return_value = mock_sock_inst
    mock_sock_inst.recv.return_value = b'{"error":"success"}\n'

    backend.pause()
    mock_sock_inst.sendall.assert_called()
    call_args = mock_sock_inst.sendall.call_args[0][0].decode("utf-8")
    assert "set_property" in call_args
    assert "pause" in call_args
    assert "true" in call_args.lower()

    backend.resume()
    call_args2 = mock_sock_inst.sendall.call_args[0][0].decode("utf-8")
    assert "false" in call_args2.lower()


@patch("socket.socket")
@patch("pathlib.Path.exists", return_value=True)
@pytest.mark.skipif(os.name == "nt", reason="Unix socket command transport")
def test_mpv_ipc_uses_newline_terminated_json(
    _mock_exists: MagicMock, mock_socket: MagicMock
) -> None:
    backend = MpvBackend()
    mock_sock_inst = MagicMock()
    mock_socket.return_value.__enter__.return_value = mock_sock_inst
    mock_sock_inst.recv.return_value = b'{"data":42,"error":"success"}\n'

    response = backend._send_command(["get_property", "time-pos"])

    sent = mock_sock_inst.sendall.call_args.args[0]
    assert sent.endswith(b"\n")
    assert not sent.endswith(b"\\n")
    assert response["data"] == 42


def test_mpv_stop_kills_process() -> None:
    backend = MpvBackend()
    mock_proc = MagicMock()
    backend._process = mock_proc

    backend.stop()
    mock_proc.terminate.assert_called_once()
    assert backend._is_playing is False
    assert backend._end_event.is_set() is True


def test_mpv_status_reports_duration() -> None:
    backend = MpvBackend()
    backend._process = MagicMock()
    backend._process.poll.return_value = None
    backend._send_command = MagicMock(  # type: ignore[method-assign]
        side_effect=[
            {"data": False},
            {"data": 12.5},
            {"data": 245.0},
            {"data": 73},
        ]
    )

    status = backend.get_status()

    assert status.state is PlaybackState.PLAYING
    assert status.elapsed_seconds == 12.5
    assert status.duration_seconds == 245.0
    assert status.volume == 73


@patch("shutil.which")
def test_detect_backend_auto_termux(mock_which: MagicMock) -> None:
    # First checks termux-media-player
    def mock_which_side_effect(x: str) -> str | None:
        return "/usr/bin/termux-media-player" if x == "termux-media-player" else None

    mock_which.side_effect = mock_which_side_effect
    backend = detect_backend("auto")
    assert isinstance(backend, TermuxBackend)


@patch("shutil.which")
def test_detect_backend_auto_mpv(mock_which: MagicMock) -> None:
    # Termux missing, mpv present
    mock_which.side_effect = lambda x: "/usr/bin/mpv" if x == "mpv" else None
    backend = detect_backend("auto")
    assert isinstance(backend, MpvBackend)


@patch("shutil.which")
def test_detect_backend_auto_prefers_mpv_over_termux_api(mock_which: MagicMock) -> None:
    mock_which.side_effect = lambda name: f"/usr/bin/{name}"

    backend = detect_backend("auto")

    assert isinstance(backend, MpvBackend)


@patch("shutil.which")
def test_detect_backend_nothing(mock_which: MagicMock) -> None:
    mock_which.return_value = None
    with pytest.raises(RuntimeError):
        detect_backend("auto")


def test_detect_backend_rejects_unknown_preference() -> None:
    with pytest.raises(ValueError, match="Unsupported audio backend"):
        detect_backend("vlc")


def test_windows_play_uses_named_pipe_and_hides_console() -> None:
    backend = MpvBackend()
    backend._windows = True
    with (
        patch("auen.backends.mpv.WindowsPipe") as pipe,
        patch("subprocess.Popen") as process,
        patch("subprocess.run", return_value=subprocess.CompletedProcess(
            [], 0, " --media-controls Flag (default: yes)\n",
        )),
        patch("threading.Thread"),
    ):
        process.return_value.poll.return_value = None
        pipe.return_value.__enter__.return_value.recv.return_value = b'{"error":"success"}\n'
        backend.play(r"C:\Music\song with spaces.mp3")
        assert f"--input-ipc-server={backend._pipe_name}" in process.call_args.args[0]
        assert process.call_args.kwargs["creationflags"] == 0x08000000
        assert "--media-controls=no" in process.call_args.args[0]
        assert "--input-media-keys=no" in process.call_args.args[0]
        assert pipe.call_count >= 2
        backend.stop()


@pytest.mark.parametrize("supported", [False, True])
def test_windows_media_option_probe_is_cached_and_old_mpv_stays_supported(supported: bool) -> None:
    backend = MpvBackend()
    backend._windows = True
    output = " --media-controls Flag (default: yes)\n" if supported else " --no-video Flag\n"
    with patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0, output)) as probe:
        options = backend._windows_input_options()
        assert "--input-media-keys=no" in options
        assert ("--media-controls=no" in options) == supported
        assert backend._windows_input_options() == options
        probe.assert_called_once()
        assert probe.call_args.kwargs["timeout"] == 2
        assert probe.call_args.kwargs["creationflags"] == 0x08000000


@pytest.mark.parametrize("error", [OSError("unavailable"), subprocess.TimeoutExpired("mpv", 2)])
def test_windows_media_option_probe_failure_does_not_block_playback(error: Exception) -> None:
    backend = MpvBackend()
    backend._windows = True
    with patch("subprocess.run", side_effect=error):
        assert backend._windows_input_options() == ["--input-media-keys=no"]


def test_windows_ipc_reads_split_events_and_response() -> None:
    backend = MpvBackend()
    backend._windows = True
    with patch("auen.backends.mpv.WindowsPipe") as pipe:
        connection = pipe.return_value.__enter__.return_value
        connection.recv.side_effect = [
            b'{"event":"start-file"}\n',
            b'{"data":',
            b'42,"error":"success"}\n',
        ]
        assert backend._send_command(["get_property", "time-pos"])["data"] == 42
        assert connection.sendall.call_args.args[0].endswith(b"\n")


def test_windows_ipc_timeout_and_malformed_response_are_reported() -> None:
    backend = MpvBackend()
    backend._windows = True
    with patch("auen.backends.mpv.WindowsPipe") as pipe:
        connection = pipe.return_value.__enter__.return_value
        connection.recv.side_effect = TimeoutError("pipe timed out")
        assert "timed out" in backend._send_command(["get_property", "pause"])["error"]
        connection.recv.side_effect = None
        connection.recv.return_value = b"[]\n"
        assert "JSON object" in backend._send_command(["get_property", "pause"])["error"]
