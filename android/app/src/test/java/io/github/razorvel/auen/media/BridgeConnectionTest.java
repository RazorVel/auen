package io.github.razorvel.auen.media;

import org.junit.Test;
import static org.junit.Assert.*;

public class BridgeConnectionTest {
    private String code(int port) {
        return "auen://media?protocol=1&port=" + port + "&token=" + "a".repeat(64);
    }

    @Test public void newPairingImmediatelyClearsOldRetryDelay() {
        BridgeConnection connection = new BridgeConnection();
        connection.connect(code(12345));
        BridgeConnection.Attempt old = connection.current();
        connection.failed(old, 1000);
        assertFalse(connection.canPoll(1001));
        connection.connect(code(12346));
        assertTrue(connection.canPoll(1001));
        assertFalse(connection.isCurrent(old));
        assertFalse(connection.failed(old, 2000));
        assertTrue(connection.canPoll(2001));
    }

    @Test public void manualConnectToSameEndpointInvalidatesInFlightResponses() {
        BridgeConnection connection = new BridgeConnection();
        connection.connect(code(12345));
        BridgeConnection.Attempt old = connection.current();
        connection.connect(code(12345));
        assertFalse(connection.isCurrent(old));
        connection.failed(connection.current(), 1000);
        connection.success(old);
        assertFalse(connection.canPoll(1001));
        connection.success(connection.current());
        assertTrue(connection.canPoll(1001));
    }

    @Test public void retryDelayCapsAtThirtySeconds() {
        BridgeConnection connection = new BridgeConnection();
        connection.connect(code(12345));
        for (int i = 0; i < 20; i++) connection.failed(connection.current(), 1000);
        assertFalse(connection.canPoll(30999));
        assertTrue(connection.canPoll(31000));
    }
}
