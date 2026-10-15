"""A hidden, process-owned top-level HWND for Windows desktop SMTC interop."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Any

_winapi: Any = ctypes


def _user32() -> Any:
    user = _winapi.WinDLL("user32", use_last_error=True)
    user.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p,
    ]
    user.CreateWindowExW.restype = wintypes.HWND
    user.DestroyWindow.argtypes = [wintypes.HWND]
    user.DestroyWindow.restype = wintypes.BOOL
    user.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                 wintypes.UINT, wintypes.UINT, wintypes.UINT]
    user.PeekMessageW.restype = wintypes.BOOL
    user.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user.TranslateMessage.restype = wintypes.BOOL
    user.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user.DispatchMessageW.restype = ctypes.c_ssize_t
    return user


class HiddenMediaWindow:
    """Never use GetConsoleWindow: Windows Terminal's HWND is not owned by auen."""

    def __init__(self) -> None:
        self._user = _user32()
        # Built-in STATIC class, top-level (parent=NULL), invisible (no WS_VISIBLE).
        # WS_EX_TOOLWINDOW also prevents an extra taskbar/Alt-Tab entry.
        handle = self._user.CreateWindowExW(
            0x80, "STATIC", "auen", 0, 0, 0, 0, 0, None, None, None, None,
        )
        if not handle:
            raise OSError("could not create auen's private media-control window")
        self.handle = int(handle)

    def pump(self) -> None:
        if not self.handle:
            return
        message = wintypes.MSG()
        # The asyncio loop does not pump Win32 messages. Bound each pass and
        # filter to our own HWND, leaving the terminal's event handling alone.
        for _ in range(32):
            if not self._user.PeekMessageW(ctypes.byref(message), self.handle, 0, 0, 1):
                break
            if message.message != 0x12:  # Do not dispatch WM_QUIT.
                self._user.TranslateMessage(ctypes.byref(message))
                self._user.DispatchMessageW(ctypes.byref(message))

    def close(self) -> None:
        if self.handle:
            self._user.DestroyWindow(self.handle)
            self.handle = 0
