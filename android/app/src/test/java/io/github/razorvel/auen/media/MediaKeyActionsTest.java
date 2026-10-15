package io.github.razorvel.auen.media;

import android.view.KeyEvent;
import org.junit.Test;
import static org.junit.Assert.*;

public class MediaKeyActionsTest {
    @Test public void mapsMediaActionsWithoutTerminalKeys() {
        assertEquals("toggle", MediaKeyActions.onEvent(0, 0, KeyEvent.KEYCODE_HEADSETHOOK));
        assertEquals("toggle", MediaKeyActions.onEvent(0, 0, KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE));
        assertEquals("play", MediaKeyActions.onEvent(0, 0, KeyEvent.KEYCODE_MEDIA_PLAY));
        assertEquals("pause", MediaKeyActions.onEvent(0, 0, KeyEvent.KEYCODE_MEDIA_PAUSE));
        assertEquals("next", MediaKeyActions.onEvent(0, 0, KeyEvent.KEYCODE_MEDIA_NEXT));
        assertEquals("previous", MediaKeyActions.onEvent(0, 0, KeyEvent.KEYCODE_MEDIA_PREVIOUS));
        assertEquals("stop", MediaKeyActions.onEvent(0, 0, KeyEvent.KEYCODE_MEDIA_STOP));
    }

    @Test public void keyUpAndHeldRepeatsDoNotDoubleToggleOrSkip() {
        assertNull(MediaKeyActions.onEvent(1, 0, KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE));
        assertNull(MediaKeyActions.onEvent(0, 1, KeyEvent.KEYCODE_MEDIA_NEXT));
        assertNull(MediaKeyActions.onEvent(0, 0, KeyEvent.KEYCODE_A));
    }
}
