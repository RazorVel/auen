"""Tests for the private local remote-control channel."""

import json
import os
import socket
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
        if os.name != "nt":
            assert control_socket_path(tmp_path).stat().st_mode & 0o777 == 0o600
    finally:
        server.close()

    assert not server.path.exists()


def test_remote_server_rejects_a_second_live_owner(tmp_path: Path) -> None:
    first = RemoteControlServer(tmp_path, lambda _command: {})
    second = RemoteControlServer(tmp_path, lambda _command: {})
    first.start()
    try:
        with pytest.raises(RuntimeError, match="another auen instance"):
            second.start()
    finally:
        first.close()


@pytest.mark.skipif(os.name == "nt", reason="Unix socket transport")
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


def test_windows_transport_round_trip_and_authentication(tmp_path: Path) -> None:
    received: list[str] = []
    server = RemoteControlServer(
        tmp_path, lambda command: received.append(command) or {}, tcp=True
    )
    server.start()
    try:
        endpoint = json.loads(server.path.read_text(encoding="utf-8"))
        with socket.create_connection(("127.0.0.1", endpoint["port"]), timeout=1) as client:
            client.sendall(b'{"command":"stop","token":"wrong"}\n')
            response = json.loads(client.recv(4096))
            assert response["ok"] is False
            assert "authentication" in response["error"]
        assert received == []
        assert send_remote_command(tmp_path, "status", tcp=True)["ok"] is True
        assert received == ["status"]
        assert server._socket.getsockname()[0] == "127.0.0.1"
    finally:
        server.close()
    assert not server.path.exists()


def test_windows_transport_second_owner_cannot_delete_endpoint(tmp_path: Path) -> None:
    first = RemoteControlServer(tmp_path, lambda _command: {}, tcp=True)
    second = RemoteControlServer(tmp_path, lambda _command: {}, tcp=True)
    first.start()
    try:
        with pytest.raises(RuntimeError, match="another auen instance"):
            second.start()
        second.close()
        assert send_remote_command(tmp_path, "status", tcp=True)["ok"] is True
    finally:
        first.close()


def test_windows_transport_replaces_stale_endpoint_and_restarts(tmp_path: Path) -> None:
    (tmp_path / "control.json").write_text("stale", encoding="utf-8")
    server = RemoteControlServer(tmp_path, lambda _command: {}, tcp=True)
    server.start()
    assert send_remote_command(tmp_path, "status", tcp=True)["ok"] is True
    server.close()
    server.start()
    try:
        assert send_remote_command(tmp_path, "status", tcp=True)["ok"] is True
    finally:
        server.close()
