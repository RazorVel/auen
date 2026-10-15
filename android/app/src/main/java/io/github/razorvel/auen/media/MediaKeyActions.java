package io.github.razorvel.auen.media;

import android.view.KeyEvent;

/** Consume key-up/held repeats without performing a second toggle or skip. */
final class MediaKeyActions {
    static String command(int key) {
        switch (key) {
            case KeyEvent.KEYCODE_MEDIA_PLAY: return "play";
            case KeyEvent.KEYCODE_MEDIA_PAUSE: return "pause";
            case KeyEvent.KEYCODE_HEADSETHOOK:
            case KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE: return "toggle";
            case KeyEvent.KEYCODE_MEDIA_NEXT: return "next";
            case KeyEvent.KEYCODE_MEDIA_PREVIOUS: return "previous";
            case KeyEvent.KEYCODE_MEDIA_STOP: return "stop";
            default: return null;
        }
    }
    static String onEvent(int action, int repeats, int key) {
        return action == KeyEvent.ACTION_DOWN && repeats == 0 ? command(key) : null;
    }
}
