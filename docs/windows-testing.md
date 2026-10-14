# Windows validation checklist

Version: `1.1.0`. Native Windows Python tests under Wine cover the Win32 named-pipe
exchange, read timeout, remote authentication, ownership lock, and immediate restart.
Navigation and playback have been confirmed in Windows Terminal after installing mpv.
The user also completed an overall functionality regression check and reported no errors.
Use the checklist below for future release and regression validation.

## Install

1. Use Windows 10/11, Python 3.10 or newer, and Windows Terminal or another VT-capable terminal.
2. Install a Windows mpv build and add its directory to `PATH`.
3. Confirm `mpv --version` works in the same terminal that will launch auen.
4. Install the wheel: `py -m pip install --force-reinstall <wheel-path>`.
5. Run `auen --version`; expect `auen 1.1.0`.
6. Run `auen doctor`; required checks should be `[ok]`. Android notification support is optional.

## Playback and remote control

1. Search and play a track; confirm audible output and a moving progress display.
2. Space pauses/resumes, `[` and `]` seek, `g` jumps, and `n` advances through Queue.
3. Save Settings with no changes, then change Volume; playback should continue.
4. From a second terminal, run `auen remote status`, `toggle`, and `next`.
5. Run `auen remote stop`; auen should exit and audio should stop without an extra console window.
6. Restart and confirm remote control works again.
7. Test cached playback with networking disabled and confirm no YouTube lookup is needed.

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
