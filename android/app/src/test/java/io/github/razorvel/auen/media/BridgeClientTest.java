package io.github.razorvel.auen.media;

import org.json.JSONObject;
import org.junit.Test;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.*;
import static org.junit.Assert.*;

public class BridgeClientTest {
    private final String token = "b".repeat(64);

    @Test public void sendsAuthenticatedActionAndReadsUnicodeReply() throws Exception {
        try (ServerSocket server = new ServerSocket(0, 1, InetAddress.getByName("127.0.0.1"))) {
            ExecutorService worker = Executors.newSingleThreadExecutor();
            try {
                Future<JSONObject> request = worker.submit(() -> {
                    try (Socket connection = server.accept()) {
                        BufferedReader input = new BufferedReader(new InputStreamReader(
                                connection.getInputStream(), StandardCharsets.UTF_8));
                        JSONObject received = new JSONObject(input.readLine());
                        connection.getOutputStream().write(
                                "{\"ok\":true,\"title\":\"日本語\"}\n".getBytes(StandardCharsets.UTF_8));
                        return received;
                    }
                });
                PairingInfo info = PairingInfo.parse("auen://media?protocol=1&port="
                        + server.getLocalPort() + "&token=" + token);
                JSONObject response = new BridgeClient(info).request("previous");
                assertEquals("日本語", response.getString("title"));
                JSONObject received = request.get(3, TimeUnit.SECONDS);
                assertEquals("previous", received.getString("command"));
                assertEquals(token, received.getString("token"));
            } finally { worker.shutdownNow(); }
        }
    }

    @Test public void rejectsUnlistedActionsBeforeConnecting() throws Exception {
        PairingInfo info = PairingInfo.parse("auen://media?protocol=1&port=1&token=" + token);
        try { new BridgeClient(info).request("shell-command"); fail("Accepted unlisted command"); }
        catch (java.io.IOException error) { assertEquals("Unsupported media action", error.getMessage()); }
    }

    @Test public void sendsSeekWithPositionAndTrackIdentity() throws Exception {
        try (ServerSocket server = new ServerSocket(0, 1, InetAddress.getByName("127.0.0.1"))) {
            ExecutorService worker = Executors.newSingleThreadExecutor();
            try {
                Future<JSONObject> request = worker.submit(() -> {
                    try (Socket connection = server.accept()) {
                        BufferedReader input = new BufferedReader(new InputStreamReader(
                                connection.getInputStream(), StandardCharsets.UTF_8));
                        JSONObject received = new JSONObject(input.readLine());
                        connection.getOutputStream().write("{\"ok\":true}\n".getBytes(StandardCharsets.UTF_8));
                        return received;
                    }
                });
                PairingInfo info = PairingInfo.parse("auen://media?protocol=1&port="
                        + server.getLocalPort() + "&token=" + token);
                new BridgeClient(info).seek(123456, "c".repeat(64));
                JSONObject received = request.get(3, TimeUnit.SECONDS);
                assertEquals("seek", received.getString("command"));
                assertEquals(123.456, received.getDouble("seconds"), 0.0001);
                assertEquals("c".repeat(64), received.getString("media_id"));
                assertEquals(token, received.getString("token"));
            } finally { worker.shutdownNow(); }
        }
    }

    @Test public void rejectsInvalidSeeksBeforeConnecting() throws Exception {
        BridgeClient client = new BridgeClient(PairingInfo.parse(
                "auen://media?protocol=1&port=1&token=" + token));
        for (String id : new String[]{null, "", "not-an-id"}) {
            try { client.seek(1000, id); fail("Invalid seek accepted"); }
            catch (java.io.IOException error) { assertEquals("Invalid seek request", error.getMessage()); }
        }
        try { client.seek(-1, "c".repeat(64)); fail("Negative seek accepted"); }
        catch (java.io.IOException error) { assertEquals("Invalid seek request", error.getMessage()); }
    }

    @Test public void failureDiagnosticsAreUsefulWithoutLeakingRawMessages() {
        assertEquals("network permission denied · check VPN/firewall",
                BridgeClient.failureSummary(new java.net.SocketException("Permission denied")));
        assertEquals("connection timed out",
                BridgeClient.failureSummary(new java.net.SocketTimeoutException("private")));
        assertEquals("connection refused",
                BridgeClient.failureSummary(new java.net.ConnectException("private")));
        assertEquals("connection unavailable",
                BridgeClient.failureSummary(new java.io.IOException(token)));
    }
}
