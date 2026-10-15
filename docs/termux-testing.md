# Termux validation checklist

Release target: 1.2.0. The v1.1.0 baseline was exercised with Termux mpv on a physical device.
The combined v1.2.0 development builds and companion 0.6.0-prototype were separately tested
on Itel RS4/Android 13. Use this checklist for subsequent regressions; final-package smoke
testing is distinct from those earlier reports.

## Before launching

1. Install a current Termux release.
2. In Termux, run `pkg update`, `pkg upgrade`, and `pkg install python git mpv ffmpeg`.
3. Install auen 1.2.0 following the [README](../README.md#install-on-android--termux), then
   run `auen --version` and `auen doctor`. Do not skip dependencies on a fresh install.
4. Confirm the doctor reports mpv and the yt-dlp Python package as available.
5. For optional notification controls, install the Termux:API companion app from the same
   source as Termux, then run `pkg install termux-api`. Confirm `auen doctor` reports the
   Android notification command.

## Playback and recovery

1. Launch `auen` and choose **Stream only**. With `backend = "auto"`, mpv should be
   selected when it is installed.
2. Search, queue a track, and start it. mpv should accept the direct stream.
3. Pause and resume with Space. Confirm the progress display continues to update.
4. Press `[` and `]`, then use `g`, and confirm seeking works when mpv is selected.
5. Press `n` with several queued tracks and confirm the next track starts without a
   traceback or overlapping audio. Test `b` near the start and after three seconds, then
   repeat with Shuffle and paused playback.
6. Quit while audio is active and confirm playback stops immediately.
7. Reopen auen and confirm the queue and prior position recover without autoplay.

## Cache and phone layout

1. Restart in **Stream and cache** mode and play a track until it becomes offline-ready.
2. Disable network access and confirm that cached track still plays.
3. Rotate the device or resize the terminal. Confirm Results and Queue switch between
   stacked and side-by-side layouts without losing their rows or selection.
4. At the narrowest practical width, confirm Time, status, progress, and playback controls
   remain visible and aligned.
5. Search for Arabic, Devanagari, and emoji-heavy titles and confirm no text crosses pane
   boundaries. Indic runs are transliterated in display text for stable terminal widths.
6. Open Offline with `l`, filter locally with `/`, and confirm cached playback works without
   network access.
7. If YouTube returns a bot challenge or HTTP 429, confirm the retry countdown appears and
   Offline playback remains available.

## Command mode and sleep

1. Focus Results or Queue, press `:`, and confirm the command field remains contained when
   the Android keyboard opens and closes.
2. Run `sleep 5s`. Confirm the active track pauses in place, the Queue is unchanged, and
   Space resumes from the paused position.
3. Queue another track and run `sleep track`. Confirm the active track finishes but the next
   track waits until Space is pressed.
4. Run `sleep cancel`, invalid sleep input, and the navigation commands. Confirm notices are
   readable and no traceback appears.
5. Focus Search and type `:`. Confirm it remains ordinary query text instead of opening
   command mode.

## Android notification controls

1. Start playback and move Termux to the background. Confirm an ongoing auen notification
   shows the current title and Pause, Next, and Stop actions.
2. Lock the phone and check whether those actions remain available on its lock screen. Some
   Android lock-screen privacy settings may require expanding or unlocking the notification.
3. Press Pause and Resume. Confirm the current track changes state without opening Termux.
4. Press Next. Confirm auen advances through its Queue and records History normally.
5. From another Termux session, run `auen remote status`, `toggle`, and `next`. Confirm they
   control the existing TUI rather than launching another player.
6. Press Stop in the notification. Confirm auen exits cleanly, audio stops, and the
   notification disappears.
7. Disable **Android playback notification** in F2 Settings. Confirm playback continues but
   no notification is shown.
8. Temporarily make Termux:API unavailable and confirm playback and clean shutdown still work
   without a traceback.

Record the Android version, Termux version, terminal dimensions, and any traceback when
reporting a failure.

## Optional headset companion

Follow [the companion setup](../android/README.md). The tested APK remains 0.6.0-prototype,
unchanged for auen 1.2.0; no reinstall is needed if that same APK is already installed.

1. Enable **Android headphone controls (APK)** in F2. Launch/restart auen: connection should
   be automatic and stay ready before playback. Grant notification permission if prompted.
2. Play cached tracks to avoid YouTube uncertainty. Minimize Termux and lock the phone;
   test headset Play/Pause, Next and Previous. Routing should report `running` while active.
3. Check notification artwork and Play/Pause feedback. If Android exposes a progress slider,
   seek while playing and paused. A delayed seek must not affect a different track.
4. Disconnect: audio continues, automatic retry stays suspended for this run, and Termux:API
   fallback controls return when enabled. Connect manually or restart auen to resume pairing.
5. Quit from Termux, leave the companion untouched, and restart several times. Reconnection
   must not hang; a second auen instance should refuse clearly without starting playback.
6. Without the APK, or with it unavailable, verify a warning and normal playback/clean quit.

Core checks above were reported passed on the tested phone. Calls, other media apps, Bluetooth
reconnect, OEM battery limits, and broader device coverage still require physical testing.
Never include pairing credentials in diagnostic screenshots.
