"""Optional media bridge: private transport, cached metadata, and safe pairing."""

import json
import os
import socket
import subprocess
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, call, patch
from urllib.parse import parse_qs, urlparse

import pytest

from auen.android_media import (
    ENDPOINT_NAME,
    AndroidMediaBridge,
    media_identity,
    media_pairing_code,
    open_media_companion,
    read_media_endpoint,
    youtube_thumbnail,
)
from auen.remote import RemoteControlServer


def request(
    path: Path, command: str, *, token: str | None = None, **parameters: object,
) -> dict[str, object]:
    endpoint = json.loads(path.read_text())
    with socket.create_connection(("127.0.0.1", endpoint["port"]), timeout=2) as connection:
        connection.sendall(json.dumps({
            "command": command, "token": endpoint["token"] if token is None else token,
            **parameters,
        }).encode() + b"\n")
        data = bytearray()
        while b"\n" not in data:
            chunk = connection.recv(4096)
            assert chunk
            data.extend(chunk)
        return json.loads(data)  # type: ignore[no-any-return]


def test_bridge_coexists_with_remote_without_polling_ui(tmp_path: Path) -> None:
    commands: list[str] = []
    normal = RemoteControlServer(tmp_path, lambda _command: {}, tcp=True)
    bridge = AndroidMediaBridge(tmp_path, lambda value: commands.append(value) or {})
    normal.start()
    try:
        bridge.start()
        try:
            assert bridge.server.path != normal.path
            if os.name != "nt":
                assert bridge.server.path.stat().st_mode & 0o777 == 0o600
            assert bridge.server._socket.getsockname()[0] == "127.0.0.1"
            assert request(bridge.server.path, "status")["state"] == "stopped"
            assert commands == []
            assert bridge.connected
            bridge.update(state="paused", title="日本語 title", elapsed=42, duration=180,
                          can_next=True, can_previous=True)
            result = request(bridge.server.path, "status")
            assert result["title"] == "日本語 title"
            assert result["elapsed_seconds"] == 42
            assert result["duration_seconds"] == 180
            assert result["protocol"] == 1
            assert commands == []
            for command in ("play", "pause", "previous", "next", "stop"):
                assert request(bridge.server.path, command)["ok"] is True
            assert commands == ["play", "pause", "previous", "next", "stop"]
        finally:
            bridge.close()
        assert normal.path.exists()
        assert not bridge.server.path.exists()
    finally:
        normal.close()


def test_wrong_token_cannot_control_or_claim_connected_companion(tmp_path: Path) -> None:
    commands: list[str] = []
    bridge = AndroidMediaBridge(tmp_path, lambda command: commands.append(command) or {})
    bridge.start()
    try:
        assert request(bridge.server.path, "status", token="wrong")["ok"] is False
        assert request(bridge.server.path, "stop", token="wrong")["ok"] is False
        assert commands == []
        assert not bridge.connected
        request(bridge.server.path, "status")
        with patch("auen.android_media.time.monotonic", return_value=bridge._last_seen + 6):
            assert not bridge.connected
    finally:
        bridge.close()


def test_pairing_discloses_only_loopback_endpoint_when_requested(tmp_path: Path) -> None:
    bridge = AndroidMediaBridge(tmp_path, lambda _command: {})
    bridge.start()
    try:
        code = urlparse(media_pairing_code(tmp_path))
        assert code.scheme == "auen"
        assert code.netloc == "media"
        fields = parse_qs(code.query)
        port, token = read_media_endpoint(tmp_path)
        assert fields == {"protocol": ["1"], "port": [str(port)], "token": [token]}
    finally:
        bridge.close()


@pytest.mark.parametrize("endpoint", [
    {}, [], {"port": True, "token": "a" * 64}, {"port": 0, "token": "a" * 64},
    {"port": 65536, "token": "a" * 64}, {"port": 22, "token": "oops"},
])
def test_invalid_pairing_endpoint_does_not_leak_credentials(
    tmp_path: Path, endpoint: object,
) -> None:
    (tmp_path / ENDPOINT_NAME).write_text(json.dumps(endpoint))
    with pytest.raises(ValueError, match="invalid media endpoint"):
        media_pairing_code(tmp_path)


def test_missing_bridge_reports_optional_setup(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="enable Android headphone controls"):
        media_pairing_code(tmp_path)


def test_open_companion_timeout_error_omits_secret_command(tmp_path: Path) -> None:
    token = "a" * 64
    (tmp_path / ENDPOINT_NAME).write_text(json.dumps({"port": 12345, "token": token}))
    with (
        patch("auen.android_media.shutil.which", return_value="/termux/am"),
        patch("auen.android_media.subprocess.run",
              side_effect=subprocess.TimeoutExpired(["am", token], 5)),
        pytest.raises(RuntimeError) as error,
    ):
        open_media_companion(tmp_path)
    assert token not in str(error.value)


def test_open_companion_uses_explicit_activity_without_shell(tmp_path: Path) -> None:
    (tmp_path / ENDPOINT_NAME).write_text(json.dumps({"port": 12345, "token": "b" * 64}))
    with (
        patch("auen.android_media.shutil.which", return_value="/termux/am"),
        patch("auen.android_media.subprocess.run",
              return_value=subprocess.CompletedProcess([], 0, None, "")) as run,
    ):
        open_media_companion(tmp_path)
    assert "--es" in run.call_args.args[0]
    assert run.call_args.kwargs.get("shell", False) is False
    assert run.call_args.kwargs["stdout"] == subprocess.DEVNULL
    assert "auto-connect" in run.call_args.args[0]


@pytest.mark.parametrize("uri", [
    "https://www.youtube.com/watch?v=Abc_123-XYZ&list=other",
    "https://youtu.be/Abc_123-XYZ?t=10",
    "https://music.youtube.com/watch?v=Abc_123-XYZ",
    "https://m.youtube.com/shorts/Abc_123-XYZ",
    "https://youtube.com/embed/Abc_123-XYZ",
    "https://youtube.com/live/Abc_123-XYZ",
])
def test_public_artwork_without_extraction(uri: str) -> None:
    assert youtube_thumbnail(uri) == "https://i.ytimg.com/vi/Abc_123-XYZ/hqdefault.jpg"


@pytest.mark.parametrize("uri", [
    None, "", "/local/audio.mp3", "file:///audio.mp3", "https://youtube.com/watch?v=bad",
    "https://youtube.com.evil/watch?v=Abc_123-XYZ", "https://i.ytimg.com/arbitrary",
    "https://youtube.com@evil/watch?v=Abc_123-XYZ", "https://[invalid/",
    "ftp://youtube.com/watch?v=Abc_123-XYZ", "https://youtu.be/Abc_123-XYZ/extra",
])
def test_artwork_rejects_non_video_sources(uri: str | None) -> None:
    assert youtube_thumbnail(uri) is None


def test_snapshot_artwork_clears_when_playback_stops(tmp_path: Path) -> None:
    bridge = AndroidMediaBridge(tmp_path, lambda _command: {})
    bridge.update(state="playing", title="song", source_uri="https://youtu.be/Abc_123-XYZ")
    assert bridge._dispatch("status")["thumbnail_url"]
    bridge.update(state="stopped", title="Nothing playing")
    assert bridge._dispatch("status")["thumbnail_url"] is None


def test_action_acknowledgement_contains_refreshed_state_without_extra_poll(
    tmp_path: Path,
) -> None:
    def act(command: str) -> dict[str, str]:
        bridge.update(state="paused" if command == "pause" else "playing", title="song")
        return {"message": "accepted"}

    bridge = AndroidMediaBridge(tmp_path, act)
    bridge.update(state="playing", title="song")
    assert bridge._dispatch("pause")["state"] == "paused"
    assert bridge._dispatch("play")["state"] == "playing"
    assert bridge._dispatch("play")["message"] == "accepted"


def test_autoconnect_bootstraps_once_then_only_quiet_bounded_retries(tmp_path: Path) -> None:
    bridge = AndroidMediaBridge(tmp_path, lambda _command: {})
    bridge._stop = MagicMock(spec=threading.Event)
    bridge._stop.wait.side_effect = [False] * 6 + [True]
    endpoint = (12345, "a" * 64)
    with patch("auen.android_media._companion_command") as launch:
        bridge._connect_loop(endpoint)
    assert launch.call_args_list == [call(endpoint, automatic=True)] + [
        call(endpoint, broadcast="connect") for _ in range(5)
    ] + [call(endpoint, broadcast="shutdown")]
    assert bridge._stop.wait.call_args_list == [
        call(value) for value in (1, 5, 10, 20, 30, 30, 30)
    ]


def test_missing_apk_is_nonfatal_and_still_retried_without_opening_windows(tmp_path: Path) -> None:
    bridge = AndroidMediaBridge(tmp_path, lambda _command: {})
    bridge._stop = MagicMock(spec=threading.Event)
    bridge._stop.wait.side_effect = [False, False, True]
    with patch(
        "auen.android_media._companion_command", side_effect=RuntimeError("absent")
    ) as launch:
        bridge._connect_loop((12345, "a" * 64))
    assert launch.call_count == 3
    assert launch.call_args_list[1].kwargs == {"broadcast": "connect"}


def test_connected_idle_companion_is_not_relaunched(tmp_path: Path) -> None:
    bridge = AndroidMediaBridge(tmp_path, lambda _command: {})
    bridge._stop = MagicMock(spec=threading.Event)
    bridge._stop.wait.side_effect = [False, False, True]
    bridge._dispatch("status")
    with patch("auen.android_media._companion_command") as launch:
        bridge._connect_loop((12345, "a" * 64))
    assert launch.call_args_list == [call((12345, "a" * 64), broadcast="shutdown")]


def test_background_retry_uses_only_explicit_authenticated_receiver(tmp_path: Path) -> None:
    from auen.android_media import _companion_command

    with (
        patch("auen.android_media.shutil.which", return_value="/termux/am"),
        patch("auen.android_media.subprocess.run",
              return_value=subprocess.CompletedProcess([], 0, None, "")) as run,
    ):
        _companion_command((12345, "a" * 64), broadcast="connect")
    args = run.call_args.args[0]
    assert args[:4] == ["/termux/am", "broadcast", "-n",
                         "io.github.razorvel.auen.media/.ConnectionReceiver"]
    assert "bridge-token" in args and "a" * 64 in args
    assert "start" not in args


def test_slow_android_start_does_not_hold_playback_shutdown(tmp_path: Path) -> None:
    bridge = AndroidMediaBridge(tmp_path, lambda _command: {})
    started = threading.Event()
    release = threading.Event()

    def slow_launch(*_args: object, **kwargs: object) -> None:
        if kwargs.get("automatic"):
            started.set()
            assert release.wait(3)

    bridge.start()
    with patch("auen.android_media._companion_command", side_effect=slow_launch) as launch:
        try:
            bridge.start_autoconnect()
            assert started.wait(2)
            before = time.monotonic()
            bridge.close()
            assert time.monotonic() - before < 1.5
            assert not bridge.server.path.exists()
        finally:
            bridge.close()
            release.set()
            assert bridge._connector is not None
            bridge._connector.join(timeout=2)
        assert not bridge._connector.is_alive()
        assert launch.call_args.kwargs == {"broadcast": "shutdown"}


def test_authenticated_seek_checks_current_media_and_capability(tmp_path: Path) -> None:
    seek = MagicMock(return_value={"message": "seeked"})
    bridge = AndroidMediaBridge(tmp_path, lambda _command: {}, seek_handler=seek)
    uri = "/private/local.opus"
    bridge.update(state="paused", title="Local", source_uri=uri, duration=180, can_seek=True)
    bridge.start()
    try:
        status = request(bridge.server.path, "status")
        assert status["can_seek"] is True
        assert status["media_id"] == media_identity(uri)
        assert uri not in json.dumps(status)
        result = request(bridge.server.path, "seek", seconds=42.5, media_id=media_identity(uri))
        assert result["ok"] is True
        seek.assert_called_once_with(42.5, media_identity(uri))
        seek.reset_mock()
        assert request(bridge.server.path, "seek", token="wrong", seconds=1,
                       media_id=media_identity(uri))["ok"] is False
        assert request(bridge.server.path, "seek", seconds=1,
                       media_id=media_identity("/previous.opus"))["ok"] is False
        bridge.update(state="stopped", title="Idle")
        assert request(bridge.server.path, "seek", seconds=1,
                       media_id=media_identity(uri))["ok"] is False
        seek.assert_not_called()
    finally:
        bridge.close()


@pytest.mark.parametrize("seconds", [None, True, -1, "10", float("nan"), float("inf"), 10**400])
def test_invalid_seek_never_reaches_player(tmp_path: Path, seconds: object) -> None:
    seek = MagicMock()
    bridge = AndroidMediaBridge(tmp_path, lambda _command: {}, seek_handler=seek)
    bridge.update(state="playing", title="song", source_uri="track", duration=180, can_seek=True)
    with pytest.raises(ValueError, match="invalid seek position"):
        bridge._seek({"seconds": seconds, "media_id": media_identity("track")})
    seek.assert_not_called()


@pytest.mark.parametrize("state,duration", [("stopped", 10), ("buffering", 10), ("playing", None)])
def test_seek_not_advertised_without_ready_track(
    tmp_path: Path, state: str, duration: float | None,
) -> None:
    bridge = AndroidMediaBridge(tmp_path, lambda _command: {}, seek_handler=MagicMock())
    bridge.update(state=state, title="song", duration=duration, source_uri="track", can_seek=True)
    assert bridge._dispatch("status")["can_seek"] is False
