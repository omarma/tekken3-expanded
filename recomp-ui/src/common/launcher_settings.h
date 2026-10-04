// launcher_settings.h — the launcher's settings as data.
//
// One table describes each setting a front end can show: its section, label,
// kind (toggle, choice, stepper), when it applies, and which LauncherModel
// functions read and change it. A front end that is not ImGui (the native
// Android launcher) renders this table instead of re-deriving which setting
// exists for which game; the logic stays in launcher_model.c.

#ifndef LAUNCHER_SETTINGS_H
#define LAUNCHER_SETTINGS_H

#include "launcher_model.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    LSET_TOGGLE  = 0,   // on/off
    LSET_CHOICE  = 1,   // one of a list of labels (the model cycles through them)
    LSET_STEPPER = 2,   // a value changed by -/+ steps
} LauncherSettingKind;

typedef struct LauncherSetting {
    const char* id;
    const char* section;   // "display" or "audio"
    const char* label;
    const char* help;      // may be NULL
    int         kind;      // LauncherSettingKind
    int         step;      // LSET_STEPPER: the -/+ amount
    int         (*available)(const LauncherModel* m);
    const char* (*dynamic_label)(const LauncherModel* m);  // overrides label when non-NULL
    int         (*is_on)(const LauncherModel* m);           // LSET_TOGGLE
    void        (*toggle)(LauncherModel* m);                // LSET_TOGGLE
    const char* (*value)(const LauncherModel* m);           // LSET_CHOICE / LSET_STEPPER
    void        (*next)(LauncherModel* m);                  // LSET_CHOICE
    void        (*add)(LauncherModel* m, int delta);        // LSET_STEPPER
    int         (*experimental)(const LauncherModel* m);    // may be NULL
} LauncherSetting;

int                    launcher_settings_count(void);
const LauncherSetting* launcher_setting_at(int index);
const LauncherSetting* launcher_setting_find(const char* id);

int         launcher_setting_available(const LauncherSetting* s, const LauncherModel* m);
const char* launcher_setting_label(const LauncherSetting* s, const LauncherModel* m);

// LSET_CHOICE: the labels the setting can take, starting with the current one
// (index 0). Found by cycling a copy of the model, which is left unchanged.
// Returns the count.
int  launcher_setting_choices(LauncherModel* m, const LauncherSetting* s,
                              char labels[][96], int max);
// LSET_CHOICE: select the label at `index` of launcher_setting_choices().
void launcher_setting_choose(LauncherModel* m, const LauncherSetting* s, int index);

#ifdef __cplusplus
}
#endif

#endif // LAUNCHER_SETTINGS_H
