# auen product requirements

This document is the recovered product baseline for the rewrite of the legacy
`audio-engine` script. The legacy script is behavioral reference material, not an
implementation to preserve.

## Product

auen is a full-screen, keyboard-first Textual audio player. Its interface should work in
Unix terminals. The current prototype supports playback through `mpv` on Linux and
Android/Termux. Playback backends advertise capabilities so additional platforms can be
introduced without changing the queue, media, persistence, or UI layers.

## Media sources

- Search YouTube and show selectable results.
- Accept YouTube URLs directly.
- Play supported local audio files.
- Import directories recursively by default, ignoring hidden directories and avoiding
  symbolic-link cycles.
- Initially recognize MP3, FLAC, Ogg/Opus, M4A/AAC, WAV, and WebM audio containers.
- Sort imported directory contents naturally and report skipped files non-intrusively.

Supporting arbitrary non-YouTube remote URLs is outside the initial scope.

## Playback and queue

- Provide play, pause, resume, next, previous, seek when supported, and volume control.
- Maintain a reorderable queue and playback history.
- Keep Queue compact as `# | Title | Time | S`; status values use `↗` for stream,
  `↓` for an active download, `✓` for offline-ready, and `!` for a failed item.
  Enter plays the selected row now, Home promotes it to play next without interruption,
  and Shift+Up/Down adjusts its priority one position.
- Support shuffle and three repeat modes: off, all, and one.
- Clearly disable or hide controls unsupported by the selected backend.
- Restore queue, history, current track, and playback position after restart or crash.

## Streaming and offline playback

At session start, ask whether to use:

1. **Stream only** — do not retain persistent remote media.
2. **Stream and cache** — begin playback as quickly as the backend permits and retain a
   managed copy for offline use.

The automatic playback cache persists between sessions and defaults to a 1 GiB limit.
Least-recently-used, unpinned items may be evicted. Tracks explicitly saved to the offline
library are pinned and must never be automatically removed. Users can inspect storage,
pin cached tracks, and remove offline tracks explicitly.

## Persistence

- Store human-editable preferences in an XDG-compatible TOML file.
- Store changing session, queue, history, download, and cache metadata transactionally in
  SQLite.
- Never require a clean shutdown for recovery data to be useful.
- Offer recovery of interrupted playback without beginning audio unexpectedly.

## Configuration

All meaningful behavioral settings must be available in a keyboard-friendly Textual
Settings screen and through scriptable `auen config` commands. Initial settings include:

- Backend selection and backend diagnostics
- Per-session streaming/cache behavior
- Cache location and size limit
- Download concurrency
- Load-more batch size (initial results adapt to the visible pane)
- Recursive directory scanning
- Default volume, shuffle, and repeat behavior
- Session restoration
- Notifications and key bindings as those features are introduced

Changes apply immediately when safe; settings requiring restart must say so.

## Installation and diagnostics

- Publish a standard Python wheel and source archive.
- Support isolated installation through `pipx` and regular virtual environments.
- Expose both `auen` and `python -m auen` entry points.
- Provide `auen doctor` for backend, dependency, configuration, and storage diagnostics.
- Keep build, test, lint, and type-check commands documented and reproducible.

## Reliability and safety

- Bound background concurrency; do not create one unbounded thread per item.
- Bound IPC reads by time and response size.
- Give subprocesses clear ownership, cancellation, and cleanup behavior.
- Make downloader and playback errors visible without crashing the interface.
- Tests must use finite mocks and enforce timeouts so a broken IPC peer cannot consume
  unbounded CPU or memory.
- Keep cache eviction separate from explicit offline-library deletion.

## Initial interface

The main screen contains a search/URL field, selectable result list, queue, and persistent
now-playing area. It exposes search, queueing, play-next, download/pin, shuffle, repeat,
progress, download state, and help through discoverable keyboard actions. `F2` opens
Settings. Offline mode should remain useful when the network is unavailable.

## Interaction and responsive UX

- A successful search moves focus to its results so Up, Down, and Enter work without an
  extra navigation step. Search loading and empty states remain visible.
- Escape from the search field cancels the active UI search when possible and returns
  focus to results, or to the queue when no results exist. A bounded extractor already in
  progress may finish silently; cancellation must not create another worker.
- On the main screen, Tab and Shift+Tab alternate only between the active left workspace
  table and Queue. Search is entered with `/` or a click/tap and left with Escape.
- Results, Downloads/Offline Library, History, and Playlists share the left workspace;
  switching views never hides Queue or the playback controls.
- A compact download-status strip reports active, queued, completed, and failed work.
  Activating it, or using the Library shortcut, opens download management and pinned
  offline tracks in the left workspace.
- The first search page adapts to the visible result-pane capacity while respecting a
  safe upper bound. Reaching the end offers an explicit confirmation to load the next
  page; additional results are never fetched merely because the cursor moved.
- Search may return tracks, albums, and playlists. `♪`, `◉`, and `≡` identify them
  respectively; only metadata-confirmed albums use the album symbol. Activating a
  collection explicitly loads a bounded track list, and Escape returns to search results.
- Search titles are ellipsized to preserve the duration column. Highlighting a result
  exposes its full title and source without requiring a wide terminal.
- Table clipping and ellipsizing use terminal display-cell width so wide characters,
  combining marks, and right-to-left scripts cannot paint beyond pane boundaries.
- Directional isolation keeps right-to-left titles from reordering duration or status
  columns. Leaving a table resets any paged title to its leftmost segment.
- Title cells retain a one-cell gutter so terminal-specific emoji and variation-selector
  widths cannot push adjacent metadata columns out of alignment.
- Table widths refresh from each pane's final viewport size after every terminal resize;
  repeated shrinking and expansion must never leave columns one resize behind.
- `Ctrl+A` selects all text in editable fields. Widget navigation keys must not silently
  conflict with playback controls.
- Seeking has visible, focusable controls in addition to shortcuts. Left and Right remain
  available to text fields and tables; playback uses unambiguous shortcuts and buttons.
- A dedicated theme picker previews each highlighted theme. Enter persists the theme;
  Escape restores the theme active when the picker opened.
- The main navigation exposes Queue, recently played History, Offline Library, and named
  Playlists as first-class destinations rather than hidden commands.
- The Offline Library lists pinned, locally playable tracks and supports play, queue,
  unpin, and explicit deletion with confirmation.
- Named playlists are durable ordered collections distinct from the transient playback
  queue. Tracks can be added from search, history, or the offline library.
- A `:` command entry inside the TUI provides keyboard-compatible forms of the legacy
  workflow, including search, URL, local file/directory import, play, pause, next, seek,
  queue, history, library, playlist, shuffle, repeat, theme, settings, help, and quit.
- A pure prompt-oriented entry point may reuse the same command dispatcher; commands must
  call session services rather than duplicate playback or persistence logic.
- Layout responds to terminal cell dimensions. Wide terminals may show results and queue
  together; narrow terminals use one pane at a time with compact focusable controls and
  reduced columns. The application does not change terminal font size or zoom, which are
  controlled by the terminal emulator.
- Responsive behavior is tested at desktop and phone-sized terminal dimensions. Unicode
  decoration must have a plain-text fallback or remain understandable when a glyph is
  unavailable.
