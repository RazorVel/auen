package io.github.razorvel.auen.media;

import android.media.AudioAttributes;
import android.media.AudioFormat;
import android.media.AudioTrack;

/** Optional silent output makes this UID eligible for Android's media-button routing. */
final class SilentRouteKeeper implements AutoCloseable {
    /** Small adapter lets host tests model Android's real static-buffer lifecycle. */
    interface Output {
        int state();
        int playState();
        int write(short[] silence);
        int loop(int frames);
        int mute();
        void play();
        void stop();
        void release();
    }
    interface Factory { Output create(); }
    static final class Failure extends IllegalStateException {
        Failure(String stage, RuntimeException cause) { super(stage, cause); }
    }
    private final Factory factory;
    private Output track;

    SilentRouteKeeper() { this(AndroidOutput::new); }
    SilentRouteKeeper(Factory factory) { this.factory = factory; }

    void start() {
        if (track != null) {
            if (track.state() == AudioTrack.STATE_INITIALIZED
                    && track.playState() == AudioTrack.PLAYSTATE_PLAYING) return;
            close(); // Recover if Android stopped the helper behind our back.
        }
        Output created;
        try { created = factory.create(); }
        catch (RuntimeException error) { throw new Failure("audio creation failed", error); }
        String stage = "audio initialization failed";
        try {
            if (created.state() == AudioTrack.STATE_UNINITIALIZED) throw new IllegalStateException();
            // MODE_STATIC starts in STATE_NO_STATIC_DATA. The first successful
            // write transitions it to STATE_INITIALIZED; checking before that
            // write used to reject a healthy buffer on Android.
            stage = "silence write failed";
            if (created.write(new short[8000]) != 8000) throw new IllegalStateException();
            stage = "audio buffer not ready";
            if (created.state() != AudioTrack.STATE_INITIALIZED) throw new IllegalStateException();
            stage = "audio loop setup failed";
            if (created.loop(8000) != AudioTrack.SUCCESS) throw new IllegalStateException();
            stage = "audio mute failed";
            if (created.mute() != AudioTrack.SUCCESS) throw new IllegalStateException();
            stage = "silent audio start failed";
            created.play();
            if (created.playState() != AudioTrack.PLAYSTATE_PLAYING) throw new IllegalStateException();
            track = created;
        } catch (RuntimeException error) {
            created.release();
            throw new Failure(stage, error);
        }
    }

    private static final class AndroidOutput implements Output {
        private final AudioTrack audio = new AudioTrack.Builder()
                .setAudioAttributes(new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA)
                        .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build())
                .setAudioFormat(new AudioFormat.Builder().setSampleRate(8000)
                        .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                        .setEncoding(AudioFormat.ENCODING_PCM_16BIT).build())
                .setTransferMode(AudioTrack.MODE_STATIC).setBufferSizeInBytes(16000).build();
        public int state() { return audio.getState(); }
        public int playState() { return audio.getPlayState(); }
        public int write(short[] silence) { return audio.write(silence, 0, silence.length); }
        public int loop(int frames) { return audio.setLoopPoints(0, frames, -1); }
        public int mute() { return audio.setVolume(0f); }
        // Do not request audio focus: audible playback remains owned by Termux/mpv.
        public void play() { audio.play(); }
        public void stop() { audio.stop(); }
        public void release() { audio.release(); }
    }

    @Override public void close() {
        if (track == null) return;
        Output previous = track;
        track = null;
        try { previous.stop(); }
        catch (IllegalStateException ignored) { /* Already stopped/released by the audio service. */ }
        finally { previous.release(); }
    }
}
