# Playback and system media controls — v1.2.0

Previous, desktop media-key integration, and Termux headphone integration form one release.
Core routing was confirmed by the user on Linux, Windows 11/CPython 3.14, and Itel RS4/Android 13.
The Android companion remains the tested, optional `0.6.0-prototype` APK. Platform-dependent
limitations and unverified Windows seek/Stop behavior are recorded below.

## Shared playback actions implemented

- `b` or the **Prev b** playback button invokes Previous while a track is playing or paused.
- At or beyond three seconds, Previous restarts the current track. Before three seconds,
  it returns to the most recent successfully played track. Without a previous track it
  restarts the current track, even near the beginning.
- Navigation follows actual playback order under shuffle. It is separate from Recently
  Played and from the queue's repeat-cycle history. The last 100 steps are kept in memory
  for the current running session; this back stack is not restored on restart.
- Going back puts the interrupted track next in Queue, so Next can return to it. The rest
  of Queue is retained, including saved duplicates. A paused Previous stays paused.
- Explicit Play/Pause do not toggle the opposite state when repeated. Play also releases
  the queue held by an after-track sleep timer.
- Manual Next takes precedence over Repeat One; natural completion still repeats the track.
- Successful Previous cancels an after-track sleep timer, like Next. Timed sleep remains active.
- Failed preparation does not create a Previous target. Controls received during a track
  transition do not duplicate the navigation sequence.

The same actions are available from a second terminal:

```console
auen remote play
auen remote pause
auen remote previous
auen remote next
auen remote toggle
auen remote status
```

Existing `auen remote stop` behavior is unchanged: it exits auen and stops audio, as does
Android notification Stop. Linux/Windows native Stop instead retains the current track and
keeps auen open; Play restarts that track from its beginning.

Ordinary `b` inside Search stays text. The playback button uses ASCII on Termux and in the
narrow layout. These terminal bindings do not themselves capture system-wide keys.

## Linux, Windows and Android integration

All platform inputs must call auen's shared actions, not control the mpv subprocess directly.
Direct mpv control would bypass auen's Queue, sleep timers, History, and track transitions.
Integration must remain optional and non-fatal when a service or permission is unavailable.

- Linux: optional MPRIS service implemented. The user confirmed cached playback, minimized
  keyboard/headset controls, paused Next, non-quitting Stop/Play and clean shutdown after routing setup.
- Windows: optional System Media Transport Controls implemented. The user confirmed card
  title/progress, minimized keyboard/headset controls, paused Next, Previous, and restart.
  Seeking and hardware Stop remain physically unverified; see the checklist below.
- Android/Termux: the opt-in bridge and native companion prototype now provide a real
  MediaSession and authenticated loopback-only connection. Setup/build instructions and
  the physical-device checklist are in [the Android README](../android/README.md).
  The user confirmed actual TWS controls while minimized/locked and disconnect fallback.
  Artwork/automatic startup/idle were accepted in the second build, but headset and restart
  reconnect regressed on Android 13/Itel RS4. The third build addresses those paths, adds
  routing diagnostics and authenticated Android slider seeking. The user accepted reconnect,
  seeking, fallback and the instance guard, but headset routing remained unavailable. The fourth
  build fixes static-buffer initialization order, improves Play/Pause acknowledgement freshness,
  and reuses auen's logo. The user confirmed Routing running, locked headset controls, and
  notification feedback on that device. The sixth companion-only build retains smaller logo
  padding and centers the wordmark only on off-white fallback artwork; loaded thumbnails have
  no wordmark or badge.
  No network-facing endpoint,
  shell access, or direct mpv IPC is exposed by the companion.

Auen remains usable without the APK. When the setting is enabled but no companion connects,
it warns that headphone controls are unavailable. Disconnect does not pause/stop audio;
the existing Android notification returns when enabled. The native Stop action intentionally
keeps the existing remote/notification semantics: quit auen and stop audio. Disconnect is
separate and affects only the companion. No independent Previous-only release is planned.

### Linux desktop media controls

Download the v1.2.0 wheel from GitHub Releases and install its optional pure-Python dependency:

```console
pipx install --force '/absolute/path/to/auen-1.2.0-py3-none-any.whl[linux]'
auen doctor
```

For a checkout, use `.venv/bin/python -m pip install -e '.[linux]'`, then
`.venv/bin/python -m auen`. Omit the extra for ordinary terminal playback.

On ordinary Linux (not Termux), auen automatically registers `org.mpris.MediaPlayer2.auen`
on the current desktop session bus when the dependency is installed. No root, service
installation, global keyboard hook, or separate daemon is required by auen. Missing dependency,
unavailable bus, name conflict, or disconnection does not stop ordinary playback. `auen doctor`
reports dependency/address availability; it does not prove the bus or hardware routing works.

Supported: Play, Pause, Play/Pause, Next, Previous, non-quitting Stop, volume, title/duration,
public YouTube artwork URL, progress, relative seek, and track-checked absolute seek. Properties
update from auen's normal UI timer; readers do not independently query mpv. Next while paused
stays paused. Stop retains the interrupted track first in Queue; Play restarts it from the
beginning. After-track sleep is cancelled by Stop; timed sleep stays armed. Root `Quit` and
`auen remote stop` still exit auen. External arbitrary URL opening, TrackList, shuffle/repeat
editing, and variable playback speeds are not advertised by this prototype.

The service follows the [MPRIS interfaces](https://specifications.freedesktop.org/mpris/latest/)
using [dbus-next](https://python-dbus-next.readthedocs.io/en/latest/). Desktop panels can display
the player and route controls. Hardware routing is controlled by the desktop/WM/headset stack,
not guaranteed just by registering MPRIS. No existing desktop bindings are changed automatically.

If `playerctl` is installed, test from another terminal:

```console
playerctl --player=auen metadata title
playerctl --player=auen play-pause
playerctl --player=auen next
playerctl --player=auen previous
playerctl --player=auen position 20
playerctl --player=auen stop
playerctl --player=auen play
```

Without playerctl, an available `gdbus` can test Play/Pause directly:

```console
gdbus call --session --dest org.mpris.MediaPlayer2.auen \
  --object-path /org/mpris/MediaPlayer2 --method org.mpris.MediaPlayer2.Player.PlayPause
```

i3 needs media-key routing bindings. The user prefers universal controls rather than auen-only
bindings. If desired, add these after installing playerctl, checking for existing bindings first.
`playerctld` selects by last activity; without it playerctl chooses the first player found.
[Playerctl selection documentation](https://github.com/altdesktop/playerctl#selecting-players-to-control).

```i3
exec --no-startup-id playerctld daemon
bindsym XF86AudioPlay exec --no-startup-id playerctl play-pause
bindsym XF86AudioPause exec --no-startup-id playerctl pause
bindsym XF86AudioNext exec --no-startup-id playerctl next
bindsym XF86AudioPrev exec --no-startup-id playerctl previous
bindsym XF86AudioStop exec --no-startup-id playerctl stop
```

Manual acceptance (user passed on Linux): play a cached/local track with another queued; minimize the
terminal and test physical keyboard Play/Pause, Next, Previous and any headset gestures.
Confirm Queue/History update, paused Next remains paused, Stop leaves the TUI open, Play
restarts the retained track, and quitting removes the player. Test seek from the desktop
controller and retain normal sleep/notification behavior. Tests use a private session bus and
silent native mpv; actual keyboard/headset routing was separately confirmed by the user.

### Windows desktop media controls

Use v1.2.0 on Windows 10/11 with CPython 3.10–3.14 and mpv in PATH. CPython 3.14 was tested;
open a terminal in the folder containing the wheel and run:

```powershell
py -3.14 -m pip install --force-reinstall ".\auen-1.2.0-py3-none-any.whl[windows]"
py -3.14 -m auen --version
py -3.14 -m auen doctor
py -3.14 -m auen
```

If Python 3.14 is absent, the Python Install Manager supports `py install 3.14`; otherwise
install a supported CPython alongside your existing Python. Current WinRT wheels do not cover
Python 3.15. An existing plain `auen` command may still launch the older Python installation.

For normal `auen` launch through an isolated Python-3.14-pinned pipx environment:

```powershell
py -3.14 -m pip install --user --upgrade pipx
py -3.14 -m pipx install --force --python 3.14 ".\auen-1.2.0-py3-none-any.whl[windows]"
py -3.14 -m pipx ensurepath --prepend --force
```

This changes your user PATH so pipx's commands take precedence. Fully close Windows Terminal
and reopen it, then run `where.exe auen`, `auen --version`, and `auen doctor`. Confirm 1.2.0,
Python 3.14 and Windows media dependencies available before using plain `auen`. If it still
resolves to 3.15, inspect the command paths first rather than uninstalling unrelated Python apps.
An existing pipx auen environment tied to another Python may need
`py -3.14 -m pipx reinstall auen --python 3.14`, followed by the same validation.
[pipx interpreter and PATH options](https://github.com/pypa/pipx/blob/main/src/pipx/main.py).
The `windows` extra installs the small prebuilt PyWinRT Foundation, Media, Media.Interop and
Storage.Streams projections (and their runtime). No SDK, APK, separate companion, or administrator
rights are required. Unsupported Python/platform combinations may lack a prebuilt WinRT wheel;
use supported CPython, or omit the extra to retain ordinary auen playback.

Windows starts the adapter automatically outside headless tests. A private invisible top-level
window belongs to auen, not Windows Terminal/conhost; SMTC requires a window owned by the caller.
[Microsoft desktop interop contract](https://learn.microsoft.com/en-us/windows/win32/api/systemmediatransportcontrolsinterop/nf-systemmediatransportcontrolsinterop-isystemmediatransportcontrolsinterop-getforwindow),
[PyWinRT interop](https://pywinrt.readthedocs.io/en/latest/api/windows/media/interop.html).
Its bounded message pump stays on the UI loop; native callbacks queue shared actions there.
No global keyboard hooks, terminal key remapping or second audio player are created.
On Windows, mpv's direct media-key handling is disabled. Newer mpv builds also have their own
SMTC session disabled, after a cached two-second-bounded option probe; unsupported flags are
not passed to older builds. A failed probe leaves ordinary playback usable, but if duplicate
media cards appear, report the mpv version and retry with a current build.
[mpv media-control options](https://mpv.io/manual/stable/#options-media-controls).

The card publishes title, public YouTube thumbnail where available, playback state and timeline.
Play/Pause, Next, Previous, non-quitting Stop and track-checked seek call the same auen actions
as Linux. Next while paused stays paused. Stop retains the interrupted track first; Play
restarts it. Windows decides which media session and UI layout receive hardware input; gestures
depend on the headset/driver. Timeline is refreshed on state changes, seeks and about every
five seconds while playing. There is no independent volume/shuffle/repeat control in this
Windows prototype. [Microsoft manual SMTC integration](https://learn.microsoft.com/en-us/windows/apps/develop/media-playback/system-media-transport-controls).

Missing dependencies, native startup failure or a later native error warn without stopping
ordinary playback. Shutdown removes native handlers, disables the media session and destroys
the private window. Already queued callbacks are ignored after close; seek callbacks queued
for a previous track cannot seek a replacement. `doctor` checks package installation, not live
Windows activation or physical routing.

User checklist (core passed on Windows 11, CPython 3.14):

1. Confirm `auen 1.2.0`; doctor should report Windows media-control dependencies available.
2. Queue at least three cached/local tracks. Start playback and minimize Windows Terminal.
3. Test keyboard media keys and headset Play/Pause, Next and Previous; Queue/History should
   still update. Compare the Windows media-card buttons with physical buttons if either fails.
4. Pause, then Next: the next track should remain paused. Previous after three seconds restarts
   the track; near its start it returns to the prior successful track.
5. If the Windows card exposes a seek slider, seek while playing and paused. Position should
   update, and a paused seek should remain paused. Some Windows layouts do not expose a slider.
6. If hardware/UI provides Stop, confirm auen stays open and Play restarts the retained track.
   `auen remote stop` remains Quit, not this non-quitting action.
7. Quit during playback. Audio should stop, the card should disappear/become inactive, and
   restarting should give working controls without an extra visible window.
8. Check ordinary terminal playback, sleep, Queue, Offline and clean shutdown for regressions.

The user confirmed native activation/card title/progress, minimized keyboard/headset controls,
Queue/History updates, paused Next, Previous semantics, cleanup and restart. No slider was
exposed, so seeking remains physically unverified. The response for Stop referred to the
missing slider, so hardware Stop is also still unverified; it is not recorded as passed.
The user also confirmed plain `auen` launcher operation after the pipx setup above.
Host tests use controlled WinRT/Win32 substitutes
plus Linux's real private bus and silent mpv; physical results above are user-reported.

### Android feasibility findings

Android routes hardware media buttons through a MediaSession; terminal characters alone
cannot provide reliable background headphone control.
[Android media-button documentation](https://developer.android.com/media/legacy/media-buttons).

Termux:API's current media-style notification builds actions but does not attach a session
token. Merely switching `termux-notification` to `--type media` is insufficient.
[Termux:API notification source](https://github.com/termux/termux-api/blob/master/app/src/main/java/com/termux/api/apis/NotificationAPI.java).

The separate mpvbridge project reports a cross-UID routing issue: Termux produces the audio
while the companion owns the session. It uses a looping silent AudioTrack in the companion
to make Android select that session. This is evidence for a prototype, not proof for auen
or every Android device, and its battery/audio-focus impact needs testing.
[mpvbridge's explanation](https://github.com/kpg-anon/mpvbridge#why-this-exists).

Do not install or attach that third-party bridge to auen's mpv as a shortcut: its direct-mpv
controls do not implement auen's navigation semantics. Auen's native prototype is built from
the source in `android/`, without third-party runtime libraries. The user authorized an
isolated SDK/JDK/Gradle build under `/tmp`; no system packages or phone apps were installed.
The first APK passed compilation/host checks and the user's core phone/headset tests. Broader
manufacturer, call/audio-focus and battery-limit behavior remains device-dependent.

## Focused manual check: first stage

Run the working tree with `.venv/bin/python -m auen`.

1. Queue three tracks and play the first. Use `b` after five seconds: the same track restarts.
2. Press `n`, then quickly `b`: the first track returns and the interrupted second track
   is next in Queue. Press `n` again to return to it.
3. Repeat with Shuffle on: Previous follows actual playback order, not a random choice.
4. Pause the second track near its start and use Previous: the previous track remains paused.
5. Try Repeat One: natural completion repeats; manual Next advances to a waiting track.
6. Arm `sleep track`, then use Previous: the after-track timer is cancelled. A timed timer
   such as `sleep 5m` must remain active instead.
7. From a second terminal run the explicit remote Play/Pause commands twice each: repeated
   Play stays playing and repeated Pause stays paused. Test remote Previous too.
8. Type `b` in Search, resize narrow/wide, and check all six playback buttons remain contained.
9. Check ordinary Queue, History, playlist, seeking, notification, and quit behavior.

The user confirmed the four core Previous/shuffle/pause/layout checks and remote Previous/Next.
This first-stage checklist does not validate TWS/headset support; use the Android checklist
for that prototype.
