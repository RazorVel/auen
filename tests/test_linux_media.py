"""MPRIS protocol tests, plus a real isolated session-bus round trip."""

import asyncio
import os
import shutil
import subprocess
from dataclasses import replace
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("dbus_next")
from dbus_next.aio.message_bus import MessageBus
from dbus_next.constants import MessageType
from dbus_next.message import Message
from dbus_next.signature import Variant

from auen.linux_media import (
    BUS_NAME,
    NO_TRACK,
    OBJECT_PATH,
    PLAYER,
    PROPERTIES,
    ROOT,
    LinuxMediaControls,
    MediaSnapshot,
)


def call(interface: str, member: str, signature: str = "", body: list | None = None) -> Message:
    return Message(destination=BUS_NAME, path=OBJECT_PATH, interface=interface, member=member,
                   signature=signature, body=body or [], serial=1)


@pytest.fixture
def controls() -> LinuxMediaControls:
    bridge = LinuxMediaControls(MagicMock(), MagicMock(), MagicMock())
    bridge.update(MediaSnapshot(
        state="Paused", track_id=OBJECT_PATH + "/track/abc", title="Song 日本語 🎵",
        elapsed=12.0, duration=100, can_next=True, can_previous=True,
        can_play=True, can_pause=True, can_seek=True,
    ))
    return bridge


@pytest.mark.parametrize("method,command", [
    ("Play", "play"), ("Pause", "pause"), ("PlayPause", "toggle"), ("Next", "next"),
    ("Previous", "previous"), ("Stop", "stop"),
])
def test_commands_use_shared_actions(
    controls: LinuxMediaControls, method: str, command: str,
) -> None:
    reply = controls.handle_message(call(PLAYER, method))
    assert reply.message_type == MessageType.METHOD_RETURN
    controls._command.assert_called_once_with(command)


def test_quit_is_separate_from_playback_stop(controls: LinuxMediaControls) -> None:
    controls.handle_message(call(ROOT, "Quit"))
    controls._command.assert_called_once_with("quit")


def test_disabled_actions_and_unknown_calls_do_not_control_playback() -> None:
    command = MagicMock()
    bridge = LinuxMediaControls(command, MagicMock(), MagicMock())
    for method in ("Play", "Pause", "Next", "Previous"):
        bridge.handle_message(call(PLAYER, method))
    command.assert_not_called()
    for interface, method, signature, body in [
        (PLAYER, "Next", "s", ["bad"]), (PLAYER, "OpenUri", "s", ["file:///etc/passwd"]),
        ("unknown.interface", "Play", "", []),
    ]:
        assert bridge.handle_message(call(interface, method, signature, body)).message_type \
            == MessageType.ERROR
    command.assert_not_called()


def test_metadata_types_position_and_capabilities(controls: LinuxMediaControls) -> None:
    reply = controls.handle_message(call(PROPERTIES, "GetAll", "s", [PLAYER]))
    props = reply.body[0]
    assert props["Metadata"].signature == "a{sv}"
    metadata = props["Metadata"].value
    assert metadata["mpris:trackid"].signature == "o"
    assert metadata["mpris:length"] == Variant("x", 100_000_000)
    assert metadata["xesam:title"].value == "Song 日本語 🎵"
    assert "xesam:url" not in metadata  # No local paths or signed playback URLs.
    assert props["Position"] == Variant("x", 12_000_000)
    assert props["CanSeek"].value
    assert "LoopStatus" not in props  # Optional features not yet supported.
    assert controls.properties(ROOT)["SupportedUriSchemes"].value == []


def test_position_advances_only_while_playing_and_is_clamped(controls: LinuxMediaControls) -> None:
    with patch("auen.linux_media.time.monotonic", return_value=100):
        controls.update(replace(controls.snapshot, state="Playing"))
    with patch("auen.linux_media.time.monotonic", return_value=105):
        assert controls.position == 17_000_000
    with patch("auen.linux_media.time.monotonic", return_value=1000):
        assert controls.position == 100_000_000
        controls.update(replace(controls.snapshot, state="Paused", elapsed=23))
    with patch("auen.linux_media.time.monotonic", return_value=2000):
        assert controls.position == 23_000_000


def test_seek_stale_track_and_boundaries(controls: LinuxMediaControls) -> None:
    identity = controls.snapshot.track_id
    for track, position in [(NO_TRACK, 10), (OBJECT_PATH + "/old", 10),
                            (identity, -1), (identity, 101_000_000)]:
        controls.handle_message(call(PLAYER, "SetPosition", "ox", [track, position]))
    controls._seek.assert_not_called()
    controls.handle_message(call(PLAYER, "SetPosition", "ox", [identity, 40_000_000]))
    controls._seek.assert_called_once_with(40, identity)
    controls._seek.reset_mock()
    controls.handle_message(call(PLAYER, "Seek", "x", [-20_000_000]))
    controls._seek.assert_called_once_with(0, identity)
    controls.handle_message(call(PLAYER, "Seek", "x", [200_000_000]))
    controls._command.assert_called_once_with("next")
    controls.update(replace(controls.snapshot, can_seek=False))
    controls._seek.reset_mock()
    controls.handle_message(call(PLAYER, "Seek", "x", [1]))
    controls._seek.assert_not_called()


def test_volume_rate_and_property_validation(controls: LinuxMediaControls) -> None:
    for value, expected in [(-1.0, 0.0), (0.6, 0.6), (5.0, 1.0)]:
        controls.handle_message(call(
            PROPERTIES, "Set", "ssv", [PLAYER, "Volume", Variant("d", value)]
        ))
        controls._volume.assert_called_with(expected)
    for value in (Variant("s", "bad"), Variant("d", float("nan"))):
        assert controls.handle_message(
            call(PROPERTIES, "Set", "ssv", [PLAYER, "Volume", value])
        ).message_type == MessageType.ERROR
    controls.handle_message(call(PROPERTIES, "Set", "ssv", [PLAYER, "Rate", Variant("d", 0.0)]))
    controls._command.assert_called_once_with("pause")
    assert controls.handle_message(call(
        PROPERTIES, "Set", "ssv", [PLAYER, "PlaybackStatus", Variant("s", "Playing")]
    )).error_name.endswith("PropertyReadOnly")


def test_updates_emit_changes_but_not_position_ticks(controls: LinuxMediaControls) -> None:
    controls._signal = MagicMock()
    controls.update(replace(controls.snapshot, elapsed=12.5))
    controls._signal.assert_not_called()
    controls.update(replace(controls.snapshot, elapsed=40, volume=0.3))
    calls = controls._signal.call_args_list
    assert calls[0].args == (PROPERTIES, "PropertiesChanged", "sa{sv}as",
                             [PLAYER, {"Volume": Variant("d", 0.3)}, []])
    assert calls[1].args == (PLAYER, "Seeked", "x", [40_000_000])


@pytest.mark.parametrize("seconds", [12.1, 40.0])
def test_explicit_seek_signals_small_and_large_changes_once(
    controls: LinuxMediaControls, seconds: float,
) -> None:
    controls._signal = MagicMock()
    controls._seek.side_effect = lambda value, identity: controls.update(
        replace(controls.snapshot, elapsed=value)
    )
    controls.handle_message(call(
        PLAYER, "SetPosition", "ox", [controls.snapshot.track_id, round(seconds * 1_000_000)]
    ))
    controls._signal.assert_called_once_with(PLAYER, "Seeked", "x", [round(seconds * 1_000_000)])


def test_errors_do_not_leak_backend_paths_and_close_ignores_calls(
    controls: LinuxMediaControls,
) -> None:
    controls._command.side_effect = RuntimeError("https://private/?token=secret")
    reply = controls.handle_message(call(PLAYER, "Play"))
    assert reply.message_type == MessageType.ERROR
    assert "secret" not in str(reply.body)
    controls.close()
    controls.close()
    assert controls.handle_message(call(PLAYER, "Play")) is None


async def test_connection_failure_is_bounded_and_cleaned_up() -> None:
    bridge = LinuxMediaControls(MagicMock(), MagicMock(), MagicMock())
    with (
        patch("auen.linux_media.MessageBus", side_effect=OSError("bus unavailable")),
        pytest.raises(OSError, match="bus unavailable"),
    ):
        await bridge.start()
    assert bridge._closed


@pytest.mark.skipif(not shutil.which("dbus-daemon"), reason="requires isolated dbus-daemon")
async def test_real_bus_introspection_commands_signals_ownership_and_cleanup() -> None:
    # A private bus never takes over an actual desktop player's media keys.
    process = subprocess.Popen(
        ["dbus-daemon", "--session", "--nofork", "--print-address=1"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
    )
    client = None
    bridge = LinuxMediaControls(MagicMock(), MagicMock(), MagicMock())
    second = LinuxMediaControls(MagicMock(), MagicMock(), MagicMock())
    try:
        assert process.stdout is not None
        address = await asyncio.wait_for(asyncio.to_thread(process.stdout.readline), 2)
        with patch.dict(os.environ, {"DBUS_SESSION_BUS_ADDRESS": address.strip()}):
            await bridge.start()
            with pytest.raises(RuntimeError, match="another auen"):
                await second.start()
            client = await MessageBus().connect()
            node = await client.introspect(BUS_NAME, OBJECT_PATH)
            proxy = client.get_proxy_object(BUS_NAME, OBJECT_PATH, node)
            player = proxy.get_interface(PLAYER)
            properties = proxy.get_interface(PROPERTIES)
            changes = []
            properties.on_properties_changed(
                lambda interface, changed, invalid: changes.append(changed)
            )
            bridge.update(MediaSnapshot(state="Playing", track_id=OBJECT_PATH + "/track/test",
                                        title="Test", duration=90, can_play=True, can_pause=True))
            await player.call_pause()
            bridge._command.assert_called_once_with("pause")
            assert await player.get_playback_status() == "Playing"
            assert (await player.get_metadata())["xesam:title"].value == "Test"
            await player.set_volume(0.4)
            bridge._volume.assert_called_once_with(0.4)
            await player.call_stop()
            bridge._command.assert_called_with("stop")
            assert any("Metadata" in changed for changed in changes)
            bridge.close()
            await asyncio.wait_for(bridge.wait_for_disconnect(), 2)
            second = LinuxMediaControls(MagicMock(), MagicMock(), MagicMock())
            await second.start()  # ownership is released, never queued/stolen
    finally:
        bridge.close()
        second.close()
        if client is not None:
            client.disconnect()
            await asyncio.wait_for(client.wait_for_disconnect(), 2)
        process.terminate()
        await asyncio.to_thread(process.wait, 2)
        if process.stdout is not None:
            process.stdout.close()
