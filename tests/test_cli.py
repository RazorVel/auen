"""Tests for the scriptable auen command-line interface."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

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


@pytest.mark.parametrize("dependency,bus,label", [
    (False, True, "install auen[linux]"),
    (True, False, "no desktop session bus"),
    (True, True, "dependency and session-bus address available"),
])
def test_doctor_linux_media_controls_are_optional(
    tmp_path: Path, capsys: object, dependency: bool, bus: bool, label: str,
) -> None:
    with (
        patch("auen.config.user_config_dir", return_value=str(tmp_path)),
        patch("auen.cli.sys.platform", "linux"),
        patch.dict("os.environ", {"DBUS_SESSION_BUS_ADDRESS": "test" if bus else ""}, clear=True),
        patch("auen.cli.shutil.which", side_effect=lambda name:
              "/usr/bin/mpv" if name == "mpv" else None),
        patch("auen.cli.importlib.util.find_spec", side_effect=lambda name:
              object() if name != "dbus_next" or dependency else None),
    ):
        assert main(["doctor"]) == 0
    assert label in capsys.readouterr().out  # type: ignore[attr-defined]


@pytest.mark.parametrize("missing", [True, False])
def test_doctor_windows_media_controls_are_optional(
    tmp_path: Path, capsys: object, missing: bool,
) -> None:
    with (
        patch("auen.config.user_config_dir", return_value=str(tmp_path)),
        patch("auen.cli.sys.platform", "win32"),
        patch("auen.cli.shutil.which", side_effect=lambda name:
              "/usr/bin/mpv" if name == "mpv" else None),
        patch("auen.cli.importlib.util.find_spec", return_value=object()),
        patch("auen.windows_media.missing_windows_media_packages",
              return_value=["winrt-Windows.Media"] if missing else []),
    ):
        assert main(["doctor"]) == 0
    output = capsys.readouterr().out  # type: ignore[attr-defined]
    assert ("install auen[windows]" if missing else "routing needs a live test") in output


def test_config_accepts_human_readable_cache_size(tmp_path: Path, capsys: object) -> None:
    with patch("auen.config.user_config_dir", return_value=str(tmp_path)):
        assert main(["config", "set", "cache.max_size", "1.5GB"]) == 0

    output = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "cache_max_bytes=1610612736" in output


def test_config_can_disable_android_notification(tmp_path: Path, capsys: object) -> None:
    with patch("auen.config.user_config_dir", return_value=str(tmp_path)):
        assert main(["config", "set", "android.notification", "false"]) == 0

    output = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "android_notification=false" in output


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


def test_doctor_checks_the_bundled_ytdlp_module_not_a_global_command(
    tmp_path: Path, capsys: object
) -> None:
    commands = {"mpv": "/usr/bin/mpv"}
    with (
        patch("auen.config.user_config_dir", return_value=str(tmp_path)),
        patch("auen.cli.shutil.which", side_effect=lambda name: commands.get(name)),
        patch("auen.cli.importlib.util.find_spec", return_value=None),
    ):
        assert main(["doctor"]) == 1

    output = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "yt-dlp Python package was not found" in output


def test_doctor_reports_mpv_as_preferred_when_both_backends_exist(
    tmp_path: Path, capsys: object
) -> None:
    commands = {
        "mpv": "/data/data/com.termux/files/usr/bin/mpv",
        "termux-media-player": "/data/data/com.termux/files/usr/bin/termux-media-player",
        "termux-volume": "/data/data/com.termux/files/usr/bin/termux-volume",
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
    assert "mpv" in output
    assert "preferred by automatic backend" in output
    assert "Termux media player" in output


def test_remote_command_contacts_running_instance(tmp_path: Path, capsys: object) -> None:
    config = MagicMock(state_dir=tmp_path)
    with (
        patch("auen.cli.AuenConfig.load", return_value=config),
        patch(
            "auen.cli.send_remote_command",
            return_value={"ok": True, "message": "Playback toggled"},
        ) as send,
    ):
        assert main(["remote", "toggle"]) == 0

    send.assert_called_once_with(tmp_path, "toggle")
    assert "Playback toggled" in capsys.readouterr().out  # type: ignore[attr-defined]


@pytest.mark.parametrize("command", ["play", "pause", "previous"])
def test_remote_cli_accepts_explicit_media_commands(tmp_path: Path, command: str) -> None:
    config = MagicMock(state_dir=tmp_path)
    with (
        patch("auen.cli.AuenConfig.load", return_value=config),
        patch("auen.cli.send_remote_command", return_value={"ok": True}) as send,
    ):
        assert main(["remote", command]) == 0
    send.assert_called_once_with(tmp_path, command)


def test_remote_command_reports_missing_instance(tmp_path: Path, capsys: object) -> None:
    config = MagicMock(state_dir=tmp_path)
    with (
        patch("auen.cli.AuenConfig.load", return_value=config),
        patch(
            "auen.cli.send_remote_command",
            side_effect=RuntimeError("no running auen instance was found"),
        ),
    ):
        assert main(["remote", "status"]) == 2

    assert "no running auen instance" in capsys.readouterr().err  # type: ignore[attr-defined]


def test_media_pairing_requires_opt_in_bridge(tmp_path: Path, capsys: object) -> None:
    with patch("auen.cli.AuenConfig.load", return_value=MagicMock(state_dir=tmp_path)):
        assert main(["media", "pair"]) == 2
    assert "enable Android headphone controls" in capsys.readouterr().err  # type: ignore[attr-defined]


def test_media_connect_does_not_print_pairing_credentials(tmp_path: Path, capsys: object) -> None:
    with (
        patch("auen.cli.AuenConfig.load", return_value=MagicMock(state_dir=tmp_path)),
        patch("auen.cli.open_media_companion") as open_companion,
    ):
        assert main(["media", "connect"]) == 0
    open_companion.assert_called_once_with(tmp_path)
    assert "Opened auen media companion" in capsys.readouterr().out  # type: ignore[attr-defined]
