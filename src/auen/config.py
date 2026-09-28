"""Configuration management for auen."""

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from platformdirs import user_cache_dir, user_config_dir

from auen.models import RepeatMode, SessionMode

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[import-not-found]


@dataclass
class AuenConfig:
    backend: str = "auto"
    cache_dir: Path = Path(user_cache_dir("auen"))
    config_dir: Path = Path(user_config_dir("auen"))
    max_download_threads: int = 4
    volume: int = 80
    shuffle: bool = False
    repeat_mode: str = RepeatMode.OFF.value
    stream_first: bool = True
    search_result_count: int = 5
    session_mode: str = SessionMode.ASK.value
    cache_max_bytes: int = 1024**3
    restore_session: bool = True
    scan_recursive: bool = True

    @classmethod
    def load(cls, overrides: dict[str, Any] | None = None) -> "AuenConfig":
        """Load configuration from TOML file, then apply overrides."""
        config_dir = Path(user_config_dir("auen"))
        config_path = config_dir / "config.toml"

        data: dict[str, Any] = {}
        if config_path.exists():
            try:
                with open(config_path, "rb") as f:
                    data = tomllib.load(f)
            except Exception as e:
                print(f"Warning: Failed to parse {config_path}: {e}", file=sys.stderr)

        # Flatten the toml structure (assuming sections like [general], [playback], [search])
        flat_data: dict[str, Any] = {}
        for section in data.values():
            if isinstance(section, dict):
                flat_data.update(section)

        # Migrate the early boolean setting without breaking existing config files.
        if "loop" in flat_data and "repeat_mode" not in flat_data:
            flat_data["repeat_mode"] = (
                RepeatMode.ALL.value if flat_data.pop("loop") else RepeatMode.OFF.value
            )

        # Convert path strings to Path objects if necessary
        if (
            "cache_dir" in flat_data
            and isinstance(flat_data["cache_dir"], str)
            and flat_data["cache_dir"]
        ):
            flat_data["cache_dir"] = Path(flat_data["cache_dir"])
        elif "cache_dir" in flat_data:
            # Drop empty cache_dir so it falls back to default
            del flat_data["cache_dir"]

        # Apply overrides (typically from CLI args)
        if overrides:
            for k, v in overrides.items():
                if v is not None:
                    # Rename CLI args if they differ from config names
                    key = k
                    if key == "no_stream":
                        flat_data["stream_first"] = not v
                        continue
                    if key == "dir":
                        # Not a config setting
                        continue
                    if key == "file":
                        # Not a config setting
                        continue
                    if key == "url":
                        continue
                    if key == "search":
                        continue
                    if key == "playlist":
                        continue

                    if key == "loop":
                        flat_data["repeat_mode"] = (
                            RepeatMode.ALL.value if v else RepeatMode.OFF.value
                        )
                        continue

                    if key in cls.__dataclass_fields__:
                        if key == "cache_dir" and isinstance(v, str) and v:
                            flat_data[key] = Path(v)
                        else:
                            flat_data[key] = v

        # Filter out keys that aren't fields of AuenConfig
        valid_keys = {f for f in cls.__dataclass_fields__}
        filtered_data = {k: v for k, v in flat_data.items() if k in valid_keys}
        filtered_data["config_dir"] = config_dir

        config = cls(**filtered_data)
        config.validate()
        return config

    def save(self) -> Path:
        """Atomically persist user-editable settings and return the config path."""
        self.validate()
        self.config_dir.mkdir(parents=True, exist_ok=True)
        config_path = self.config_dir / "config.toml"
        temporary_path = self.config_dir / ".config.toml.tmp"

        content = "\n".join(
            [
                "# auen settings — editable by hand or through `auen config`.",
                "[general]",
                f"backend = {_toml_string(self.backend)}",
                f"session_mode = {_toml_string(self.session_mode)}",
                f"restore_session = {_toml_bool(self.restore_session)}",
                "",
                "[playback]",
                f"volume = {self.volume}",
                f"shuffle = {_toml_bool(self.shuffle)}",
                f"repeat_mode = {_toml_string(self.repeat_mode)}",
                f"stream_first = {_toml_bool(self.stream_first)}",
                "",
                "[search]",
                f"search_result_count = {self.search_result_count}",
                "",
                "[cache]",
                f"cache_dir = {_toml_string(str(self.cache_dir))}",
                f"cache_max_bytes = {self.cache_max_bytes}",
                f"max_download_threads = {self.max_download_threads}",
                "",
                "[library]",
                f"scan_recursive = {_toml_bool(self.scan_recursive)}",
                "",
            ]
        )

        temporary_path.write_text(content, encoding="utf-8")
        temporary_path.chmod(0o600)
        os.replace(temporary_path, config_path)
        return config_path

    def validate(self) -> None:
        """Reject invalid values before they reach playback or the UI."""
        if self.backend not in {"auto", "mpv", "termux"}:
            raise ValueError(f"Unsupported backend: {self.backend}")
        if self.repeat_mode not in {mode.value for mode in RepeatMode}:
            raise ValueError(f"Unsupported repeat mode: {self.repeat_mode}")
        if self.session_mode not in {mode.value for mode in SessionMode}:
            raise ValueError(f"Unsupported session mode: {self.session_mode}")
        if not 0 <= self.volume <= 100:
            raise ValueError("volume must be between 0 and 100")
        if self.max_download_threads < 1:
            raise ValueError("max_download_threads must be at least 1")
        if self.search_result_count < 1:
            raise ValueError("search_result_count must be at least 1")
        if self.cache_max_bytes < 0:
            raise ValueError("cache_max_bytes cannot be negative")


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _toml_bool(value: bool) -> str:
    return "true" if value else "false"
