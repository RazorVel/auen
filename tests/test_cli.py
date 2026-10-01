"""Tests for the scriptable auen command-line interface."""

import subprocess
from pathlib import Path
from unittest.mock import patch

from auen.cli import main


def test_config_set_get_and_reset(tmp_path: Path, capsys: object) -> None:
    with patch("auen.config.user_config_dir", return_value=str(tmp_path)):
        assert main(["config", "set", "playback.volume", "65"]) == 0
        assert main(["config", "get", "volume"]) == 0
        assert main(["config", "reset", "playback.volume"]) == 0

    output = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "volume=65" in output
    assert "65" in output
    assert "volume=80" in output


def test_config_accepts_human_readable_cache_size(tmp_path: Path, capsys: object) -> None:
    with patch("auen.config.user_config_dir", return_value=str(tmp_path)):
        assert main(["config", "set", "cache.max_size", "1.5GB"]) == 0

    output = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "cache_max_bytes=1610612736" in output


def test_config_rejects_unknown_setting(tmp_path: Path, capsys: object) -> None:
    with patch("auen.config.user_config_dir", return_value=str(tmp_path)):
        assert main(["config", "get", "made.up"]) == 2

    error = capsys.readouterr().err  # type: ignore[attr-defined]
    assert "unknown setting" in error


def test_config_save_round_trip(tmp_path: Path) -> None:
    with patch("auen.config.user_config_dir", return_value=str(tmp_path)):
        assert main(["config", "set", "session.mode", "stream_and_cache"]) == 0
        assert main(["config", "get", "session.mode"]) == 0

    assert (tmp_path / "config.toml").exists()


def test_doctor_probes_termux_api_and_volume(tmp_path: Path, capsys: object) -> None:
    commands = {
        "termux-media-player": "/data/data/com.termux/files/usr/bin/termux-media-player",
        "termux-volume": "/data/data/com.termux/files/usr/bin/termux-volume",
        "yt-dlp": "/data/data/com.termux/files/usr/bin/yt-dlp",
    }
    with (
        patch("auen.config.user_config_dir", return_value=str(tmp_path)),
        patch("auen.cli.shutil.which", side_effect=lambda name: commands.get(name)),
        patch(
            "auen.cli.subprocess.run",
            return_value=subprocess.CompletedProcess([], 0, "No track currently!", ""),
        ),
    ):
        assert main(["doctor"]) == 0

    output = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "Termux volume" in output
    assert "companion responded" in output


def test_doctor_reports_incomplete_termux_api_package(tmp_path: Path, capsys: object) -> None:
    commands = {
        "termux-media-player": "/termux-media-player",
        "yt-dlp": "/yt-dlp",
    }
    with (
        patch("auen.config.user_config_dir", return_value=str(tmp_path)),
        patch("auen.cli.shutil.which", side_effect=lambda name: commands.get(name)),
        patch(
            "auen.cli.subprocess.run",
            return_value=subprocess.CompletedProcess([], 1, "", "API unavailable"),
        ),
    ):
        assert main(["doctor"]) == 1

    output = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "termux-volume was not found" in output
    assert "API unavailable" in output
