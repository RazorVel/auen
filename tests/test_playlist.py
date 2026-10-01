"""Tests for the playlist module."""

import threading
import time

from auen.models import RepeatMode, Track, TrackSource
from auen.playlist import Playlist


def make_track(title: str) -> Track:
    return Track(title=title, source=TrackSource.LOCAL, uri=f"/{title}")


def test_add_and_next() -> None:
    playlist = Playlist()
    track1 = make_track("t1")
    track2 = make_track("t2")

    playlist.add(track1)
    playlist.add(track2)

    assert playlist.queue_length == 2
    assert playlist.next() == track1
    assert playlist.next() == track2
    assert playlist.queue_length == 0


def test_next_blocks_until_available() -> None:
    playlist = Playlist()
    track = make_track("t1")
    result: list[Track | None] = []

    def consumer() -> None:
        result.append(playlist.next(timeout=5.0))

    t = threading.Thread(target=consumer)
    t.start()

    # Give the thread a moment to block
    time.sleep(0.1)
    playlist.add(track)
    t.join(timeout=2.0)

    assert len(result) == 1
    assert result[0] == track


def test_next_timeout() -> None:
    playlist = Playlist()
    assert playlist.next(timeout=0.1) is None


def test_shuffle_randomizes_order() -> None:
    playlist = Playlist()
    playlist.shuffle = True

    # Over 10 iterations, it shouldn't always be FIFO
    fifo_matches = 0
    for _ in range(10):
        playlist.clear()
        tracks = [make_track(f"t{i}") for i in range(5)]
        playlist.add_many(tracks)

        pulled = [playlist.next() for _ in range(5)]
        if pulled == tracks:
            fifo_matches += 1

    assert fifo_matches < 10


def test_shuffle_off_preserves_order() -> None:
    playlist = Playlist()
    playlist.shuffle = False

    tracks = [make_track(f"t{i}") for i in range(5)]
    playlist.add_many(tracks)

    pulled = [playlist.next() for _ in range(5)]
    assert pulled == tracks


def test_remove_by_index() -> None:
    playlist = Playlist()
    tracks = [make_track(f"t{i}") for i in range(3)]
    playlist.add_many(tracks)

    removed = playlist.remove(1)
    assert removed == tracks[1]

    remaining = playlist.queue_list
    assert remaining == [tracks[0], tracks[2]]


def test_remove_invalid_index() -> None:
    playlist = Playlist()
    assert playlist.remove(0) is None
    assert playlist.remove(-1) is None


def test_jump_moves_to_head() -> None:
    playlist = Playlist()
    tracks = [make_track(f"t{i}") for i in range(3)]
    playlist.add_many(tracks)

    jumped = playlist.jump(2)
    assert jumped == tracks[2]
    assert playlist.queue_list[0] == tracks[2]


def test_move_changes_queue_priority_and_clamps_at_edges() -> None:
    playlist = Playlist()
    tracks = [make_track(f"t{i}") for i in range(3)]
    playlist.add_many(tracks)

    assert playlist.move(2, -1) == 1
    assert playlist.queue_list == [tracks[0], tracks[2], tracks[1]]
    assert playlist.move(1, -10) == 0
    assert playlist.queue_list[0] == tracks[2]
    assert playlist.move(99, 1) is None


def test_mark_played_adds_to_history() -> None:
    playlist = Playlist()
    track = make_track("t1")
    playlist.mark_played(track)

    assert playlist.history_length == 1
    assert playlist.history_list == [track]


def test_recycle_with_loop_on() -> None:
    playlist = Playlist()
    playlist.repeat_mode = RepeatMode.ALL
    track = make_track("t1")
    playlist.mark_played(track)

    playlist.recycle()

    assert playlist.history_length == 0
    assert playlist.queue_length == 1
    assert playlist.queue_list == [track]


def test_recycle_with_loop_off() -> None:
    playlist = Playlist()
    playlist.repeat_mode = RepeatMode.OFF
    track = make_track("t1")
    playlist.mark_played(track)

    playlist.recycle()

    assert playlist.history_length == 1
    assert playlist.queue_length == 0


def test_complete_repeats_one_track() -> None:
    playlist = Playlist()
    playlist.repeat_mode = RepeatMode.ONE
    track = make_track("t1")

    playlist.complete(track)

    assert playlist.history_list == [track]
    assert playlist.queue_list == [track]


def test_complete_repeats_all_after_queue_finishes() -> None:
    playlist = Playlist()
    playlist.repeat_mode = RepeatMode.ALL
    first = make_track("t1")
    second = make_track("t2")
    playlist.mark_played(first)

    playlist.complete(second)

    assert playlist.history_list == []
    assert playlist.queue_list == [first, second]


def test_clear() -> None:
    playlist = Playlist()
    playlist.add(make_track("t1"))
    playlist.mark_played(make_track("t2"))

    playlist.clear()

    assert playlist.queue_length == 0
    assert playlist.history_length == 1


def test_thread_safety() -> None:
    playlist = Playlist()
    num_threads = 5
    items_per_thread = 100

    def producer(t_id: int) -> None:
        for i in range(items_per_thread):
            playlist.add(make_track(f"t{t_id}_{i}"))

    def consumer() -> None:
        for _ in range(items_per_thread):
            playlist.next(timeout=1.0)

    producers = [threading.Thread(target=producer, args=(i,)) for i in range(num_threads)]
    consumers = [threading.Thread(target=consumer) for _ in range(num_threads)]

    for t in producers + consumers:
        t.start()

    for t in producers + consumers:
        t.join(timeout=5.0)

    assert playlist.queue_length == 0
