"""Private local control channel for an active auen TUI instance."""

from __future__ import annotations

import contextlib
import json
import socket
import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

REMOTE_COMMANDS = {"toggle", "next", "stop", "status"}
_MAX_MESSAGE_BYTES = 64 * 1024


def control_socket_path(state_dir: Path) -> Path:
    return state_dir / "control.sock"


class RemoteControlServer:
    """Serve small JSON requests over a user-owned Unix-domain socket."""

    def __init__(
        self,
        state_dir: Path,
        handler: Callable[[str], dict[str, Any]],
    ) -> None:
        self.path = control_socket_path(state_dir)
        self.handler = handler
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.parent.chmod(0o700)
        if self.path.exists():
            if _socket_accepts_connections(self.path):
                raise RuntimeError("another auen instance is already accepting remote commands")
            self.path.unlink()

        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            server.bind(str(self.path))
            self.path.chmod(0o600)
            server.listen(4)
            server.settimeout(0.2)
        except Exception:
            server.close()
            with contextlib.suppress(OSError):
                self.path.unlink()
            raise

        self._socket = server
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._serve,
            name="auen-remote-control",
            daemon=True,
        )
        self._thread.start()

    def _serve(self) -> None:
        server = self._socket
        if server is None:
            return
        while not self._stop_event.is_set():
            try:
                connection, _address = server.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            with connection:
                response = self._handle_connection(connection)
                with contextlib.suppress(OSError):
                    connection.sendall(_encode_message(response))

    def _handle_connection(self, connection: socket.socket) -> dict[str, Any]:
        try:
            request = _receive_message(connection)
            command = request.get("command")
            if not isinstance(command, str) or command not in REMOTE_COMMANDS:
                return {"ok": False, "error": "unsupported remote command"}
            response = self.handler(command)
            return {"ok": True, **response}
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:  # Keep a bad UI callback from killing the server thread.
            return {"ok": False, "error": f"remote command failed: {exc}"}

    def close(self) -> None:
        self._stop_event.set()
        server = self._socket
        self._socket = None
        if server is not None:
            with (
                contextlib.suppress(OSError),
                socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as wake,
            ):
                wake.settimeout(0.1)
                wake.connect(str(self.path))
            with contextlib.suppress(OSError):
                server.close()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=1.0)
        self._thread = None
        with contextlib.suppress(OSError):
            self.path.unlink()


def send_remote_command(
    state_dir: Path,
    command: str,
    *,
    timeout: float = 1.5,
) -> dict[str, Any]:
    if command not in REMOTE_COMMANDS:
        raise ValueError(f"unsupported remote command: {command}")
    path = control_socket_path(state_dir)
    if not path.exists():
        raise RuntimeError("no running auen instance was found")
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(timeout)
            client.connect(str(path))
            client.sendall(_encode_message({"command": command}))
            response = _receive_message(client)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(f"could not contact the running auen instance: {exc}") from exc
    if response.get("ok") is not True:
        raise RuntimeError(str(response.get("error") or "remote command failed"))
    return response


def _socket_accepts_connections(path: Path) -> bool:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.2)
            probe.connect(str(path))
    except OSError:
        return False
    return True


def _encode_message(message: dict[str, Any]) -> bytes:
    return json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n"


def _receive_message(connection: socket.socket) -> dict[str, Any]:
    data = bytearray()
    while b"\n" not in data:
        chunk = connection.recv(4096)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > _MAX_MESSAGE_BYTES:
            raise ValueError("remote message exceeded 64 KiB")
    if not data:
        raise ValueError("remote peer sent an empty message")
    first_line = bytes(data).split(b"\n", 1)[0]
    decoded = json.loads(first_line.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("remote message must be a JSON object")
    return decoded
