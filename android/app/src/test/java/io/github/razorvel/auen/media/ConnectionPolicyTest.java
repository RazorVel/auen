package io.github.razorvel.auen.media;

import org.junit.Test;
import static org.junit.Assert.*;

public class ConnectionPolicyTest {
    @Test public void acceptsOnlyCurrentPrivatePairing() {
        String token = "a".repeat(64);
        String code = "auen://media?protocol=1&port=12345&token=" + token;
        assertTrue(ConnectionPolicy.matches(code, 12345, token));
        assertFalse(ConnectionPolicy.matches(code, 12346, token));
        assertFalse(ConnectionPolicy.matches(code, 12345, "b".repeat(64)));
        assertFalse(ConnectionPolicy.matches(code, 12345, null));
        assertFalse(ConnectionPolicy.matches("invalid", 12345, token));
        assertFalse(ConnectionPolicy.matches(code, 12345, token + "extra"));
    }
}
