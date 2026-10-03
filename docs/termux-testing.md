# Termux validation checklist

Version 0.4.0 has been exercised with the Termux `mpv` package on a physical Android device.
Use this checklist for release and regression validation.

## Before launching

1. Install a current Termux release.
2. In Termux, run `pkg update` and `pkg install python git mpv ffmpeg`.
3. Install auen, then run `auen doctor`.
4. Confirm the doctor reports mpv and the yt-dlp Python package as available.

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

Record the Android version, Termux version, terminal dimensions, and any traceback when
reporting a failure.
