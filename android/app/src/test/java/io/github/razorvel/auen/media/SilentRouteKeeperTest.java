package io.github.razorvel.auen.media;

import android.media.AudioTrack;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import org.junit.Test;
import static org.junit.Assert.*;

public class SilentRouteKeeperTest {
    private static final class FakeOutput implements SilentRouteKeeper.Output {
        int state = AudioTrack.STATE_NO_STATIC_DATA;
        int playState = AudioTrack.PLAYSTATE_STOPPED;
        int writeResult = 8000;
        int loopResult = AudioTrack.SUCCESS;
        int muteResult = AudioTrack.SUCCESS;
        int releases;
        boolean playFails;
        boolean stopFails;
        final List<String> calls = new ArrayList<>();
        public int state() { return state; }
        public int playState() { return playState; }
        public int write(short[] data) {
            calls.add("write");
            assertEquals(8000, data.length);
            for (short sample : data) assertEquals(0, sample);
            if (writeResult == 8000) state = AudioTrack.STATE_INITIALIZED;
            return writeResult;
        }
        public int loop(int frames) {
            calls.add("loop");
            assertEquals(AudioTrack.STATE_INITIALIZED, state);
            assertEquals(8000, frames);
            return loopResult;
        }
        public int mute() { calls.add("mute"); return muteResult; }
        public void play() {
            calls.add("play");
            if (playFails) throw new IllegalStateException("raw native message");
            playState = AudioTrack.PLAYSTATE_PLAYING;
        }
        public void stop() {
            calls.add("stop");
            playState = AudioTrack.PLAYSTATE_STOPPED;
            if (stopFails) throw new IllegalStateException();
        }
        public void release() { calls.add("release"); releases++; }
    }

    @Test public void writesBeforeRequiringInitializedStaticBuffer() {
        FakeOutput output = new FakeOutput();
        SilentRouteKeeper keeper = new SilentRouteKeeper(() -> output);
        assertEquals(AudioTrack.STATE_NO_STATIC_DATA, output.state);
        keeper.start();
        assertEquals(Arrays.asList("write", "loop", "mute", "play"), output.calls);
        assertEquals(AudioTrack.PLAYSTATE_PLAYING, output.playState);
        keeper.start(); // Repeated status snapshots must not restart healthy audio.
        assertEquals(4, output.calls.size());
        keeper.close();
        keeper.close();
        assertEquals(1, output.releases);
    }

    @Test public void recoversIfAndroidStoppedTheOutput() {
        FakeOutput first = new FakeOutput();
        FakeOutput second = new FakeOutput();
        ArrayDeque<FakeOutput> outputs = new ArrayDeque<>(Arrays.asList(first, second));
        SilentRouteKeeper keeper = new SilentRouteKeeper(outputs::removeFirst);
        keeper.start();
        first.playState = AudioTrack.PLAYSTATE_STOPPED;
        keeper.start();
        assertEquals(1, first.releases);
        assertEquals(AudioTrack.PLAYSTATE_PLAYING, second.playState);
        keeper.close();
        assertEquals(1, second.releases);
    }

    @Test public void failedStagesReleaseResourcesAndExposeOnlySafeStage() {
        String[] stages = {"audio initialization failed", "silence write failed",
                "audio loop setup failed", "audio mute failed", "silent audio start failed"};
        for (int i = 0; i < stages.length; i++) {
            FakeOutput output = new FakeOutput();
            if (i == 0) output.state = AudioTrack.STATE_UNINITIALIZED;
            if (i == 1) output.writeResult = 7999;
            if (i == 2) output.loopResult = AudioTrack.ERROR_BAD_VALUE;
            if (i == 3) output.muteResult = AudioTrack.ERROR;
            if (i == 4) output.playFails = true;
            SilentRouteKeeper keeper = new SilentRouteKeeper(() -> output);
            try { keeper.start(); fail("Failed audio stage accepted"); }
            catch (SilentRouteKeeper.Failure error) { assertEquals(stages[i], error.getMessage()); }
            assertEquals(1, output.releases);
            keeper.close();
            assertEquals(1, output.releases);
        }
    }

    @Test public void alreadyStoppedOutputIsStillReleased() {
        FakeOutput output = new FakeOutput();
        output.stopFails = true;
        SilentRouteKeeper keeper = new SilentRouteKeeper(() -> output);
        keeper.start();
        keeper.close();
        assertEquals(1, output.releases);
    }

    @Test public void creationFailureHasNoRawErrorInDiagnostic() {
        SilentRouteKeeper keeper = new SilentRouteKeeper(() -> {
            throw new IllegalArgumentException("sensitive native message");
        });
        try { keeper.start(); fail("Creation failure accepted"); }
        catch (SilentRouteKeeper.Failure error) { assertEquals("audio creation failed", error.getMessage()); }
        keeper.close();
    }
}
