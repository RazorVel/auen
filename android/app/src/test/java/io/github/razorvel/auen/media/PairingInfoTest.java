package io.github.razorvel.auen.media;

import org.junit.Test;
import static org.junit.Assert.*;

public class PairingInfoTest {
    private final String token = "a".repeat(64);
    private String code(String port) {
        return "auen://media?protocol=1&port=" + port + "&token=" + token;
    }

    @Test public void acceptsVersionedConnectionCode() {
        PairingInfo parsed = PairingInfo.parse(code("12345"));
        assertEquals(12345, parsed.port);
        assertEquals(token, parsed.token);
    }

    @Test public void rejectsRemoteAddressesAndMalformedCodes() {
        String[] values = {null, "", code("0"), code("65536"), code("true"),
                code("12345").replace("auen://media", "http://example.org"),
                code("12345").replace("auen://media", "auen://user@media"),
                code("12345") + "&port=22", code("12345") + "#fragment",
                code("12345").replace("protocol=1", "protocol=2"),
                code("12345").replace(token, "bad-secret")};
        for (String value : values) {
            try { PairingInfo.parse(value); fail("Accepted invalid code"); }
            catch (IllegalArgumentException error) {
                assertFalse(error.getMessage().contains(token));
                assertFalse(error.getMessage().contains("bad-secret"));
            }
        }
    }
}
