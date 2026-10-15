package io.github.razorvel.auen.media;

import java.io.ByteArrayInputStream;
import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.util.Arrays;
import org.junit.Test;
import org.junit.Rule;
import org.junit.rules.TemporaryFolder;
import static org.junit.Assert.*;

public class ThumbnailStoreTest {
    @Rule public TemporaryFolder temporary = new TemporaryFolder();

    @Test public void onlyFixedPublicThumbnailUrlsAreAccepted() {
        assertTrue(ThumbnailStore.allowed("https://i.ytimg.com/vi/Abc_123-XYZ/hqdefault.jpg"));
        for (String url : Arrays.asList(null, "", "http://i.ytimg.com/vi/Abc_123-XYZ/hqdefault.jpg",
                "https://evil/vi/Abc_123-XYZ/hqdefault.jpg", "https://i.ytimg.com@evil/a.jpg",
                "https://i.ytimg.com/vi/Abc_123-XYZ/hqdefault.jpg?token=private",
                "https://i.ytimg.com/vi/../hqdefault.jpg")) assertFalse(ThumbnailStore.allowed(url));
    }

    @Test public void responsesHaveAHardSizeLimit() throws Exception {
        byte[] bytes = new byte[ThumbnailStore.MAX_IMAGE_BYTES];
        assertEquals(bytes.length, ThumbnailStore.readBounded(new ByteArrayInputStream(bytes)).length);
        try {
            ThumbnailStore.readBounded(new ByteArrayInputStream(new byte[bytes.length + 1]));
            fail("Oversized artwork accepted");
        } catch (IOException expected) { /* bounded */ }
    }

    @Test public void cachedArtworkWorksWithoutNetwork() throws Exception {
        File directory = temporary.newFolder();
        File cached = new File(directory, "Abc_123-XYZ.jpg");
        byte[] bytes = new byte[]{1, 2, 3};
        Files.write(cached.toPath(), bytes);
        assertArrayEquals(bytes, new ThumbnailStore(directory).load(
                "https://i.ytimg.com/vi/Abc_123-XYZ/hqdefault.jpg"));
    }

    @Test public void evictionIsBoundedAndLeavesUnrelatedFilesAlone() throws Exception {
        File directory = temporary.newFolder();
        File unrelated = new File(directory, "unrelated");
        Files.write(unrelated.toPath(), new byte[]{1});
        for (int i = 0; i < 10; i++) {
            File file = new File(directory, String.format("%011d.jpg", i));
            Files.write(file.toPath(), new byte[ThumbnailStore.MAX_IMAGE_BYTES]);
            file.setLastModified(i + 1);
        }
        new ThumbnailStore(directory).trim();
        assertFalse(new File(directory, "00000000000.jpg").exists());
        assertTrue(new File(directory, "00000000009.jpg").exists());
        assertTrue(unrelated.exists());
        long total = 0;
        for (File file : directory.listFiles()) if (!file.equals(unrelated)) total += file.length();
        assertTrue(total <= ThumbnailStore.MAX_CACHE_BYTES);
    }
}
