"""Optional Android notification controls backed by Termux:API."""

from __future__ import annotations

import shlex
import shutil
import subprocess
import threading

_NOTIFICATION_ID = "auen-playback"


class TermuxNotificationController:
    """Publish non-fatal playback controls without owning audio playback."""

    def __init__(
        self,
        *,
        notification_command: str | None = None,
        remove_command: str | None = None,
        auen_command: str | None = None,
    ) -> None:
        self.notification_command = notification_command or shutil.which(
            "termux-notification"
        )
        self.remove_command = remove_command or shutil.which("termux-notification-remove")
        self.auen_command = auen_command or shutil.which("auen")
        self.last_error: str | None = None
        self._condition = threading.Condition()
        self._pending: tuple[str, bool] | None = None
        self._last_requested: tuple[str, bool] | None = None
        self._closed = False
        self._thread: threading.Thread | None = None
        if self.available:
            self._thread = threading.Thread(
                target=self._run,
                name="auen-termux-notification",
                daemon=True,
            )
            self._thread.start()

    @property
    def available(self) -> bool:
        return self.notification_command is not None and self.auen_command is not None

    def update(self, title: str, *, playing: bool) -> None:
        if not self.available or self._closed:
            return
        requested = (title, playing)
        with self._condition:
            if requested == self._last_requested:
                return
            self._last_requested = requested
            self._pending = requested
            self._condition.notify()

    def clear(self) -> None:
        if not self.available or self._closed:
            return
        with self._condition:
            self._last_requested = None
            self._pending = ("", False)
            self._condition.notify()

    def close(self) -> None:
        with self._condition:
            if self._closed:
                return
            self._closed = True
            self._pending = None
            self._condition.notify()
        self._remove_without_waiting()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=0.5)

    def _run(self) -> None:
        while True:
            with self._condition:
                while self._pending is None and not self._closed:
                    self._condition.wait()
                if self._closed:
                    return
                requested = self._pending
                self._pending = None
            if requested is None:
                continue
            title, playing = requested
            if title:
                self._show(title, playing=playing)
            else:
                self._remove()

    def _show(self, title: str, *, playing: bool) -> None:
        assert self.notification_command is not None
        assert self.auen_command is not None
        toggle_action = shlex.join([self.auen_command, "remote", "toggle"])
        next_action = shlex.join([self.auen_command, "remote", "next"])
        stop_action = shlex.join([self.auen_command, "remote", "stop"])
        command = [
            self.notification_command,
            "--id",
            _NOTIFICATION_ID,
            "--title",
            "auen · Playing" if playing else "auen · Paused",
            "--content",
            title,
            "--ongoing",
            "--alert-once",
            "--priority",
            "low",
            "--button1",
            "Pause" if playing else "Resume",
            "--button1-action",
            toggle_action,
            "--button2",
            "Next",
            "--button2-action",
            next_action,
            "--button3",
            "Stop",
            "--button3-action",
            stop_action,
        ]
        self._run_command(command)

    def _remove(self) -> None:
        if self.remove_command is None:
            return
        self._run_command([self.remove_command, _NOTIFICATION_ID])

    def _remove_without_waiting(self) -> None:
        if self.remove_command is None:
            return
        try:
            subprocess.Popen(
                [self.remove_command, _NOTIFICATION_ID],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            self.last_error = str(exc)

    def _run_command(self, command: list[str]) -> None:
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=3.0,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.last_error = str(exc)
            return
        if result.returncode:
            self.last_error = (result.stderr or result.stdout).strip() or "command failed"
        else:
            self.last_error = None
