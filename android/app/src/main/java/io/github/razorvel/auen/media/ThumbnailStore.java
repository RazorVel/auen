package io.github.razorvel.auen.media;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.Arrays;
import java.util.Comparator;
import java.util.regex.Pattern;

/** Small public-artwork cache. No cookies, bridge credentials, redirects, or arbitrary URLs. */
final class ThumbnailStore {
    static final int MAX_IMAGE_BYTES = 1024 * 1024;
    static final long MAX_CACHE_BYTES = 8L * 1024 * 1024;
    private static final Pattern ALLOWED = Pattern.compile(
            "https://i\\.ytimg\\.com/vi/[A-Za-z0-9_-]{11}/hqdefault\\.jpg");
    private final File directory;

    ThumbnailStore(File directory) { this.directory = directory; }

    static boolean allowed(String url) { return url != null && ALLOWED.matcher(url).matches(); }

    byte[] load(String url) throws IOException {
        if (!allowed(url)) throw new IOException("Unsupported artwork");
        if (!directory.isDirectory() && !directory.mkdirs()) throw new IOException("No artwork cache");
        String id = url.substring("https://i.ytimg.com/vi/".length(), url.lastIndexOf('/'));
        File cached = new File(directory, id + ".jpg");
        if (cached.isFile() && cached.length() <= MAX_IMAGE_BYTES) {
            try (InputStream input = new FileInputStream(cached)) {
                byte[] bytes = readBounded(input);
                cached.setLastModified(System.currentTimeMillis());
                return bytes;
            }
        }
        HttpURLConnection connection = (HttpURLConnection) new URL(url).openConnection();
        connection.setConnectTimeout(2000);
        connection.setReadTimeout(2000);
        connection.setInstanceFollowRedirects(false);
        try {
            if (connection.getResponseCode() != 200 || connection.getContentLengthLong() > MAX_IMAGE_BYTES) {
                throw new IOException("Artwork unavailable");
            }
            byte[] bytes;
            try (InputStream input = connection.getInputStream()) { bytes = readBounded(input); }
            File temporary = new File(directory, id + ".tmp");
            try {
                try (FileOutputStream output = new FileOutputStream(temporary)) { output.write(bytes); }
                if (!temporary.renameTo(cached)) throw new IOException("Cannot cache artwork");
            } finally { if (temporary.exists()) temporary.delete(); }
            trim();
            return bytes;
        } finally { connection.disconnect(); }
    }

    static byte[] readBounded(InputStream input) throws IOException {
        ByteArrayOutputStream result = new ByteArrayOutputStream();
        byte[] buffer = new byte[8192];
        long deadline = System.nanoTime() + 3_000_000_000L;
        int count;
        while ((count = input.read(buffer)) != -1) {
            if (System.nanoTime() > deadline || result.size() + count > MAX_IMAGE_BYTES) {
                throw new IOException("Artwork exceeds limit");
            }
            result.write(buffer, 0, count);
        }
        return result.toByteArray();
    }

    void trim() {
        File[] files = directory.listFiles((dir, name) -> name.matches("[A-Za-z0-9_-]{11}\\.jpg"));
        if (files == null) return;
        Arrays.sort(files, Comparator.comparingLong(File::lastModified));
        long size = 0;
        for (File file : files) size += file.length();
        for (File file : files) {
            if (size <= MAX_CACHE_BYTES) break;
            long bytes = file.length();
            if (file.delete()) size -= bytes;
        }
    }
}
