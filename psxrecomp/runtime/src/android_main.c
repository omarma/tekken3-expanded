/* android_main.c — Android entry point for the runtime (libmain.so).
 *
 * SDLActivity loads libmain.so and calls SDL_main on its own thread. The
 * activity has already extracted the APK's data into the app's internal
 * storage, laid out like the PC build folder (the disc's tracks stay in the
 * APK, see android_apk_file.c); running from there lets every
 * relative path the runtime uses (SDL_GetBasePath is "./" on Android) resolve
 * as it does on PC. stdout and stderr go nowhere on Android, so both are
 * forwarded to logcat under the "psxrecomp" tag.
 */
#include <SDL3/SDL.h>

#include <android/log.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "savestate.h"
#include "touch_controls.h"

#include <jni.h>

int main(int argc, char** argv);

/* ---- in-game menu (org.psxrecomp.GameMenu) --------------------------------
 * Back (or a pad's Home/Mode button) opens a native menu over the game. While
 * it is open the game waits at the vblank boundary (psx_android_pause_gate,
 * called from main.cpp's vblank body); save/load states go through the same
 * requests as the desktop F1-F12 keys and run once the game resumes. Back to
 * launcher quits like Quit game, then the app starts again, in a new process,
 * on the launcher: the next game starts from scratch. */
static volatile int s_menu_paused;
static volatile int s_back_to_launcher;

/* The runtime leaves with std::exit (main.cpp, on SDL_QUIT, once the memory
 * cards are flushed): no Java code runs after it. So the new start is asked
 * for here, from the exit itself (atexit) or main's return, while the app is
 * still in the foreground: the activity's relaunchOnLauncher() starts it
 * again, and Android starts that in a new process once this one is gone. */
static void relaunch_if_asked(void)
{
    if (!s_back_to_launcher) return;
    s_back_to_launcher = 0;
    JNIEnv* env = (JNIEnv*)SDL_GetAndroidJNIEnv();
    jobject activity = env ? (jobject)SDL_GetAndroidActivity() : NULL;
    if (!activity) {
        __android_log_write(ANDROID_LOG_ERROR, "psxrecomp", "back to the launcher: no activity");
        return;
    }
    jclass cls = (*env)->GetObjectClass(env, activity);
    jmethodID relaunch = (*env)->GetMethodID(env, cls, "relaunchOnLauncher", "()V");
    if (relaunch) (*env)->CallVoidMethod(env, activity, relaunch);
    if ((*env)->ExceptionCheck(env)) {
        (*env)->ExceptionDescribe(env);
        (*env)->ExceptionClear(env);
    }
    (*env)->DeleteLocalRef(env, cls);
    (*env)->DeleteLocalRef(env, activity);
    __android_log_write(ANDROID_LOG_INFO, "psxrecomp", "back to the launcher: the app starts again");
}

JNIEXPORT void JNICALL Java_org_psxrecomp_GameMenu_nativeBackToLauncher(JNIEnv* env, jclass cls)
{
    (void)env; (void)cls;
    s_back_to_launcher = 1;   /* then nativeQuit: the runtime exits, relaunch_if_asked runs */
}

void psx_android_pause_gate(void)
{
    while (s_menu_paused) {
        SDL_PumpEvents();   /* lifecycle (backgrounding) keeps working */
        SDL_Delay(16);
    }
}

JNIEXPORT void JNICALL Java_org_psxrecomp_GameMenu_nativeSetPaused(JNIEnv* env, jclass cls,
                                                                   jboolean paused)
{
    (void)env; (void)cls;
    s_menu_paused = paused ? 1 : 0;
    touch_controls_release_all();   /* the menu took the fingers */
}

JNIEXPORT jboolean JNICALL Java_org_psxrecomp_GameMenu_nativeSlotUsed(JNIEnv* env, jclass cls,
                                                                      jint slot)
{
    (void)env; (void)cls;
    return savestate_slot_exists(slot) ? JNI_TRUE : JNI_FALSE;
}

JNIEXPORT jboolean JNICALL Java_org_psxrecomp_GameMenu_nativeSaveState(JNIEnv* env, jclass cls,
                                                                       jint slot)
{
    (void)env; (void)cls;
    return savestate_request_save(slot) ? JNI_TRUE : JNI_FALSE;
}

JNIEXPORT jboolean JNICALL Java_org_psxrecomp_GameMenu_nativeLoadState(JNIEnv* env, jclass cls,
                                                                       jint slot)
{
    (void)env; (void)cls;
    return savestate_request_load(slot) ? JNI_TRUE : JNI_FALSE;
}

void psx_input_status(char* out, int cap);   /* main.cpp */

/* The layout editor (org.psxrecomp.TouchEditor) saved touch_controls.ini. */
JNIEXPORT void JNICALL Java_org_psxrecomp_GameMenu_nativeReloadTouch(JNIEnv* env, jclass cls)
{
    (void)env; (void)cls;
    touch_controls_reload();
}

JNIEXPORT jstring JNICALL Java_org_psxrecomp_GameMenu_nativeStatus(JNIEnv* env, jclass cls)
{
    (void)cls;
    char text[1024];
    psx_input_status(text, sizeof(text));
    for (char* c = text; *c; ++c) if ((unsigned char)*c >= 0x80) *c = '?';   /* modified UTF-8 */
    return (*env)->NewStringUTF(env, text);
}

/* The display cutout's insets, as fractions of the screen (org.psxrecomp.SafeArea). */
JNIEXPORT void JNICALL Java_org_psxrecomp_SafeArea_nativeSetSafeArea(JNIEnv* env, jclass cls,
                                                                   jfloat left, jfloat top,
                                                                   jfloat right, jfloat bottom)
{
    (void)env; (void)cls;
    psx_safe_area_set(left, top, right, bottom);
}

JNIEXPORT void JNICALL Java_org_psxrecomp_GameMenu_nativeQuit(JNIEnv* env, jclass cls)
{
    (void)env; (void)cls;
    s_menu_paused = 0;
    SDL_Event quit;
    SDL_zero(quit);
    quit.type = SDL_EVENT_QUIT;
    SDL_PushEvent(&quit);   /* the runtime's own exit: memory cards flushed */
}

static int s_log_pipe[2] = { -1, -1 };
/* The last run's log, also as a file in the data folder, for the in-game
 * menu's Share log (org.psxrecomp.GameMenu). */
static FILE* s_log_file;

static void* log_forward_thread(void* arg)
{
    (void)arg;
    char line[1024];
    size_t used = 0;
    for (;;) {
        char c;
        ssize_t n = read(s_log_pipe[0], &c, 1);
        if (n <= 0) break;
        if (c == '\n' || used == sizeof(line) - 1) {
            line[used] = '\0';
            __android_log_write(ANDROID_LOG_INFO, "psxrecomp", line);
            if (s_log_file) { fputs(line, s_log_file); fputc('\n', s_log_file); fflush(s_log_file); }
            used = 0;
            if (c == '\n') continue;
        }
        line[used++] = c;
    }
    return NULL;
}

static void forward_stdio_to_logcat(void)
{
    const char* data = SDL_GetAndroidInternalStoragePath();
    if (data) {
        char path[1024];
        snprintf(path, sizeof(path), "%s/psxrecomp.log", data);
        s_log_file = fopen(path, "w");
    }
    if (pipe(s_log_pipe) != 0) return;
    setvbuf(stdout, NULL, _IOLBF, 0);
    setvbuf(stderr, NULL, _IONBF, 0);
    dup2(s_log_pipe[1], STDOUT_FILENO);
    dup2(s_log_pipe[1], STDERR_FILENO);
    pthread_t thread;
    if (pthread_create(&thread, NULL, log_forward_thread, NULL) == 0)
        pthread_detach(thread);
}

__attribute__((visibility("default")))
int SDL_main(int argc, char** argv)
{
    forward_stdio_to_logcat();
    /* Landscape only. SDL picks the orientation from the window otherwise,
     * and the launcher's window is resizable, so it would follow the phone. */
    SDL_SetHint(SDL_HINT_ORIENTATIONS, "LandscapeLeft LandscapeRight");

    const char* data = SDL_GetAndroidInternalStoragePath();
    if (!data || chdir(data) != 0) {
        __android_log_print(ANDROID_LOG_ERROR, "psxrecomp",
                            "cannot enter the data folder %s", data ? data : "(none)");
        return 1;
    }

    /* An APK built with --disc-sector-log maps the disc sectors the game
     * reads (disc_sector_log.c) into the app's external files folder, where
     * adb pull and a USB file transfer reach it. */
    const char* external = NULL;
    if (!getenv("PSX_DISC_SECTOR_LOG") && access("disc-sector-log.on", F_OK) == 0 &&
        (external = SDL_GetAndroidExternalStoragePath()) != NULL) {
        char log_path[1024];
        snprintf(log_path, sizeof log_path, "%s/disc-sectors.bin", external);
        setenv("PSX_DISC_SECTOR_LOG", log_path, 1);
    }

    /* argv[0] names the runtime beside its data, as on PC. */
    char* args[64];
    int count = 0;
    args[count++] = "./main";
    for (int i = 1; i < argc && count < 63; i++) args[count++] = argv[i];
    args[count] = NULL;
    atexit(relaunch_if_asked);   /* Back to launcher (see relaunch_if_asked) */
    const int code = main(count, args);
    relaunch_if_asked();
    return code;
}
