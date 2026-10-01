"""Tests for Termux backend."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from auen.backends.termux import TermuxBackend
from auen.models import PlaybackState


def completed(stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")


@patch("subprocess.run")
def test_termux_play(mock_run: MagicMock) -> None:
    mock_run.return_value = completed("Now Playing: file.opus")
    backend = TermuxBackend()
    backend.play("/path/to/file.opus")
    mock_run.assert_called_with(
        ["termux-media-player", "play", "/path/to/file.opus"],
        capture_output=True,
        text=True,
        check=False,
        timeout=5.0,
    )
    assert backend._is_playing is True
    assert backend._end_event.is_set() is False


@patch("subprocess.run")
def test_termux_pause_resume(mock_run: MagicMock) -> None:
    mock_run.return_value = completed()
    backend = TermuxBackend()
    backend.play("test")

    backend.pause()
    mock_run.assert_called_with(
        ["termux-media-player", "pause"],
        capture_output=True,
        text=True,
        check=False,
        timeout=5.0,
    )
    assert backend._is_playing is False

    backend.resume()
    mock_run.assert_called_with(
        ["termux-media-player", "play"],
        capture_output=True,
        text=True,
        check=False,
        timeout=5.0,
    )
    assert backend._is_playing is True


@patch("subprocess.run")
def test_termux_get_status_playing(mock_run: MagicMock) -> None:
    backend = TermuxBackend()
    backend._is_playing = True

    mock_run.return_value = completed(
        "Status: Playing\nTrack: Test\nCurrent Position: 01:02 / 03:45"
    )

    status = backend.get_status()
    assert status.state == PlaybackState.PLAYING
    assert status.elapsed_seconds == 62


@patch("subprocess.run")
def test_termux_get_status_paused(mock_run: MagicMock) -> None:
    backend = TermuxBackend()
    mock_run.return_value = completed(
        "Status: Paused\nTrack: Test\nCurrent Position: 1:02:03 / 1:30:00"
    )

    status = backend.get_status()

    assert status.state == PlaybackState.PAUSED
    assert status.elapsed_seconds == 3723


@patch("subprocess.run")
def test_termux_get_status_stopped(mock_run: MagicMock) -> None:
    backend = TermuxBackend()
    backend._is_playing = True

    mock_run.return_value = completed("No track currently!")

    status = backend.get_status()
    assert status.state == PlaybackState.STOPPED
    assert backend._is_playing is False
    assert backend._end_event.is_set() is True


def test_termux_supports_streaming() -> None:
    backend = TermuxBackend()
    assert backend.supports_streaming is False
    assert backend.supports_seek is False
    assert backend.capabilities.reports_position is True
    assert backend.capabilities.volume is False


@patch("subprocess.run")
def test_termux_volume_is_optional(mock_run: MagicMock) -> None:
    mock_run.return_value = completed()
    backend = TermuxBackend(volume_available=True)

    backend.set_volume(50)

    mock_run.assert_called_once_with(
        ["termux-volume", "music", "8"],
        capture_output=True,
        text=True,
        check=False,
        timeout=5.0,
    )
    assert backend.capabilities.volume is True


@patch("subprocess.run")
def test_termux_command_failure_is_actionable(mock_run: MagicMock) -> None:
    mock_run.return_value = subprocess.CompletedProcess(
        [], 1, stdout="", stderr="API unavailable"
    )

    with pytest.raises(RuntimeError, match="API unavailable"):
        TermuxBackend().play("/music/file.m4a")


@patch("subprocess.run", side_effect=subprocess.TimeoutExpired("termux-media-player", 1))
def test_termux_command_timeout_is_bounded(_mock_run: MagicMock) -> None:
    with pytest.raises(RuntimeError, match="did not respond"):
        TermuxBackend(command_timeout=1).get_status()
