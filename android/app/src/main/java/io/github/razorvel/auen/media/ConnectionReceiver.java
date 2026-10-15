package io.github.razorvel.auen.media;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;

/** Quiet authenticated retries; never opens a window from the background. */
public final class ConnectionReceiver extends BroadcastReceiver {
    @Override public void onReceive(Context context, Intent intent) {
        SharedPreferences preferences = context.getSharedPreferences("connection", Context.MODE_PRIVATE);
        if (!ConnectionPolicy.matches(preferences.getString("code", ""),
                intent.getIntExtra("bridge-port", 0), intent.getStringExtra("bridge-token"))) return;
        String action = intent.getAction();
        Intent service = new Intent(context, MediaControlService.class);
        if ("io.github.razorvel.auen.media.shutdown".equals(action)) {
            // Deliver a generation-scoped command, not an unconditional stopService
            // that could destroy a newer connection already queued by MainActivity.
            service.setAction("shutdown").putExtra("bridge-port", intent.getIntExtra("bridge-port", 0))
                    .putExtra("bridge-token", intent.getStringExtra("bridge-token"));
            try { context.startService(service); }
            catch (RuntimeException ignored) { /* No running service needs cleanup. */ }
        } else if ("io.github.razorvel.auen.media.connect".equals(action)
                && !preferences.getBoolean("suspended", false)) {
            try { context.startForegroundService(service); }
            catch (RuntimeException ignored) {
                preferences.edit().putString("status", "Android blocked background start. "
                        + "Open the companion or run auen media connect.").apply();
            }
        }
    }
}
