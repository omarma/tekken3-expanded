package com.tekken3expanded;

import android.content.Intent;
import android.os.Bundle;
import android.view.KeyEvent;
import android.view.MotionEvent;

import org.libsdl.app.SDLActivity;
import org.psxrecomp.GameMenu;
import org.psxrecomp.SafeArea;
import org.recompui.launcher.LauncherBridge;

import java.io.File;

/**
 * The game: SDL runs the runtime (libmain.so) from the data folder that
 * PrepareActivity set up (see GameData). The launcher (settings, then PLAY)
 * is recomp-ui's native Android screens.
 */
public class GameActivity extends SDLActivity {
    static final String EXTRA_LAUNCHER = "launcher";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        LauncherBridge.attach(this);
        SafeArea.watch(this);   // the game and its buttons keep clear of a notch
    }

    /**
     * The in-game menu's Back to launcher: called by the runtime (android_main.c)
     * as it exits, the memory cards saved. RelaunchActivity, in a process of its
     * own, ends this one and starts the game again on the launcher (whatever
     * "skip the launcher" says): nothing of the old game is left.
     */
    public void relaunchOnLauncher() {
        startActivity(new Intent(this, RelaunchActivity.class)
                .putExtra(RelaunchActivity.EXTRA_PID, android.os.Process.myPid())
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
    }

    @Override
    protected void onPause() {
        // Leaving the app (home, a call, the recent apps) pauses the game: it
        // comes back on the in-game menu instead of running on at once.
        if (!isFinishing() && !LauncherBridge.isShowing() && !GameMenu.isShowing()) {
            try {
                GameMenu.show(this);
            } catch (UnsatisfiedLinkError e) {
                // libmain.so did not load: SDL shows its own error.
            }
        }
        super.onPause();
    }

    @Override
    public boolean dispatchKeyEvent(KeyEvent event) {
        // A controller button being bound in the launcher goes to SDL.
        if (LauncherBridge.dispatchPadKey(event)) return true;
        // In game, Back (or a pad's Home/Mode) opens the in-game menu instead
        // of closing the app; the launcher and the menu handle their own keys.
        if (GameMenu.isMenuKey(event.getKeyCode()) && !LauncherBridge.isShowing()
                && !GameMenu.isShowing()) {
            if (event.getAction() == KeyEvent.ACTION_UP) GameMenu.show(this);
            return true;
        }
        return super.dispatchKeyEvent(event);
    }

    @Override
    public boolean dispatchGenericMotionEvent(MotionEvent event) {
        if (LauncherBridge.dispatchPadMotion(event)) return true;
        return super.dispatchGenericMotionEvent(event);
    }

    @Override
    protected String[] getArguments() {
        // A test APK can carry runtime arguments (build_apk.py --launch-args).
        String text = GameData.readText(new File(getFilesDir(), "launch-args.txt")).trim();
        if (getIntent().getBooleanExtra(EXTRA_LAUNCHER, false)) {
            text = (text + "\n--launcher").trim();   // back from the in-game menu
        }
        return text.isEmpty() ? new String[0] : text.split("\n");
    }

    @Override
    protected String[] getLibraries() {
        // SDL is linked statically into libmain.so.
        return new String[] { "main" };
    }
}
