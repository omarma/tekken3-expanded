package org.psxrecomp;

import android.app.Activity;
import android.graphics.Insets;
import android.os.Build;
import android.view.DisplayCutout;
import android.view.View;
import android.view.WindowInsets;
import android.view.WindowManager;

import java.util.Arrays;

/**
 * The part of the screen clear of a display cutout (a notch or a punch hole,
 * and a curved "waterfall" edge). The game stays full screen and draws under
 * the cutout; its on-screen buttons, and the game's picture when it would
 * reach into the cutout, keep to the safe area (touch_controls.c), and so do
 * the screens drawn over the game (the launcher, the in-game menu, the
 * layout editor). The status and navigation bars are hidden (immersive), so
 * only the cutout counts.
 */
public final class SafeArea {
    private static int[] sSent;

    private SafeArea() {}

    /** The cutout's insets on v's window, in pixels: left, top, right, bottom. */
    public static int[] insets(View v) {
        int[] out = new int[4];
        WindowInsets wi = v.getRootWindowInsets();
        DisplayCutout c = wi != null ? wi.getDisplayCutout() : null;
        if (c == null) return out;
        out[0] = c.getSafeInsetLeft();
        out[1] = c.getSafeInsetTop();
        out[2] = c.getSafeInsetRight();
        out[3] = c.getSafeInsetBottom();
        if (Build.VERSION.SDK_INT >= 30) {
            Insets w = c.getWaterfallInsets();
            out[0] = Math.max(out[0], w.left);
            out[1] = Math.max(out[1], w.top);
            out[2] = Math.max(out[2], w.right);
            out[3] = Math.max(out[3], w.bottom);
        }
        return out;
    }

    /**
     * Lets the game draw under the cutout on every Android version, and keeps
     * the runtime told where the safe area is. The activity calls it once,
     * after its native library is loaded.
     */
    public static void watch(Activity activity) {
        // Android 11+ gets this from SDL when it goes full screen; 9 and 10
        // would otherwise letterbox the whole window away from the cutout.
        if (Build.VERSION.SDK_INT < 30) {
            WindowManager.LayoutParams lp = activity.getWindow().getAttributes();
            lp.layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES;
            activity.getWindow().setAttributes(lp);
        }
        final View decor = activity.getWindow().getDecorView();
        // New insets (turning the phone over moves the cutout to the other side).
        decor.setOnApplyWindowInsetsListener((v, in) -> {
            WindowInsets out = v.onApplyWindowInsets(in);
            v.post(() -> publish(v));
            return out;
        });
        decor.addOnLayoutChangeListener((v, l, t, r, b, ol, ot, or, ob) -> publish(v));
        decor.post(() -> publish(decor));
    }

    private static void publish(View decor) {
        final int w = decor.getWidth(), h = decor.getHeight();
        if (w <= 0 || h <= 0) return;
        int[] in = insets(decor);
        int[] key = { in[0], in[1], in[2], in[3], w, h };
        if (Arrays.equals(key, sSent)) return;
        sSent = key;
        nativeSetSafeArea(in[0] / (float) w, in[1] / (float) h, in[2] / (float) w, in[3] / (float) h);
    }

    /** Pads v by the cutout's insets (on top of its own padding), now and when they change. */
    public static void pad(final View v) {
        final int[] base = { v.getPaddingLeft(), v.getPaddingTop(), v.getPaddingRight(), v.getPaddingBottom() };
        final Runnable apply = () -> {
            int[] in = insets(v);
            int l = base[0] + in[0], t = base[1] + in[1], r = base[2] + in[2], b = base[3] + in[3];
            if (l != v.getPaddingLeft() || t != v.getPaddingTop()
                    || r != v.getPaddingRight() || b != v.getPaddingBottom()) {
                v.setPadding(l, t, r, b);
            }
        };
        v.addOnAttachStateChangeListener(new View.OnAttachStateChangeListener() {
            @Override public void onViewAttachedToWindow(View view) { view.post(apply); }
            @Override public void onViewDetachedFromWindow(View view) {}
        });
        v.setOnApplyWindowInsetsListener((view, in) -> {
            view.post(apply);
            return view.onApplyWindowInsets(in);
        });
        if (v.isAttachedToWindow()) v.post(apply);
    }

    static native void nativeSetSafeArea(float left, float top, float right, float bottom);
}
