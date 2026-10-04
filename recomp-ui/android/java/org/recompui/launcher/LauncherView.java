package org.recompui.launcher;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.res.ColorStateList;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.Drawable;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.StateListDrawable;
import android.text.TextUtils;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.view.ViewGroup;
import android.widget.FrameLayout;
import android.widget.HorizontalScrollView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Switch;
import android.widget.TextView;

import org.psxrecomp.SafeArea;
import org.psxrecomp.TouchEditor;
import org.psxrecomp.TouchLayout;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.File;
import java.util.ArrayList;
import java.util.List;

/**
 * The launcher's screens, built from Android widgets: sections on the left
 * with PLAY at the bottom, the section on the right. Every value shown comes
 * from the C model through LauncherBridge, and every change goes back
 * through it; after a change the section is rebuilt from the model, so the
 * screen never shows a value the model does not hold.
 */
final class LauncherView extends LinearLayout {
    // Palette (dark, one accent).
    private static final int BG = 0xFF0E1016;
    private static final int RAIL = 0xFF141722;
    private static final int CARD = 0xFF1B1F2B;
    private static final int CONTROL = 0xFF262B3A;
    private static final int BORDER = 0xFF30364A;
    private static final int TEXT = 0xFFECECF2;
    private static final int MUTED = 0xFF9AA0B4;
    private static final int ACCENT = 0xFF6E56CF;
    private static final int ACCENT_DIM = 0xFF3E3470;
    private static final int WARN = 0xFFE8A33D;
    private static final int FOCUS = 0xFF58C4F0;

    private static final String CONTROLLERS = "Controllers";
    private static final String TOUCH = "Touch";
    private static final String DISPLAY = "Display";
    private static final String AUDIO = "Audio";
    private static final String MODS = "Mods";
    private static final String MEMORY_CARDS = "Memory cards";

    private final Context ctx;
    private final LinearLayout tabs;
    private final FrameLayout content;
    private final TextView status;
    private final List<TextView> tabViews = new ArrayList<>();
    private String section = CONTROLLERS;
    private String modGroup = null;
    private int bindPlayer = -1;          // the Buttons page is open for this player
    private String shownBindings = "";
    private TouchLayout touch;

    LauncherView(Context context) {
        super(context);
        ctx = context;
        touch = new TouchLayout(new File(context.getFilesDir(), "touch_controls.ini"));
        setOrientation(HORIZONTAL);
        setBackgroundColor(BG);
        setClickable(true);   // the game surface underneath gets no touches
        SafeArea.pad(this);   // full screen, the screens clear of a notch

        // ---- rail: title, sections, PLAY -------------------------------------
        LinearLayout rail = new LinearLayout(ctx);
        rail.setOrientation(VERTICAL);
        rail.setBackgroundColor(RAIL);
        rail.setPadding(dp(16), dp(16), dp(16), dp(16));
        addView(rail, new LayoutParams(dp(210), ViewGroup.LayoutParams.MATCH_PARENT));

        JSONObject game = json(LauncherBridge.nativeGame());
        TextView title = text(game.optString("name", ""), 19, TEXT);
        title.setTypeface(Typeface.DEFAULT_BOLD);
        title.setMaxLines(2);
        title.setEllipsize(TextUtils.TruncateAt.END);
        rail.addView(title);
        String platform = game.optString("platform", "");
        if (!platform.isEmpty()) rail.addView(text(platform, 12, MUTED));

        ScrollView tabScroll = new ScrollView(ctx);
        tabScroll.setVerticalScrollBarEnabled(false);
        tabs = new LinearLayout(ctx);
        tabs.setOrientation(VERTICAL);
        tabs.setPadding(0, dp(14), 0, dp(8));
        tabScroll.addView(tabs);
        rail.addView(tabScroll, new LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));
        addTab(CONTROLLERS);
        addTab(TOUCH);
        addTab(DISPLAY);
        addTab(AUDIO);
        if (game.optBoolean("hasMods")) addTab(MODS);
        addTab(MEMORY_CARDS);

        TextView play = new TextView(ctx);
        play.setText("PLAY");
        play.setTextSize(TypedValue.COMPLEX_UNIT_SP, 18);
        play.setTypeface(Typeface.DEFAULT_BOLD);
        play.setTextColor(Color.WHITE);
        play.setGravity(Gravity.CENTER);
        play.setBackground(states(ACCENT, 0xFF8470E0, dp(12)));
        play.setFocusable(true);
        play.setOnClickListener(v -> play());
        play.setAlpha(game.optBoolean("canLaunch") ? 1f : 0.45f);
        rail.addView(play, new LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(56)));

        // ---- section area --------------------------------------------------------
        LinearLayout right = new LinearLayout(ctx);
        right.setOrientation(VERTICAL);
        right.setPadding(dp(20), dp(14), dp(20), dp(10));
        addView(right, new LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, 1f));
        status = text("", 13, WARN);
        status.setVisibility(GONE);
        right.addView(status);
        if (!game.optBoolean("hasGame", true)) {
            TextView note = text("This build has no game in it. Build the APK with the setup on your computer.", 13, WARN);
            note.setPadding(0, 0, 0, dp(8));
            right.addView(note);
        }
        content = new FrameLayout(ctx);
        right.addView(content, new LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));
    }

    void start() {
        select(section);
        if (!tabViews.isEmpty()) tabViews.get(0).requestFocus();
    }

    @Override
    public boolean dispatchKeyEvent(KeyEvent event) {
        // Back (or B / Circle on a pad) leaves the game from the launcher.
        if (event.getKeyCode() == KeyEvent.KEYCODE_BACK && event.getAction() == KeyEvent.ACTION_UP
                && bindPlayer >= 0) {
            closeBindings();   // Back leaves the Buttons page first
            return true;
        }
        if (event.getKeyCode() == KeyEvent.KEYCODE_BACK && event.getAction() == KeyEvent.ACTION_UP) {
            LauncherBridge.hide();
            LauncherBridge.nativeQuit();
            return true;
        }
        return super.dispatchKeyEvent(event);
    }

    // ---- navigation -----------------------------------------------------------------
    private void addTab(String name) {
        TextView tab = text(name, 15, TEXT);
        tab.setGravity(Gravity.CENTER_VERTICAL);
        tab.setPadding(dp(14), 0, dp(14), 0);
        tab.setFocusable(true);
        tab.setOnClickListener(v -> select(name));
        tab.setTag(name);
        LayoutParams lp = new LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(44));
        lp.bottomMargin = dp(6);
        tabs.addView(tab, lp);
        tabViews.add(tab);
    }

    private void select(String name) {
        if (bindPlayer >= 0) closeBindings();
        section = name;
        for (TextView tab : tabViews) {
            boolean on = name.equals(tab.getTag());
            tab.setBackground(on ? states(ACCENT_DIM, ACCENT_DIM, dp(10)) : states(RAIL, CONTROL, dp(10)));
            tab.setTextColor(on ? Color.WHITE : TEXT);
        }
        refresh();
    }

    /** Rebuilds the current section from the model. */
    private void refresh() {
        content.removeAllViews();
        View view;
        switch (section) {
            case DISPLAY: view = settingsGrid("display"); break;
            case AUDIO: view = settingsGrid("audio"); break;
            case MODS: view = mods(); break;
            case MEMORY_CARDS: view = memoryCards(); break;
            case TOUCH: view = touchPage(); break;
            default: view = bindPlayer >= 0 ? bindings(bindPlayer) : controllers(); break;
        }
        ScrollView scroll = new ScrollView(ctx);
        scroll.setFillViewport(true);
        scroll.addView(view);
        content.addView(scroll);
    }

    private void play() {
        if (bindPlayer >= 0) closeBindings();
        String error = LauncherBridge.nativePlay();
        if (error == null || error.isEmpty()) {
            LauncherBridge.hide();
        } else {
            showStatus(error);
        }
    }

    private void showStatus(String message) {
        status.setText(message);
        status.setVisibility(message == null || message.isEmpty() ? GONE : VISIBLE);
    }

    // ---- Controllers ----------------------------------------------------------------
    private View controllers() {
        LinearLayout row = new LinearLayout(ctx);
        row.setOrientation(HORIZONTAL);
        JSONArray players = jsonArray(LauncherBridge.nativePlayers());
        if (players.length() == 0) {
            return text("Controllers are fixed for this game.", 14, MUTED);
        }
        for (int i = 0; i < players.length(); i++) {
            JSONObject player = players.optJSONObject(i);
            LinearLayout card = card();
            card.addView(eyebrow("PLAYER " + (player.optInt("player") + 1)));

            card.addView(label("Input"));
            JSONArray sources = player.optJSONArray("sources");
            TextView source = valueButton(player.optString("source"));
            source.setOnClickListener(v -> pickSource(player.optInt("player"), sources));
            card.addView(source, fullWidth(dp(48)));

            JSONArray modes = player.optJSONArray("modes");
            if (modes != null && modes.length() > 0) {
                card.addView(label("Mode"));
                LinearLayout seg = new LinearLayout(ctx);
                for (int m = 0; m < modes.length(); m++) {
                    JSONObject mode = modes.optJSONObject(m);
                    boolean on = mode.optInt("mode") == player.optInt("mode");
                    boolean enabled = mode.optBoolean("enabled", true);
                    TextView b = text(mode.optString("label"), 14, on ? Color.WHITE : TEXT);
                    b.setGravity(Gravity.CENTER);
                    b.setBackground(on ? states(ACCENT, ACCENT, dp(8)) : states(CONTROL, BORDER, dp(8)));
                    b.setFocusable(enabled);
                    b.setAlpha(enabled ? 1f : 0.4f);
                    if (enabled) {
                        final int p = player.optInt("player");
                        final int value = mode.optInt("mode");
                        b.setOnClickListener(v -> { LauncherBridge.nativeSetPadMode(p, value); refresh(); });
                    }
                    LayoutParams lp = new LayoutParams(0, dp(44), 1f);
                    if (m > 0) lp.leftMargin = dp(8);
                    seg.addView(b, lp);
                }
                card.addView(seg);
            }
            if (player.optBoolean("canBind")) {
                final int p = player.optInt("player");
                TextView buttons = valueButton("Buttons");
                buttons.setText("Buttons…");
                buttons.setOnClickListener(v -> openBindings(p));
                LayoutParams blp = fullWidth(dp(46));
                blp.topMargin = dp(12);
                card.addView(buttons, blp);
            } else if (player.optInt("kind") == 3) {
                TextView note = text("Buttons on the screen, over the game. Set them up in Touch. "
                        + "A controller works too: the buttons hide while you use it.", 12, MUTED);
                note.setPadding(0, dp(10), 0, 0);
                card.addView(note);
            }
            LayoutParams lp = new LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
            if (i > 0) lp.leftMargin = dp(14);
            row.addView(card, lp);
        }
        return row;
    }

    private void pickSource(int player, JSONArray sources) {
        if (sources == null) return;
        String[] labels = new String[sources.length()];
        int checked = -1;
        for (int i = 0; i < sources.length(); i++) {
            JSONObject s = sources.optJSONObject(i);
            labels[i] = s.optString("label") + (s.optBoolean("claimed") ? "  (other player)" : "");
            if (s.optBoolean("selected")) checked = i;
        }
        dialog().setTitle("Player " + (player + 1) + " input")
                .setSingleChoiceItems(labels, checked, (d, which) -> {
                    JSONObject s = sources.optJSONObject(which);
                    if (!s.optBoolean("claimed")) LauncherBridge.nativeSetSource(player, which);
                    d.dismiss();
                    refresh();
                })
                .setNegativeButton("Cancel", null)
                .show();
    }

    // ---- Display / Audio: two settings per line -------------------------------------
    private View settingsGrid(String name) {
        JSONArray rows = jsonArray(LauncherBridge.nativeSettings(name));
        LinearLayout card = card();
        LinearLayout line = null;
        for (int i = 0; i < rows.length(); i++) {
            if (i % 2 == 0) {
                line = new LinearLayout(ctx);
                line.setOrientation(HORIZONTAL);
                card.addView(line);
            }
            LinearLayout cell = new LinearLayout(ctx);
            cell.setOrientation(VERTICAL);
            cell.setPadding(0, dp(6), dp(i % 2 == 0 ? 16 : 0), dp(8));
            settingCell(cell, rows.optJSONObject(i));
            line.addView(cell, new LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        }
        if (rows.length() % 2 == 1 && line != null) {
            line.addView(new View(ctx), new LayoutParams(0, 1, 1f));
        }
        if (rows.length() == 0) card.addView(text("Nothing to set here for this game.", 14, MUTED));
        return card;
    }

    private void settingCell(LinearLayout cell, JSONObject row) {
        final String id = row.optString("id");
        TextView label = label(row.optString("label"));
        cell.addView(label);
        switch (row.optInt("kind")) {
            case 0: {   // toggle
                Switch sw = toggle(row.optBoolean("on"));
                sw.setOnClickListener(v -> { LauncherBridge.nativeToggle(id); refresh(); });
                cell.addView(sw);
                break;
            }
            case 2: {   // stepper
                cell.addView(stepper(row.optString("value"),
                        () -> { LauncherBridge.nativeStep(id, -1); refresh(); },
                        () -> { LauncherBridge.nativeStep(id, +1); refresh(); }));
                break;
            }
            default: {  // choice
                TextView value = valueButton(row.optString("value"));
                value.setOnClickListener(v -> pickChoice(id, row.optString("label")));
                cell.addView(value, fullWidth(dp(46)));
                break;
            }
        }
        if (row.optBoolean("experimental")) cell.addView(text("Experimental", 11, WARN));
        String help = row.optString("help", "");
        if (!help.isEmpty()) {
            TextView h = text(help, 11, MUTED);
            h.setPadding(0, dp(3), 0, 0);
            cell.addView(h);
        }
    }

    private void pickChoice(String id, String title) {
        JSONArray choices = jsonArray(LauncherBridge.nativeChoices(id));
        String[] labels = new String[choices.length()];
        for (int i = 0; i < labels.length; i++) labels[i] = choices.optString(i);
        // Index 0 is always the current value.
        dialog().setTitle(title)
                .setSingleChoiceItems(labels, 0, (d, which) -> {
                    LauncherBridge.nativeChoose(id, which);
                    d.dismiss();
                    refresh();
                })
                .setNegativeButton("Cancel", null)
                .show();
    }

    // ---- Mods: categories + a grid of switches ------------------------------------------
    private View mods() {
        JSONObject data = json(LauncherBridge.nativeMods());
        JSONArray features = data.optJSONArray("features");
        LinearLayout box = new LinearLayout(ctx);
        box.setOrientation(VERTICAL);
        if (features == null || features.length() == 0) {
            box.addView(text("No mods in this build.", 14, MUTED));
            return box;
        }
        List<String> groups = new ArrayList<>();
        for (int i = 0; i < features.length(); i++) {
            String g = features.optJSONObject(i).optString("group");
            if (!groups.contains(g)) groups.add(g);
        }
        if (modGroup == null || !groups.contains(modGroup)) modGroup = groups.get(0);

        HorizontalScrollView chipScroll = new HorizontalScrollView(ctx);
        chipScroll.setHorizontalScrollBarEnabled(false);
        LinearLayout chips = new LinearLayout(ctx);
        for (String g : groups) {
            boolean on = g.equals(modGroup);
            TextView chip = text(g, 14, on ? Color.WHITE : TEXT);
            chip.setGravity(Gravity.CENTER);
            chip.setPadding(dp(16), 0, dp(16), 0);
            chip.setBackground(on ? states(ACCENT, ACCENT, dp(20)) : states(CONTROL, BORDER, dp(20)));
            chip.setFocusable(true);
            chip.setOnClickListener(v -> { modGroup = g; refresh(); });
            LayoutParams lp = new LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, dp(40));
            lp.rightMargin = dp(8);
            chips.addView(chip, lp);
        }
        chipScroll.addView(chips);
        box.addView(chipScroll);

        String note = data.optString("status", "");
        TextView hint = text(note.isEmpty() ? "Touch a mod's name for its details and options." : note,
                12, note.isEmpty() ? MUTED : WARN);
        hint.setPadding(0, dp(8), 0, dp(8));
        box.addView(hint);

        final int columns = getWidth() > dp(1100) ? 3 : 2;
        LinearLayout line = null;
        int cell = 0;
        for (int i = 0; i < features.length(); i++) {
            JSONObject f = features.optJSONObject(i);
            if (!modGroup.equals(f.optString("group"))) continue;
            if (cell % columns == 0) {
                line = new LinearLayout(ctx);
                box.addView(line);
            }
            LayoutParams lp = new LayoutParams(0, dp(58), 1f);
            lp.bottomMargin = dp(10);
            if (cell % columns != 0) lp.leftMargin = dp(10);
            line.addView(modCard(f), lp);
            cell++;
        }
        while (line != null && cell % columns != 0) {
            LayoutParams lp = new LayoutParams(0, dp(58), 1f);
            lp.leftMargin = dp(10);
            line.addView(new View(ctx), lp);
            cell++;
        }
        return box;
    }

    private View modCard(JSONObject f) {
        LinearLayout card = new LinearLayout(ctx);
        card.setGravity(Gravity.CENTER_VERTICAL);
        card.setPadding(dp(14), 0, dp(10), 0);
        card.setBackground(box(CARD, BORDER, dp(12)));
        TextView name = text((f.optBoolean("error") ? "! " : "") + f.optString("name"), 15, TEXT);
        name.setMaxLines(2);
        name.setEllipsize(TextUtils.TruncateAt.END);
        name.setFocusable(true);
        name.setBackground(states(Color.TRANSPARENT, CONTROL, dp(8)));
        name.setPadding(dp(4), dp(8), dp(4), dp(8));
        name.setOnClickListener(v -> modDetails(f));
        card.addView(name, new LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        Switch sw = toggle(f.optBoolean("enabled"));
        sw.setOnClickListener(v -> {
            LauncherBridge.nativeModEnable(f.optString("package"), f.optString("id"), !f.optBoolean("enabled"));
            refresh();
        });
        card.addView(sw);
        return card;
    }

    private void modDetails(JSONObject f) {
        final String pkg = f.optString("package");
        final String id = f.optString("id");
        LinearLayout body = new LinearLayout(ctx);
        body.setOrientation(VERTICAL);
        body.setPadding(dp(22), dp(8), dp(22), dp(8));
        ScrollView scroll = new ScrollView(ctx);
        scroll.addView(body);
        AlertDialog dlg = dialog().setTitle(f.optString("name")).setView(scroll)
                .setPositiveButton("Close", null).create();
        fillModDetails(body, f, pkg, id);
        dlg.show();
    }

    private void fillModDetails(LinearLayout body, JSONObject f, String pkg, String id) {
        body.removeAllViews();
        String author = f.optString("author", "");
        if (!author.isEmpty()) body.addView(text("by " + author, 12, MUTED));
        String desc = f.optString("description", "");
        if (!desc.isEmpty()) {
            TextView d = text(desc, 14, TEXT);
            d.setPadding(0, dp(8), 0, dp(8));
            body.addView(d);
        }
        String st = f.optString("status", "");
        if (!st.isEmpty()) body.addView(text(st, 12, f.optBoolean("error") ? WARN : MUTED));

        JSONArray options = jsonArray(LauncherBridge.nativeModOptions(pkg, id));
        String lastGroup = null;
        for (int i = 0; i < options.length(); i++) {
            JSONObject o = options.optJSONObject(i);
            String group = o.optString("group", "");
            if (lastGroup == null || !lastGroup.equals(group)) {
                lastGroup = group;
                TextView g = eyebrow(group.isEmpty() ? "SETTINGS" : group.toUpperCase());
                g.setPadding(0, dp(12), 0, dp(4));
                body.addView(g);
            }
            body.addView(modOption(body, f, pkg, id, o));
        }
    }

    private View modOption(LinearLayout body, JSONObject f, String pkg, String id, JSONObject o) {
        final String opt = o.optString("id");
        final boolean disabled = o.optBoolean("disabled");
        LinearLayout row = new LinearLayout(ctx);
        row.setOrientation(VERTICAL);
        row.setPadding(0, dp(4), 0, dp(6));
        row.setAlpha(disabled ? 0.45f : 1f);
        Runnable reload = () -> fillModDetails(body, f, pkg, id);
        switch (o.optInt("type")) {
            case 0: {   // boolean
                Switch sw = toggle("true".equals(o.optString("value")));
                sw.setText(o.optString("label"));
                sw.setTextColor(TEXT);
                sw.setEnabled(!disabled);
                sw.setOnClickListener(v -> {
                    LauncherBridge.nativeModSetOption(pkg, id, opt,
                            "true".equals(o.optString("value")) ? "false" : "true");
                    reload.run();
                });
                row.addView(sw, fullWidth(ViewGroup.LayoutParams.WRAP_CONTENT));
                break;
            }
            case 1: {   // choice
                row.addView(label(o.optString("label")));
                JSONArray choices = o.optJSONArray("choices");
                String current = o.optString("value");
                String shown = current;
                int checked = -1;
                String[] labels = new String[choices == null ? 0 : choices.length()];
                for (int c = 0; c < labels.length; c++) {
                    labels[c] = choices.optJSONObject(c).optString("label");
                    if (current.equals(choices.optJSONObject(c).optString("value"))) {
                        checked = c;
                        shown = labels[c];
                    }
                }
                TextView value = valueButton(shown);
                final int selected = checked;
                if (!disabled) value.setOnClickListener(v -> dialog().setTitle(o.optString("label"))
                        .setSingleChoiceItems(labels, selected, (d, which) -> {
                            LauncherBridge.nativeModSetOption(pkg, id, opt,
                                    choices.optJSONObject(which).optString("value"));
                            d.dismiss();
                            reload.run();
                        }).setNegativeButton("Cancel", null).show());
                row.addView(value, fullWidth(dp(46)));
                break;
            }
            default: {  // integer
                row.addView(label(o.optString("label")));
                long value = parseLong(o.optString("value"), 0);
                long step = Math.max(1, o.optLong("step", 1));
                long min = o.optLong("min", Long.MIN_VALUE);
                long max = o.optLong("max", Long.MAX_VALUE);
                row.addView(stepper(String.valueOf(value),
                        () -> { if (!disabled) { LauncherBridge.nativeModSetOption(pkg, id, opt,
                                String.valueOf(Math.max(min, value - step))); reload.run(); } },
                        () -> { if (!disabled) { LauncherBridge.nativeModSetOption(pkg, id, opt,
                                String.valueOf(Math.min(max, value + step))); reload.run(); } }));
                break;
            }
        }
        String desc = o.optString("description", "");
        if (!desc.isEmpty()) row.addView(text(desc, 12, MUTED));
        return row;
    }

    // ---- Memory cards ---------------------------------------------------------------
    private View memoryCards() {
        LinearLayout row = new LinearLayout(ctx);
        JSONArray cards = jsonArray(LauncherBridge.nativeMemcards());
        if (cards.length() == 0) return text("This game has no memory cards.", 14, MUTED);
        for (int i = 0; i < cards.length(); i++) {
            JSONObject c = cards.optJSONObject(i);
            LinearLayout card = card();
            card.addView(eyebrow("MEMORY CARD " + (c.optInt("slot") + 1)));
            TextView name = text(c.optString("name"), 15, TEXT);
            name.setPadding(0, dp(6), 0, 0);
            card.addView(name);
            card.addView(text(c.optInt("used") + " / 15 blocks used", 13, MUTED));
            Switch sw = toggle(c.optBoolean("enabled"));
            sw.setText("Inserted");
            sw.setTextColor(TEXT);
            final int slot = c.optInt("slot");
            sw.setOnClickListener(v -> { LauncherBridge.nativeToggleMemcard(slot); refresh(); });
            card.addView(sw, fullWidth(ViewGroup.LayoutParams.WRAP_CONTENT));
            TextView fresh = valueButton("");
            fresh.setText("New blank card");
            fresh.setGravity(Gravity.CENTER);
            fresh.setOnClickListener(v -> dialog().setTitle("New memory card " + (slot + 1))
                    .setMessage("Put a new, empty card in this slot? The current card is kept "
                            + "in the app's folder, but the game will no longer see its saves.")
                    .setPositiveButton("Create", (d, w) -> {
                        String made = LauncherBridge.nativeNewMemcard(slot);
                        showStatus(made == null || made.isEmpty() ? "The card could not be created." : "");
                        refresh();
                    })
                    .setNegativeButton("Cancel", null)
                    .show());
            LayoutParams flp = fullWidth(dp(44));
            flp.topMargin = dp(8);
            card.addView(fresh, flp);
            LayoutParams lp = new LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
            if (i > 0) lp.leftMargin = dp(14);
            row.addView(card, lp);
        }
        return row;
    }

    // ---- Buttons: a controller's bindings (the PC launcher's Configure page) ------------
    private final Runnable pollBindings = new Runnable() {
        @Override public void run() {
            if (bindPlayer < 0) return;
            if (!LauncherBridge.nativeBindings(bindPlayer).equals(shownBindings)) refresh();
            postDelayed(this, 100);
        }
    };

    private void openBindings(int player) {
        bindPlayer = player;
        refresh();
        removeCallbacks(pollBindings);
        postDelayed(pollBindings, 100);
    }

    private void closeBindings() {
        LauncherBridge.nativeCancelCapture();
        removeCallbacks(pollBindings);
        bindPlayer = -1;
        refresh();
    }

    private View bindings(int player) {
        shownBindings = LauncherBridge.nativeBindings(player);
        JSONObject data = json(shownBindings);
        LinearLayout box = new LinearLayout(ctx);
        box.setOrientation(VERTICAL);
        JSONArray buttons = data.optJSONArray("buttons");
        if (buttons == null) {   // the source changed: nothing to bind any more
            bindPlayer = -1;
            removeCallbacks(pollBindings);
            return controllers();
        }
        LinearLayout card = card();
        card.addView(eyebrow("PLAYER " + (player + 1) + " BUTTONS"));
        card.addView(text(data.optString("pad"), 16, TEXT));

        final int capturing = data.optInt("capturing", -1);
        String hint;
        int hintColor = WARN;
        if (!data.optBoolean("connected")) {
            hint = "Connect this controller to change its buttons.";
        } else if (capturing < 0) {
            hint = "Touch a button, then press the controller button to use for it.";
            hintColor = MUTED;
        } else if (data.optBoolean("waitRelease")) {
            hint = "Let go of the controller's buttons…";
        } else {
            String name = "";
            for (int i = 0; i < buttons.length(); i++)
                if (buttons.optJSONObject(i).optInt("button") == capturing)
                    name = buttons.optJSONObject(i).optString("label");
            hint = "Press the controller button for " + name
                    + (data.optBoolean("mapAll") ? " (all buttons, one after the other)" : "") + ".";
        }
        TextView h = text(hint, 13, hintColor);
        h.setPadding(0, dp(6), 0, dp(10));
        card.addView(h);

        // Three columns, top to bottom (D-pad / face / shoulders), as on PC.
        final int columns = 3, rows = (buttons.length() + columns - 1) / columns;
        LinearLayout grid = new LinearLayout(ctx);
        for (int c = 0; c < columns; c++) {
            LinearLayout col = new LinearLayout(ctx);
            col.setOrientation(VERTICAL);
            for (int r = 0; r < rows; r++) {
                int i = c * rows + r;
                if (i >= buttons.length()) break;
                JSONObject b = buttons.optJSONObject(i);
                final int index = b.optInt("button");
                LinearLayout line = new LinearLayout(ctx);
                line.setGravity(Gravity.CENTER_VERTICAL);
                TextView label = text(b.optString("label"), 13, MUTED);
                line.addView(label, new LayoutParams(dp(96), ViewGroup.LayoutParams.WRAP_CONTENT));
                boolean on = index == capturing;
                String bind = b.optString("bind");
                TextView chip = text(on ? "press…" : (bind.isEmpty() ? "—" : bind), 14,
                        on ? Color.WHITE : TEXT);
                chip.setGravity(Gravity.CENTER);
                chip.setSingleLine(true);
                chip.setEllipsize(TextUtils.TruncateAt.END);
                chip.setBackground(on ? states(ACCENT, ACCENT, dp(8)) : states(CONTROL, BORDER, dp(8)));
                chip.setFocusable(true);
                chip.setOnClickListener(v -> {
                    if (on) LauncherBridge.nativeCancelCapture();
                    else LauncherBridge.nativeCaptureButton(player, index);
                    refresh();
                });
                line.addView(chip, new LayoutParams(0, dp(40), 1f));
                LayoutParams llp = fullWidth(ViewGroup.LayoutParams.WRAP_CONTENT);
                llp.bottomMargin = dp(6);
                col.addView(line, llp);
            }
            LayoutParams clp = new LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
            if (c > 0) clp.leftMargin = dp(16);
            grid.addView(col, clp);
        }
        card.addView(grid);

        LinearLayout actions = new LinearLayout(ctx);
        actions.setPadding(0, dp(10), 0, 0);
        addAction(actions, capturing >= 0 ? "Stop" : "Map all", () -> {
            if (capturing >= 0) LauncherBridge.nativeCancelCapture();
            else LauncherBridge.nativeCaptureAll(player);
            refresh();
        });
        addAction(actions, "Defaults", () -> { LauncherBridge.nativeResetBindings(player); refresh(); });
        addAction(actions, "Save profile", () -> {
            LauncherBridge.nativeSaveBindings(player);
            showStatus("");
            android.widget.Toast.makeText(ctx, "Saved for this controller.", android.widget.Toast.LENGTH_SHORT).show();
        });
        addAction(actions, "Done", this::closeBindings);
        card.addView(actions);
        box.addView(card);
        return box;
    }

    private void addAction(LinearLayout row, String name, Runnable action) {
        TextView b = text(name, 14, TEXT);
        b.setGravity(Gravity.CENTER);
        b.setBackground(states(CONTROL, BORDER, dp(10)));
        b.setFocusable(true);
        b.setOnClickListener(v -> action.run());
        LayoutParams lp = new LayoutParams(0, dp(44), 1f);
        if (row.getChildCount() > 0) lp.leftMargin = dp(8);
        row.addView(b, lp);
    }

    // ---- Touch: the on-screen buttons ------------------------------------------------
    private View touchPage() {
        touch = new TouchLayout(touch.file);   // the editor may have changed it
        LinearLayout box = new LinearLayout(ctx);
        box.setOrientation(HORIZONTAL);

        LinearLayout side = card();
        side.addView(eyebrow("TOUCH CONTROLS"));
        TextView about = text("For a player whose input is Touch. A controller works too: "
                + "the buttons hide while you use it.", 12, MUTED);
        about.setPadding(0, 0, 0, dp(6));
        side.addView(about);
        Switch shown = toggle(touch.visible);
        shown.setText("Show the buttons");
        shown.setTextColor(TEXT);
        shown.setOnClickListener(v -> { touch.visible = !touch.visible; touch.save(); refresh(); });
        side.addView(shown, fullWidth(ViewGroup.LayoutParams.WRAP_CONTENT));
        if (!touch.visible) side.addView(text("Hidden buttons still work where they would be.", 11, MUTED));
        side.addView(label("Directions"));
        LinearLayout styles = new LinearLayout(ctx);
        String[] styleNames = { "D-pad", "Stick", "Floating" };
        for (int s = 0; s < styleNames.length; s++) {
            final int value = s;
            boolean on = touch.stick == s;
            TextView b = text(styleNames[s], 13, on ? Color.WHITE : TEXT);
            b.setGravity(Gravity.CENTER);
            b.setBackground(on ? states(ACCENT, ACCENT, dp(8)) : states(CONTROL, BORDER, dp(8)));
            b.setFocusable(true);
            b.setOnClickListener(v -> { touch.stick = value; touch.save(); refresh(); });
            LayoutParams lp = new LayoutParams(0, dp(40), 1f);
            if (s > 0) lp.leftMargin = dp(6);
            styles.addView(b, lp);
        }
        side.addView(styles);
        if (touch.stick == 2) {
            side.addView(text("The stick starts where your thumb lands on the left half.", 11, MUTED));
        }
        side.addView(label("Neutral middle"));
        side.addView(stepper(touch.neutral + "%",
                () -> { touch.neutral = Math.max(10, touch.neutral - 5); touch.save(); refresh(); },
                () -> { touch.neutral = Math.min(60, touch.neutral + 5); touch.save(); refresh(); }));
        side.addView(text("Sliding through the middle counts as letting go (for f, N, d, d/f).",
                11, MUTED));
        side.addView(label("Opacity"));
        side.addView(stepper(touch.opacity + "%",
                () -> { touch.opacity = Math.max(10, touch.opacity - 10); touch.save(); refresh(); },
                () -> { touch.opacity = Math.min(100, touch.opacity + 10); touch.save(); refresh(); }));
        side.addView(label("Size of all the buttons"));
        side.addView(stepper(touch.size + "%",
                () -> { touch.size = Math.max(50, touch.size - 10); touch.save(); refresh(); },
                () -> { touch.size = Math.min(160, touch.size + 10); touch.save(); refresh(); }));
        box.addView(side, new LayoutParams(dp(280), ViewGroup.LayoutParams.WRAP_CONTENT));

        LinearLayout edit = card();
        edit.addView(eyebrow("LAYOUT"));
        int hidden = 0;
        for (boolean s : touch.shown) if (!s) hidden++;
        edit.addView(text("Place each button where your thumbs want it, make it bigger or smaller, "
                + "or hide the ones you do not use. The editor shows the whole screen, as in the game.",
                13, TEXT));
        if (hidden > 0) {
            TextView h = text(hidden + (hidden == 1 ? " button hidden." : " buttons hidden."), 12, MUTED);
            h.setPadding(0, dp(6), 0, 0);
            edit.addView(h);
        }
        TextView open = text("Edit layout", 16, Color.WHITE);
        open.setGravity(Gravity.CENTER);
        open.setBackground(states(ACCENT, 0xFF8470E0, dp(12)));
        open.setFocusable(true);
        open.setOnClickListener(v -> TouchEditor.show((Activity) ctx, this::refresh));
        LayoutParams olp = fullWidth(dp(56));
        olp.topMargin = dp(16);
        edit.addView(open, olp);
        LayoutParams elp = new LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        elp.leftMargin = dp(14);
        box.addView(edit, elp);
        return box;
    }

    // ---- widgets --------------------------------------------------------------------
    private LinearLayout card() {
        LinearLayout card = new LinearLayout(ctx);
        card.setOrientation(VERTICAL);
        card.setPadding(dp(18), dp(14), dp(18), dp(14));
        card.setBackground(box(CARD, BORDER, dp(14)));
        return card;
    }

    private TextView eyebrow(String s) {
        TextView t = text(s, 12, ACCENT);
        t.setTypeface(Typeface.DEFAULT_BOLD);
        t.setLetterSpacing(0.15f);
        t.setPadding(0, 0, 0, dp(4));
        return t;
    }

    private TextView label(String s) {
        TextView t = text(s, 13, MUTED);
        t.setPadding(0, dp(8), 0, dp(4));
        return t;
    }

    private TextView valueButton(String value) {
        TextView b = text(value + "  ▾", 15, TEXT);
        b.setGravity(Gravity.CENTER_VERTICAL);
        b.setPadding(dp(14), 0, dp(14), 0);
        b.setSingleLine(true);
        b.setEllipsize(TextUtils.TruncateAt.END);
        b.setBackground(states(CONTROL, BORDER, dp(10)));
        b.setFocusable(true);
        return b;
    }

    private View stepper(String value, Runnable minus, Runnable plus) {
        LinearLayout row = new LinearLayout(ctx);
        row.setGravity(Gravity.CENTER_VERTICAL);
        TextView down = text("−", 20, TEXT);
        TextView up = text("+", 20, TEXT);
        for (TextView b : new TextView[] { down, up }) {
            b.setGravity(Gravity.CENTER);
            b.setBackground(states(CONTROL, BORDER, dp(10)));
            b.setFocusable(true);
        }
        down.setOnClickListener(v -> minus.run());
        up.setOnClickListener(v -> plus.run());
        TextView v = text(value, 16, TEXT);
        v.setGravity(Gravity.CENTER);
        row.addView(down, new LayoutParams(dp(48), dp(44)));
        row.addView(v, new LayoutParams(dp(84), dp(44)));
        row.addView(up, new LayoutParams(dp(48), dp(44)));
        return row;
    }

    private Switch toggle(boolean on) {
        Switch sw = new Switch(ctx);
        sw.setChecked(on);
        sw.setMinHeight(dp(44));
        int[][] st = { { android.R.attr.state_checked }, {} };
        sw.setThumbTintList(new ColorStateList(st, new int[] { Color.WHITE, 0xFFBFC3D0 }));
        sw.setTrackTintList(new ColorStateList(st, new int[] { ACCENT, 0xFF454B5E }));
        return sw;
    }

    private TextView text(String s, int sp, int color) {
        TextView t = new TextView(ctx);
        t.setText(s);
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp);
        t.setTextColor(color);
        return t;
    }

    private LayoutParams fullWidth(int height) {
        return new LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, height);
    }

    private AlertDialog.Builder dialog() {
        return new AlertDialog.Builder(ctx, android.R.style.Theme_Material_Dialog_Alert);
    }

    private Drawable box(int fill, int stroke, int radius) {
        GradientDrawable d = new GradientDrawable();
        d.setColor(fill);
        d.setCornerRadius(radius);
        d.setStroke(dp(1), stroke);
        return d;
    }

    /** Normal / pressed / focused (a pad or keyboard shows where it is). */
    private Drawable states(int fill, int pressed, int radius) {
        StateListDrawable s = new StateListDrawable();
        GradientDrawable focused = new GradientDrawable();
        focused.setColor(pressed);
        focused.setCornerRadius(radius);
        focused.setStroke(dp(2), FOCUS);
        GradientDrawable down = new GradientDrawable();
        down.setColor(pressed);
        down.setCornerRadius(radius);
        GradientDrawable normal = new GradientDrawable();
        normal.setColor(fill);
        normal.setCornerRadius(radius);
        s.addState(new int[] { android.R.attr.state_focused }, focused);
        s.addState(new int[] { android.R.attr.state_pressed }, down);
        s.addState(new int[] {}, normal);
        return s;
    }

    private int dp(float v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }

    private static long parseLong(String s, long fallback) {
        try { return Long.parseLong(s.trim()); } catch (RuntimeException e) { return fallback; }
    }

    private static JSONObject json(String s) {
        try { return new JSONObject(s == null ? "{}" : s); } catch (JSONException e) { return new JSONObject(); }
    }

    private static JSONArray jsonArray(String s) {
        try { return new JSONArray(s == null ? "[]" : s); } catch (JSONException e) { return new JSONArray(); }
    }
}
