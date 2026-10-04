"""Tests for optional Termux notification controls."""

import subprocess
from unittest.mock import patch

from auen.termux_notification import TermuxNotificationController


def test_notification_buttons_call_auen_remote_commands() -> None:
    controller = TermuxNotificationController(
        notification_command="/termux/bin/termux-notification",
        remove_command="/termux/bin/termux-notification-remove",
        auen_command="/termux/bin/auen",
    )
    with patch("auen.termux_notification.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess([], 0, "", "")
        controller._show("Track title", playing=True)

    command = run.call_args.args[0]
    assert "Track title" in command
    assert "Pause" in command
    assert "/termux/bin/auen remote toggle" in command
    assert "/termux/bin/auen remote next" in command
    assert "/termux/bin/auen remote stop" in command
    controller.close()


def test_notification_failure_is_recorded_instead_of_raised() -> None:
    controller = TermuxNotificationController(
        notification_command="termux-notification",
        auen_command="auen",
    )
    with patch(
        "auen.termux_notification.subprocess.run",
        side_effect=subprocess.TimeoutExpired("termux-notification", 3),
    ):
        controller._show("Track title", playing=False)

    assert controller.last_error is not None
    controller.close()


def test_notification_is_unavailable_without_commands() -> None:
    with patch("auen.termux_notification.shutil.which", return_value=None):
        controller = TermuxNotificationController()

    assert not controller.available
    controller.update("Ignored", playing=True)
    controller.close()
