"""Command-line entry point and scriptable settings interface for auen."""

from __future__ import annotations

import argparse
import importlib.util
import shutil
import subprocess
import sys
from dataclasses import fields
from pathlib import Path
from typing import TYPE_CHECKING, Any

from auen import __version__
from auen.config import AuenConfig
from auen.remote import send_remote_command

if TYPE_CHECKING:
    from collections.abc import Sequence

SETTING_ALIASES = {
    "android.notification": "android_notification",
    "android.notification_controls": "android_notification",
    "cache.max_size": "cache_max_bytes",
    "cache.max_bytes": "cache_max_bytes",
    "cache.directory": "cache_dir",
    "downloads.workers": "max_download_threads",
    "library.recursive": "scan_recursive",
    "playback.repeat": "repeat_mode",
    "playback.shuffle": "shuffle",
    "playback.volume": "volume",
    "search.load_more": "search_result_count",
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
    remote_parser = subparsers.add_parser("remote", help="Control a running auen instance")
    remote_parser.add_argument(
        "remote_command",
        choices=("toggle", "next", "stop", "status"),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "config":
            return _handle_config(args)
        if args.command == "doctor":
            return _doctor()
        if args.command == "remote":
            return _handle_remote(args.remote_command)
        if args.command is None:
            return _launch_tui()
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"auen: {exc}", file=sys.stderr)
        return 2

    parser.print_help()
    return 0


def _handle_remote(command: str) -> int:
    config = AuenConfig.load()
    response = send_remote_command(config.state_dir, command)
    message = response.get("message")
    if isinstance(message, str) and message:
        print(message)
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

    termux = shutil.which("termux-media-player")
    termux_notification = shutil.which("termux-notification")
    mpv = shutil.which("mpv")
    if mpv:
        print(f"[ok] mpv: {mpv} (preferred by automatic backend)")
    if termux_notification:
        print(f"[ok] Android notification controls: {termux_notification}")
    else:
        print("[info] Android notification controls are optional (Termux:API)")
    if termux:
        print(f"[ok] Termux media player: {termux}")
        volume = shutil.which("termux-volume")
        if volume:
            print(f"[ok] Termux volume: {volume}")
        else:
            print("[fail] termux-volume was not found (install the termux-api package)")
            problems += 1
        try:
            probe = subprocess.run(
                ["termux-media-player", "info"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5.0,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(f"[fail] Termux:API companion did not respond: {exc}")
            problems += 1
        else:
            if probe.returncode == 0:
                print("[ok] Termux:API companion responded")
            else:
                detail = (probe.stderr or probe.stdout).strip()
                print(f"[fail] Termux:API companion: {detail or 'command failed'}")
                problems += 1
    if not mpv and not termux:
        print("[fail] No playback backend found (mpv or termux-media-player)")
        problems += 1

    if importlib.util.find_spec("yt_dlp") is not None:
        print("[ok] yt-dlp Python package")
    else:
        print("[fail] yt-dlp Python package was not found")
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
