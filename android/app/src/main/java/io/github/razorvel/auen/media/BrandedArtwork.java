package io.github.razorvel.auen.media;

import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Rect;
import android.graphics.RectF;

/** Compose notification artwork, not the source assets or cached thumbnails. */
final class BrandedArtwork {
    static final int SIZE = 512;
    static final int BACKGROUND = 0xFFEAE7E2; // Warm off-white, not a gray placeholder.
    static final int BADGE = 0xF220242C;      // High contrast for the white source wordmark.
    static final float PADDING = 12f;

    static Bitmap render(Bitmap thumbnail, Bitmap wordmark) {
        Bitmap result = Bitmap.createBitmap(SIZE, SIZE, Bitmap.Config.ARGB_8888);
        Canvas canvas = new Canvas(result);
        Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG | Paint.FILTER_BITMAP_FLAG);
        canvas.drawColor(BACKGROUND);
        if (thumbnail != null) {
            int[] crop = centerCrop(thumbnail.getWidth(), thumbnail.getHeight());
            canvas.drawBitmap(thumbnail, new Rect(crop[0], crop[1], crop[2], crop[3]),
                    new Rect(0, 0, SIZE, SIZE), paint);
        }
        if (showWordmark(thumbnail != null, wordmark != null)) {
            float[] bounds = wordmarkBounds(wordmark.getWidth(), wordmark.getHeight());
            RectF mark = new RectF(bounds[0], bounds[1], bounds[2], bounds[3]);
            paint.setColor(BADGE);
            canvas.drawRoundRect(new RectF(mark.left - PADDING, mark.top - PADDING,
                    mark.right + PADDING, mark.bottom + PADDING), 12f, 12f, paint);
            paint.setColor(0xFFFFFFFF);
            canvas.drawBitmap(wordmark, null, mark, paint);
        }
        return result;
    }

    static boolean showWordmark(boolean hasThumbnail, boolean hasWordmark) {
        return !hasThumbnail && hasWordmark;
    }

    static int[] centerCrop(int width, int height) {
        if (width <= 0 || height <= 0) throw new IllegalArgumentException("Invalid artwork size");
        int side = Math.min(width, height);
        int left = (width - side) / 2;
        int top = (height - side) / 2;
        return new int[]{left, top, left + side, top + side};
    }

    static float[] wordmarkBounds(int width, int height) {
        if (width <= 0 || height <= 0) throw new IllegalArgumentException("Invalid wordmark size");
        float scale = Math.min(SIZE * 0.26f / width, SIZE * 0.10f / height);
        float left = (SIZE - width * scale) / 2f;
        float top = (SIZE - height * scale) / 2f;
        return new float[]{left, top, left + width * scale, top + height * scale};
    }
}
