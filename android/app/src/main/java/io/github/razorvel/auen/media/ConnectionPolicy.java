package io.github.razorvel.auen.media;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

/** Only the current, privately paired player may retry or shut down its companion. */
final class ConnectionPolicy {
    static boolean matches(String code, int port, String token) {
        if (token == null || !token.matches("[0-9a-f]{64}")) return false;
        try {
            PairingInfo saved = PairingInfo.parse(code);
            return saved.port == port && MessageDigest.isEqual(
                    saved.token.getBytes(StandardCharsets.US_ASCII),
                    token.getBytes(StandardCharsets.US_ASCII));
        } catch (IllegalArgumentException ignored) { return false; }
    }
}
