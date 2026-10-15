# v1.2.0 release preparation checkpoint

Updated: 2026-10-15 (Asia/Jakarta).

## Goal

Prepare the combined v1.2.0 release: Previous, shared explicit playback actions,
desktop media keys, and Termux headphone control. Refresh previews, installation steps,
and platform documentation. The user authorized the release commit and push on 2026-10-15.
Check GitHub's Linux/Windows CI afterward; tagging and publication are not authorized yet.

## Current release preparation

- User accepted the recommendation to retain the tested companion 0.6.0-prototype APK
  unchanged. Python version is now 1.2.0; the independent native version remains 0.6.0.
- Rechecked: `/tmp/auen-android-build.ypveNy` and its signing key are gone, as is the old
  Linux smoke environment. Do not silently create another key or repeat the SDK download.
  Future APK updates need key recovery or an explicitly documented companion-only migration.
  The tested APK still exists, with unchanged SHA-256
  `9fba484424bba65d7d8641710e0082ddf4880a067790f5245774b93b6a003a74`.
- README now documents release-wheel/source installation, Python-3.14-pinned Windows pipx
  with plain `auen`, Linux optional dependency/routing, and optional Termux companion/fallback.
  Platform/setup guides updated; Windows seek and hardware Stop remain unverified.
- User reports final v1.2.0 installed and shallow-tested successfully on all three platforms.
  This is a smoke-test report, not a new exhaustive hardware regression pass.
- Added two user-approved lossless screenshot crops to README: Android companion lock-screen
  media card and Termux:API fallback notification. Only these card pixels are saved in the
  repository; full screenshots, unrelated notifications, and pairing/setup screen are excluded.
  PNG metadata stripped; decoded pixels match the exact source rectangles. All eight README
  image links resolve and diff whitespace checks pass. Documentation-only wheel/source
  refreshed; runtime code and APK unchanged. Windows screenshot is not supplied or fabricated.
  User requested tighter straight-edged crops: removed 12 pixels per side from both cards,
  leaving 658x300 and 658x282 images without surrounding wallpaper. Card controls remain intact.
- Refreshed real-TUI previews include Previous and an after-track sleep indicator. Generator
  normalizes no-color environment and uses a readable stacked phone viewport. All five SVGs
  were byte-identical on regeneration. Browser overview/History/phone inspection completed;
  later browser recovery failed, so all final crops were also raster-inspected with a local
  monospace font. Cairo's bidi-isolate placeholder glyphs are renderer limitations, not a
  change to the SVG titles. User README/native-SVG review remains the final visual gate.
- Preview QA found Play/Pause clipped in narrow layouts. Increased its minimum width from
  12 to 14 and added a rendered-text assertion at 60 columns; focused layout checks passed.
- Full regression after that correction: 433 passed in 54.58 seconds. Ruff clean;
  strict mypy clean for Linux (30 files including generator) and Windows (29 package files).
  CI now includes Python 3.14 and installs Windows projection dependencies on Windows;
  that updated remote matrix has not been executed by this agent.
- Final wheel/source build passed. Fresh isolated normal-dependency installation, pip check,
  version/path verification, optional-independent Windows import, headless open/quit at
  60 columns passed. Added the linux extra and repeated smoke/pip check; a real gdbus
  PlayPause reached the installed adapter on a private bus, without touching desktop routing.
- Verification directory: `/tmp/auen-release-smoke.0jiTPj` (about 92 MiB, including an isolated
  renderer). Existing user auen/pipx installations were not changed. No SDK was downloaded.
- Release assets in `dist/`: `auen-1.2.0-py3-none-any.whl` (98,028 bytes),
  `auen-1.2.0.tar.gz`, retained `auen-media-controls-0.6.0-prototype.apk` (91,155 bytes),
  `auen-media-controls-0.6.0-prototype-source-v1.2.0.zip` (94,076 bytes), and
  `SHA256SUMS-v1.2.0.txt`. Only these current assets are intended for upload; older dev files
  remain untouched. Checksums are generated outside versioned source to avoid circular hashes.
  Wheel excludes native APK/binaries/keys; source archives include native code and both logos,
  but no APK/SDK/toolchain/signing key. The native ZIP contains refreshed setup instructions.
  The release commit/push is now authorized; GitHub CI is the next gate. No tag or publication
  is authorized. Release binaries/toolchains remain outside versioned source.
  Historical artifacts/toolchain/test records below describe earlier development stages.

## Known

- Published baseline: v1.1.0, local baseline commit f5319d6. User reported publication.
- The tree was clean when this batch began. All current modifications belong to this stage.
- Auen owns Queue and track transitions; mpv is only the audio backend. Platform control
  integrations must use auen's actions, not independently skip/reload mpv.
- Existing remote Stop and Android notification Stop exit auen. Desktop hardware Stop
  is separately implemented as non-quitting playback stop.
- Previous uses actual successful playback order, not the aggregated Recently Played list.
- Android notification buttons are not a MediaSession. Companion and audio run under separate
  Android UIDs, so reliable headset routing needs a physical-device prototype.
- The user approved an isolated Android toolchain under `/tmp`, asked for source/setup
  instructions plus an APK build and disk-usage report, and forbade large committed files.
  No system packages or phone apps were installed. Only source/resources/build definitions
  belong in Git; binaries, SDKs/caches, local configuration, and signing keys are ignored.
- The user additionally required ordinary auen playback without the companion, with a
  non-fatal warning when the optional hardware-control functionality is unavailable.

## Done

- Previous on `b`, a compact playback button, and `auen remote previous`.
- Three-second restart/back semantics; paused state preserved; interrupted track queued next;
  actual shuffle playback order followed. Navigation back stack is session-only, bounded at 100.
- Explicit `auen remote play` and `pause`, alongside existing toggle/next/stop/status.
  Play/Pause are idempotent, including requests received during preparation/Previous transitions.
- Queue navigation/priority entries take precedence over shuffle. Manual Next overrides
  Repeat One; natural completion still repeats normally.
- Previous cancels after-track sleep only after a successful action. Timed sleep is preserved.
- Focused tests cover queue preservation, multiple back/forward steps, pause, thresholds,
  failures, repeat, shuffle, rapid requests, empty playback, Search text, narrow controls,
  CLI, both remote transports, and real silent-output mpv IPC.
- Requirements updated; design, source links, and manual checklist in
  [media-controls.md](media-controls.md). Development version reached `1.2.0.dev6` during
  Windows acceptance; final version/docs/previews are recorded in the release section above.
- User confirmed Previous restart/back/forward, shuffle, paused state, narrow layout, ordinary
  playback, and remote Previous/Next. The platform was not specified in the latest report.
- Opt-in **Android headphone controls (APK)** setting, separate token-authenticated loopback
  server, cached metadata snapshots (polls do not call mpv/UI), and `auen media pair/connect`.
- Absent/disconnected companions warn without stopping playback. The legacy Termux:API
  notification is suppressed only while a heartbeat is active, and returns after disconnect.
- Native Java MediaSession companion under `android/`, with explicit pairing, metadata,
  Previous/Play/Pause/Next/Stop forwarding, optional silent routing, foreground lifecycle,
  strict credential/endpoint parsing, bounded I/O, and backup/device-transfer exclusions.
  Disconnect stops only the companion. Hardware Stop retains auen's existing exiting behavior.
- Build/setup instructions and physical-device checklist in [android/README.md](../android/README.md).
- User confirmed the first Android prototype: manual pair/connect, actual headset
  Play/Pause/Next/Previous while minimized/locked, and disconnect restoring legacy controls
  without interrupting audio. The user requested thumbnails and automatic persistent connection.
- New refinement: one automatic activity handoff per auen run (no Connect tap), then quiet
  authenticated receiver retries at 5/10/20/30-second intervals, capped at 30 seconds. No repeated
  window launches. Receiver validates current private token/port; manual Disconnect suspends
  retries for that run, while explicit Connect or a new run resumes. Existing manual pairing stays.
- Companion survives transient socket failures with backoff and remains connected/session-ready
  while idle; the silent AudioTrack still runs only for active/paused/buffering playback.
  Normal quit/disable sends asynchronous authenticated shutdown without holding audio cleanup.
  Android may block background/force-stop restarts; manual visible connection remains the fallback.
- Public YouTube thumbnails in native MediaSession/notification. Separate bounded artwork worker,
  latest-only pending work, stale-track guard, fixed HTTPS image URL allowlist, no redirects/cookies,
  1 MiB transfer limit, sampled <=512-pixel bitmap, 8 MiB LRU disk cache, 60-second failure retry.
  Local/unavailable art uses the app icon; cached pictures work offline. No extra yt-dlp requests.
- Second-build user results: automatic startup, thumbnails, and idle connection passed.
  Headset controls failed and lock-screen controls sometimes disappeared; restart/manual
  reconnect could hang. Device: Itel RS4, Android 13. Do not claim this regression is fixed
  on-device yet. Screenshot's yt-dlp API request failed with Errno 13 (network permission denied),
  not the usual bot/sign-in/rate-limit message. VPN/firewall policy is a possibility, not proven.
- Third-build changes: connection generations reset retry state immediately on fresh Connect;
  stale replies/failures cannot poison a new connection. A single-instance companion Activity
  refreshes saved pairing details; shutdown is credential-scoped and startId-scoped, rather
  than unconditionally stopping whichever service is now active.
- Restored the first device-verified active/idle MediaSession lifecycle while retaining the
  idle socket/service. Explicit media-key dispatch consumes key-up/held repeats safely. Silent
  AudioTrack checks its actual play state and recreates if Android stopped it. Companion now
  shows version, Routing, Last input, and Last reply (no raw exception/token leakage).
- Authenticated Android MediaSession slider seeking: capability/duration gating, onSeekTo,
  finite bounded position and hashed current-source identity, UI-thread stale-track recheck,
  duration clamp, shared auen seek action with paused state preserved. No CLI remote expansion.
  User clarified Android notification is the priority; terminal progress remains unchanged.
- One player per state directory, locked before session restore/backend startup; also detects
  older builds' live remote endpoint. A second terminal gets a readable refusal, not a second
  restored Queue/player. Remote/media CLI commands remain usable. Permission-denied extraction
  errors now identify a system/network-access problem rather than implying a YouTube IP block.
- Third-build user results: automatic startup, repeat restart/manual reconnect, Android slider,
  disconnect/fallback, and duplicate-instance refusal all passed. Headsets still failed:
  Routing unavailable, Last input none since connection, Last reply connecting. On-screen
  buttons worked but sometimes repeated the same visible action. User also requested existing
  auen logo integration in the companion, specifically docs/assets/logo-icon.png.
- Found concrete silent-helper bug, present in earlier prototypes: MODE_STATIC starts in
  STATE_NO_STATIC_DATA until the first write. Code required STATE_INITIALIZED before writing
  and therefore short-circuited on a healthy buffer. Android's official API state contract
  confirms this. Fourth build now writes silence first, checks readiness afterwards, verifies
  mute/loop/play results, releases failed outputs, and reports only safe stage-specific errors.
  A small injectable Output adapter enables host tests with the real initial-state sequence.
  Earlier reports of functioning headset buttons do not prove that the helper was working.
- Play/Pause/Toggle now refresh the cached snapshot before acknowledgement; Android bridge
  acknowledgements include that snapshot and native UI applies it immediately, with fallback
  polling for older auen versions. Separate Play/Pause PendingIntent identities avoid retargeting
  a visible stale button. Successful polling no longer leaves Last reply stuck at connecting.
- Companion launcher, header, default artwork and monochrome notification icon reuse the
  approved logo bitmap unchanged. Gradle copies docs/assets/logo-icon.png into generated
  resources; adaptive/monochrome XML preserves its wide proportions. Source/generated logo
  hashes match (85f62820ee3b28bdfc3cb65ed1d1d73516f42b20076a405d4fb6a0e91e8b1ab0).
  No new bitmap or toolchain is committed. Original placeholder drawable replaced. Android 8
  framework source confirms unrecognized monochrome tag is ignored on pre-13 implementations.
- Fourth-build user acceptance: Routing running, actual headset Play/Pause/Next/Previous
  while locked, notification feedback and logo all passed on Itel RS4/Android 13. The user
  successfully pip-installed the dev4 source tarball instead of the wheel; that installs the
  same Python version via a build step. No need to reinstall Python just to switch formats.
- Fifth companion-only visual update (Python remains 1.2.0.dev4): smaller centered launcher
  and header icon. User clarified notification should show an off-white (not gray) placeholder
  without thumbnails, and always a small bottom-left wordmark. Implemented warm #EAE7E2 tile,
  square center-cropped thumbnails, plus the unchanged white logo-wordmark.png on a dark
  padded rounded badge. Runtime composition uses the existing artwork worker; cached image
  bytes stay original. Status bar uses a padded monochrome wordmark. OEM/System UI cropping
  may affect final placement, so phone visual acceptance remains pending.
- Sixth companion-only update supersedes the fifth build's artwork placement: user requested
  the wordmark only in the center when no thumbnail is loaded. The warm off-white fallback
  retains the small contrasting padded badge, now centered on both axes. Loaded thumbnails
  have no wordmark/badge. Smaller launcher/header logos remain unchanged. Python stays dev4.
- User accepted the sixth Android build's artwork with "OK good"; no further Android visual
  changes this turn. The accepted APK remains 0.6.0-prototype and also works with Python dev5.
- Linux MPRIS prototype implemented in `linux_media.py`, optional `auen[linux]`/dbus-next extra.
  Runs on Textual's event loop, cached metadata/position/capabilities, shared actions, stale-track
  guarded seek, volume and change signals. Automatic only on ordinary Linux with a desktop bus;
  not Termux, Windows or headless tests. Missing dependency/bus, conflict or disconnect warns
  without stopping playback. `doctor` checks dependency/address, not actual bus connectivity.
- Non-quitting hardware Stop retains the interrupted track first in Queue and holds playback;
  Play restarts it from the beginning. Covers preparation/paused/shuffle, avoids holding the
  control lock during backend startup. Desktop Next preserves pause. Remote/Android Stop still
  quits, MPRIS root Quit also quits. After-track sleep is cancelled by desktop Stop; timed sleep
  is retained. Optional unsupported MPRIS features are not advertised.
- Linux setup/checklist documented in media-controls.md. No i3/system/installed-player changes.
  The user subsequently configured routing and confirmed cached playback, minimized keyboard/
  headset controls, paused Next, non-quitting Stop/Play and clean audio shutdown. They prefer
  universal playerctl bindings with playerctld last-activity routing, not auen-exclusive keys.
  Setup docs updated; actual WM configuration remains user-owned.
- Windows research was paused at the user's quota request, then resumed explicitly. Dev6 now
  has optional `auen[windows]` PyWinRT SMTC integration, a private invisible process-owned
  top-level HWND and bounded UI-loop message pump. Never use Terminal/conhost's foreign HWND.
  Native callbacks enqueue shared actions without blocking or touching UI/mpv from native threads.
- Windows publishes state/title/public thumbnail/timeline, forwards Play/Pause/Next/Previous,
  non-quitting Stop and stale-track guarded seek. Timeline updates about every five seconds or
  on state/track/seek changes. Cleanup removes event handlers, disables SMTC and destroys the
  window; partial initialization/late callbacks/missing packages warn without breaking playback.
- Metadata moved to dependency-free desktop_media.py, retaining Linux re-exports/protocol IDs.
  Windows seek and metadata paths no longer import dbus-next. No Android protocol changes or
  APK rebuild. Windows media-control dependency diagnostics added without native activation.
- mpv Windows media keys disabled; native mpv SMTC also disabled if its --media-controls option
  is supported (one cached 2-second option probe, hidden console). Older builds never receive
  an unsupported flag; probe failure is non-fatal. Windows duplicate-card/routing acceptance
  remains pending. Linux/Termux subprocess options remain unchanged.
- Downloaded five matching PyWinRT 3.2.1 CPython 3.12 Windows wheels solely to inspect exact
  projection signatures/metadata under /tmp/auen-winrt-check.y4EunH (about 655 KB compressed).
  No native libraries installed/executed on Linux, no SDK/system/WM changes or Windows live QA.
- Windows user acceptance on Windows 11 with CPython 3.14/dev6: version/doctor dependencies,
  media-card title/progress with no warning, minimized keyboard/headset Play/Pause/Next/Previous,
  Queue/History updates, paused Next, Previous restart/back behavior, quit/audio cleanup and
  successful restart all passed. On quitting, Windows selects their Vivaldi/Netflix session.
  No seek slider exposed, so seek is not physically verified. Their Stop response mentioned
  the missing slider, not a Stop test; retain hardware Stop as unverified, not passed/failed.
- Initial Windows non-response was missing optional dependencies under Python 3.15. Current
  WinRT wheels stop at CPython 3.14. User installed 3.14 via the Python Install Manager and
  tested with explicit py -3.14 -m auen. They want normal `auen` launch going forward; documented
  a Python-3.14-pinned pipx setup and PATH validation. User confirmed plain `auen` now works.

## Tests

- Latest full regression: 433 passed in 53.98 seconds. Windows callback marshaling, native
  contract/metadata/timeline/cleanup, stale seek, optional startup/doctor checks and Windows mpv
  option compatibility added. Final focused backend/Windows tests: 32 passed. Initial Windows
  contract plus Linux protocol checks: 33 passed; focused app/CLI checks: 13 passed.
  Previous full regression: 408 passed in 53.32 seconds. Adds private real-bus introspection,
  ownership/cleanup, property/signals/seek/error checks, optional-dependency fallback, desktop
  command routing, pause-preserving Next and Stop/Play regression including silent native mpv.
  Final focused Linux/CLI rerun: 37 passed; Stop/private-bus timing rerun: 9 passed.
  Previous full regression: 378 passed in 53.01 seconds. Those tests verify immediate refreshed
  acknowledgement state and UI Pause publishing before the response, not after a timer tick.
  Previous full regression: 376 passed in 51.39 seconds, including new instance/reconnect/seek checks.
  Intermediate third-build run: 375 passed in 53.34 seconds; focused tests: 198 passed.
  Previous build: 359 passed in 52.79 seconds, including slow Android startup not blocking
  shutdown. Earlier intermediate run: 358 passed in 52.88 seconds. Focused bridge/CLI tests passed;
  a UI test's expected startup wording was updated in the implementation and full reruns passed.
- Final transport/CLI focused rerun: 42 passed; no-companion/disconnect UI tests passed.
- Playback/navigation focused checks repeated three times: 19 passed each time.
- Ruff: clean. Strict mypy: clean for Linux (30 source files including preview generator)
  and win32 (29 package source files).
- Native Linux mpv Previous/restart/pause/forward/clean shutdown test passed with `--ao=null`.
- CLI help includes the new Play, Pause, and Previous commands.
- `git diff --check`: clean.
- Private socket tests require normal local permissions. A restricted-sandbox UI/socket run
  failed and reached its 60-second guard; bounded reruns with local socket permissions passed.
- The pytest script launcher could not execute in this environment; running the verified
  interpreter module worked. No virtual-environment launchers were edited.
- Latest Android APK: 27 host JVM tests passed (including crop/layout/invalid-size tests and
  thumbnail-vs-placeholder wordmark visibility), build succeeded. Python code unchanged this turn, so reused its verified 378-test
  result rather than repeating the whole suite. Previous build: 22 native tests, including
  initial static-buffer state/write order, failure cleanup, idempotence and stopped-helper
  recovery. Android lint: 0 errors, 1 expected
  ExportedReceiver warning, documented rather than suppressed. Separately signed Termux must call
  this receiver; the private token/port check replaces a same-signature manifest permission.
  APK signature verification and package/permissions/min-SDK inspection passed.
  No agent-side emulator/physical phone/headset tests were performed. User's first-prototype
  results/regressions are recorded above; sixth-build visuals were accepted by the user. SDK XML/deprecated-framework
  compatibility notices are present in the build log, not hidden; compile/lint checks pass.
- Development wheel/source archive built. Isolated installed-wheel path/runtime/metadata
  version 1.2.0.dev4 and doctor verified in the reused `/tmp/auen-dev2-smoke`;
  the user's installed auen/pipx environment was not changed.
- Dev5 installation: an old shared-system-site-packages smoke environment was incomplete
  (anyascii missing) and pip check exposed unrelated host proton/cffi requirements. No host
  packages were changed. Re-tested in a fresh isolated `/tmp/auen-linux-smoke.5Yg5I5`: normal
  wheel dependency resolution, pip check, version, app import and headless open/quit all passed
  without dbus-next, proving base playback remains optional-dependency independent.
  Final wheel reinstalled there with the linux extra: pip check clean, version dev5, real gdbus
  PlayPause delivered on a private dbus-run-session bus. Source checkout doctor passed with
  optional Android informational message. Development venv gained dbus-next; user pipx unchanged.
- Dev6 wheel smoke in the same isolated environment: pip check clean, version dev6, installed
  app and Windows adapter import without any WinRT packages, headless open/quit pass, real
  installed Linux gdbus command on a private bus passes. Wheel metadata includes platform-gated
  windows extra and contains no APK, PyWinRT binaries, signing keys or toolchain.
  Windows-native API signatures audited against downloaded 3.2.1 projection stubs, but no
  live Windows process/SMTC/keyboard/headset test has been performed. Old Wine/Python test
  environment is gone; do not infer native Windows acceptance from host fakes.
- No APK/JAR/signing key is included in the Python wheel. Git ignores verified for Android
  caches, build outputs, APKs, local SDK configuration, and keys. Native source remains small.

## Historical development artifacts and disk usage

- Prior temporary `/tmp/auen-android-build.p89ZZR` is gone, including its debug key. No old key
  was found in the checkout/default Android key directory. Recreated under the user's existing
  isolated-toolchain authorization; the new key means Android may require uninstalling only
  the old companion before installing this APK. Auen data is unaffected. Tell user explicitly.
- Former toolchain/cache/output root: `/tmp/auen-android-build.ypveNy` (now gone).
- APK: `dist/auen-media-controls-0.6.0-prototype.apk`, 91,155 bytes; debug-signed test build.
  SHA256: `9fba484424bba65d7d8641710e0082ddf4880a067790f5245774b93b6a003a74`.
  Same certificate as 0.2.0 (SHA256 `b6811c3d2550910fab72c44a4cddac17db7f07ebebd19c9a963b50870f700fac`):
  normal update install should work, no uninstall from the second build required.
- Latest wheel: `dist/auen-1.2.0.dev6-py3-none-any.whl`, 95,760 bytes.
  SHA256: `e19b9baad257ff0e9fc03761ad69a0be9859ffbf123e4aeebc62e5ac0251476f`.
  Python source: `dist/auen-1.2.0.dev6.tar.gz`; includes native source/assets, no APK/keys/toolchain.
  Dev5 remains available as the user-accepted Linux test build; no old artifact removed.
- Existing Python source archive `dist/auen-1.2.0.dev4.tar.gz` is the fourth-build snapshot;
  the Python package/wheel is unchanged by the fifth/sixth builds. Companion-only source archive:
  `dist/auen-media-controls-0.6.0-prototype-source.zip`, containing native build/source/tests,
  setup instructions and both logo assets; no SDK/APK/cache/signing key.
- Allocated disk measured at 2,034,434,048 bytes, about 1.89 GiB/2.03 GB, including downloaded
  archives, SDK, JDK, Gradle, dependency caches, key, and build/check output. Nothing material
  was deleted by this turn. Binaries/toolchains remain ignored, outside versioned source.
- JDK 21, Gradle 8.9, AGP 8.7.3, platform 35, build-tools 34.0.0, platform-tools.
  Official download checksums verified. Key: `android-user/debug.keystore` under the temp root;
  do not commit it. `/tmp` is not durable: preserving the key securely needs a deliberate choice.

## Remaining release gates

1. User final-package shallow smoke passed on all three platforms. Review the newly added
   notification crops in README; docs-only package refresh does not require repeating the
   runtime regression. The unchanged companion APK does not need reinstalling.
2. Windows seek slider not exposed and hardware Stop not confirmed: keep both explicitly
   unverified. Android calls/audio focus/OEM battery limits remain broader coverage items.
   These are documented limits, not newly claimed passes.
3. Commit and push the reviewed batch (authorized), then confirm GitHub's Linux/Windows CI.
   Tagging needs further approval and release publication remains user-owned. No user data,
   installed player, window-manager routing, or phone app was changed here.

## Resume

Inspect `/home/razor/Repos/auen` status and the current release section above. Use the final
wheel in `dist/` for the short user smoke, not an older installed v1.1.0/dev package. Reuse
completed checks unless code changes. Keep Windows seek/Stop unverified. Verify asset checksums
before release upload; do not silently replace the tested APK or regenerate signing credentials.
The user approved commit/push. Inspect Git HEAD and its GitHub Actions run for the current
publication state rather than interpreting this pre-commit checkpoint as a live status.
Wait for further direction before tagging or publishing the release.
