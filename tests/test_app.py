"""Tests for the Textual application shell and settings screen."""

from pathlib import Path

from auen.app import AuenApp, SessionModeScreen, SettingsScreen
from auen.config import AuenConfig
from auen.models import SessionMode


async def test_startup_asks_for_session_mode(tmp_path: Path) -> None:
    config = AuenConfig(config_dir=tmp_path, session_mode=SessionMode.ASK.value)
    app = AuenApp(config)

    async with app.run_test() as pilot:
        assert isinstance(app.screen, SessionModeScreen)
        await pilot.click("#stream-only")
        await pilot.pause()

        assert app.current_session_mode is SessionMode.STREAM_ONLY


async def test_settings_screen_saves_to_shared_config(tmp_path: Path) -> None:
    config = AuenConfig(config_dir=tmp_path, session_mode=SessionMode.STREAM_ONLY.value)
    app = AuenApp(config)

    async with app.run_test() as pilot:
        await pilot.press("f2")
        await pilot.pause()
        assert isinstance(app.screen, SettingsScreen)

        volume = app.screen.query_one("#volume")
        volume.value = "61"
        await pilot.click("#save")
        await pilot.pause()

        assert app.config.volume == 61
        assert (tmp_path / "config.toml").exists()
