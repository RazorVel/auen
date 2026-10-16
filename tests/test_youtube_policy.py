"""Tests for shared anonymous YouTube request pacing and cooldown."""

import threading
from concurrent.futures import CancelledError, ThreadPoolExecutor

import pytest

from auen.youtube_policy import YouTubeCooldownError, YouTubeRequestGate


class FakeTime:
    def __init__(self) -> None:
        self.now = 100.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_gate_spaces_request_starts() -> None:
    fake = FakeTime()
    gate = YouTubeRequestGate(
        minimum_interval_seconds=1.25,
        clock=fake.clock,
        sleeper=fake.sleep,
    )

    gate.wait_turn()
    gate.wait_turn()

    assert fake.sleeps == [1.25]


def test_cancel_interrupts_request_spacing() -> None:
    gate = YouTubeRequestGate(minimum_interval_seconds=30)
    gate.wait_turn()
    cancelled = threading.Event()
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(gate.wait_turn, cancelled=cancelled)
        cancelled.set()
        with pytest.raises(CancelledError):
            future.result(timeout=1)


def test_gate_fails_fast_until_cooldown_expires() -> None:
    fake = FakeTime()
    gate = YouTubeRequestGate(
        minimum_interval_seconds=0,
        cooldown_seconds=120,
        clock=fake.clock,
        sleeper=fake.sleep,
    )

    assert gate.block() == 120
    with pytest.raises(YouTubeCooldownError, match=r"Try again in 2:00"):
        gate.wait_turn()

    fake.now += 120
    gate.wait_turn()
    assert gate.remaining_seconds == 0


@pytest.mark.parametrize(
    ("minimum_interval", "cooldown"),
    [(-1, 1), (1, -1)],
)
def test_gate_rejects_negative_timings(
    minimum_interval: float,
    cooldown: float,
) -> None:
    with pytest.raises(ValueError):
        YouTubeRequestGate(
            minimum_interval_seconds=minimum_interval,
            cooldown_seconds=cooldown,
        )
