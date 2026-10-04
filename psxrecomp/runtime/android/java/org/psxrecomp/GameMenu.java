package org.psxrecomp;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.Drawable;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.StateListDrawable;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.view.ViewGroup;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.io.File;
import java.io.RandomAccessFile;
import java.nio.charset.StandardCharsets;

/**
 * The in-game menu: what the desktop does with keys (pause, F1-F12 save
 * states, closing the window), on a phone that has none. Back or a pad's
 * Home/Mode button opens it; the game waits at the next frame while it is
 * open (android_main.c). Back to launcher quits the game and starts the app
 * again on the launcher screens, so the next PLAY starts a new game.
 */
public final class GameMenu extends FrameLayout {
    private static final int SLOTS = 4;
    private static final int SCRIM = 0xCC06070B;
    private static final int CARD = 0xFF1B1F2B;
    private static final int CONTROL = 0xFF262B3A;
    private static final int BORDER = 0xFF30364A;
    private static final int TEXT = 0xFFECECF2;
    private static final int ACCENT = 0xFF6E56CF;
    private static final int FOCUS = 0xFF58C4F0;

    private static GameMenu sShowing;

    private final Activity activity;
    private final LinearLayout card;

    /** True for the keys that open the menu. */
    public static boolean isMenuKey(int keyCode) {
        return keyCode == KeyEvent.KEYCODE_BACK || keyCode == KeyEvent.KEYCODE_BUTTON_MODE;
    }

    public static boolean isShowing() {
        return sShowing != null;
    }

    /** Opens the menu over the game and pauses it. */
    public static void show(Activity activity) {
        if (sShowing != null) return;
        nativeSetPaused(true);
        sShowing = new GameMenu(activity);
        activity.addContentView(sShowing, new ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        sShowing.main();
    }

    private GameMenu(Activity activity) {
        super(activity);
        this.activity = activity;
        setBackgroundColor(SCRIM);
        setClickable(true);
        card = new LinearLayout(activity);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setPadding(dp(24), dp(20), dp(24), dp(20));
        card.setBackground(box(CARD, BORDER, dp(16)));
        // Scrolls when the phone is too short for it (landscape).
        ScrollView scroll = new ScrollView(activity);
        scroll.setFillViewport(false);
        scroll.addView(card);
        addView(scroll, new LayoutParams(dp(360), ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.CENTER));
        SafeArea.pad(this);   // centred clear of a notch; the scrim still covers it
    }

    @Override
    public boolean dispatchKeyEvent(KeyEvent event) {
        // Back / Mode again closes the menu and resumes.
        if (isMenuKey(event.getKeyCode())) {
            if (event.getAction() == KeyEvent.ACTION_UP) close();
            return true;
        }
        return super.dispatchKeyEvent(event);
    }

    private void main() {
        card.removeAllViews();
        card.addView(title("Paused"));
        button("Resume", this::close);
        button("Save state", () -> slots(true));
        button("Load state", () -> slots(false));
        button("Back to launcher", () -> {
            // The game quits (memory cards saved), then the app starts again on
            // the launcher, in a new process (android_main.c calls the
            // activity's relaunchOnLauncher()): a new game from scratch,
            // whatever the launcher changes.
            nativeBackToLauncher();
            close();
            nativeQuit();
        });
        button("Quit game", () -> {
            close();
            nativeQuit();
        });
        button("Touch controls layout", () -> TouchEditor.show(activity, () -> {
            nativeReloadTouch();   // the game draws the new layout from now on
            focusFirst();
        }));
        button("Share log", this::shareLog);
        TextView status = new TextView(activity);
        status.setText(nativeStatus());
        status.setTextColor(0xFF9AA0B4);
        status.setTextSize(TypedValue.COMPLEX_UNIT_SP, 11);
        status.setTextIsSelectable(true);
        status.setPadding(0, dp(6), 0, 0);
        card.addView(status);
        focusFirst();
    }

    /** Sends the status and this run's log (its end) to another app. */
    private void shareLog() {
        StringBuilder text = new StringBuilder(nativeStatus()).append("\n\n");
        File log = new File(activity.getFilesDir(), "psxrecomp.log");
        try (RandomAccessFile f = new RandomAccessFile(log, "r")) {
            long size = f.length(), from = Math.max(0, size - 60000);
            byte[] bytes = new byte[(int) (size - from)];
            f.seek(from);
            f.readFully(bytes);
            text.append(new String(bytes, StandardCharsets.UTF_8));
        } catch (Exception e) {
            text.append("(no log: ").append(e.getMessage()).append(")");
        }
        Intent send = new Intent(Intent.ACTION_SEND);
        send.setType("text/plain");
        send.putExtra(Intent.EXTRA_SUBJECT, "psxrecomp log");
        send.putExtra(Intent.EXTRA_TEXT, text.toString());
        activity.startActivity(Intent.createChooser(send, "Share log"));
    }

    private void slots(boolean save) {
        card.removeAllViews();
        card.addView(title(save ? "Save state" : "Load state"));
        for (int slot = 0; slot < SLOTS; slot++) {
            final int s = slot;
            boolean used = nativeSlotUsed(slot);
            String label = "Slot " + (slot + 1) + (used ? "" : "  (empty)");
            TextView b = button(label, () -> {
                boolean staged = save ? nativeSaveState(s) : nativeLoadState(s);
                close();
                if (!staged) {
                    android.widget.Toast.makeText(activity, save ? "The game cannot be saved right now."
                            : "This state cannot be loaded.", android.widget.Toast.LENGTH_SHORT).show();
                } else if (save) {
                    android.widget.Toast.makeText(activity, "Saved to slot " + (s + 1),
                            android.widget.Toast.LENGTH_SHORT).show();
                }
            });
            if (!save && !used) {
                b.setEnabled(false);
                b.setAlpha(0.4f);
            }
        }
        button("Back", this::main);
        focusFirst();
    }

    private void close() {
        if (sShowing != this) return;
        sShowing = null;
        if (getParent() instanceof ViewGroup) ((ViewGroup) getParent()).removeView(this);
        nativeSetPaused(false);
    }

    private TextView title(String s) {
        TextView t = new TextView(activity);
        t.setText(s);
        t.setTextColor(TEXT);
        t.setTypeface(Typeface.DEFAULT_BOLD);
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, 20);
        t.setPadding(0, 0, 0, dp(12));
        return t;
    }

    private TextView button(String label, Runnable action) {
        TextView b = new TextView(activity);
        b.setText(label);
        b.setTextColor(TEXT);
        b.setTextSize(TypedValue.COMPLEX_UNIT_SP, 16);
        b.setGravity(Gravity.CENTER_VERTICAL);
        b.setPadding(dp(16), 0, dp(16), 0);
        b.setFocusable(true);
        b.setBackground(states());
        b.setOnClickListener(v -> action.run());
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(50));
        lp.bottomMargin = dp(8);
        card.addView(b, lp);
        return b;
    }

    private void focusFirst() {
        for (int i = 0; i < card.getChildCount(); i++) {
            View v = card.getChildAt(i);
            if (v.isFocusable() && v.isEnabled()) { v.requestFocus(); return; }
        }
    }

    private Drawable box(int fill, int stroke, int radius) {
        GradientDrawable d = new GradientDrawable();
        d.setColor(fill);
        d.setCornerRadius(radius);
        d.setStroke(dp(1), stroke);
        return d;
    }

    private Drawable states() {
        StateListDrawable s = new StateListDrawable();
        GradientDrawable focused = new GradientDrawable();
        focused.setColor(ACCENT);
        focused.setCornerRadius(dp(10));
        focused.setStroke(dp(2), FOCUS);
        GradientDrawable pressed = new GradientDrawable();
        pressed.setColor(ACCENT);
        pressed.setCornerRadius(dp(10));
        GradientDrawable normal = new GradientDrawable();
        normal.setColor(CONTROL);
        normal.setCornerRadius(dp(10));
        s.addState(new int[] { android.R.attr.state_focused }, focused);
        s.addState(new int[] { android.R.attr.state_pressed }, pressed);
        s.addState(new int[] {}, normal);
        return s;
    }

    private int dp(float v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }

    static native void nativeSetPaused(boolean paused);
    static native boolean nativeSlotUsed(int slot);
    static native boolean nativeSaveState(int slot);
    static native boolean nativeLoadState(int slot);
    static native void nativeBackToLauncher();
    static native void nativeQuit();
    static native String nativeStatus();
    static native void nativeReloadTouch();
}
