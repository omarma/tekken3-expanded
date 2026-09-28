// launcher_profile.h — per-system "variant profiles" (ABI apply dispatcher).
//
// A variant profile bundles a whole console's launcher identity as ONE unit so
// theme, controller art, platform label, ROM noun, and capability set can never
// drift apart. A host selects a profile by name (its system), then overrides the
// per-GAME specifics (which aspects THIS title offers, whether pad-mode is
// locked, the box art, ROM hashes, etc.).
//
//   RecompLauncherCGameInfo gi = {0};
//   launcher_profile_apply("psx", &gi);   // system defaults (theme+pad+caps)
//   gi.name = "Ape Escape"; gi.aspect_mask = 0x7; gi.pad_mode_selectable = 0; ...
//
// The controller IMAGE is staged per variant by the build (recomp_ui.cmake PAD
// override, or the shipped pad_analog/pad_digital.tga when pad_mode_supported).
// This header only sets the DATA (theme name, platform, rom_noun, capability
// flags); it never hardcodes a look into the core.
//
// Built-out consoles keep their apply row in their own unit under
// src/consoles/<id>/<id>_profile.h (launcher_profile_apply_<id>() + the name
// matcher) — this header just dispatches by name. Consoles still stubbed get
// an identity-only row inline below until they are built out.
//
// Adding a new system = add src/consoles/<id>/ and one dispatch line here.

#ifndef LAUNCHER_PROFILE_H
#define LAUNCHER_PROFILE_H

#include "recomp_launcher.h"
#include "consoles/snes/snes_profile.h"
#include "consoles/psx/psx_profile.h"
#include "consoles/gba/gba_profile.h"
#include "consoles/n64/n64_profile.h"
#include "consoles/nes/nes_profile.h"
#include "consoles/genesis/genesis_profile.h"
#include "consoles/gb/gb_profile.h"
#include "consoles/nds/nds_profile.h"
#include <string.h>

#ifdef __cplusplus
extern "C" {
#endif

// Case-insensitive exact-string match helper (avoids <ctype.h> in a header).
// Kept for source compatibility with existing hosts/harnesses that call it
// (e.g. proto_main.c); new per-console code uses lps_streq_ci
// (launcher_system_types.h) / the launcher_console_is_<id>() matchers.
static inline int lpr_is(const char* a, const char* b) {
    if (!a || !b) return 0;
    for (; *a && *b; ++a, ++b) {
        char ca = (*a >= 'A' && *a <= 'Z') ? (char)(*a + 32) : *a;
        char cb = (*b >= 'A' && *b <= 'Z') ? (char)(*b + 32) : *b;
        if (ca != cb) return 0;
    }
    return *a == 0 && *b == 0;
}

// Apply a system's default identity + capabilities onto `gi`. Unknown names get
// the neutral default (CRT theme, "ROM" noun, no extra capabilities). Returns 1
// if the name matched a known profile, 0 otherwise. The host should call this
// FIRST, then set per-game fields (name, box art, hashes, and any per-title
// capability overrides such as which aspects the game actually offers).
static inline int launcher_profile_apply(const char* name, RecompLauncherCGameInfo* gi) {
    if (!gi) return 0;

    // --- built-out consoles (rows live in src/consoles/<id>/) ----------------
    if (launcher_console_is_psx(name))  { launcher_profile_apply_psx(gi);  return 1; }
    if (launcher_console_is_snes(name)) { launcher_profile_apply_snes(gi); return 1; }
    if (launcher_console_is_gba(name))  { launcher_profile_apply_gba(gi);  return 1; }
    if (launcher_console_is_n64(name))  { launcher_profile_apply_n64(gi);  return 1; }
    if (launcher_console_is_nes(name))  { launcher_profile_apply_nes(gi);  return 1; }
    if (launcher_console_is_genesis(name)) { launcher_profile_apply_genesis(gi); return 1; }
    if (launcher_console_is_gbc(name))  { launcher_profile_apply_gbc(gi);  return 1; }
    if (launcher_console_is_gb(name))   { launcher_profile_apply_gb(gi);   return 1; }
    if (launcher_console_is_nds(name))  { launcher_profile_apply_nds(gi);  return 1; }

    // --- other systems: identity now, capabilities refined as each is built --
    if (lpr_is(name, "smsgg") || lpr_is(name, "sms") || lpr_is(name, "gg")) {
        gi->theme = NULL; gi->platform = "MASTER SYSTEM"; gi->rom_noun = "ROM"; return 1;
    }
    if (lpr_is(name, "vb") || lpr_is(name, "virtualboy")) {
        gi->theme = NULL; gi->platform = "VIRTUAL BOY"; gi->rom_noun = "ROM"; return 1;
    }

    // Neutral fallback.
    gi->theme = NULL; gi->rom_noun = "ROM";
    return 0;
}

#ifdef __cplusplus
}
#endif

#endif // LAUNCHER_PROFILE_H
