// launcher_system.h — SystemProfile aggregator: one row per console.
//
// The TYPES (SystemProfile + its module specs) live in
// src/common/launcher_system_types.h; each BUILT-OUT console's row lives in
// its own unit under src/consoles/<id>/<id>_profile.h (pad vocabulary +
// panel composition + profile row + ABI capability defaults, one file per
// console). This header aggregates them and provides the by-id / inference
// lookups, plus stub rows for consoles nobody ships on yet.
//
// Adding a system = adding src/consoles/<id>/<id>_profile.h (copy a built-out
// console — PSX is the deep-surface model, GBA the cartridge-handheld model),
// including it here, and registering it in the two lookups below + the
// dispatch in src/launcher_profile.h. Nothing else in the core changes.
//
// ---- how a game's SystemProfile is chosen -----------------------------------
// The public C ABI (RecompLauncherCGameInfo, recomp_launcher.h) is NOT changed
// by this refactor — hosts keep calling launcher_profile_apply(name, gi) (or
// hand-building `gi`) exactly as before, and that keeps writing the same ABI
// capability flags it always has. launcher_system_infer() below derives the
// matching SystemProfile FROM those already-set ABI fields (primarily
// `platform`, with a capability-flag fallback for callers that build `gi` by
// hand without going through launcher_profile_apply). launcher_model_init()
// calls it once and caches the result on the model so panels never re-infer.

#ifndef LAUNCHER_NG_SYSTEM_H
#define LAUNCHER_NG_SYSTEM_H

#include "launcher_system_types.h"

#include "consoles/snes/snes_profile.h"
#include "consoles/psx/psx_profile.h"
#include "consoles/gba/gba_profile.h"
#include "consoles/n64/n64_profile.h"
#include "consoles/nes/nes_profile.h"
#include "consoles/genesis/genesis_profile.h"
#include "consoles/gb/gb_profile.h"
#include "consoles/nds/nds_profile.h"

#ifdef __cplusplus
extern "C" {
#endif

// ---- stub rows: identity only, minimal composition, NOT verified today --------
// These never get selected by launcher_system_infer() unless a host sets
// `platform` to exactly match (launcher_profile_apply already does, per name)
// — no game ships on these yet, so they render with the same minimal
// (legacy/SNES-shaped) settings surface as a safe default. Promoting a stub
// to a real console = moving it to src/consoles/<id>/ (see header comment).
#define LNG_STUB_PROFILE(ID, PLATFORM, ROM_NOUN)                                   \
    static const SystemProfile kSystemProfile_##ID = {                            \
        #ID, PLATFORM, NULL, ROM_NOUN,                                             \
        { kSnesPadButtons, LNG_SNES_PAD_BUTTON_COUNT, "pad.tga", NULL, NULL, 2, 0 },\
        { SAVE_NONE, 0, NULL },                                                    \
        { 1, 0, 1, 0, 0,0,0,0,0, 0,0,0,0,0, 0,0 },                                 \
        { 0, NULL },                                                               \
        LNG_HOTKEYS_ALL,                                                           \
        kPanelsDashboardCommon, kPanelsSettingsStub, kPanelsControllerCommon,      \
    }

LNG_STUB_PROFILE(smsgg,  "MASTER SYSTEM",      "ROM");
LNG_STUB_PROFILE(vb,     "VIRTUAL BOY",        "ROM");

#undef LNG_STUB_PROFILE

// Resolve a SystemProfile by its short id ("psx", "snes", ...) — same names
// launcher_profile_apply() accepts. Returns NULL if unknown.
static inline const SystemProfile* launcher_system_by_id(const char* name) {
    if (!name || !name[0]) return NULL;
    if (launcher_console_is_psx(name))  return &kSystemProfilePsx;
    if (launcher_console_is_snes(name)) return &kSystemProfileSnes;
    if (launcher_console_is_gba(name))  return &kSystemProfileGba;
    if (launcher_console_is_n64(name))  return &kSystemProfileN64;
    if (launcher_console_is_nes(name))  return &kSystemProfileNes;
    if (launcher_console_is_genesis(name)) return &kSystemProfileGenesis;
    if (launcher_console_is_gbc(name))  return &kSystemProfileGbc;
    if (launcher_console_is_gb(name))   return &kSystemProfileGb;
    if (launcher_console_is_nds(name))  return &kSystemProfileNds;
    if (lps_streq_ci(name, "smsgg") || lps_streq_ci(name, "sms") || lps_streq_ci(name, "gg"))
        return &kSystemProfile_smsgg;
    if (lps_streq_ci(name, "vb") || lps_streq_ci(name, "virtualboy")) return &kSystemProfile_vb;
    return NULL;
}

// Infer the SystemProfile for a game built through the C ABI. Primary signal
// is `platform` (the same console-subtitle string launcher_profile_apply()
// already sets per system — a de facto system id already present in the ABI).
// Falls back to a capability-flag heuristic for hosts that hand-build
// RecompLauncherCGameInfo without a recognized platform string (matches
// today's ONLY two real capability shapes: the PSX "deep settings" surface,
// or the legacy/SNES-shaped minimal surface).
static inline const SystemProfile* launcher_system_infer(const RecompLauncherCGameInfo* gi) {
    if (gi && gi->platform && gi->platform[0]) {
        if (lps_streq_ci(gi->platform, "PLAYSTATION"))       return &kSystemProfilePsx;
        if (lps_streq_ci(gi->platform, "SUPER NINTENDO"))    return &kSystemProfileSnes;
        if (lps_streq_ci(gi->platform, "NINTENDO 64"))       return &kSystemProfileN64;
        // Both spellings: launcher_profile_apply_genesis sets "SEGA GENESIS";
        // "GENESIS" was the pre-buildout stub label (kept for host compat).
        if (lps_streq_ci(gi->platform, "SEGA GENESIS"))      return &kSystemProfileGenesis;
        if (lps_streq_ci(gi->platform, "GENESIS"))           return &kSystemProfileGenesis;
        if (lps_streq_ci(gi->platform, "GAME BOY ADVANCE"))  return &kSystemProfileGba;
        // Both the built-out label and the old stub's "NINTENDO" resolve to
        // the NES row, so hosts built against the stub-era string keep working.
        if (lps_streq_ci(gi->platform, "NINTENDO ENTERTAINMENT SYSTEM"))
            return &kSystemProfileNes;
        if (lps_streq_ci(gi->platform, "NINTENDO"))          return &kSystemProfileNes;
        if (lps_streq_ci(gi->platform, "GAME BOY COLOR"))    return &kSystemProfileGbc;
        if (lps_streq_ci(gi->platform, "GAME BOY"))          return &kSystemProfileGb;
        if (lps_streq_ci(gi->platform, "NINTENDO DS"))       return &kSystemProfileNds;
        if (lps_streq_ci(gi->platform, "MASTER SYSTEM"))     return &kSystemProfile_smsgg;
        if (lps_streq_ci(gi->platform, "VIRTUAL BOY"))       return &kSystemProfile_vb;
    }
    if (gi && (gi->pad_mode_supported || gi->has_window_size || gi->has_renderer ||
               gi->has_bios || gi->has_supersampling))
        return &kSystemProfilePsx;
    return &kSystemProfileSnes;   // default: today's minimal/legacy surface
}

#ifdef __cplusplus
}
#endif

#endif // LAUNCHER_NG_SYSTEM_H
