"""Generate deterministic README previews from the real Textual application.

Run from the repository root with::

    .venv/bin/python docs/generate_previews.py

The sample library lives in a temporary directory and is deleted afterwards.
No network access or real playback backend is used.
"""

from __future__ import annotations

import asyncio
import math
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from textual.widgets import DataTable, Input, ProgressBar, Static

from auen.app import AuenApp
from auen.cache import CacheManager
from auen.config import AuenConfig
from auen.downloads import DownloadManager
from auen.models import MediaCollection, SessionMode, Track, TrackSource
from auen.session import AuenSession
from auen.state import StateStore

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs" / "assets"


def track(number: int, title: str, duration: str) -> Track:
    minutes, seconds = (int(part) for part in duration.split(":"))
    return Track(
        title=title,
        source=TrackSource.YOUTUBE,
        uri=f"https://www.youtube.com/watch?v=preview{number:02d}",
        duration_seconds=minutes * 60 + seconds,
        duration_display=duration,
        track_id=f"preview-{number:02d}",
    )


TRACKS = [
    track(1, "Tycho - Awake", "4:44"),
    track(2, "Nujabes - Aruarian Dance", "4:10"),
    track(3, "Men I Trust - Show Me How", "3:35"),
    track(4, "Khruangbin - Friday Morning", "6:50"),
    track(5, "Yussef Dayes - Black Classical Music", "5:02"),
    track(6, "Lamp - For Lovers", "4:06"),
    track(7, "The Marías - No One Noticed", "3:57"),
    track(8, "Masayoshi Takanaka - Blue Lagoon", "5:05"),
]


def build_app(root: Path) -> tuple[AuenApp, AuenSession]:
    config = AuenConfig(
        config_dir=root / "config",
        cache_dir=root / "cache",
        state_dir=root / "state",
        session_mode=SessionMode.STREAM_ONLY.value,
        restore_session=False,
        android_notification=False,
    )
    state = StateStore(config.state_dir / "state.sqlite3")
    cache = CacheManager(config.cache_dir)
    downloads = DownloadManager(cache, max_workers=1)
    session = AuenSession(config, state=state, cache=cache, downloads=downloads)

    session.enqueue_many([TRACKS[1], TRACKS[2], TRACKS[4]])

    now = datetime(2026, 10, 4, 9, 50, tzinfo=timezone.utc)
    for offset, item in enumerate([TRACKS[0], TRACKS[3], TRACKS[1], TRACKS[5]]):
        session.state.record_play(item, played_at=now - timedelta(hours=offset * 7))
    session.state.record_play(TRACKS[0], played_at=now + timedelta(minutes=1))
    session.state.record_play(TRACKS[0], played_at=now + timedelta(minutes=2))

    favorites = session.create_named_playlist("Late-night favorites")
    for item in [TRACKS[0], TRACKS[2], TRACKS[5], TRACKS[7]]:
        session.add_to_named_playlist(favorites.playlist_id, item)
    focus = session.create_named_playlist("Deep focus")
    for item in [TRACKS[1], TRACKS[3], TRACKS[4]]:
        session.add_to_named_playlist(focus.playlist_id, item)
    session.create_named_playlist("Morning walk")

    for index, item in enumerate([TRACKS[0], TRACKS[1], TRACKS[3], TRACKS[5], TRACKS[7]]):
        destination = cache.destination_for(item)
        with destination.open("wb") as media:
            media.truncate((index + 3) * 1024 * 1024 + index * 173_000)
        cache.register(item, destination, pinned=index in {0, 3})

    return AuenApp(config, session=session), session


def show_playback(app: AuenApp) -> None:
    current = TRACKS[0]
    app.session.current_track = current
    app._show_now_playing(current)
    app.query_one("#playback-progress", ProgressBar).update(total=284, progress=97)
    app.query_one("#playback-time", Static).update("1:37 / 4:44")
    app._refresh_download_status()


async def capture(
    filename: str,
    *,
    size: tuple[int, int],
    view: str,
    termux: bool = False,
    crop: tuple[int, int, int, int] | None = None,
) -> None:
    with TemporaryDirectory(prefix="auen-preview-") as temporary:
        old_termux = os.environ.get("TERMUX_VERSION")
        if termux:
            os.environ["TERMUX_VERSION"] = "preview"
        else:
            os.environ.pop("TERMUX_VERSION", None)
        try:
            app, session = build_app(Path(temporary))
            async with app.run_test(size=size) as pilot:
                results: list[Track | MediaCollection] = [
                    TRACKS[0],
                    TRACKS[1],
                    MediaCollection("Japanese city-pop essentials", "preview:playlist"),
                    TRACKS[3],
                    TRACKS[6],
                ]
                app.query_one("#search-bar", Input).value = "music for focus"
                app._show_results(results, has_more=True, cursor_row=1)
                app._refresh_queue()
                show_playback(app)

                if view == "history":
                    app._show_history(cursor_row=0)
                elif view == "playlist":
                    playlist = next(
                        item
                        for item in session.named_playlists()
                        if item.name == "Late-night favorites"
                    )
                    app._show_named_playlist_tracks(playlist, cursor_row=1)
                elif view == "library":
                    app._show_library(cursor_row=1)
                elif view != "overview":
                    raise ValueError(f"unknown preview view: {view}")

                app.query_one("#results", DataTable).focus()
                app._update_context_guides()
                await pilot.pause()
                svg = app.export_screenshot(title="auen")
                svg = re.sub(r"terminal-\d+", "terminal-auen", svg)
                svg = re.sub(r">\d{2}:\d{2}:\d{2}<", ">12:34:56<", svg, count=1)
                svg = re.sub(r"^[ \t]+$", "", svg, flags=re.MULTILINE)
                if crop is not None:
                    x, y, width, height = crop
                    svg = re.sub(
                        r'^<svg class="rich-terminal" viewBox="[^"]+"',
                        (
                            '<svg class="rich-terminal" '
                            f'viewBox="{x} {y} {width} {height}" '
                            f'width="{width}" height="{height}" '
                            'style="overflow:hidden"'
                        ),
                        svg,
                        count=1,
                    )
                else:
                    dimensions = re.search(
                        r'^<svg class="rich-terminal" viewBox="0 0 ([\d.]+) ([\d.]+)"',
                        svg,
                    )
                    if dimensions is None:
                        raise ValueError("Rich screenshot has no usable viewBox")
                    width = math.ceil(float(dimensions.group(1)))
                    height = math.ceil(float(dimensions.group(2)))
                    svg = re.sub(
                        r'^<svg class="rich-terminal" viewBox="([^"]+)"',
                        (
                            '<svg class="rich-terminal" viewBox="\\1" '
                            f'width="{width}" height="{height}" '
                            'style="overflow:hidden"'
                        ),
                        svg,
                        count=1,
                    )
                (ASSETS / filename).write_text(svg, encoding="utf-8")
        finally:
            if old_termux is None:
                os.environ.pop("TERMUX_VERSION", None)
            else:
                os.environ["TERMUX_VERSION"] = old_termux


async def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    await capture("auen-wide.svg", size=(120, 32), view="overview")
    pane_crop = (12, 145, 946, 210)
    await capture(
        "auen-history.svg", size=(78, 28), view="history", crop=pane_crop
    )
    await capture(
        "auen-playlist.svg", size=(78, 28), view="playlist", crop=pane_crop
    )
    await capture(
        "auen-library.svg", size=(78, 28), view="library", crop=pane_crop
    )
    await capture("auen-termux.svg", size=(60, 32), view="overview", termux=True)


if __name__ == "__main__":
    asyncio.run(main())
