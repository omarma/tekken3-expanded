// launcher_android.h — the Android launcher backend (native Android screens).

#ifndef LAUNCHER_ANDROID_H
#define LAUNCHER_ANDROID_H

#include "launcher_model.h"

#ifdef __cplusplus
extern "C" {
#endif

// Shows the launcher screens and waits for PLAY (LNG_ACTION_LAUNCH) or the
// player leaving (LNG_ACTION_QUIT). Returns LNG_ACTION_LAUNCH at once when
// the app registered no launcher screens (LauncherBridge.attach not called).
LngAction launcher_android_run(LauncherModel* m);

#ifdef __cplusplus
}
#endif

#endif // LAUNCHER_ANDROID_H
