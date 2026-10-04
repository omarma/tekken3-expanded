package com.tekken3expanded;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.Typeface;
import android.os.Bundle;
import android.util.Log;
import android.util.TypedValue;
import android.view.Gravity;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;

/**
 * Opens the app. After an install or an update it copies the game data out
 * of the APK on a background thread, with a progress bar, then starts the
 * game (GameActivity); otherwise it starts the game at once. The disc itself
 * (~700 MB) is not copied: the game reads it from the APK.
 */
public class PrepareActivity extends Activity {
    private static final String TAG = "Tekken3";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        if (GameData.ready(this)) {
            startGame();
            return;
        }

        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setGravity(Gravity.CENTER);
        box.setBackgroundColor(0xFF0E1016);
        int pad = dp(48);
        box.setPadding(pad, pad, pad, pad);
        TextView title = new TextView(this);
        title.setText("Preparing the game");
        title.setTextColor(0xFFECECF2);
        title.setTypeface(Typeface.DEFAULT_BOLD);
        title.setTextSize(TypedValue.COMPLEX_UNIT_SP, 22);
        box.addView(title);
        TextView detail = new TextView(this);
        detail.setText("First start after installing or updating. This takes a minute.");
        detail.setTextColor(0xFF9AA0B4);
        detail.setTextSize(TypedValue.COMPLEX_UNIT_SP, 14);
        detail.setPadding(0, dp(8), 0, dp(20));
        box.addView(detail);
        ProgressBar bar = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        bar.setMax(1000);
        bar.setProgressTintList(android.content.res.ColorStateList.valueOf(0xFF6E56CF));
        box.addView(bar, new LinearLayout.LayoutParams(dp(420), dp(12)));
        TextView percent = new TextView(this);
        percent.setTextColor(0xFF9AA0B4);
        percent.setPadding(0, dp(10), 0, 0);
        box.addView(percent);
        setContentView(box);

        new Thread(() -> {
            long[] last = { 0 };
            try {
                GameData.prepare(this, (done, total) -> {
                    long now = System.currentTimeMillis();
                    if (now - last[0] < 100 && done < total) return;
                    last[0] = now;
                    int permille = total > 0 ? (int) Math.min(1000, done * 1000 / total) : 0;
                    runOnUiThread(() -> {
                        bar.setProgress(permille);
                        percent.setText((permille / 10) + " %");
                    });
                });
                runOnUiThread(this::startGame);
            } catch (Exception e) {
                Log.e(TAG, "Could not prepare the game data", e);
                runOnUiThread(() -> {
                    title.setText("The game could not be prepared");
                    detail.setText("Check that the phone has some free space, then open the "
                            + "game again.\n\n" + e.getMessage());
                    detail.setTextColor(Color.rgb(0xE8, 0xA3, 0x3D));
                });
            }
        }, "prepare-game-data").start();
    }

    private void startGame() {
        startActivity(new Intent(this, GameActivity.class));
        overridePendingTransition(0, 0);
        finish();
    }

    private int dp(float v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }
}
