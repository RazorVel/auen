package io.github.razorvel.auen.media;

import java.net.URI;
import java.net.URLDecoder;
import java.util.HashMap;
import java.util.Map;

/** Strict pairing parser: never accept a network hostname or print credentials in errors. */
final class PairingInfo {
    final int port;
    final String token;

    private PairingInfo(int port, String token) { this.port = port; this.token = token; }

    static PairingInfo parse(String code) {
        try {
            if (code == null || code.length() > 512) throw new IllegalArgumentException();
            URI uri = new URI(code.trim());
            if (!"auen".equals(uri.getScheme()) || !"media".equals(uri.getHost())
                    || uri.getUserInfo() != null || uri.getPort() != -1
                    || uri.getFragment() != null || !uri.getPath().isEmpty()) {
                throw new IllegalArgumentException();
            }
            Map<String, String> values = new HashMap<>();
            if (uri.getRawQuery() == null) throw new IllegalArgumentException();
            for (String part : uri.getRawQuery().split("&")) {
                String[] pair = part.split("=", 2);
                if (pair.length != 2) throw new IllegalArgumentException();
                String key = URLDecoder.decode(pair[0], "UTF-8");
                if (values.put(key, URLDecoder.decode(pair[1], "UTF-8")) != null) {
                    throw new IllegalArgumentException();
                }
            }
            if (values.size() != 3 || !"1".equals(values.get("protocol"))) {
                throw new IllegalArgumentException();
            }
            int port = Integer.parseInt(values.get("port"));
            String token = values.get("token");
            if (port < 1 || port > 65535 || token == null || !token.matches("[0-9a-f]{64}")) {
                throw new IllegalArgumentException();
            }
            return new PairingInfo(port, token);
        } catch (Exception ignored) {
            throw new IllegalArgumentException("Invalid connection code. Pair again from Termux.");
        }
    }
}
