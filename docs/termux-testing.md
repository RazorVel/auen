# Termux validation checklist

Version 1.0.0 has been exercised with the Termux `mpv` package on a physical Android device.
Use this checklist for release and regression validation.

## Before launching

1. Install a current Termux release.
2. In Termux, run `pkg update` and `pkg install python git mpv ffmpeg`.
3. Install auen, then run `auen doctor`.
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
   traceback or overlapping audio.
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
