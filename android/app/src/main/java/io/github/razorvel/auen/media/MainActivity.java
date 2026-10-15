package io.github.razorvel.auen.media;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.view.View;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

public final class MainActivity extends Activity {
    private EditText code;
    private CheckBox routeKeeper;
    private TextView status;
    private TextView diagnostics;
    private String displayedCode = "";
    private SharedPreferences preferences;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Runnable refresh = new Runnable() {
        @Override public void run() {
            status.setText(preferences.getString("status", "Not connected"));
            diagnostics.setText(getString(R.string.diagnostics,
                    preferences.getString("routing", "idle"),
                    preferences.getString("lastInput", "none"),
                    preferences.getString("lastReply", "none")));
            handler.postDelayed(this, 1000);
        }
    };

    @Override public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        preferences = getSharedPreferences("connection", MODE_PRIVATE);
        ScrollView scroll = new ScrollView(this);
        LinearLayout content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        int padding = Math.round(20 * getResources().getDisplayMetrics().density);
        content.setPadding(padding, padding, padding, padding);
        scroll.addView(content);
        setContentView(scroll);
        ImageView logo = new ImageView(this);
        logo.setImageResource(R.drawable.auen_logo);
        logo.setScaleType(ImageView.ScaleType.FIT_CENTER);
        int logoPadding = Math.round(8 * getResources().getDisplayMetrics().density);
        logo.setPadding(logoPadding, logoPadding, logoPadding, logoPadding);
        logo.setContentDescription(getString(R.string.app_name));
        content.addView(logo, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                Math.round(80 * getResources().getDisplayMetrics().density)));
        text(content, "auen media controls · " + BuildConfig.VERSION_NAME, 24);
        text(content, "Auen still runs and plays audio in Termux. This optional app forwards "
                + "headphone and lock-screen actions to that player.", 16);
        text(content, "Enable Android headphone controls in auen F2. Run auen media connect "
                + "if automatic connection is blocked, or paste auen media pair below. "
                + "Keep the code private. Disconnect suspends automatic retries until auen restarts.", 16);
        code = new EditText(this);
        code.setHint("Private connection code");
        code.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        code.setSingleLine(true);
        code.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO);
        displayedCode = preferences.getString("code", "");
        code.setText(displayedCode);
        content.addView(code);
        routeKeeper = new CheckBox(this);
        routeKeeper.setText(R.string.route_keeper);
        routeKeeper.setChecked(preferences.getBoolean("routeKeeper", true));
        content.addView(routeKeeper);
        text(content, "This helper outputs silence, not music. Android may need it to route "
                + "headset buttons while Termux owns the real audio. It may use extra battery. "
                + "Turning it off can leave only on-screen controls working.", 14);
        Button connect = new Button(this);
        connect.setText(R.string.connect);
        connect.setOnClickListener(view -> connect());
        content.addView(connect);
        Button disconnect = new Button(this);
        disconnect.setText(R.string.disconnect);
        disconnect.setOnClickListener(view -> {
            stopService(new Intent(this, MediaControlService.class));
            preferences.edit().putBoolean("suspended", true).putString("status", "Disconnected · "
                    + "automatic connection suspended until auen restarts or you tap Connect").apply();
        });
        content.addView(disconnect);
        status = text(content, "Not connected", 16);
        diagnostics = text(content, "Routing: idle", 14);
        text(content, "Previous · Play/Pause · Next. Hardware Stop quits auen, like its "
                + "notification Stop. No root, microphone, accessibility, storage, "
                + "or permission to execute Termux commands is requested.", 14);
        applyIncoming(getIntent());
    }

    private TextView text(LinearLayout parent, String value, int size) {
        TextView text = new TextView(this);
        text.setText(value);
        text.setTextSize(size);
        text.setPadding(0, 0, 0, 16);
        parent.addView(text);
        return text;
    }

    @Override public void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        applyIncoming(intent);
    }

    private void applyIncoming(Intent intent) {
        if (!intent.hasExtra("bridge-port") || !intent.hasExtra("bridge-token")) return;
        String candidate = "auen://media?protocol=1&port="
                + intent.getIntExtra("bridge-port", 0) + "&token=" + intent.getStringExtra("bridge-token");
        try {
            PairingInfo incoming = PairingInfo.parse(candidate);
            boolean automatic = intent.getBooleanExtra("return-to-termux", false);
            boolean same = ConnectionPolicy.matches(preferences.getString("code", ""),
                    incoming.port, incoming.token);
            if (automatic && same && preferences.getBoolean("suspended", false)) {
                finish();
                return;
            }
            code.setText(candidate);
            displayedCode = candidate;
            if (intent.getBooleanExtra("auto-connect", false)) {
                connect();
                // Allow Android's first-run notification permission prompt to complete.
                if (automatic && (Build.VERSION.SDK_INT < 33 || checkSelfPermission(
                        Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED)) finish();
            }
        } catch (IllegalArgumentException ignored) { showStatus("Invalid connection details"); }
    }

    private void connect() {
        String value = code.getText().toString().trim();
        try { PairingInfo.parse(value); }
        catch (IllegalArgumentException error) { showStatus(error.getMessage()); return; }
        preferences.edit().putString("code", value)
                .putBoolean("suspended", false)
                .putBoolean("routeKeeper", routeKeeper.isChecked()).apply();
        displayedCode = value;
        if (Build.VERSION.SDK_INT >= 33
                && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 1);
        }
        showStatus("Connecting to auen…");
        try { startForegroundService(new Intent(this, MediaControlService.class)); }
        catch (RuntimeException ignored) {
            showStatus("Android could not start controls. Keep this app visible and try again.");
        }
    }

    private void showStatus(String value) {
        preferences.edit().putString("status", value).apply();
        status.setText(value);
    }

    @Override public void onResume() {
        super.onResume();
        // Refresh a previously open screen, but never overwrite a manual edit.
        String saved = preferences.getString("code", "");
        if (code.getText().toString().equals(displayedCode)) {
            displayedCode = saved;
            code.setText(saved);
        }
        handler.post(refresh);
    }
    @Override public void onPause() {
        handler.removeCallbacks(refresh);
        super.onPause();
    }
}
