# auen

<p align="center">
  <img src="docs/assets/logo.png" alt="auen logo" width="220">
</p>

`auen` is a keyboard-first terminal audio player for Linux and Android/Termux. It uses a
full-screen Textual interface for YouTube search, queue management, streaming, and a
size-limited persistent playback cache.

> **Release — v1.0.0:** The first stable release brings together core playback, responsive
> rendering, History, named playlists, Offline media, command mode, sleep timers, remote
> control, optional Android notification actions, anonymous-request cooldown, and reliable
> shutdown behavior validated with `mpv` on Linux and a physical Termux device.

![auen in a wide terminal](docs/assets/auen-wide.svg)

### Recently played

History keeps the most recent play time and play count while exposing the same play, queue,
offline, and playlist actions as the rest of auen.

![Recently played history](docs/assets/auen-history.svg)

### Named playlists

Saved playlists retain their ordering and duplicates. Tracks can be played immediately,
queued next, appended together, reordered, or saved into another playlist.

![An opened named playlist](docs/assets/auen-playlist.svg)

### Offline library

The local-only library shows duration, file size, and whether each track is retained (`◆`)
or belongs to the automatic size-limited cache (`○`).

![Offline media library](docs/assets/auen-library.svg)

### Termux layout

On phone-width terminals, Results and Queue stack vertically. Termux uses stable ASCII pane
borders while keeping playback, seeking, command mode, and the offline status strip visible.

![auen in Termux phone-width layout](docs/assets/auen-termux.svg)

## What works in v1.0.0

- Search YouTube and select tracks, albums, or playlists.
- Load more results explicitly without fetching merely by moving the cursor.
- Stream immediately or stream while retaining a managed offline copy.
- Play, pause, jump to a timestamp, seek by 10 seconds, and skip tracks with `mpv`.
- Add duplicate tracks with confirmation; play any queued row now or move its priority.
- Persist the queue, recently played tracks, cached media, settings, and playback position
  across restarts and crashes.
- Open Recently Played with `h`, including last-played timestamps and play counts; play now,
  play next, remove individual entries, or clear history with confirmation.
- Create, rename, delete, open, reorder, and play durable named playlists. Add tracks from
  search results, History, Queue, or another named playlist, or append a whole playlist to
  Queue in saved order.
- See streaming, downloading, and offline availability directly in Queue, History, and an
  opened named playlist.
- Open Offline media with `l`; filter locally without a network connection, inspect duration
  and size, play or queue cached tracks, retain or release automatic cache entries, delete
  managed media safely, and inspect cache usage and download activity.
- Pace anonymous YouTube operations across search, streaming, and downloads. A bot challenge
  or HTTP 429 starts a short fail-fast cooldown shown in the Offline strip, while cached and
  local playback remain available.
- Get compact, view-specific key guidance at the bottom of the focused Results or Queue pane.
- Preview and save themes, with an adaptive side-by-side or stacked phone-width layout.
- Configure behavior through the TUI or scriptable `auen config` commands.
- Open compact command mode with `:` for sleep timers, navigation, settings, themes, help,
  and clean quitting. Duration timers pause in place; `sleep track` holds the remaining Queue.
- Control a running instance through a private local socket. On Termux, optional notification
  actions provide Pause/Resume, Next, and Stop without replacing mpv as the audio backend.

Version 1.0 establishes the current controls, persistent data, and Linux/Termux workflows as
auen's stable core. Future features will continue to be guided by real usage. auen deliberately
does not use Google-account cookies, so videos or networks that require authenticated YouTube
access may be unavailable. Request pacing can reduce bursts, but it cannot bypass a YouTube IP
or account challenge.

## Requirements

- Python 3.10 or newer
- Linux with `mpv`, or Android with Termux and its `mpv` package
- Network access for YouTube search and streaming

`pipx` is recommended on Linux because it keeps auen and its Python dependencies in an
isolated environment.

## Install on Linux

Install the system playback backend first. For Debian and Ubuntu:

```console
sudo apt install mpv pipx
pipx ensurepath
```

Install the tagged release directly from GitHub:

```console
pipx install 'git+https://github.com/razorvel/auen.git@v1.0.0'
auen doctor
auen
```

For a checked-out source tree, use `pipx install .`. A regular virtual environment also
works:

```console
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
auen doctor
auen
```

## Prepare Termux for testing

Install [Termux](https://github.com/termux/termux-app#installation), then run:

```console
pkg update
pkg install python git mpv ffmpeg
python -m pip install 'git+https://github.com/razorvel/auen.git@v1.0.0'
auen doctor
auen
```

mpv is selected automatically and provides seeking, direct streaming, volume control, and
precise position reporting. Termux:API is not required when mpv is installed.

Optional Android notification controls require the
[Termux:API companion app](https://github.com/termux/termux-api#installation) from the same
source as Termux, then install its command package:

```console
pkg install termux-api
```

Termux and its companion apps must come from the same source because their signatures must
match. auen continues to use mpv for audio; Termux:API is used only to display an ongoing
notification with Pause/Resume, Next, and Stop actions. Disable it through **Android playback
notification** in Settings or `auen config set android.notification false`.

The same private local control channel is available from another Termux session:

```console
auen remote status
auen remote toggle
auen remote next
auen remote stop
```

`stop` cleanly exits the running auen instance. Missing or unresponsive notification support
never interrupts playback, and the local control socket is accessible only to the current
Termux/Linux user.

The real-device test sequence and expected limitations are recorded in
[`docs/termux-testing.md`](docs/termux-testing.md).

## Essential controls

| Key | Action |
| --- | --- |
| `/` | Focus search |
| `Tab` / `Shift+Tab` | Switch between Results and Queue |
| `Enter` | Open a collection, queue a result, or play a queued row now |
| `Esc` | Leave search or return from a collection |
| `Space` | Play or pause |
| `[` / `]` | Seek backward or forward 10 seconds |
| `g` | Jump to a timestamp |
| `n` | Play next track |
| `h` | Open or leave Recently Played |
| `p` | Open or leave named Playlists |
| `l` | Open or leave Offline media |
| `:` | Open command mode |
| `s` | Save the selected track to a named playlist |
| `e` | Append every track in the currently open named playlist to Queue |
| `d` | Retain the selected result for offline playback |
| `Home` | Promote the selected queued track to play next |
| `Shift+Up` / `Shift+Down` | Change queue priority |
| `Delete` | Remove the selected queued track |
| `F2` | Open Settings |
| `F3` | Preview and select a theme |
| `q` | Quit and stop playback |

In Recently Played, Enter plays the selected track now, Home places it next, `a` appends it
to Queue, Delete removes one entry, `c` clears all history after confirmation, and Escape
returns to the exact prior Results view.

In Playlists, `c` creates, `r` renames, Delete removes with confirmation, and Enter opens a
playlist. Inside one, Enter plays now, Home plays next, `a` appends to Queue,
`e` confirms and appends the entire playlist, Shift+Up/Down reorders, Delete removes a
track, and Escape returns to the playlist list.

Availability symbols are consistent across Queue, Recently Played, and opened playlists:
`✓` is available offline, `↓` is downloading, and `↗` will stream.

In Offline media, `◆` is explicitly retained and `○` is an automatic cache entry eligible
for size-based eviction. `/` focuses a title filter that works entirely from the local cache.
Enter plays now, Home plays next, `a` appends to Queue, `s` saves to a named playlist, `k`
switches between retained and bounded cache, Delete removes the managed media file after
confirmation, and Escape restores the prior Results view. Older cached entries show an
unknown duration until first playback; mpv then discovers and saves it locally.

Left and Right page through a long selected title. Leaving that row restores its title to
the beginning. Playback seeking deliberately uses `[` and `]`, so arrow keys remain safe
for tables and text fields.

### Command mode and sleep timers

Press `:` while Results or Queue is focused, type a command, and press Enter. Escape closes
the command field without running anything. Search continues to accept `:` as ordinary text.

| Command | Action |
| --- | --- |
| `sleep 30` | Pause playback in 30 minutes |
| `sleep 1h 20m` | Pause after a combined duration |
| `sleep 1:30` | Pause in 1 hour 30 minutes |
| `sleep at 23:30` | Pause at the next occurrence of that local time |
| `sleep track` | Finish the current track, then hold Queue playback |
| `sleep` | Show the active timer |
| `sleep cancel` | Cancel the active timer |
| `library`, `history`, `playlists` | Open that view |
| `settings`, `theme` | Open that screen |
| `help`, `quit` | Show command help or quit auen |

An active timer appears beside Now Playing. Duration timers pause the current track in place;
Space resumes it. After-track timers preserve the remaining Queue, and Space starts its next
track. Sleep timers intentionally do not survive quitting and restarting auen.

Some terminals disagree with Textual about the rendered width of shaped Indic scripts,
which can corrupt adjacent columns. auen transliterates only those script runs in table and
Now Playing display text; the original Unicode title remains unchanged in searches, saved
state, playlists, and playback metadata.

## Settings from the terminal

```console
auen config list
auen config get cache.max_size
auen config set cache.max_size 1.5GB
auen config set session.mode stream_and_cache
auen config set history.limit 500
auen config reset playback.volume
```

Preferences are stored in the platform configuration directory. Queue and recovery data
use a separate transactional SQLite database. Run `auen doctor` whenever installation or
backend setup is unclear.

## Develop and build

```console
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
make check
make build
```

`make check` runs the test suite with a safety timeout, linting, and strict type checking.
`make build` creates a wheel and source archive in `dist/`. The product baseline and
future requirements are in [`docs/requirements.md`](docs/requirements.md).

## License

auen is available under the [MIT License](LICENSE).
