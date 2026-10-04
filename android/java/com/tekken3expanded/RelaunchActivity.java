package com.tekken3expanded;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.os.Process;

/**
 * Back to launcher's second half, in a process of its own (":relaunch", see
 * the manifest): makes sure the game's process is gone, then starts the game
 * again on the launcher. Started by GameActivity.relaunchOnLauncher while the
 * game exits; the new GameActivity then gets a new process, with nothing of
 * the old game left (the way ProcessPhoenix restarts an app).
 */
public class RelaunchActivity extends Activity {
    static final String EXTRA_PID = "pid";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        int pid = getIntent().getIntExtra(EXTRA_PID, 0);
        if (pid != 0 && pid != Process.myPid()) Process.killProcess(pid);
        startActivity(new Intent(this, GameActivity.class)
                .putExtra(GameActivity.EXTRA_LAUNCHER, true)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK));
        overridePendingTransition(0, 0);
        finish();
        Runtime.getRuntime().exit(0);
    }
}
