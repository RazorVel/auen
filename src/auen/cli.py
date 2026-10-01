"""Command-line entry point and scriptable settings interface for auen."""

from __future__ import annotations

import argparse
import shutil
import sys
from dataclasses import fields
from pathlib import Path
from typing import TYPE_CHECKING, Any

from auen import __version__
from auen.config import AuenConfig

if TYPE_CHECKING:
    from collections.abc import Sequence

SETTING_ALIASES = {
    "cache.max_size": "cache_max_bytes",
    "cache.max_bytes": "cache_max_bytes",
    "cache.directory": "cache_dir",
    "downloads.workers": "max_download_threads",
    "library.recursive": "scan_recursive",
    "playback.repeat": "repeat_mode",
    "playback.shuffle": "shuffle",
    "playback.volume": "volume",
    "search.results": "search_result_count",
    "session.mode": "session_mode",
    "session.restore": "restore_session",
    "ui.theme": "theme",
}

HIDDEN_SETTINGS = {"config_dir", "state_dir"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="auen",
        description="Terminal audio player with YouTube search and offline playback.",
    )
    parser.add_argument("--version", action="version", version=f"auen {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    config_parser = subparsers.add_parser("config", help="View or change settings")
    config_commands = config_parser.add_subparsers(dest="config_command", required=True)
    config_commands.add_parser("list", help="List settings")

    get_parser = config_commands.add_parser("get", help="Print one setting")
    get_parser.add_argument("key")

    set_parser = config_commands.add_parser("set", help="Change one setting")
    set_parser.add_argument("key")
    set_parser.add_argument("value")

    reset_parser = config_commands.add_parser("reset", help="Reset one setting")
    reset_parser.add_argument("key")

    subparsers.add_parser("doctor", help="Check runtime dependencies and configuration")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "config":
            return _handle_config(args)
        if args.command == "doctor":
            return _doctor()
        if args.command is None:
            return _launch_tui()
    except (OSError, ValueError) as exc:
        print(f"auen: {exc}", file=sys.stderr)
        return 2

    parser.print_help()
    return 0


def _handle_config(args: argparse.Namespace) -> int:
    config = AuenConfig.load()

    if args.config_command == "list":
        for key in _setting_names():
            print(f"{key}={_format_value(getattr(config, key))}")
        return 0

    key = _resolve_setting(args.key)
    if args.config_command == "get":
        print(_format_value(getattr(config, key)))
        return 0

    if args.config_command == "set":
        current = getattr(config, key)
        setattr(config, key, _parse_value(args.value, current, key))
    elif args.config_command == "reset":
        setattr(config, key, getattr(AuenConfig(), key))

    path = config.save()
    print(f"{key}={_format_value(getattr(config, key))}")
    print(f"Saved {path}")
    return 0


def _setting_names() -> list[str]:
    return sorted(field.name for field in fields(AuenConfig) if field.name not in HIDDEN_SETTINGS)


def _resolve_setting(key: str) -> str:
    normalized = key.strip().lower().replace("-", "_")
    resolved = SETTING_ALIASES.get(normalized, normalized.replace(".", "_"))
    if resolved not in _setting_names():
        raise ValueError(f"unknown setting: {key}")
    return resolved


def _parse_value(raw: str, current: Any, key: str) -> Any:
    if isinstance(current, bool):
        normalized = raw.casefold()
        if normalized in {"true", "yes", "on", "1"}:
            return True
        if normalized in {"false", "no", "off", "0"}:
            return False
        raise ValueError(f"{key} expects true or false")
    if isinstance(current, int):
        if key == "cache_max_bytes":
            return _parse_size(raw)
        try:
            return int(raw)
        except ValueError as exc:
            raise ValueError(f"{key} expects a whole number") from exc
    if isinstance(current, Path):
        return Path(raw).expanduser()
    return raw


def _parse_size(raw: str) -> int:
    normalized = raw.strip().upper().replace(" ", "")
    units = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3}
    for suffix in ("GB", "MB", "KB", "B"):
        if normalized.endswith(suffix):
            number = normalized[: -len(suffix)]
            try:
                return int(float(number) * units[suffix])
            except ValueError as exc:
                raise ValueError(f"invalid storage size: {raw}") from exc
    try:
        return int(normalized)
    except ValueError as exc:
        raise ValueError(f"invalid storage size: {raw}") from exc


def _format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _doctor() -> int:
    problems = 0
    print(f"[ok] Python {sys.version_info.major}.{sys.version_info.minor}")

    try:
        config = AuenConfig.load()
        print(f"[ok] Configuration: {config.config_dir / 'config.toml'}")
    except (OSError, ValueError) as exc:
        print(f"[fail] Configuration: {exc}")
        problems += 1

    mpv = shutil.which("mpv")
    termux = shutil.which("termux-media-player")
    if mpv:
        print(f"[ok] mpv: {mpv}")
    elif termux:
        print(f"[ok] Termux media player: {termux}")
    else:
        print("[fail] No playback backend found (mpv or termux-media-player)")
        problems += 1

    ytdlp = shutil.which("yt-dlp")
    if ytdlp:
        print(f"[ok] yt-dlp: {ytdlp}")
    else:
        print("[fail] yt-dlp executable was not found")
        problems += 1

    return 1 if problems else 0


def _launch_tui() -> int:
    try:
        from auen.app import run
    except ImportError:
        print("auen: the Textual interface is not installed yet", file=sys.stderr)
        return 2
    run()
    return 0
