"""Tests for the config module."""

from pathlib import Path
from unittest.mock import patch

import pytest

from auen.config import AuenConfig


def test_config_defaults() -> None:
    config = AuenConfig()
    assert config.backend == "auto"
    assert config.max_download_threads == 4
    assert config.volume == 80
    assert config.shuffle is False
    assert config.repeat_mode == "off"
    assert config.stream_first is True
    assert config.search_result_count == 5
    assert config.session_mode == "ask"
    assert config.cache_max_bytes == 1024**3
    assert config.restore_session is True
    assert config.scan_recursive is True
    assert config.theme == "textual-dark"
    assert isinstance(config.cache_dir, Path)
    assert isinstance(config.config_dir, Path)


def test_config_load_from_toml(tmp_path: Path) -> None:
    toml_content = b"""
    [general]
    backend = "mpv"
    max_download_threads = 2

    [playback]
    volume = 50
    shuffle = true

    [search]
    search_result_count = 10
    """
    config_file = tmp_path / "config.toml"
    config_file.write_bytes(toml_content)

    with patch("auen.config.user_config_dir", return_value=str(tmp_path)):
        config = AuenConfig.load()

    assert config.backend == "mpv"
    assert config.max_download_threads == 2
    assert config.volume == 50
    assert config.shuffle is True
    assert config.search_result_count == 10
    # Defaults should remain for unconfigured values
    assert config.repeat_mode == "off"
    assert config.stream_first is True


def test_config_cli_overrides(tmp_path: Path) -> None:
    # CLI args override TOML
    toml_content = b"""
    [playback]
    volume = 50
    """
    config_file = tmp_path / "config.toml"
    config_file.write_bytes(toml_content)

    overrides = {
        "volume": 75,
        "no_stream": True,  # Translated to stream_first = False
        "shuffle": True,
    }

    with patch("auen.config.user_config_dir", return_value=str(tmp_path)):
        config = AuenConfig.load(overrides)

    assert config.volume == 75
    assert config.stream_first is False
    assert config.shuffle is True


def test_config_xdg_paths() -> None:
    config = AuenConfig()
    assert config.cache_dir.name == "auen"
    assert config.config_dir.name == "auen"


def test_config_migrates_legacy_loop_setting(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text("[playback]\nloop = true\n")

    with patch("auen.config.user_config_dir", return_value=str(tmp_path)):
        config = AuenConfig.load()

    assert config.repeat_mode == "all"


def test_config_rejects_invalid_values() -> None:
    config = AuenConfig(volume=101)

    with pytest.raises(ValueError, match="volume"):
        config.validate()
