# auen Android media-control companion (prototype)

This optional native app forwards TWS/headphone and Android media-session actions to the
auen player already running in Termux. It does not replace auen or mpv and never executes
shell commands. Android 8.0/API 26 or newer is required. Physical device/headset validation
passed on Itel RS4/Android 13: locked headset controls, notification feedback, automatic
connection, reconnect, idle readiness, slider seeking, artwork, and disconnect fallback.
The final artwork/padding was also accepted. Other devices and call/audio-focus behavior
remain unverified. Python auen **1.2.0** ships alongside the unchanged, tested companion
**0.6.0-prototype**; their version numbers are independent. The companion remains optional.

## Install and pair

1. Install mpv in Termux (`pkg install mpv ffmpeg python`), then install the auen wheel:

   ```console
   python -m pip install --upgrade ~/downloads/auen-1.2.0-py3-none-any.whl
   auen --version
   ```

2. Transfer and install the companion APK. It appears as **auen media controls**. This is a
   locally debug-signed test APK, not a production release. Android may ask you to allow
   installation from the file manager/browser used to open it.
   Use `auen-media-controls-0.6.0-prototype.apk` from the v1.2.0 release. If that exact APK is
   already installed, no APK update is needed. Python dependencies install normally; do not
   use `--no-deps` on a fresh installation.
3. Launch auen, open F2, enable **Android headphone controls (APK)**, and save. The feature is
   off by default. Missing/unpaired companions produce a warning, not a playback failure.
4. The companion should open briefly, connect automatically, and return to Termux. No Connect
   tap is needed. Grant Android's first-run notification permission if prompted. It remains
   connected even before a track plays or when Queue is empty. If automatic startup is blocked,
   keep Termux visible and, from a second session, run:

   ```console
   auen media connect
   ```

   This opens the companion and connects without a button press. If Android cannot open it,
   install `termux-am` or use the manual
   method: run `auen media pair`, copy the entire connection code, open the app, paste, and
   tap Connect. The input is masked and credentials are never printed by `media connect`.
5. Play a track with another waiting in Queue. Check the app/notification title and the
   Previous, Play/Pause, and Next controls. Then test the actual headset with Termux minimized
   and the phone locked. Earbud gestures are determined by the headset/OS, not by auen.
6. Restarting auen rotates the port/token and performs a fresh automatic handoff. A background
   worker retries quietly after 5, 10, 20, then every 30 seconds; retries never open the app's
   screen. The companion also retries transient socket failures, backing off to 30 seconds.
   **Disconnect** suspends automatic retries for this auen run. Tap Connect or run
   `auen media connect` to resume manually; a new auen run reconnects automatically.

The `0.6.0-prototype` APK uses the same signing key as `0.2.0`–`0.5.0-prototype` and can update
them normally. The original `0.1.0-prototype` key was lost with the old temporary toolchain; updating
from that first build requires uninstalling **only the companion**. This resets companion
preferences, not auen's Queue, playlists, library, or settings.
Keep your signing key outside Git for future compatible updates; `/tmp` is not durable storage.
The temporary build toolchain/key used for this tested APK is no longer available. This
release retains the existing binary rather than generating a different signature. A future
APK update requires recovery of that key or a documented companion-only uninstall/reinstall;
a rebuild with a new key cannot update the installed APK in place.

SHA-256 of the retained APK:
`9fba484424bba65d7d8641710e0082ddf4880a067790f5245774b93b6a003a74`.
Do not mistake this APK checksum for its signing certificate fingerprint.

File types: `.whl` is an already-built Python package; `.tar.gz` is the matching Python source
distribution, which pip builds before installing. Either can install auen; the wheel skips the
build step. `.apk` installs the separate Android companion, not the Python player. Installing
the source distribution does not automatically build or install the companion APK.

The connection code is a private credential for the current player. Do not post it, put it
in screenshots/logs, or share it. Connections are always to `127.0.0.1`, require a random
256-bit token, and allow only the fixed media actions. No remote shell or mpv IPC is exposed.
The companion stores the code in its private preferences, excluding it from backup and
device-transfer rules. Disconnect keeps that private code to recognize and ignore retries
from the suspended run. A new run replaces it; uninstalling the companion removes it.

Reconnect uses a fresh connection generation and immediately resets any old retry delay.
Replies/failures from an older generation are ignored. The companion screen is single-instance
and refreshes stored pairing details instead of letting a stale screen replace a new connection.
Shutdown requests are scoped to their old credentials, not an unconditional stop of a new session.

## Android progress seeking and diagnostics

For a ready track with a known duration and seek support, Android's MediaSession advertises
seeking and forwards its slider to auen. Drag (or tap, where supported) the expanded Android
notification/lock-screen progress line. Android decides whether a given media-card layout
offers dragging, tapping, or a read-only line; auen cannot replace that system widget. There
is no change to the terminal's progress bar. Seeking preserves paused playback. Each request
contains a track identity, so a late slider event cannot seek a different track after Next.
Requests are authenticated, finite/bounded, and clamped to the current track duration; no raw
mpv or shell command is accepted. See [Android's seek callback](https://developer.android.com/reference/android/media/session/MediaSession.Callback#onSeekTo(long)).

The companion shows **Routing**, **Last input**, and **Last reply**, with no private pairing
code in those diagnostics. If headphone controls do not work, note these values immediately
after pressing a button and compare with the on-screen Android buttons. `running` means the
silent AudioTrack is playing; `none since connection` means no supported input was received.
An unavailable helper now includes a safe setup-stage reason (creation, write, loop, mute, start)
instead of hiding all failures behind one generic message. Successful status polling changes
the initial Last reply from `connecting` to `status received`.
A bridge permission-denied message may indicate a phone VPN/firewall policy. Never share the
masked connection code. Session activation follows actual playback/paused/buffering state;
the underlying connection still stays ready while idle. Android may hide the idle media card.

## Thumbnail artwork

YouTube tracks publish their public video thumbnail to the MediaSession and notification.
Artwork is loaded on a separate worker: it cannot delay Pause, Next, or status polling. There
are no extra yt-dlp extraction/login requests. Only fixed HTTPS `i.ytimg.com/vi/<id>/hqdefault.jpg`
URLs are allowed; no cookies or connection credentials are sent. Redirects are rejected,
downloads are limited to 1 MiB, decoded pictures to 512 pixels per side, and the private
least-recently-used disk cache to 8 MiB. Fetching artwork makes an ordinary request to
YouTube's image CDN, even for a cached audio track if its picture has not been cached yet.
Previously cached pictures can appear offline. Missing artwork/local tracks use a warm off-white tile;
an artwork failure never interrupts audio. Failed artwork retries at most once a minute for
the currently selected track. Android decides how much artwork its notification layout shows.

## Optional/fallback behavior

- Auen works without the APK. All ordinary TUI playback and remote commands remain available.
- If controls are enabled but the companion is absent or disconnected, auen warns that
  headphone controls are unavailable; it does not stop audio or throw a traceback.
- The existing Termux:API notification is suppressed only while a companion heartbeat is
  active. It returns after disconnect if **Android playback notification** is enabled.
- **Disconnect companion** stops only the companion/session/silent helper, not auen playback.
- A native hardware **Stop** uses the existing `auen remote stop` behavior: it quits auen and
  stops audio. Notification Disconnect is deliberately different from Stop.
- Missing permissions or a failed silent helper do not change the mpv playback backend.
- Normal auen quit/disable sends an authenticated asynchronous shutdown, removing the native
  card without waiting for Android before stopping audio. After a process kill or phone-side
  delivery failure, the card may remain waiting; Disconnect stops it manually.

Android can deny background service/activity starts or prevent a force-stopped app from
restarting. Quiet retries do not bypass those rules. Open the companion/run `auen media connect`
when Android requires a visible user action. Manufacturer battery limits may also need manual
adjustment. See [Android's foreground-service start restrictions](https://developer.android.com/develop/background-work/services/fgs/restrictions-bg-start).

## Why there is a silent helper

Termux owns the actual audio while the companion owns the MediaSession. Android can fail to
route headset events to that separate app. The optional helper loops a one-second zero-volume
AudioTrack while playing/paused, to make the companion eligible for that routing. It does not
play the song, request audio focus, read the microphone, or keep a wake lock. It is off when
there is no active playback state or the companion disconnects. It may increase battery use;
turning its checkbox off may leave only notification/lock-screen buttons working.

The static buffer must receive silence before it reaches `STATE_INITIALIZED`: its initial
`STATE_NO_STATIC_DATA` is valid, not a creation failure. Earlier prototypes checked the ready
state too soon and short-circuited before writing data. The fourth build corrects this order;
host lifecycle tests model the initial state, failures/cleanup, repeated polls and recovery.
[Android AudioTrack state documentation](https://developer.android.com/reference/android/media/AudioTrack#STATE_NO_STATIC_DATA).

Play/Pause/Toggle now refresh auen's snapshot before acknowledging the command. The companion
applies that acknowledgement directly rather than polling an old snapshot immediately. Play
and Pause notification intents also have separate identities to avoid retargeting a still-visible
button as Android refreshes it. Device animation/touch delivery remains Android-controlled.

## Branding

Launcher and companion header reuse `docs/assets/logo-icon.png`, reduced in size with centered
padding. The notification uses `docs/assets/logo-wordmark.png`: a small white wordmark on a dark
rounded badge, centered only when no thumbnail is loaded. When a thumbnail is available, it is
center-cropped to a square without any wordmark or badge. The fallback background is warm off-white
(`#EAE7E2`), not gray. A charcoal badge keeps the white lettering readable on the fallback.

Both source bitmaps are unchanged. Gradle copies them into generated resources; there is no
second versioned bitmap. Composition happens in memory, on the existing artwork worker for
downloaded/cached thumbnails. The 8 MiB cache still stores original thumbnail bytes, not branded
copies. Adaptive/monochrome XML supports launcher shapes and Android 13 themed icons; the status
bar uses a padded monochrome wordmark. Build from the full repository or companion-source archive
so both referenced docs assets are available.

The badge is part of the image, not a custom Android media-card layout. System UI/OEM cropping
and rounded corners can alter the final presentation; verify placement on the target phone.

Do not assume call interruptions, audio-focus interactions, reconnects, battery restrictions,
and different manufacturers work until they have been tested on a physical device. Neither
root nor accessibility, storage, notification-listener, or Termux RUN_COMMAND permission is
required by this prototype. The normal INTERNET permission is needed for the local socket.

## Build from source (no bundled SDK/toolchain)

Use JDK 17 or newer (verified with JDK 21), Gradle **8.9**, and Android SDK platform **35**.
The project pins Android Gradle Plugin **8.7.3**. Install Android Build Tools **34.0.0**;
platform-tools are optional for APK inspection/adb. Get these from the official
[Android SDK tools](https://developer.android.com/studio#command-tools),
[Gradle distributions](https://gradle.org/releases/), and [JDK](https://adoptium.net/).
Accept the SDK license as part of your own SDK installation.

Point `JAVA_HOME` and `ANDROID_HOME` at those installed tools, then:

```console
cd android
gradle --no-daemon :app:assembleDebug :app:testDebugUnitTest :app:lintDebug
```

The APK is at `app/build/outputs/apk/debug/app-debug.apk`. To keep caches and generated output
outside the checkout, set `GRADLE_USER_HOME` to a temporary/cache directory and pass
`-PauenBuildRoot=/absolute/output/directory`. `ANDROID_USER_HOME` can isolate SDK preferences
and the debug signing key as well. A debug key is for testing only; sign a release separately
with a private key when publishing. No signing keys or credentials belong in Git.

Only source, small resources, and build definitions are versioned. `.gradle`, build folders,
APKs/AABs, local SDK configuration, and signing keys are ignored. Dependencies are fetched
at build time; there are no runtime AndroidX/third-party libraries in this app.

Lint reports one intentional `ExportedReceiver` warning: the retry receiver must be callable
by separately signed Termux, so it cannot require the companion's signature permission.
Instead it rejects every request unless both port and a constant-time-checked 256-bit private
pairing token match. It accepts only connect/shutdown, not arbitrary commands or addresses.
Host tests cover mismatched/malformed credentials. This is documented rather than suppressed.

## Physical-device acceptance

1. Without the APK: enable headphone controls, verify a warning, and confirm normal playback.
2. Start auen with the switch enabled: no Connect tap; check connected status while idle.
   A first-run Android notification permission prompt is expected, not bypassed.
3. Play two YouTube tracks: verify title, progress, thumbnail changes, and no stale image
   after rapidly skipping. Try cached artwork offline; missing artwork must not affect audio.
4. Test actual TWS/wired Play/Pause, Next, and Previous while locked/backgrounded.
   If controls disappear/fail, record Routing/Last input/Last reply and whether on-screen
   buttons still work. Do not assume host tests prove Android chooses this media session.
   While playing and paused, test the Android progress slider. Skip to another track and
   verify a delayed slider interaction cannot seek the wrong track.
5. Verify Previous's three-second rule, shuffle order, paused navigation, Queue, and History.
6. Empty Queue/stop playback: connection should remain ready, without the silent AudioTrack.
7. Disconnect: audio continues, retries stay suspended, and the legacy notification returns.
   Resume manually or restart auen: automatic connection should work again.
8. Temporarily interrupt the bridge connection: the service waits/retries rather than exiting.
   Force-stop may need a manual app launch because of Android restrictions.
9. Quit auen normally: audio, notifications, and the companion's media session should disappear.
10. Check calls, another media app, Bluetooth reconnect, keyboard resizing, sleep and battery limits.

Report Android version, phone/headset models, gesture mapping, and any failure. Never include
the pairing code in diagnostic screenshots.
