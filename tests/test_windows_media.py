"""Portable SMTC contract tests. These do not claim real Windows/headset routing."""

import asyncio
import threading
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from auen.desktop_media import NO_TRACK, MediaSnapshot, desktop_track_identity
from auen.windows_media import WindowsMediaControls, _WinRTSession, missing_windows_media_packages
from auen.windows_window import HiddenMediaWindow, _user32


def playing() -> MediaSnapshot:
    return MediaSnapshot(
        state="Playing", track_id=desktop_track_identity("one"), title="Song 🎵 日本語",
        elapsed=12, duration=100, art_url="https://i.ytimg.com/vi/test/hqdefault.jpg",
        can_play=True, can_pause=True, can_next=True, can_previous=True, can_seek=True,
    )


def native_api(controls: MagicMock) -> dict[str, object]:
    media = SimpleNamespace(
        SystemMediaTransportControlsButton=SimpleNamespace(
            PLAY=0, PAUSE=1, STOP=2, NEXT=6, PREVIOUS=7,
        ),
        MediaPlaybackStatus=SimpleNamespace(CLOSED=0, STOPPED=2, PLAYING=3, PAUSED=4),
        MediaPlaybackType=SimpleNamespace(MUSIC=1),
        SystemMediaTransportControlsTimelineProperties=SimpleNamespace,
    )
    return {
        "winrt.windows.media": media,
        "winrt.windows.foundation": SimpleNamespace(Uri=lambda uri: uri),
        "winrt.windows.storage.streams": SimpleNamespace(
            RandomAccessStreamReference=SimpleNamespace(create_from_uri=lambda uri: uri),
        ),
        "winrt.windows.media.interop": SimpleNamespace(get_for_window=lambda hwnd: controls),
    }


def test_native_registration_buttons_metadata_timeline_and_cleanup() -> None:
    controls, button, seek = MagicMock(), MagicMock(), MagicMock()
    controls.add_button_pressed.return_value = "button-token"
    controls.add_playback_position_change_requested.return_value = "seek-token"
    with patch("auen.windows_media.import_module", side_effect=native_api(controls).__getitem__):
        session = _WinRTSession(123, button, seek)
        handler = controls.add_button_pressed.call_args.args[0]
        for native, action in [(0, "play"), (1, "pause"), (2, "stop"),
                               (6, "next"), (7, "previous")]:
            handler(None, SimpleNamespace(button=native))
            button.assert_called_with(action)
        button.reset_mock()
        handler(None, SimpleNamespace(button=99))
        button.assert_not_called()
        handler = controls.add_playback_position_change_requested.call_args.args[0]
        handler(None, SimpleNamespace(requested_playback_position=timedelta(seconds=45)))
        seek.assert_called_once_with(45)
        session.update(playing())
        assert controls.is_enabled
        assert controls.playback_status == 3
        assert controls.is_next_enabled and controls.is_previous_enabled
        assert controls.display_updater.music_properties.title == "Song 🎵 日本語"
        assert controls.display_updater.thumbnail == playing().art_url
        timeline = controls.update_timeline_properties.call_args.args[0]
        assert timeline.position == timedelta(seconds=12)
        assert timeline.end_time == timeline.max_seek_time == timedelta(seconds=100)
        session.update(replace(playing(), state="Paused", art_url=None, can_seek=False))
        assert controls.playback_status == 4
        assert controls.display_updater.clear_all.call_count == 2
        assert controls.update_timeline_properties.call_args.args[0].max_seek_time == timedelta(0)
        session.close()
        controls.remove_button_pressed.assert_called_once_with("button-token")
        controls.remove_playback_position_change_requested.assert_called_once_with("seek-token")
        assert not controls.is_enabled
        assert controls.playback_status == 0


def test_timeline_throttles_ticks_but_publishes_seek_and_state_changes() -> None:
    controls = MagicMock()
    with patch("auen.windows_media.import_module", side_effect=native_api(controls).__getitem__):
        session = _WinRTSession(123, MagicMock(), MagicMock())
        with patch("auen.windows_media.time.monotonic", return_value=100):
            session.update(playing())
        for elapsed in (0.5, 1, 2, 3, 4):
            with patch("auen.windows_media.time.monotonic", return_value=100 + elapsed):
                session.update(replace(playing(), elapsed=12 + elapsed))
        assert controls.update_timeline_properties.call_count == 1
        assert controls.display_updater.update.call_count == 1
        with patch("auen.windows_media.time.monotonic", return_value=105):
            session.update(replace(playing(), elapsed=17))
        assert controls.update_timeline_properties.call_count == 2
        with patch("auen.windows_media.time.monotonic", return_value=105.5):
            session.update(replace(playing(), elapsed=45))
        assert controls.update_timeline_properties.call_count == 3
        session.update(replace(playing(), state="Stopped", track_id=NO_TRACK, can_play=False,
                               can_pause=False, duration=None))
        assert not controls.is_enabled
        assert controls.playback_status == 2
        assert controls.update_timeline_properties.call_args.args[0].end_time == timedelta(0)
        session.close()


def test_native_partial_start_failure_removes_registered_handler() -> None:
    controls = MagicMock()
    controls.add_button_pressed.return_value = "registered"
    controls.add_playback_position_change_requested.side_effect = OSError("unsupported")
    with (
        patch("auen.windows_media.import_module", side_effect=native_api(controls).__getitem__),
        pytest.raises(OSError, match="unsupported"),
    ):
        _WinRTSession(123, MagicMock(), MagicMock())
    controls.remove_button_pressed.assert_called_once_with("registered")
    assert not controls.is_enabled


@pytest.mark.parametrize("action", ["play", "pause", "next", "previous", "stop"])
async def test_native_thread_callbacks_marshal_to_owning_loop(action: str) -> None:
    command, seek, error = MagicMock(), MagicMock(), MagicMock()
    bridge = WindowsMediaControls(command, seek, error)
    bridge.update(playing())
    thread = threading.Thread(target=bridge._button, args=(action,))
    thread.start()
    thread.join(timeout=1)
    assert not thread.is_alive()
    command.assert_not_called()  # Native callback returned without touching UI/mpv.
    await asyncio.sleep(0)
    command.assert_called_once_with(action)
    bridge.close()


async def test_disabled_buttons_late_callbacks_and_stale_seeks_are_ignored() -> None:
    command, seek = MagicMock(), MagicMock()
    bridge = WindowsMediaControls(command, seek, MagicMock())
    bridge._button("next")
    bridge._button("unknown")
    await asyncio.sleep(0)
    command.assert_not_called()
    bridge.update(playing())
    bridge._position(40)
    bridge.update(replace(playing(), track_id=desktop_track_identity("new")))
    await asyncio.sleep(0)
    seek.assert_not_called()
    bridge._position(45)
    await asyncio.sleep(0)
    seek.assert_called_once_with(45, desktop_track_identity("new"))
    seek.reset_mock()
    for seconds in (-1, 101, float("nan"), float("inf")):
        bridge._position(seconds)
    await asyncio.sleep(0)
    seek.assert_not_called()
    bridge._button("play")
    bridge._position(10)
    bridge.close()
    await asyncio.sleep(0)
    command.assert_not_called()
    seek.assert_not_called()


async def test_bridge_start_failure_cleans_private_window() -> None:
    bridge = WindowsMediaControls(MagicMock(), MagicMock(), MagicMock())
    with (
        patch("auen.windows_media.HiddenMediaWindow") as window,
        patch("auen.windows_media._WinRTSession", side_effect=ImportError("missing PyWinRT")),
        pytest.raises(ImportError),
    ):
        bridge.start()
    window.return_value.close.assert_called_once()
    assert bridge._closed


async def test_bridge_native_failure_warns_once_and_closes_everything() -> None:
    error = MagicMock()
    bridge = WindowsMediaControls(MagicMock(), MagicMock(), error)
    with (
        patch("auen.windows_media.HiddenMediaWindow") as window,
        patch("auen.windows_media._WinRTSession") as session,
    ):
        bridge.start()
        bridge.pump()
        window.return_value.pump.assert_called_once()
        session.return_value.update.side_effect = OSError("native failure")
        bridge.update(playing())
        bridge.update(playing())
        bridge.pump()
        bridge.close()
        session.return_value.close.assert_called_once()
        window.return_value.close.assert_called_once()
        error.assert_called_once()


async def test_cleanup_failure_cannot_prevent_window_cleanup() -> None:
    bridge = WindowsMediaControls(MagicMock(), MagicMock(), MagicMock())
    with (
        patch("auen.windows_media.HiddenMediaWindow") as window,
        patch("auen.windows_media._WinRTSession") as session,
    ):
        bridge.start()
        session.return_value.close.side_effect = OSError("native session already gone")
        bridge.close()
        window.return_value.close.assert_called_once()


def test_hidden_window_is_top_level_invisible_and_pump_bounded() -> None:
    user = MagicMock()
    user.CreateWindowExW.return_value = 0x123456789  # Must not truncate 64-bit HWNDs.
    user.PeekMessageW.return_value = True
    with patch("auen.windows_window._user32", return_value=user):
        window = HiddenMediaWindow()
    args = user.CreateWindowExW.call_args.args
    assert args[0] == 0x80 and args[1] == "STATIC"
    assert not args[3] & 0x10000000  # no WS_VISIBLE
    assert args[8] is None  # no parent, not a message-only/Terminal-owned window
    assert window.handle == 0x123456789
    window.pump()
    assert user.PeekMessageW.call_count == 32
    window.close()
    window.close()
    user.DestroyWindow.assert_called_once_with(0x123456789)


def test_ctypes_signatures_preserve_native_handles() -> None:
    with patch("auen.windows_window._winapi"):
        user = _user32()
    from ctypes import c_ssize_t, wintypes
    assert user.CreateWindowExW.restype is wintypes.HWND
    assert user.DispatchMessageW.restype is c_ssize_t


def test_doctor_dependency_check_never_activates_winrt() -> None:
    from importlib.metadata import PackageNotFoundError
    with patch("auen.windows_media.version", side_effect=PackageNotFoundError):
        assert "winrt-Windows.Media.Interop" in missing_windows_media_packages()
    with patch("auen.windows_media.version", return_value="3.2.1"):
        assert missing_windows_media_packages() == []
