"""Private local control channel for an active auen TUI instance."""

from __future__ import annotations

import contextlib
import hmac
import json
import os
import secrets
import socket
import sys
import threading
from typing import TYPE_CHECKING, Any, BinaryIO

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

REMOTE_COMMANDS = {"toggle", "next", "stop", "status"}
_MAX_MESSAGE_BYTES = 64 * 1024


def control_socket_path(state_dir: Path) -> Path:
    return state_dir / "control.sock"


def _socket_family(tcp: bool) -> int:
    if tcp:
        return socket.AF_INET
    family = getattr(socket, "AF_UNIX", None)
    if family is None:
        raise RuntimeError("Unix remote control is unavailable on this platform")
    return int(family)


class RemoteControlServer:
    """Serve small JSON requests over a user-owned Unix-domain socket."""

    def __init__(
        self,
        state_dir: Path,
        handler: Callable[[str], dict[str, Any]],
        *,
        tcp: bool | None = None,
    ) -> None:
        self._tcp = os.name == "nt" if tcp is None else tcp
        self.path = state_dir / "control.json" if self._tcp else control_socket_path(state_dir)
        self._token = secrets.token_hex(32) if self._tcp else ""
        self._address: tuple[str, int] | str = str(self.path)
        self.handler = handler
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._endpoint_lock: BinaryIO | None = None

    def start(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self._tcp:
            self._start_tcp()
            return
        self.path.parent.chmod(0o700)
        if self.path.exists():
            if _socket_accepts_connections(self.path):
                raise RuntimeError("another auen instance is already accepting remote commands")
            self.path.unlink()

        server = socket.socket(_socket_family(False), socket.SOCK_STREAM)
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
        self._start_thread()

    def _start_tcp(self) -> None:
        # Lock endpoint ownership separately so an OS-assigned port can be used
        # on every start, without collisions or TCP TIME_WAIT restart failures.
        self._lock_endpoint()
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if os.name == "nt":
                server.setsockopt(socket.SOL_SOCKET, getattr(socket, "SO_EXCLUSIVEADDRUSE", -5), 1)
            server.bind(("127.0.0.1", 0))
            port = server.getsockname()[1]
            self._address = ("127.0.0.1", port)
            server.listen(4)
            server.settimeout(0.2)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps({"port": port, "token": self._token}),
                encoding="utf-8",
            )
            temporary.chmod(0o600)
            temporary.replace(self.path)
        except OSError as exc:
            server.close()
            self._unlock_endpoint()
            raise RuntimeError(f"could not start local remote controls: {exc}") from exc
        self._socket = server
        self._start_thread()

    def _lock_endpoint(self) -> None:
        lock_file = (self.path.parent / "control.lock").open("a+b")
        try:
            if lock_file.tell() == 0:
                lock_file.write(b"\0")
                lock_file.flush()
            lock_file.seek(0)
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            lock_file.close()
            raise RuntimeError(
                "another auen instance is already accepting remote commands"
            ) from exc
        self._endpoint_lock = lock_file

    def _unlock_endpoint(self) -> None:
        if self._endpoint_lock is not None:
            self._endpoint_lock.close()
            self._endpoint_lock = None

    def _start_thread(self) -> None:
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
                connection.settimeout(1.5)
                response = self._handle_connection(connection)
                with contextlib.suppress(OSError):
                    connection.sendall(_encode_message(response))

    def _handle_connection(self, connection: socket.socket) -> dict[str, Any]:
        try:
            request = _receive_message(connection)
            if self._tcp:
                token = request.get("token")
                if not isinstance(token, str) or not hmac.compare_digest(token, self._token):
                    return {"ok": False, "error": "remote authentication failed"}
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
                socket.socket(_socket_family(self._tcp), socket.SOCK_STREAM) as wake,
            ):
                wake.settimeout(0.1)
                wake.connect(self._address)
            with contextlib.suppress(OSError):
                server.close()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=1.0)
        self._thread = None
        if server is not None:
            with contextlib.suppress(OSError):
                self.path.unlink()
        self._unlock_endpoint()


def send_remote_command(
    state_dir: Path,
    command: str,
    *,
    timeout: float = 1.5,
    tcp: bool | None = None,
) -> dict[str, Any]:
    if command not in REMOTE_COMMANDS:
        raise ValueError(f"unsupported remote command: {command}")
    use_tcp = os.name == "nt" if tcp is None else tcp
    path = state_dir / "control.json" if use_tcp else control_socket_path(state_dir)
    if not path.exists():
        raise RuntimeError("no running auen instance was found")
    try:
        address: tuple[str, int] | str = str(path)
        request: dict[str, Any] = {"command": command}
        if use_tcp:
            endpoint = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(endpoint, dict):
                raise ValueError("invalid remote endpoint")
            port = endpoint.get("port")
            token = endpoint.get("token")
            if type(port) is not int or not 1 <= port <= 65535 or not isinstance(token, str):
                raise ValueError("invalid remote endpoint")
            address = ("127.0.0.1", port)
            request["token"] = token
        with socket.socket(_socket_family(use_tcp), socket.SOCK_STREAM) as client:
            client.settimeout(timeout)
            client.connect(address)
            client.sendall(_encode_message(request))
            response = _receive_message(client)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(f"could not contact the running auen instance: {exc}") from exc
    if response.get("ok") is not True:
        raise RuntimeError(str(response.get("error") or "remote command failed"))
    return response


def _socket_accepts_connections(path: Path) -> bool:
    try:
        with socket.socket(_socket_family(False), socket.SOCK_STREAM) as probe:
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
