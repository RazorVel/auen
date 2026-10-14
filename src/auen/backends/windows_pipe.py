"""Small, timeout-bounded client for mpv's Windows byte-mode named pipe."""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from typing import Any

_winapi: Any = ctypes


def _kernel32() -> Any:
    # These ctypes APIs exist only on Windows; keep importing auen portable.
    kernel = _winapi.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.SetNamedPipeHandleState.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    kernel.SetNamedPipeHandleState.restype = wintypes.BOOL
    for name in ("ReadFile", "WriteFile"):
        method = getattr(kernel, name)
        method.argtypes = [
            wintypes.HANDLE,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.c_void_p,
        ]
        method.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    return kernel


class WindowsPipe:
    """Socket-like IPC operations without indefinite Windows file reads/writes."""

    def __init__(self, name: str, *, timeout: float = 2.0) -> None:
        self._kernel = _kernel32()
        self._timeout = timeout
        deadline = time.monotonic() + timeout
        while True:
            self._handle = self._kernel.CreateFileW(name, 0xC0000000, 0, None, 3, 0, None)
            if self._handle != ctypes.c_void_p(-1).value:
                break
            error = int(_winapi.get_last_error())
            # mpv briefly recreates its pipe between clients. Retry absent/busy
            # instances, while preserving permission and other real failures.
            if error not in {2, 231} or time.monotonic() >= deadline:
                raise _windows_error(error)
            time.sleep(0.01)
        # PIPE_NOWAIT keeps both reads and writes bounded by our deadline.
        # Leave the default byte-read mode required by mpv's JSON stream.
        mode = wintypes.DWORD(1)
        if not self._kernel.SetNamedPipeHandleState(self._handle, ctypes.byref(mode), None, None):
            exception = _windows_error()
            self.close()
            raise exception

    def __enter__(self) -> WindowsPipe:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        if self._handle is not None:
            self._kernel.CloseHandle(self._handle)
            self._handle = None

    def sendall(self, data: bytes) -> None:
        deadline = time.monotonic() + self._timeout
        sent = 0
        while sent < len(data):
            buffer = ctypes.create_string_buffer(data[sent:])
            sent += self._transfer("WriteFile", buffer, len(data) - sent, deadline)

    def recv(self, size: int) -> bytes:
        buffer = ctypes.create_string_buffer(size)
        count = self._transfer("ReadFile", buffer, size, time.monotonic() + self._timeout)
        return bytes(buffer.raw[:count])

    def _transfer(self, name: str, buffer: Any, size: int, deadline: float) -> int:
        while time.monotonic() < deadline:
            count = wintypes.DWORD()
            success = getattr(self._kernel, name)(
                self._handle,
                buffer,
                size,
                ctypes.byref(count),
                None,
            )
            if success and count.value:
                return int(count.value)
            if not success:
                error = int(_winapi.get_last_error())
                if error == 109:  # ERROR_BROKEN_PIPE: peer closed.
                    if name == "ReadFile":
                        return 0
                    raise BrokenPipeError("mpv closed its control pipe")
                if error != 232:  # ERROR_NO_DATA: no bytes available yet.
                    raise _windows_error(error)
            time.sleep(0.01)
        raise TimeoutError("mpv control pipe did not respond in time")


def _windows_error(code: int | None = None) -> OSError:
    error: OSError = _winapi.WinError(code)
    return error
