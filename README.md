# auen

`auen` is a keyboard-first terminal audio player for Linux and Termux. It is being built
around a Textual interface, selectable YouTube search results, local music, a persistent
queue, and a managed offline library.

> **Development status:** the models, playlist, Linux/Termux backend abstraction,
> crash-safe session store, configuration CLI, startup-mode prompt, and Settings screen
> exist. Search, cache management, and end-to-end playback orchestration are still under
> construction.

## Requirements

- Python 3.10 or newer
- Linux with `mpv`, or Android/Termux with Termux:API
- `pipx` for the simplest isolated installation

The interface is designed to remain portable across Unix terminals. Playback support is
currently limited to Linux and Termux, with room for additional backends later.

## Install

From a release or checked-out source directory:

```console
pipx install .
auen doctor
auen
```

Without `pipx`:

```console
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
auen doctor
```

`auen doctor` checks the configuration, audio backend, and `yt-dlp` installation and
reports actionable setup problems without launching the interface.

## Settings from the terminal

Press `F2` inside auen to open the Settings screen. The same settings are scriptable:

```console
auen config list
auen config get cache.max_size
auen config set cache.max_size 1.5GB
auen config set session.mode stream_and_cache
auen config reset playback.volume
```

Settings are stored in the platform's XDG configuration directory. Queue and recovery
state are kept separately in a transactional SQLite database.

## Develop and build

```console
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
make check
make build
```

`make check` runs tests with a safety timeout, linting, and strict type checking. Build
artifacts are written to `dist/` as a wheel and source archive.

The agreed product behavior and implementation boundaries are recorded in
[`docs/requirements.md`](docs/requirements.md).
