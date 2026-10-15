"""Optional MPRIS service, on the same asyncio loop as auen's shared actions.

Only this module imports dbus-next. Without the linux extra, other platforms and
ordinary playback do not depend on a D-Bus installation.
"""

from __future__ import annotations

import asyncio
import math
import time
from typing import TYPE_CHECKING, Any

from dbus_next.aio.message_bus import MessageBus
from dbus_next.constants import MessageType, NameFlag, RequestNameReply
from dbus_next.message import Message
from dbus_next.signature import Variant

from auen.desktop_media import NO_TRACK as NO_TRACK
from auen.desktop_media import OBJECT_PATH as OBJECT_PATH
from auen.desktop_media import MediaSnapshot as MediaSnapshot

if TYPE_CHECKING:
    from collections.abc import Callable

BUS_NAME = "org.mpris.MediaPlayer2.auen"
ROOT = "org.mpris.MediaPlayer2"
PLAYER = ROOT + ".Player"
PROPERTIES = "org.freedesktop.DBus.Properties"

# Optional LoopStatus/Shuffle/OpenUri/TrackList are deliberately not advertised.
INTROSPECTION = """<node>
<interface name="org.mpris.MediaPlayer2">
 <method name="Raise"/><method name="Quit"/>
 <property name="CanQuit" type="b" access="read"/>
 <property name="CanRaise" type="b" access="read"/>
 <property name="HasTrackList" type="b" access="read"/>
 <property name="Identity" type="s" access="read"/>
 <property name="SupportedUriSchemes" type="as" access="read"/>
 <property name="SupportedMimeTypes" type="as" access="read"/>
</interface>
<interface name="org.mpris.MediaPlayer2.Player">
 <method name="Next"/><method name="Previous"/><method name="Pause"/>
 <method name="PlayPause"/><method name="Stop"/><method name="Play"/>
 <method name="Seek"><arg name="Offset" type="x" direction="in"/></method>
 <method name="SetPosition"><arg name="TrackId" type="o" direction="in"/>
  <arg name="Position" type="x" direction="in"/></method>
 <signal name="Seeked"><arg name="Position" type="x"/></signal>
 <property name="PlaybackStatus" type="s" access="read"/>
 <property name="Rate" type="d" access="readwrite"/>
 <property name="Metadata" type="a{sv}" access="read"/>
 <property name="Volume" type="d" access="readwrite"/>
 <property name="Position" type="x" access="read"/>
 <property name="MinimumRate" type="d" access="read"/>
 <property name="MaximumRate" type="d" access="read"/>
 <property name="CanGoNext" type="b" access="read"/>
 <property name="CanGoPrevious" type="b" access="read"/>
 <property name="CanPlay" type="b" access="read"/>
 <property name="CanPause" type="b" access="read"/>
 <property name="CanSeek" type="b" access="read"/>
 <property name="CanControl" type="b" access="read"/>
</interface>
<interface name="org.freedesktop.DBus.Introspectable">
 <method name="Introspect"><arg type="s" direction="out"/></method>
</interface>
<interface name="org.freedesktop.DBus.Peer"><method name="Ping"/></interface>
<interface name="org.freedesktop.DBus.Properties">
 <method name="Get"><arg type="s" direction="in"/><arg type="s" direction="in"/>
  <arg type="v" direction="out"/></method>
 <method name="GetAll"><arg type="s" direction="in"/>
  <arg type="a{sv}" direction="out"/></method>
 <method name="Set"><arg type="s" direction="in"/><arg type="s" direction="in"/>
  <arg type="v" direction="in"/></method>
 <signal name="PropertiesChanged"><arg type="s"/><arg type="a{sv}"/><arg type="as"/></signal>
</interface>
</node>"""


class LinuxMediaControls:
    """Cached properties never query mpv; commands run on the owning UI loop."""

    def __init__(
        self, command: Callable[[str], Any], seek: Callable[[float, str], Any],
        volume: Callable[[float], Any],
    ) -> None:
        self._command = command
        self._seek = seek
        self._volume = volume
        self._bus: MessageBus | None = None
        self._closed = False
        self._seeking = False
        self.snapshot = MediaSnapshot()
        self._updated_at = time.monotonic()

    async def start(self) -> None:
        try:
            self._bus = MessageBus()
            await asyncio.wait_for(self._bus.connect(), timeout=2.0)
            self._bus.add_message_handler(self.handle_message)
            reply = await asyncio.wait_for(
                self._bus.request_name(BUS_NAME, NameFlag.DO_NOT_QUEUE), timeout=2.0,
            )
            if reply is not RequestNameReply.PRIMARY_OWNER:
                raise RuntimeError("another auen instance owns Linux media controls")
        except BaseException:
            self.close()
            raise

    async def wait_for_disconnect(self) -> None:
        if self._bus is not None:
            await self._bus.wait_for_disconnect()  # type: ignore[no-untyped-call]

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._bus is not None:
            self._bus.disconnect()  # type: ignore[no-untyped-call]

    @property
    def position(self) -> int:
        seconds = self.snapshot.elapsed
        if self.snapshot.state == "Playing":
            seconds += max(0.0, time.monotonic() - self._updated_at)
        if self.snapshot.duration is not None:
            seconds = min(seconds, self.snapshot.duration)
        return round(max(0.0, seconds) * 1_000_000)

    def update(self, snapshot: MediaSnapshot) -> None:
        before = self.properties(PLAYER)
        predicted = self.position
        old = self.snapshot
        self.snapshot = snapshot
        self._updated_at = time.monotonic()
        after = self.properties(PLAYER)
        changed = {key: value for key, value in after.items()
                   if key != "Position" and value != before[key]}
        if changed:
            self._signal(PROPERTIES, "PropertiesChanged", "sa{sv}as", [PLAYER, changed, []])
        if (not self._seeking and snapshot.track_id != NO_TRACK
                and old.track_id == snapshot.track_id
                and abs(self.position - predicted) > 1_500_000):
            self._signal(PLAYER, "Seeked", "x", [self.position])

    def _signal(self, interface: str, member: str, signature: str, body: list[Any]) -> None:
        if not self._closed and self._bus is not None and self._bus.connected:
            self._bus.send(Message.new_signal(OBJECT_PATH, interface, member, signature, body))

    def properties(self, interface: str) -> dict[str, Variant]:
        if interface == ROOT:
            return {
                "CanQuit": Variant("b", True), "CanRaise": Variant("b", False),
                "HasTrackList": Variant("b", False), "Identity": Variant("s", "auen"),
                "SupportedUriSchemes": Variant("as", []),
                "SupportedMimeTypes": Variant("as", []),
            }
        if interface != PLAYER:
            raise ValueError("unknown media interface")
        snapshot = self.snapshot
        metadata: dict[str, Variant] = {}
        if snapshot.track_id != NO_TRACK:
            metadata = {"mpris:trackid": Variant("o", snapshot.track_id),
                        "xesam:title": Variant("s", snapshot.title)}
            if snapshot.duration is not None:
                metadata["mpris:length"] = Variant("x", round(snapshot.duration * 1_000_000))
            if snapshot.art_url:
                metadata["mpris:artUrl"] = Variant("s", snapshot.art_url)
        return {
            "PlaybackStatus": Variant("s", snapshot.state),
            "Rate": Variant("d", 1.0), "MinimumRate": Variant("d", 1.0),
            "MaximumRate": Variant("d", 1.0), "Volume": Variant("d", snapshot.volume),
            "Position": Variant("x", self.position), "Metadata": Variant("a{sv}", metadata),
            "CanGoNext": Variant("b", snapshot.can_next),
            "CanGoPrevious": Variant("b", snapshot.can_previous),
            "CanPlay": Variant("b", snapshot.can_play),
            "CanPause": Variant("b", snapshot.can_pause),
            "CanSeek": Variant("b", snapshot.can_seek), "CanControl": Variant("b", True),
        }

    def handle_message(self, message: Message) -> Message | None:
        if (self._closed or message.message_type is not MessageType.METHOD_CALL
                or message.path != OBJECT_PATH):
            return None
        try:
            return self._dispatch(message)
        except (OSError, RuntimeError, ValueError):
            # Do not leak a backend exception (potentially a URL or local path).
            return Message.new_error(message, "org.mpris.MediaPlayer2.Error.Failed",
                                     "Playback control is unavailable or the track changed")

    def _dispatch(self, message: Message) -> Message:
        interface, member, args = message.interface, message.member, message.body
        signature = message.signature
        if interface == "org.freedesktop.DBus.Introspectable" and member == "Introspect":
            if signature == "":
                return Message.new_method_return(message, "s", [INTROSPECTION])
        elif interface == "org.freedesktop.DBus.Peer" and member == "Ping" and signature == "":
            return Message.new_method_return(message)
        elif interface == PROPERTIES:
            if member == "GetAll" and signature == "s":
                return Message.new_method_return(message, "a{sv}", [self.properties(args[0])])
            if member == "Get" and signature == "ss":
                properties = self.properties(args[0])
                if args[1] in properties:
                    return Message.new_method_return(message, "v", [properties[args[1]]])
                return Message.new_error(message, "org.freedesktop.DBus.Error.UnknownProperty",
                                         "Unknown media property")
            if member == "Set" and signature == "ssv":
                return self._set_property(message)
        elif interface == ROOT and signature == "":
            if member == "Quit":
                self._command("quit")
            elif member != "Raise":
                return self._unknown(message)
            return Message.new_method_return(message)
        elif interface == PLAYER:
            commands = {"Play": "play", "Pause": "pause", "PlayPause": "toggle",
                        "Next": "next", "Previous": "previous", "Stop": "stop"}
            if member in commands and signature == "":
                allowed = {"Play": self.snapshot.can_play, "Pause": self.snapshot.can_pause,
                           "Next": self.snapshot.can_next,
                           "Previous": self.snapshot.can_previous}
                if allowed.get(member, True):
                    self._command(commands[member])
                return Message.new_method_return(message)
            if member == "Seek" and signature == "x":
                if self.snapshot.can_seek:
                    position = max(0, self.position + args[0]) / 1_000_000
                    if self.snapshot.duration is not None and position > self.snapshot.duration:
                        if self.snapshot.can_next:
                            self._command("next")
                    else:
                        self._seek_to(position, self.snapshot.track_id)
                return Message.new_method_return(message)
            if member == "SetPosition" and signature == "ox":
                if (self.snapshot.can_seek and args[0] == self.snapshot.track_id
                        and args[0] != NO_TRACK and args[1] >= 0
                        and (self.snapshot.duration is None
                             or args[1] <= self.snapshot.duration * 1_000_000)):
                    self._seek_to(args[1] / 1_000_000, args[0])
                return Message.new_method_return(message)
        return self._unknown(message)

    def _seek_to(self, seconds: float, track_id: str) -> None:
        # The UI callback refreshes the snapshot synchronously. Emit even for
        # sub-second seeks, once only, using the actual backend-reported result.
        self._seeking = True
        try:
            self._seek(seconds, track_id)
        finally:
            self._seeking = False
        if self.snapshot.track_id == track_id:
            self._signal(PLAYER, "Seeked", "x", [self.position])

    def _set_property(self, message: Message) -> Message:
        interface, key, value = message.body
        properties = self.properties(interface)
        if key not in properties:
            return Message.new_error(message, "org.freedesktop.DBus.Error.UnknownProperty",
                                     "Unknown media property")
        if interface != PLAYER or key not in {"Volume", "Rate"}:
            return Message.new_error(message, "org.freedesktop.DBus.Error.PropertyReadOnly",
                                     "Read-only media property")
        if value.signature != "d" or not math.isfinite(value.value):
            raise ValueError("invalid media property")
        if key == "Volume":
            self._volume(min(1.0, max(0.0, value.value)))
        elif value.value == 0:
            self._command("pause")
        return Message.new_method_return(message)

    @staticmethod
    def _unknown(message: Message) -> Message:
        return Message.new_error(message, "org.freedesktop.DBus.Error.UnknownMethod",
                                 "Unknown method or invalid argument signature")
