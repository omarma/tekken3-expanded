package org.recompui.launcher;

import android.app.Activity;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewGroup;

import org.libsdl.app.SDLActivity;
import org.libsdl.app.SDLControllerManager;

/**
 * The link between recomp-ui's launcher model (C, launcher_android.c) and the
 * native launcher screens (LauncherView).
 *
 * The app calls attach() once its native library is loaded. When the runtime
 * reaches the launcher, native code calls show() and waits; the screens read
 * and change settings through the native methods, and PLAY (nativePlay) or
 * leaving (nativeQuit) lets the runtime go on. Data comes back as JSON.
 */
public final class LauncherBridge {
    private static Activity sActivity;
    private static LauncherView sView;

    private LauncherBridge() {}

    /** Enables the native launcher for this activity. */
    public static void attach(Activity activity) {
        sActivity = activity;
        nativeRegister();
    }

    /** True while the launcher screens cover the game. */
    public static boolean isShowing() {
        return sView != null;
    }

    /**
     * While a controller button is being bound (the Buttons page), the pad's
     * events go to SDL, where the native launcher reads them, instead of
     * moving the focus around the screens. The activity calls these first.
     */
    public static boolean dispatchPadKey(KeyEvent event) {
        if (sView == null || !nativeCapturing()
                || !SDLControllerManager.isDeviceSDLJoystick(event.getDeviceId())) return false;
        SDLActivity.handleKeyEvent(null, event.getKeyCode(), event, null);
        return true;
    }

    public static boolean dispatchPadMotion(MotionEvent event) {
        if (sView == null || !nativeCapturing()
                || !SDLControllerManager.isDeviceSDLJoystick(event.getDeviceId())) return false;
        SDLControllerManager.handleJoystickMotionEvent(event);
        return true;
    }

    // Called by native code, on the runtime's thread.
    static void show() {
        final Activity activity = sActivity;
        if (activity == null) return;
        activity.runOnUiThread(() -> {
            if (sView != null) return;
            // Full screen: status and navigation bars come back on a swipe.
            activity.getWindow().getDecorView().setSystemUiVisibility(
                    View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY | View.SYSTEM_UI_FLAG_FULLSCREEN
                    | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                    | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION);
            sView = new LauncherView(activity);
            activity.addContentView(sView, new ViewGroup.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
            sView.start();
        });
    }

    static void hide() {
        final View view = sView;
        sView = null;
        if (view != null && view.getParent() instanceof ViewGroup) {
            ((ViewGroup) view.getParent()).removeView(view);
        }
    }

    static native void nativeRegister();
    static native String nativeGame();
    static native String nativeSettings(String section);
    static native String nativeChoices(String id);
    static native void nativeChoose(String id, int index);
    static native void nativeToggle(String id);
    static native void nativeStep(String id, int direction);
    static native String nativePlayers();
    static native void nativeSetSource(int player, int index);
    static native void nativeSetPadMode(int player, int mode);
    static native String nativeBindings(int player);
    static native void nativeCaptureButton(int player, int button);
    static native void nativeCaptureAll(int player);
    static native boolean nativeCapturing();
    static native void nativeCancelCapture();
    static native void nativeResetBindings(int player);
    static native void nativeSaveBindings(int player);
    static native String nativeMemcards();
    static native void nativeToggleMemcard(int slot);
    static native String nativeNewMemcard(int slot);
    static native String nativeMods();
    static native String nativeModOptions(String pkg, String id);
    static native boolean nativeModEnable(String pkg, String id, boolean on);
    static native boolean nativeModSetOption(String pkg, String id, String option, String value);
    static native String nativePlay();
    static native void nativeQuit();
}
