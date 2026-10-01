# Termux validation checklist

Version 0.1.0 contains a Termux backend, but it is not considered validated until this
checklist passes on a physical Android device.

## Before launching

1. Install Termux and the Termux:API companion app from the same distribution source.
2. In Termux, run `pkg update` and `pkg install python git termux-api`.
3. Install auen, then run `auen doctor`.
4. Confirm the doctor reports the media player, volume command, companion response, and
   yt-dlp Python package as available.

If the companion does not respond, open Android's app settings and confirm that Termux
and Termux:API are both installed, allowed to run, and came from compatible sources.

## Playback and recovery

1. Launch `auen` and choose **Stream only**.
2. Search, queue a track, and start it. Initial playback may wait for a temporary local
   file because Android's media player does not accept auen's direct YouTube stream URL.
3. Pause and resume with Space. Confirm the progress display continues to update.
4. Press `n` with several queued tracks and confirm the next track starts without a
   traceback or overlapping audio.
5. Quit while audio is active and confirm playback stops immediately.
6. Reopen auen and confirm the queue and prior position recover without autoplay.

## Cache and phone layout

1. Restart in **Stream and cache** mode and play a track until it becomes offline-ready.
2. Disable network access and confirm that cached track still plays.
3. Rotate the device or resize the terminal. Confirm Results and Queue switch between
   stacked and side-by-side layouts without losing their rows or selection.
4. At the narrowest practical width, confirm Time, status, progress, and playback controls
   remain visible and aligned.
5. Search for Arabic, Devanagari, and emoji-heavy titles and confirm no text crosses pane
   boundaries.

Record the Android version, Termux source/version, Termux:API version, terminal dimensions,
and any traceback when reporting a failure. Termux regressions discovered after v0.1.0
should be fixed in a v0.1.x hotfix before new feature work resumes.
