package org.psxrecomp;

import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RectF;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Locale;

/**
 * The on-screen buttons' settings (touch_controls.ini beside the runtime,
 * read by psxrecomp's touch_controls.c) and their shapes, for the launcher's
 * Touch page and the layout editor. Each button has its own place (its
 * centre, as fractions of the safe area: the screen less a display cutout's
 * insets, see SafeArea), size and whether it shows. The sizes and the look
 * are those of touch_controls.c (RetroArch's "flat" PSX overlay), in
 * fractions of the safe area's height.
 */
public final class TouchLayout {
    public static final int DPAD = 0, TRIANGLE = 1, CIRCLE = 2, CROSS = 3, SQUARE = 4,
            L1 = 5, L2 = 6, R1 = 7, R2 = 8, SELECT = 9, START = 10, COUNT = 11;
    static final String[] KEYS = { "dpad", "triangle", "circle", "cross", "square",
            "l1", "l2", "r1", "r2", "select", "start" };
    public static final String[] NAMES = { "D-pad", "Triangle", "Circle", "Cross", "Square",
            "L1", "L2", "R1", "R2", "Select", "Start" };
    // touch_controls.c kDefaults: RetroArch's flat PSX overlay on a 20:9 phone.
    private static final float[][] DEFAULTS = {
            { 0.125f, 0.780f }, { 0.875f, 0.669f }, { 0.925f, 0.780f }, { 0.875f, 0.891f },
            { 0.825f, 0.780f }, { 0.049f, 0.490f }, { 0.049f, 0.300f }, { 0.951f, 0.490f },
            { 0.951f, 0.300f }, { 0.450f, 0.925f }, { 0.550f, 0.925f } };
    public static final float MIN_SCALE = 0.4f, MAX_SCALE = 3.0f;

    public final File file;
    public boolean visible = true;
    public int opacity = 70, size = 100;
    public int stick = 0;   // the D-pad as 0 a cross, 1 a joystick, 2 a floating joystick
    public int neutral = 35;   // the neutral middle, percent of the D-pad's reach
    public final float[] x = new float[COUNT], y = new float[COUNT], scale = new float[COUNT];
    public final boolean[] shown = new boolean[COUNT];
    /** The display cutout's insets in pixels (left, top, right, bottom): the buttons stay inside. */
    public final int[] insets = new int[4];

    public TouchLayout(File file) {
        this.file = file;
        resetLayout();
        load();
    }

    /** Every button back where it starts, at its size, shown. */
    public void resetLayout() {
        for (int i = 0; i < COUNT; i++) reset(i);
    }

    /** Button i back where it starts, at its size, shown. */
    public void reset(int i) {
        x[i] = DEFAULTS[i][0];
        y[i] = DEFAULTS[i][1];
        scale[i] = 1f;
        shown[i] = true;
    }

    private void load() {
        String text;
        try {
            text = new String(Files.readAllBytes(file.toPath()), StandardCharsets.UTF_8);
        } catch (IOException | RuntimeException e) {
            return;   // no file yet: the defaults
        }
        for (String line : text.split("\n")) {
            String[] kv = line.split("=", 2);
            if (kv.length != 2 || line.startsWith(";")) continue;
            String key = kv[0].trim();
            String[] v = kv[1].trim().split(",");
            try {
                int item = -1;
                for (int i = 0; i < COUNT; i++) if (KEYS[i].equals(key)) item = i;
                if (item >= 0 && v.length == 4) {
                    x[item] = clamp(Float.parseFloat(v[0].trim()), 0f, 1f);
                    y[item] = clamp(Float.parseFloat(v[1].trim()), 0f, 1f);
                    scale[item] = clamp(Float.parseFloat(v[2].trim()), MIN_SCALE, MAX_SCALE);
                    shown[item] = Integer.parseInt(v[3].trim()) != 0;
                    continue;
                }
                float f = Float.parseFloat(v[0].trim());
                switch (key) {
                    case "visible": visible = f != 0; break;
                    case "opacity": opacity = Math.max(10, Math.min(100, (int) f)); break;
                    case "size": size = Math.max(50, Math.min(160, (int) f)); break;
                    case "stick": stick = Math.max(0, Math.min(2, (int) f)); break;
                    case "neutral": neutral = Math.max(10, Math.min(60, (int) f)); break;
                    default: break;
                }
            } catch (NumberFormatException e) {
                // a line this version does not read
            }
        }
    }

    public void save() {
        StringBuilder s = new StringBuilder(String.format(Locale.ROOT,
                "; On-screen buttons (the launcher's Touch page and its layout editor)\n"
                + "visible=%d\nopacity=%d\nsize=%d\nstick=%d\nneutral=%d\n",
                visible ? 1 : 0, opacity, size, stick, neutral));
        for (int i = 0; i < COUNT; i++) {
            s.append(String.format(Locale.ROOT, "%s=%.4f,%.4f,%.2f,%d\n",
                    KEYS[i], x[i], y[i], scale[i], shown[i] ? 1 : 0));
        }
        try (FileOutputStream out = new FileOutputStream(file)) {
            out.write(s.toString().getBytes(StandardCharsets.UTF_8));
        } catch (IOException e) {
            // the settings stay as they were
        }
    }

    // ---- geometry (touch_controls.c compute_layout) --------------------------------
    /** The safe area's width and height on a w x h screen. */
    public float areaW(int w) {
        float a = w - insets[0] - insets[2];
        return a >= 1f ? a : w;
    }

    public float areaH(int h) {
        float a = h - insets[1] - insets[3];
        return a >= 1f ? a : h;
    }

    private float areaX(int w) {
        return areaW(w) == w ? 0f : insets[0];
    }

    private float areaY(int h) {
        return areaH(h) == h ? 0f : insets[1];
    }

    /** The button's size unit in pixels on a screen h pixels high. */
    public float unit(int i, int h) {
        return areaH(h) * size / 100f * scale[i];
    }

    /** Half width and half height of the button's box. */
    public float[] half(int i, int h) {
        float u = unit(i, h);
        switch (i) {
            case DPAD: { float e = (stick != 0 ? 0.150f : 0.170f) * u; return new float[] { e, e }; }
            case TRIANGLE: case CIRCLE: case CROSS: case SQUARE: return new float[] { 0.066f * u, 0.066f * u };
            case SELECT: return new float[] { 0.062f * u, 0.034f * u };
            case START: return new float[] { 0.062f * u, 0.040f * u };
            default: return new float[] { 0.085f * u, 0.085f * u };
        }
    }

    /** The button's centre on a w x h screen, kept in the safe area. */
    public float cx(int i, int w, int h) {
        float hw = half(i, h)[0], aw = areaW(w);
        return areaX(w) + clamp(x[i] * aw, hw, aw - hw);
    }

    public float cy(int i, int w, int h) {
        float hh = half(i, h)[1], ah = areaH(h);
        return areaY(h) + clamp(y[i] * ah, hh, ah - hh);
    }

    /** Places button i with its centre at (px, py) on a w x h screen, kept in the safe area. */
    public void moveTo(int i, float px, float py, int w, int h) {
        x[i] = clamp((px - areaX(w)) / areaW(w), 0f, 1f);
        y[i] = clamp((py - areaY(h)) / areaH(h), 0f, 1f);
        // Stored where it shows (the runtime keeps it in the area the same way).
        x[i] = (cx(i, w, h) - areaX(w)) / areaW(w);
        y[i] = (cy(i, w, h) - areaY(h)) / areaH(h);
    }

    public RectF bounds(int i, int w, int h) {
        float[] hs = half(i, h);
        float cx = cx(i, w, h), cy = cy(i, w, h);
        return new RectF(cx - hs[0], cy - hs[1], cx + hs[0], cy + hs[1]);
    }

    // ---- drawing (the flat look of touch_controls.c) ------------------------------------
    private final Paint fill = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint line = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint ink = new Paint(Paint.ANTI_ALIAS_FLAG);

    {
        line.setStyle(Paint.Style.STROKE);
        ink.setStrokeCap(Paint.Cap.ROUND);
        ink.setStrokeJoin(Paint.Join.ROUND);
        ink.setTextAlign(Paint.Align.CENTER);
    }

    private static int white(float a) {
        return Color.argb(Math.round(Math.max(0f, Math.min(1f, a)) * 255), 255, 255, 255);
    }

    /** Draws button i on a w x h screen, a its opacity (0..1). */
    public void draw(Canvas c, int i, int w, int h, float a) {
        final float u = unit(i, h), cx = cx(i, w, h), cy = cy(i, w, h);
        fill.setStyle(Paint.Style.FILL);
        fill.setColor(Color.argb(Math.round(0.12f * a * 255), 0, 0, 0));
        line.setColor(white(0.9f * a));
        line.setStrokeWidth(Math.max(1.5f, 0.0045f * u));
        ink.setColor(white(0.95f * a));
        switch (i) {
            case DPAD:
                if (stick != 0) {
                    line.setStrokeWidth(Math.max(1.2f, 0.0035f * u));
                    c.drawCircle(cx, cy, 0.150f * u, line);
                    line.setStrokeWidth(Math.max(2f, 0.0075f * u));
                    c.drawCircle(cx, cy, 0.068f * u, fill);
                    c.drawCircle(cx, cy, 0.068f * u, line);
                } else {
                    dpad(c, cx, cy, u);
                }
                break;
            case TRIANGLE: case CIRCLE: case CROSS: case SQUARE:
                face(c, i, cx, cy, 0.066f * u, u);
                break;
            case SELECT:
                line.setStrokeWidth(Math.max(1.2f, 0.0035f * u));
                c.drawRect(cx - 0.062f * u, cy - 0.034f * u, cx + 0.062f * u, cy + 0.034f * u, fill);
                c.drawRect(cx - 0.062f * u, cy - 0.034f * u, cx + 0.062f * u, cy + 0.034f * u, line);
                break;
            case START: {
                line.setStrokeWidth(Math.max(1.2f, 0.0035f * u));
                Path p = new Path();
                p.moveTo(cx - 0.062f * u, cy - 0.040f * u);
                p.lineTo(cx + 0.062f * u, cy);
                p.lineTo(cx - 0.062f * u, cy + 0.040f * u);
                p.close();
                c.drawPath(p, fill);
                c.drawPath(p, line);
                break;
            }
            default: {   // L1 L2 R1 R2
                float s = 0.085f * u, r = 0.018f * u;
                RectF box = new RectF(cx - s, cy - s, cx + s, cy + s);
                c.drawRoundRect(box, r, r, fill);
                c.drawRoundRect(box, r, r, line);
                ink.setStyle(Paint.Style.FILL);
                ink.setTextSize(s * 0.75f);
                c.drawText(NAMES[i], cx, cy - (ink.descent() + ink.ascent()) / 2, ink);
                break;
            }
        }
    }

    private void dpad(Canvas c, float cx, float cy, float u) {
        float hw = 0.063f * u, hl = 0.073f * u, off = 0.094f * u;
        line.setStrokeWidth(Math.max(1.2f, 0.0035f * u));
        ink.setStyle(Paint.Style.FILL);
        for (int k = 0; k < 4; k++) {
            c.save();
            c.translate(cx, cy);
            c.rotate(90 * k);
            c.translate(0, -off);
            Path p = new Path();   // a pentagon pointing at the middle
            p.moveTo(-hw, -hl); p.lineTo(hw, -hl); p.lineTo(hw, hl - hw);
            p.lineTo(0, hl); p.lineTo(-hw, hl - hw); p.close();
            c.drawPath(p, fill);
            c.drawPath(p, line);
            float ar = 0.021f * u, ay = -hl * 0.42f;
            Path t = new Path();   // a small arrow pointing out
            t.moveTo(0, ay - ar); t.lineTo(ar * 0.87f, ay + ar * 0.5f); t.lineTo(-ar * 0.87f, ay + ar * 0.5f);
            t.close();
            c.drawPath(t, ink);
            c.restore();
        }
    }

    private void face(Canvas c, int i, float cx, float cy, float r, float u) {
        c.drawCircle(cx, cy, r, fill);
        c.drawCircle(cx, cy, r, line);
        ink.setStyle(Paint.Style.STROKE);
        ink.setStrokeWidth(Math.max(1f, 0.012f * u));
        switch (i) {
            case TRIANGLE: {
                Path t = new Path();
                for (int k = 0; k < 3; k++) {
                    double an = Math.toRadians(-90 + 120 * k);
                    float px = cx + (float) Math.cos(an) * r * 0.5f;
                    float py = cy + r * 0.1f + (float) Math.sin(an) * r * 0.5f;
                    if (k == 0) t.moveTo(px, py); else t.lineTo(px, py);
                }
                t.close();
                c.drawPath(t, ink);
                break;
            }
            case CIRCLE: c.drawCircle(cx, cy, r * 0.43f, ink); break;
            case CROSS:
                c.drawLine(cx - r * 0.38f, cy - r * 0.38f, cx + r * 0.38f, cy + r * 0.38f, ink);
                c.drawLine(cx - r * 0.38f, cy + r * 0.38f, cx + r * 0.38f, cy - r * 0.38f, ink);
                break;
            default: {
                float s = r * 0.354f;
                c.drawRect(cx - s, cy - s, cx + s, cy + s, ink);
                break;
            }
        }
    }

    static float clamp(float v, float lo, float hi) {
        return Math.max(lo, Math.min(hi, v));
    }
}
