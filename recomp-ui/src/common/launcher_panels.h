// launcher_panels.h — the launcher's PANEL system (composition unit).
//
// Every card the launcher draws — GAME, CONTROLLER, DISPLAY, AUDIO, INPUT
// (multitap), SYSTEM (BIOS), HOTKEYS, the CONTROLLER-view rebind page — is a
// registered LauncherPanel: a stable id, which view it belongs to, a slot
// hint for layout, an `available` predicate (per-GAME gating), and a `draw`
// function (the card body; the caller has already opened the card chrome).
//
// The launcher does NOT hardcode which panels a console gets: each
// SystemProfile (launcher_system.h) lists panel ids in
// panels_dashboard/panels_settings/panels_controller — that is the
// COMPOSITION half of the architecture (docs/ARCHITECTURE.md). The registry
// here is just the id -> draw-function lookup table; a system's array
// decides which ids it uses and in what order.
//
// Panels are game-AGNOSTIC: they read capability from the model (which is
// built from the game's C-ABI struct + its inferred SystemProfile), never
// from a game name.

#ifndef LAUNCHER_NG_PANELS_H
#define LAUNCHER_NG_PANELS_H

#include "launcher_model.h"
#include "launcher_theme.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    LNG_SLOT_MAIN = 0,   // primary column (dashboard: art-led GAME; settings: DISPLAY)
    LNG_SLOT_SIDE,       // secondary column (dashboard: CONTROLLER; settings: AUDIO, then INPUT/SYSTEM/… stacked below)
    LNG_SLOT_WIDE,       // spans the full width (HOTKEYS, CONTROLLER-view page)
} LngPanelSlot;

// A panel is a composition unit (docs/ARCHITECTURE.md "Concrete C shape").
typedef struct {
    const char* id;
    LngView     view;      // which view it appears in
    int         slot;      // LngPanelSlot
    int  (*available)(const LauncherModel* m);        // NULL => always available
    void (*draw)(LauncherModel* m, const LauncherTheme* th);
} LauncherPanel;

// The registry for the current build. Returns a {id=NULL} sentinel-terminated
// array; implemented by the active render backend (today: launcher_imgui.cpp,
// the only backend — its draw functions are the only ones that speak ImGui).
const LauncherPanel* launcher_panels_all(void);

// Look up a registered panel by id (from a SystemProfile's panels_* array).
// Returns NULL if no panel with that id is registered.
const LauncherPanel* launcher_panel_find(const char* id);

// True when this panel should be shown for this game (available == NULL means
// unconditionally available; a system's composition array is what already
// decided this game's system offers the panel at all).
bool launcher_panel_available(const LauncherPanel* p, const LauncherModel* m);

#ifdef __cplusplus
}
#endif

#endif // LAUNCHER_NG_PANELS_H
