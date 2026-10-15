package io.github.razorvel.auen.media;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.net.ConnectException;
import java.net.SocketTimeoutException;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.Locale;

/** Bounded, authenticated JSON exchange with auen only. No shell or mpv access. */
final class BridgeClient {
    private final PairingInfo endpoint;
    BridgeClient(PairingInfo endpoint) { this.endpoint = endpoint; }

    static String failureSummary(Exception error) {
        String message = error.getMessage();
        if (message != null && message.toLowerCase(Locale.ROOT).contains("permission denied")) {
            return "network permission denied · check VPN/firewall";
        }
        if (error instanceof SocketTimeoutException) return "connection timed out";
        if (error instanceof ConnectException) return "connection refused";
        // Never copy arbitrary error messages or credentials into diagnostics.
        return "connection unavailable";
    }

    JSONObject request(String command) throws IOException {
        if (!Arrays.asList("status", "play", "pause", "toggle", "next", "previous", "stop")
                .contains(command)) throw new IOException("Unsupported media action");
        JSONObject request = new JSONObject();
        try { request.put("command", command); }
        catch (Exception ignored) { throw new IOException("Invalid media action"); }
        return exchange(request);
    }

    JSONObject seek(long positionMs, String mediaId) throws IOException {
        if (positionMs < 0 || mediaId == null || !mediaId.matches("[0-9a-f]{64}")) {
            throw new IOException("Invalid seek request");
        }
        JSONObject request = new JSONObject();
        try {
            request.put("command", "seek");
            request.put("seconds", positionMs / 1000.0);
            request.put("media_id", mediaId);
        } catch (Exception ignored) { throw new IOException("Invalid seek request"); }
        return exchange(request);
    }

    private JSONObject exchange(JSONObject request) throws IOException {
        try (Socket socket = new Socket()) {
            // Never resolve a user-supplied hostname, even from a pairing intent.
            socket.connect(new InetSocketAddress(
                    InetAddress.getByAddress(new byte[]{127, 0, 0, 1}), endpoint.port), 1500);
            socket.setSoTimeout(1500);
            request.put("token", endpoint.token);
            socket.getOutputStream().write((request + "\n").getBytes(StandardCharsets.UTF_8));
            InputStream input = socket.getInputStream();
            ByteArrayOutputStream data = new ByteArrayOutputStream();
            long deadline = System.nanoTime() + 2_000_000_000L;
            while (true) {
                if (System.nanoTime() > deadline) throw new IOException("Media reply timed out");
                int next = input.read();
                if (next == -1) throw new IOException("Media connection closed");
                if (next == '\n') break;
                if (data.size() >= 65536) throw new IOException("Media reply is too large");
                data.write(next);
            }
            JSONObject result = new JSONObject(data.toString("UTF-8"));
            if (!result.optBoolean("ok", false)) {
                throw new IOException("Auen rejected the media action. Pair again if needed.");
            }
            return result;
        } catch (IOException error) {
            throw error;
        } catch (Exception ignored) {
            throw new IOException("Invalid media reply");
        }
    }
}
