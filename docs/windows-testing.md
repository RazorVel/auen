# Windows validation checklist

Release target: `1.2.0`. Earlier v1.1.0 native Windows Python tests under Wine cover the Win32 named-pipe
exchange, read timeout, remote authentication, ownership lock, and immediate restart.
Navigation and playback have been confirmed in Windows Terminal after installing mpv.
The user also completed an overall functionality regression check and reported no errors.
Use the checklist below for future release and regression validation.

## Install

1. Use Windows 10/11 and a VT-capable terminal. For media controls, use the tested CPython 3.14
   setup in the [README](../README.md#install-on-windows); current WinRT wheels exclude 3.15.
2. Install a Windows mpv build and add its directory to `PATH`.
3. Confirm `mpv --version` works in the same terminal that will launch auen.
4. Install the wheel with `[windows]` into a Python-3.14-pinned pipx environment as documented.
   Close/reopen Windows Terminal and check `where.exe auen` to avoid an older launcher.
5. Run `auen --version`; expect `auen 1.2.0`.
6. Run `auen doctor`; confirm Python 3.14, mpv, and Windows media-control dependencies `[ok]`.
   Android notification support is optional. Doctor does not test native activation/routing.

## Playback and remote control

1. Search and play a track; confirm audible output and a moving progress display.
2. Space pauses/resumes, `[` and `]` seek, `g` jumps, and `n` advances through Queue.
3. Save Settings with no changes, then change Volume; playback should continue.
4. From a second terminal, run `auen remote status`, `toggle`, and `next`.
5. Run `auen remote stop`; auen should exit and audio should stop without an extra console window.
6. Restart and confirm remote control works again.
7. Test cached playback with networking disabled and confirm no YouTube lookup is needed.

## Network-failure recovery (v1.2.0 hardening)

Use a naturally occurring failure or disconnect networking; do not repeatedly request a
YouTube-blocked video to manufacture a block. Automated tests simulate stalled requests.

1. Queue several tracks. If playback fails, the failed track and remaining Queue should stay
   intact, with a Playback held notice; no chain of automatic skips or retries should occur.
2. Restore the connection/VPN and press Space to retry. A genuine YouTube cooldown still
   applies until its countdown expires; network restoration does not bypass access blocks.
3. Alternatively, press `n` to skip the failed track, or select a cached track in Queue and
   press Enter. Offline playback must not wait for YouTube access.
4. Quit during a stalled search, stream preparation, or download. Audio should stop and the
   shell should return promptly rather than waiting for network retries. Restart and check
   that the interrupted track and remaining Queue survived without duplicate recovery entries.

On 2026-10-16 the user reported passing all four requested Windows recovery checks with
the rebuilt v1.2.0 wheel: Queue stays intact on failure, Space retries after connectivity
returns, Enter plays a cached Queue track while network playback is unavailable, and quit
during a stalled request returns promptly with Queue preserved after restart. These are
user-reported device results, separate from the automated process-lifecycle simulations.

## UI and persistence

1. Test Results, Queue, History (`h`), Playlists (`p`), and Offline (`l`).
2. Resize narrow/wide; verify the stacked layout, titles, metadata, and pane boundaries.
3. Check long titles, emoji, Arabic, and Indic text, plus Left/Right traversal.
4. Test Settings (F2), Theme Preview (F3), and `:sleep 5s`.
5. Quit and restart; Queue, History, playlists, settings, and cached media must remain intact.

## Playlist transfer

1. Select a named playlist and press `x`. Choose Selected, then export to a path containing spaces.
2. Export to the same path again; the existing file must be preserved with a readable notice.
3. Import with `i`, then Escape; nothing should change.
4. Import the exported file under its existing name; identical track sources should be skipped.
5. Import a file with one existing and one new source: the new one should append, with no suffix.
6. Verify `youtu.be` and `youtube.com/watch?v=` links to the same video are deduplicated.
7. Use `auen playlist import <path> --name <new-name>`; saved order and duplicates should survive.
8. Try malformed JSON; existing playlists should remain unchanged.
9. Restart; imported tracks and playlist ordering should persist.
10. Verify import/export works with networking disabled. Export does not include audio files.
11. Export again with All playlists selected. Import that file and confirm every playlist is
    restored or merged by name, with matching track sources skipped per playlist.

Record the Windows build, Python and mpv versions, terminal used, and any traceback when
reporting a failure.

## Media-control acceptance

The earlier baseline checks were reported for v1.1.0. Version 1.2.0 adds optional Windows
SMTC integration through the `[windows]` extra. Installation,
limitations, and the media-key/headset checklist are in
[media-controls.md](media-controls.md#windows-desktop-media-controls).
The user separately confirmed core Windows 11 SMTC behavior on CPython 3.14/dev6: card title/
progress, minimized keyboard/headset Play/Pause/Next/Previous, paused Next, Previous semantics,
Queue/History updates and clean quit/restart. Seek has no exposed slider; hardware Stop has
not been confirmed. The user also confirmed plain `auen` launch after the Python-3.14-pinned
pipx setup. These are user-reported device tests of the dev6 code, not agent-side Windows
hardware tests. The final 1.2.0 package still needs its short install/version/play/quit smoke
check; do not infer it from the older v1.1.0 report.
