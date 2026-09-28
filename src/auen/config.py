"""Configuration management for auen."""

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from platformdirs import user_cache_dir, user_config_dir

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
    loop: bool = False
    stream_first: bool = True
    search_result_count: int = 5

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

                    if key in cls.__dataclass_fields__:
                        if key == "cache_dir" and isinstance(v, str) and v:
                            flat_data[key] = Path(v)
                        else:
                            flat_data[key] = v

        # Filter out keys that aren't fields of AuenConfig
        valid_keys = {f for f in cls.__dataclass_fields__}
        filtered_data = {k: v for k, v in flat_data.items() if k in valid_keys}

        return cls(**filtered_data)
