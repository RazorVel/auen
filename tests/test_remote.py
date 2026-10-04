"""Tests for the private local remote-control channel."""

from pathlib import Path

import pytest

from auen.remote import RemoteControlServer, control_socket_path, send_remote_command


def test_remote_server_round_trip_and_private_permissions(tmp_path: Path) -> None:
    received: list[str] = []
    server = RemoteControlServer(
        tmp_path,
        lambda command: received.append(command) or {"message": "Nothing playing"},
    )
    server.start()
    try:
        response = send_remote_command(tmp_path, "status")

        assert response["ok"] is True
        assert response["message"] == "Nothing playing"
        assert received == ["status"]
        assert control_socket_path(tmp_path).stat().st_mode & 0o777 == 0o600
    finally:
        server.close()

    assert not control_socket_path(tmp_path).exists()


def test_remote_server_rejects_a_second_live_owner(tmp_path: Path) -> None:
    first = RemoteControlServer(tmp_path, lambda _command: {})
    second = RemoteControlServer(tmp_path, lambda _command: {})
    first.start()
    try:
        with pytest.raises(RuntimeError, match="another auen instance"):
            second.start()
    finally:
        first.close()


def test_remote_server_replaces_a_stale_socket_path(tmp_path: Path) -> None:
    path = control_socket_path(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    path.write_text("stale")
    server = RemoteControlServer(tmp_path, lambda _command: {})

    server.start()
    server.close()

    assert not path.exists()


def test_remote_client_reports_missing_instance(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="no running auen instance"):
        send_remote_command(tmp_path, "toggle")


def test_remote_client_rejects_unknown_command(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unsupported remote command"):
        send_remote_command(tmp_path, "volume-up")
