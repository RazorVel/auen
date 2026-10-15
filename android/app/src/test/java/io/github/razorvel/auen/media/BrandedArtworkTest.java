package io.github.razorvel.auen.media;

import org.junit.Test;
import static org.junit.Assert.*;

public class BrandedArtworkTest {
    @Test public void squareCropIsCenteredForWideTallAndSquarePictures() {
        assertArrayEquals(new int[]{60, 0, 420, 360}, BrandedArtwork.centerCrop(480, 360));
        assertArrayEquals(new int[]{0, 60, 360, 420}, BrandedArtwork.centerCrop(360, 480));
        assertArrayEquals(new int[]{0, 0, 512, 512}, BrandedArtwork.centerCrop(512, 512));
    }

    @Test public void wordmarkIsSmallPaddedAndCenteredWithoutDistortion() {
        float[] bounds = BrandedArtwork.wordmarkBounds(285, 85);
        float width = bounds[2] - bounds[0];
        float height = bounds[3] - bounds[1];
        assertEquals(285f / 85f, width / height, 0.0001f);
        assertEquals(BrandedArtwork.SIZE * 0.26f, width, 0.001f);
        assertEquals(BrandedArtwork.SIZE / 2f, (bounds[0] + bounds[2]) / 2f, 0.001f);
        assertEquals(BrandedArtwork.SIZE / 2f, (bounds[1] + bounds[3]) / 2f, 0.001f);
        assertTrue(bounds[0] > BrandedArtwork.PADDING);
        assertTrue(bounds[3] + BrandedArtwork.PADDING < BrandedArtwork.SIZE);
    }

    @Test public void onlyMissingThumbnailsShowTheWordmark() {
        assertTrue(BrandedArtwork.showWordmark(false, true));
        assertFalse(BrandedArtwork.showWordmark(true, true));
        assertFalse(BrandedArtwork.showWordmark(true, false));
        assertFalse(BrandedArtwork.showWordmark(false, false));
    }

    @Test public void tallArtworkCannotMakeAnOversizedBadge() {
        float[] bounds = BrandedArtwork.wordmarkBounds(85, 285);
        assertEquals(BrandedArtwork.SIZE * 0.10f, bounds[3] - bounds[1], 0.001f);
        assertTrue(bounds[2] > bounds[0]);
    }

    @Test public void invalidImageSizesAreRejected() {
        try { BrandedArtwork.centerCrop(0, 100); fail("Zero width accepted"); }
        catch (IllegalArgumentException expected) { /* bounded input */ }
        try { BrandedArtwork.wordmarkBounds(100, -1); fail("Negative height accepted"); }
        catch (IllegalArgumentException expected) { /* bounded input */ }
    }
}
