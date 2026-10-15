package io.github.razorvel.auen.media;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.media.MediaMetadata;
import android.media.session.MediaSession;
import android.media.session.PlaybackState;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.SystemClock;
import android.view.KeyEvent;

import org.json.JSONObject;

import java.util.concurrent.Executors;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.io.File;

/** Native media-session adapter. All real playback/navigation stays in auen. */
public final class MediaControlService extends Service {
    private static final String CHANNEL = "auen-media-controls";
    private static final int NOTIFICATION = 1;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final ScheduledExecutorService worker = Executors.newSingleThreadScheduledExecutor();
    // One running and one latest pending request; rapid Next cannot build an artwork backlog.
    private final ThreadPoolExecutor artworkWorker = new ThreadPoolExecutor(1, 1, 0,
            TimeUnit.MILLISECONDS, new ArrayBlockingQueue<>(1),
            new ThreadPoolExecutor.DiscardOldestPolicy());
    private final SilentRouteKeeper routeKeeper = new SilentRouteKeeper();
    private MediaSession session;
    private final BridgeConnection connection = new BridgeConnection();
    private String connectionCode = "";
    private SharedPreferences preferences;
    private boolean running;
    private volatile boolean closed;
    private boolean silentRouting;
    private boolean routingUnavailable;
    private String routingFailure = "";
    private String title = "Connecting to auen…";
    private String state = "stopped";
    private String artworkUrl = "";
    private Bitmap artwork;
    private Bitmap defaultArtwork;
    private Bitmap brandingWordmark;
    private long artworkRetryAt;
    private boolean artworkLoading;
    private JSONObject latest;
    private ThumbnailStore thumbnails;

    @Override public void onCreate() {
        super.onCreate();
        preferences = getSharedPreferences("connection", MODE_PRIVATE);
        thumbnails = new ThumbnailStore(new File(getCacheDir(), "thumbnails"));
        brandingWordmark = BitmapFactory.decodeResource(getResources(), R.drawable.auen_wordmark);
        defaultArtwork = BrandedArtwork.render(null, brandingWordmark);
        getSystemService(NotificationManager.class).createNotificationChannel(
                new NotificationChannel(CHANNEL, "Auen media controls", NotificationManager.IMPORTANCE_LOW));
        session = new MediaSession(this, "auen");
        session.setFlags(MediaSession.FLAG_HANDLES_MEDIA_BUTTONS | MediaSession.FLAG_HANDLES_TRANSPORT_CONTROLS);
        session.setCallback(new MediaSession.Callback() {
            @Override public void onPlay() { systemAction("play"); }
            @Override public void onPause() { systemAction("pause"); }
            @Override public void onSkipToNext() { systemAction("next"); }
            @Override public void onSkipToPrevious() { systemAction("previous"); }
            @Override public void onStop() { systemAction("stop"); }
            @Override public void onSeekTo(long position) { seek(position); }
            @Override public boolean onMediaButtonEvent(Intent intent) {
                KeyEvent key = intent.getParcelableExtra(Intent.EXTRA_KEY_EVENT);
                if (key == null || MediaKeyActions.command(key.getKeyCode()) == null) {
                    return super.onMediaButtonEvent(intent);
                }
                String command = MediaKeyActions.onEvent(key.getAction(), key.getRepeatCount(), key.getKeyCode());
                if (command != null) systemAction(command);
                return true;
            }
        }, main);
        session.setSessionActivity(openActivity());
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && "shutdown".equals(intent.getAction())) {
            int port = intent.getIntExtra("bridge-port", 0);
            String token = intent.getStringExtra("bridge-token");
            if (ConnectionPolicy.matches(connectionCode, port, token)
                    && ConnectionPolicy.matches(preferences.getString("code", ""), port, token)) {
                preferences.edit().putBoolean("suspended", true).putString("status", "Auen closed").apply();
                stopSelf(startId);
            } else if (!running) stopSelf(startId);
            return START_NOT_STICKY;
        }
        if (intent != null && "disconnect".equals(intent.getAction())) {
            preferences.edit().putBoolean("suspended", true).putString("status",
                    "Disconnected · automatic connection suspended until auen restarts or you tap Connect").apply();
            stopSelf(startId);
            return START_NOT_STICKY;
        }
        if (preferences.getBoolean("suspended", false)) {
            stopSelf();
            return START_NOT_STICKY;
        }
        try {
            String code = preferences.getString("code", "");
            boolean connecting = intent == null || intent.getAction() == null;
            if (connection.current() == null || !code.equals(connectionCode) || connecting) {
                connection.connect(code);
                connectionCode = code;
                preferences.edit().putString("lastInput", "none since connection")
                        .putString("lastReply", "connecting").apply();
            }
            silentRouting = preferences.getBoolean("routeKeeper", true);
            routingUnavailable = false;
            routingFailure = "";
        } catch (IllegalArgumentException error) {
            preferences.edit().putString("status", error.getMessage()).apply();
            stopSelf();
            return START_NOT_STICKY;
        }
        if (running) {
            String command = intent == null ? null : intent.getAction();
            if (command != null) {
                preferences.edit().putString("lastInput", "notification: " + command).apply();
                send(command);
            }
            else worker.execute(this::poll); // Fresh Connect never inherits an old retry delay.
            return START_NOT_STICKY;
        }
        running = true;
        // Visible initial handoff, then authenticated quiet retries; never at boot.
        try { startForeground(NOTIFICATION, notification()); }
        catch (RuntimeException ignored) {
            preferences.edit().putString("status", "Android could not enable background controls").apply();
            stopSelf();
            return START_NOT_STICKY;
        }
        worker.scheduleWithFixedDelay(this::poll, 0, 1, TimeUnit.SECONDS);
        return START_NOT_STICKY;
    }

    private void send(String command) {
        if (closed || !running) return;
        BridgeConnection.Attempt target = connection.current();
        worker.execute(() -> {
            if (!connection.isCurrent(target) || closed) return;
            try {
                JSONObject result = target.client.request(command);
                if (closed || !connection.isCurrent(target)) return;
                preferences.edit().putString("lastReply", command + " accepted").apply();
                if ("stop".equals(command)) main.post(() -> {
                    if (closed || !connection.isCurrent(target)) return;
                    preferences.edit().putString("status", "Stopped auen").apply();
                    stopSelf();
                });
                else {
                    connection.success(target);
                    if (result.optInt("protocol", 0) == 1) {
                        main.post(() -> { if (connection.isCurrent(target)) apply(result); });
                    } else poll(); // Compatible with older auen builds.
                }
            } catch (Exception error) { failed(target, error); }
        });
    }

    private void poll() {
        if (closed || !connection.canPoll(SystemClock.elapsedRealtime())) return;
        BridgeConnection.Attempt target = connection.current();
        try {
            JSONObject result = target.client.request("status");
            if (result.optInt("protocol", 0) != 1) throw new IllegalArgumentException();
            connection.success(target);
            main.post(() -> { if (connection.isCurrent(target)) apply(result); });
        } catch (Exception error) { failed(target, error); }
    }

    private void failed(BridgeConnection.Attempt target, Exception error) {
        if (!connection.failed(target, SystemClock.elapsedRealtime())) return;
        main.post(() -> {
            if (closed || !connection.isCurrent(target)) return;
            state = "stopped";
            session.setActive(false);
            session.setPlaybackState(new PlaybackState.Builder().setState(
                    PlaybackState.STATE_STOPPED, 0, 0).build());
            routeKeeper.close();
            preferences.edit().putString("routing", "idle · bridge unavailable")
                    .putString("lastReply", "bridge: " + BridgeClient.failureSummary(error)).apply();
            preferences.edit().putString("status", "Waiting for auen · retrying automatically. "
                    + "Playback is unaffected.").apply();
            getSystemService(NotificationManager.class).notify(NOTIFICATION, notification());
        });
    }

    private void apply(JSONObject result) {
        if (closed) return;
        latest = result;
        String reply = preferences.getString("lastReply", "connecting");
        if ("connecting".equals(reply) || reply.startsWith("bridge:")) {
            preferences.edit().putString("lastReply", "status received").apply();
        }
        state = result.optString("state", "stopped");
        title = result.optString("title", "Auen");
        boolean active = "playing".equals(state) || "paused".equals(state) || "buffering".equals(state);
        // Preserve the device-verified active/idle transition. Keeping the socket
        // connected does not require publishing an active stopped MediaSession.
        session.setActive(active);
        if (active && silentRouting) {
            try {
                routeKeeper.start();
                preferences.edit().putString("routing", "running").apply();
            }
            catch (RuntimeException error) {
                silentRouting = false;
                routingUnavailable = true;
                routingFailure = error instanceof SilentRouteKeeper.Failure
                        ? error.getMessage() : "audio setup failed";
                preferences.edit().putString("routing", "unavailable · " + routingFailure
                        + " · reconnect to retry").apply();
            }
        } else {
            routeKeeper.close();
            preferences.edit().putString("routing", routingUnavailable ? "unavailable · " + routingFailure
                    + " · reconnect to retry"
                    : silentRouting ? "idle" : "disabled").apply();
        }
        int playback = "playing".equals(state) ? PlaybackState.STATE_PLAYING
                : "paused".equals(state) ? PlaybackState.STATE_PAUSED
                : "buffering".equals(state) ? PlaybackState.STATE_BUFFERING : PlaybackState.STATE_STOPPED;
        long actions = PlaybackState.ACTION_PLAY | PlaybackState.ACTION_PAUSE
                | PlaybackState.ACTION_PLAY_PAUSE | PlaybackState.ACTION_STOP;
        if (result.optBoolean("can_next", false)) actions |= PlaybackState.ACTION_SKIP_TO_NEXT;
        if (result.optBoolean("can_previous", false)) actions |= PlaybackState.ACTION_SKIP_TO_PREVIOUS;
        if (result.optBoolean("can_seek", false)) actions |= PlaybackState.ACTION_SEEK_TO;
        long position = Math.max(0, (long) (result.optDouble("elapsed_seconds", 0) * 1000));
        session.setPlaybackState(new PlaybackState.Builder().setActions(actions)
                .setState(playback, position, playback == PlaybackState.STATE_PLAYING ? 1f : 0f,
                        SystemClock.elapsedRealtime()).build());
        updateArtwork(result.optString("thumbnail_url", ""));
        publishMetadata();
        getSystemService(NotificationManager.class).notify(NOTIFICATION, notification());
        String warning = routingUnavailable ? " · Headphone routing unavailable"
                : !silentRouting && active ? " · Headphone helper disabled" : "";
        preferences.edit().putString("status", "Connected · " + state + " · " + title + warning).apply();
    }

    private void systemAction(String command) {
        preferences.edit().putString("lastInput", "system/headset: " + command).apply();
        send(command);
    }

    private void seek(long position) {
        if (closed || latest == null || !latest.optBoolean("can_seek", false)) return;
        String mediaId = latest.optString("media_id", "");
        BridgeConnection.Attempt target = connection.current();
        preferences.edit().putString("lastInput", "system slider: seek").apply();
        worker.execute(() -> {
            if (closed || !connection.isCurrent(target)) return;
            try {
                target.client.seek(Math.max(0, position), mediaId);
                if (!connection.isCurrent(target)) return;
                preferences.edit().putString("lastReply", "seek accepted").apply();
                connection.success(target);
                poll();
            } catch (Exception ignored) {
                // A late seek for a skipped track is harmless, not a lost connection.
                preferences.edit().putString("lastReply", "seek unavailable or track changed").apply();
            }
        });
    }

    private void publishMetadata() {
        if (closed || latest == null) return;
        Bitmap picture = artwork != null ? artwork : defaultArtwork;
        MediaMetadata.Builder metadata = new MediaMetadata.Builder()
                .putString(MediaMetadata.METADATA_KEY_TITLE, title)
                .putString(MediaMetadata.METADATA_KEY_ARTIST, "auen · Termux")
                .putBitmap(MediaMetadata.METADATA_KEY_ALBUM_ART, picture)
                .putBitmap(MediaMetadata.METADATA_KEY_DISPLAY_ICON, picture);
        double duration = latest.optDouble("duration_seconds", 0);
        if (duration > 0 && Double.isFinite(duration)) {
            metadata.putLong(MediaMetadata.METADATA_KEY_DURATION, (long) (duration * 1000));
        }
        session.setMetadata(metadata.build());
    }

    private void updateArtwork(String candidate) {
        String url = ThumbnailStore.allowed(candidate) ? candidate : "";
        if (!url.equals(artworkUrl)) {
            artworkUrl = url;
            artwork = null;
            artworkLoading = false;
            artworkRetryAt = 0;
        }
        if (url.isEmpty() || artwork != null || artworkLoading
                || SystemClock.elapsedRealtime() < artworkRetryAt) return;
        artworkLoading = true;
        artworkWorker.execute(() -> {
            Bitmap loaded = null;
            try {
                byte[] bytes = thumbnails.load(url);
                BitmapFactory.Options bounds = new BitmapFactory.Options();
                bounds.inJustDecodeBounds = true;
                BitmapFactory.decodeByteArray(bytes, 0, bytes.length, bounds);
                if (bounds.outWidth > 0 && bounds.outWidth <= 4096
                        && bounds.outHeight > 0 && bounds.outHeight <= 4096) {
                    BitmapFactory.Options options = new BitmapFactory.Options();
                    options.inSampleSize = 1;
                    while (Math.max(bounds.outWidth, bounds.outHeight) / options.inSampleSize > 512) {
                        options.inSampleSize *= 2;
                    }
                    loaded = BitmapFactory.decodeByteArray(bytes, 0, bytes.length, options);
                    if (loaded != null) loaded = BrandedArtwork.render(loaded, brandingWordmark);
                }
            } catch (Exception ignored) { /* Artwork must never fail or delay playback. */ }
            Bitmap result = loaded;
            main.post(() -> {
                if (closed || !url.equals(artworkUrl)) return;
                artworkLoading = false;
                artwork = result;
                artworkRetryAt = SystemClock.elapsedRealtime() + 60000;
                publishMetadata();
                getSystemService(NotificationManager.class).notify(NOTIFICATION, notification());
            });
        });
    }

    private PendingIntent openActivity() {
        return PendingIntent.getActivity(this, 0, new Intent(this, MainActivity.class),
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }

    private Notification.Action action(int icon, String label, String command, int id) {
        Intent intent = new Intent(this, MediaControlService.class).setAction(command);
        PendingIntent pending = PendingIntent.getService(this, id, intent,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        return new Notification.Action.Builder(icon, label, pending).build();
    }

    private Notification notification() {
        boolean playing = "playing".equals(state);
        return new Notification.Builder(this, CHANNEL)
                .setSmallIcon(R.drawable.ic_stat_auen)
                .setLargeIcon(artwork != null ? artwork : defaultArtwork)
                .setContentTitle(title).setContentText("auen · " + state)
                .setContentIntent(openActivity()).setOnlyAlertOnce(true).setOngoing(true)
                .addAction(action(android.R.drawable.ic_media_previous, "Previous", "previous", 1))
                .addAction(action(playing ? android.R.drawable.ic_media_pause : android.R.drawable.ic_media_play,
                        playing ? "Pause" : "Play", playing ? "pause" : "play", playing ? 21 : 20))
                .addAction(action(android.R.drawable.ic_media_next, "Next", "next", 3))
                .addAction(action(android.R.drawable.ic_menu_close_clear_cancel, "Disconnect", "disconnect", 4))
                .setStyle(new Notification.MediaStyle().setMediaSession(session.getSessionToken())
                        .setShowActionsInCompactView(0, 1, 2)).build();
    }

    @Override public IBinder onBind(Intent intent) { return null; }

    @Override public void onDestroy() {
        closed = true;
        running = false;
        worker.shutdownNow();
        artworkWorker.shutdownNow();
        main.removeCallbacksAndMessages(null);
        routeKeeper.close();
        preferences.edit().putString("routing", "idle · disconnected").apply();
        if (session != null) { session.setActive(false); session.release(); }
        stopForeground(STOP_FOREGROUND_REMOVE);
        if (preferences.getString("status", "").startsWith("Connected")) {
            preferences.edit().putString("status", "Companion disconnected; auen playback is unaffected").apply();
        }
        super.onDestroy();
    }
}
