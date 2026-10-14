"""Nonblocking Win32 pipe behavior with finite fake I/O."""

from unittest.mock import MagicMock, patch

import pytest

from auen.backends.windows_pipe import WindowsPipe


def test_pipe_configures_nonblocking_mode_and_closes_handle() -> None:
    kernel = MagicMock()
    kernel.CreateFileW.return_value = 123
    with (
        patch("auen.backends.windows_pipe._kernel32", return_value=kernel),
        WindowsPipe(r"\\.\pipe\test"),
    ):
        mode = kernel.SetNamedPipeHandleState.call_args.args[1]._obj.value
        assert mode == 1
    kernel.CloseHandle.assert_called_once_with(123)


def test_pipe_write_handles_partial_writes() -> None:
    kernel = MagicMock()
    kernel.CreateFileW.return_value = 123
    written: list[bytes] = []

    def write(_handle: int, buffer: object, size: int, count: object, _overlapped: object) -> bool:
        amount = min(3, size)
        written.append(buffer.raw[:amount])  # type: ignore[attr-defined]
        count._obj.value = amount  # type: ignore[attr-defined]
        return True

    kernel.WriteFile.side_effect = write
    with (
        patch("auen.backends.windows_pipe._kernel32", return_value=kernel),
        WindowsPipe(r"\\.\pipe\test") as pipe,
    ):
        pipe.sendall(b"abcdefg")
    assert b"".join(written) == b"abcdefg"


def test_pipe_empty_read_times_out_without_unbounded_blocking() -> None:
    kernel = MagicMock()
    kernel.CreateFileW.return_value = 123
    with (
        patch("auen.backends.windows_pipe._kernel32", return_value=kernel),
        patch("auen.backends.windows_pipe.time.monotonic", side_effect=[0, 0, 0, 3]),
        patch("auen.backends.windows_pipe.time.sleep"),
        WindowsPipe(r"\\.\pipe\test") as pipe,
        pytest.raises(TimeoutError, match="did not respond"),
    ):
        pipe.recv(4096)
    assert kernel.ReadFile.call_count == 1
    kernel.CloseHandle.assert_called_once_with(123)
