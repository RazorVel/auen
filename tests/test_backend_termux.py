"""Tests for Termux backend."""

from unittest.mock import MagicMock, patch

from auen.backends.termux import TermuxBackend
from auen.models import PlaybackState


@patch("subprocess.run")
def test_termux_play(mock_run: MagicMock) -> None:
    backend = TermuxBackend()
    backend.play("/path/to/file.opus")
    mock_run.assert_called_with(
        ["termux-media-player", "play", "/path/to/file.opus"],
        capture_output=True,
        check=False,
    )
    assert backend._is_playing is True
    assert backend._end_event.is_set() is False


@patch("subprocess.run")
def test_termux_pause_resume(mock_run: MagicMock) -> None:
    backend = TermuxBackend()
    backend.play("test")

    backend.pause()
    mock_run.assert_called_with(
        ["termux-media-player", "pause"],
        capture_output=True,
        check=False,
    )
    assert backend._is_playing is False

    backend.resume()
    mock_run.assert_called_with(
        ["termux-media-player", "play"],
        capture_output=True,
        check=False,
    )
    assert backend._is_playing is True


@patch("subprocess.run")
def test_termux_get_status_playing(mock_run: MagicMock) -> None:
    backend = TermuxBackend()
    backend._is_playing = True

    mock_result = MagicMock()
    mock_result.stdout = "Current track: Test"
    mock_run.return_value = mock_result

    status = backend.get_status()
    assert status.state == PlaybackState.PLAYING


@patch("subprocess.run")
def test_termux_get_status_stopped(mock_run: MagicMock) -> None:
    backend = TermuxBackend()
    backend._is_playing = True

    mock_result = MagicMock()
    mock_result.stdout = "No track currently!"
    mock_run.return_value = mock_result

    status = backend.get_status()
    assert status.state == PlaybackState.STOPPED
    assert backend._is_playing is False
    assert backend._end_event.is_set() is True


def test_termux_supports_streaming() -> None:
    backend = TermuxBackend()
    assert backend.supports_streaming is False
    assert backend.supports_seek is False
