package org.psxrecomp;

import android.app.Activity;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.DashPathEffect;
import android.graphics.Paint;
import android.graphics.RectF;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.StateListDrawable;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewGroup;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.io.File;

/**
 * The layout editor for the on-screen buttons, full screen: every button
 * where the game draws it. Touch a button to select it (it lights up), drag
 * it to move it, pinch or use - / + to size it, Hide to take it off the
 * screen (it stays here, faded, to bring it back). Done saves
 * touch_controls.ini; the launcher's Touch page and the in-game menu open it.
 * The buttons keep clear of a display cutout as in the game (SafeArea).
 */
public final class TouchEditor extends FrameLayout {
    private static final int BG = 0xFF0B0D12;
    private static final int GAME = 0xFF2A1512;
    private static final int BAR = 0xE61B1F2B;
    private static final int CONTROL = 0xFF262B3A;
    private static final int TEXT = 0xFFECECF2;
    private static final int MUTED = 0xFF9AA0B4;
    private static final int ACCENT = 0xFF6E56CF;
    private static final int SELECT = 0xFFFFC857;

    private static TouchEditor sShowing;

    private final Activity activity;
    private final TouchLayout layout;
    private final Runnable onClose;
    private final Board board;
    private final LinearLayout bar;
    private int selected = -1;

    public static boolean isShowing() {
        return sShowing != null;
    }

    /** Opens the editor over everything; onClose runs after Done saved. */
    public static void show(Activity activity, Runnable onClose) {
        if (sShowing != null) return;
        sShowing = new TouchEditor(activity, onClose);
        activity.addContentView(sShowing, new ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        sShowing.requestFocus();
    }

    private TouchEditor(Activity activity, Runnable onClose) {
        super(activity);
        this.activity = activity;
        this.onClose = onClose;
        layout = new TouchLayout(new File(activity.getFilesDir(), "touch_controls.ini"));
        setFocusable(true);
        setFocusableInTouchMode(true);
        board = new Board();
        addView(board, new LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        bar = new LinearLayout(activity);
        bar.setGravity(Gravity.CENTER_VERTICAL);
        bar.setPadding(dp(10), dp(6), dp(10), dp(6));
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(BAR);
        bg.setCornerRadius(dp(14));
        bar.setBackground(bg);
        LayoutParams lp = new LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, dp(56),
                Gravity.TOP | Gravity.CENTER_HORIZONTAL);
        lp.topMargin = dp(8);
        addView(bar, lp);
        refreshBar();
    }

    @Override
    public boolean dispatchKeyEvent(KeyEvent event) {
        if (event.getKeyCode() == KeyEvent.KEYCODE_BACK) {   // Back = Done
            if (event.getAction() == KeyEvent.ACTION_UP) done();
            return true;
        }
        return super.dispatchKeyEvent(event);
    }

    private void done() {
        if (sShowing != this) return;
        layout.save();
        sShowing = null;
        if (getParent() instanceof ViewGroup) ((ViewGroup) getParent()).removeView(this);
        if (onClose != null) onClose.run();
    }

    // ---- the tool bar: what the selected button can do -------------------------------
    private void refreshBar() {
        bar.removeAllViews();
        if (selected < 0) {
            TextView hint = text("Touch a button to select it", MUTED);
            hint.setPadding(dp(6), 0, dp(12), 0);
            bar.addView(hint);
            action("Reset all", () -> { layout.resetLayout(); selected = -1; refreshBar(); board.invalidate(); });
        } else {
            TextView name = text(TouchLayout.NAMES[selected], TEXT);
            name.setPadding(dp(6), 0, dp(10), 0);
            bar.addView(name);
            action("−", () -> resize(1f / 1.1f));
            TextView pct = text(Math.round(layout.scale[selected] * 100) + "%", TEXT);
            pct.setGravity(Gravity.CENTER);
            bar.addView(pct, new LinearLayout.LayoutParams(dp(56), ViewGroup.LayoutParams.MATCH_PARENT));
            action("+", () -> resize(1.1f));
            action(layout.shown[selected] ? "Hide" : "Show", () -> {
                layout.shown[selected] = !layout.shown[selected];
                refreshBar();
                board.invalidate();
            });
            action("Reset", () -> { layout.reset(selected); refreshBar(); board.invalidate(); });
        }
        action("Done", this::done);
    }

    private void resize(float factor) {
        if (selected < 0) return;
        layout.scale[selected] = TouchLayout.clamp(layout.scale[selected] * factor,
                TouchLayout.MIN_SCALE, TouchLayout.MAX_SCALE);
        refreshBar();
        board.invalidate();
    }

    private void action(String label, Runnable run) {
        TextView b = text(label, TEXT);
        b.setGravity(Gravity.CENTER);
        b.setPadding(dp(14), 0, dp(14), 0);
        StateListDrawable s = new StateListDrawable();
        GradientDrawable down = new GradientDrawable();
        down.setColor(ACCENT);
        down.setCornerRadius(dp(10));
        GradientDrawable normal = new GradientDrawable();
        normal.setColor(CONTROL);
        normal.setCornerRadius(dp(10));
        s.addState(new int[] { android.R.attr.state_pressed }, down);
        s.addState(new int[] {}, normal);
        b.setBackground(s);
        b.setMinWidth(dp(44));
        b.setOnClickListener(v -> run.run());
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.MATCH_PARENT);
        lp.leftMargin = dp(6);
        bar.addView(b, lp);
    }

    private TextView text(String s, int color) {
        TextView t = new TextView(activity);
        t.setText(s);
        t.setTextColor(color);
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15);
        t.setGravity(Gravity.CENTER_VERTICAL);
        return t;
    }

    private int dp(float v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }

    // ---- the screen with the buttons ----------------------------------------------------
    private final class Board extends View {
        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint mark = new Paint(Paint.ANTI_ALIAS_FLAG);
        private float grabX, grabY;           // finger to centre, while moving
        private float pinchStart, scaleStart; // while pinching
        private boolean pinching;

        Board() {
            super(activity);
            mark.setStyle(Paint.Style.STROKE);
        }

        /** Takes the cutout's insets (where the buttons may go), as the game does. */
        private void syncInsets() {
            int[] in = SafeArea.insets(this);
            if (java.util.Arrays.equals(in, layout.insets)) return;
            System.arraycopy(in, 0, layout.insets, 0, 4);
            LayoutParams lp = (LayoutParams) bar.getLayoutParams();
            lp.topMargin = dp(8) + in[1];
            bar.setLayoutParams(lp);
        }

        @Override
        protected void onDraw(Canvas c) {
            syncInsets();
            final int w = getWidth(), h = getHeight();
            c.drawColor(BG);
            paint.setColor(GAME);   // where the game's picture is (4:3, in the middle)
            c.drawRect(gameRect(w, h), paint);
            final float a = layout.opacity / 100f;
            for (int i = 0; i < TouchLayout.COUNT; i++) {
                layout.draw(c, i, w, h, layout.shown[i] ? Math.max(a, 0.6f) : 0.22f);
                if (!layout.shown[i]) {   // a hidden button: dashed, to bring back
                    mark.setColor(0x99FFFFFF);
                    mark.setStrokeWidth(dp(1.5f));
                    mark.setPathEffect(new DashPathEffect(new float[] { dp(6), dp(5) }, 0));
                    RectF r = layout.bounds(i, w, h);
                    c.drawRect(r, mark);
                    mark.setPathEffect(null);
                }
            }
            if (selected >= 0) {
                RectF r = layout.bounds(selected, w, h);
                r.inset(-dp(6), -dp(6));
                paint.setColor(Color.argb(40, 255, 200, 87));
                c.drawRoundRect(r, dp(10), dp(10), paint);
                mark.setColor(SELECT);
                mark.setStrokeWidth(dp(3));
                c.drawRoundRect(r, dp(10), dp(10), mark);
            }
        }

        /** The game's 4:3 picture: centred, or in the safe area when it would reach into a cutout
         *  (gpu_gl_renderer.c letterbox_rect_aspect). */
        private RectF gameRect(int w, int h) {
            float gw = Math.min(w, h * 4f / 3f), gh = gw * 3f / 4f;
            RectF r = new RectF((w - gw) / 2, (h - gh) / 2, (w + gw) / 2, (h + gh) / 2);
            int[] in = layout.insets;
            int tb = Math.max(in[1], in[3]);
            if (r.left >= in[0] && r.right <= w - in[2] && r.top >= tb) return r;
            float sw = w - in[0] - in[2], sh = h - 2 * tb;
            if (sw <= 0 || sh <= 0) return r;
            gw = Math.min(sw, sh * 4f / 3f);
            gh = gw * 3f / 4f;
            float x = in[0] + (sw - gw) / 2, y = tb + (sh - gh) / 2;
            return new RectF(x, y, x + gw, y + gh);
        }

        /** The button under (x, y), the smallest one first. */
        private int hit(float x, float y) {
            int best = -1;
            float area = Float.MAX_VALUE;
            for (int i = 0; i < TouchLayout.COUNT; i++) {
                RectF r = layout.bounds(i, getWidth(), getHeight());
                r.inset(-dp(8), -dp(8));
                if (r.contains(x, y) && r.width() * r.height() < area) {
                    area = r.width() * r.height();
                    best = i;
                }
            }
            return best;
        }

        @Override
        public boolean onTouchEvent(MotionEvent e) {
            syncInsets();
            final int w = getWidth(), h = getHeight();
            switch (e.getActionMasked()) {
                case MotionEvent.ACTION_DOWN: {
                    selected = hit(e.getX(), e.getY());
                    pinching = false;
                    if (selected >= 0) {
                        grabX = layout.cx(selected, w, h) - e.getX();
                        grabY = layout.cy(selected, w, h) - e.getY();
                    }
                    refreshBar();
                    invalidate();
                    return true;
                }
                case MotionEvent.ACTION_POINTER_DOWN:
                    if (selected >= 0 && e.getPointerCount() == 2) {
                        pinching = true;
                        pinchStart = spread(e);
                        scaleStart = layout.scale[selected];
                    }
                    return true;
                case MotionEvent.ACTION_MOVE:
                    if (selected < 0) return true;
                    if (pinching && e.getPointerCount() >= 2) {
                        float d = spread(e);
                        if (pinchStart > 1f) {
                            layout.scale[selected] = TouchLayout.clamp(scaleStart * d / pinchStart,
                                    TouchLayout.MIN_SCALE, TouchLayout.MAX_SCALE);
                            refreshBar();
                        }
                    } else if (!pinching) {
                        layout.moveTo(selected, e.getX() + grabX, e.getY() + grabY, w, h);
                    }
                    invalidate();
                    return true;
                case MotionEvent.ACTION_UP:
                case MotionEvent.ACTION_CANCEL:
                    pinching = false;
                    return true;
                default:
                    return true;
            }
        }

        private float spread(MotionEvent e) {
            float dx = e.getX(0) - e.getX(1), dy = e.getY(0) - e.getY(1);
            return (float) Math.sqrt(dx * dx + dy * dy);
        }
    }
}
