"""Tests for mpv backend."""

from unittest.mock import MagicMock, patch

import pytest

from auen.backends import detect_backend
from auen.backends.mpv import MpvBackend
from auen.backends.termux import TermuxBackend
from auen.models import PlaybackState


@patch("subprocess.Popen")
@patch("pathlib.Path.exists")
@patch("threading.Thread")
def test_mpv_play_starts_process(
    mock_thread: MagicMock, mock_exists: MagicMock, mock_popen: MagicMock
) -> None:
    backend = MpvBackend()

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
