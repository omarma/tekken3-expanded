// bios_rom_alias.h — accept both BIOS ROM filename conventions.
//
// The multi-BIOS work introduced region-qualified ROM filenames
// ("US-PSX-SCPH1001.BIN", "US-PSOne-SCPH101.BIN", "EUR-PSX-SCPH5552.bin")
// alongside the historical bare model name ("SCPH1001.BIN"). Both conventions
// are in the wild: every existing dump folder, bios.cfg, game.toml and
// tools/regen_bios.sh default uses the bare name, while master's SCPH*.toml
// files now name the qualified one. Whichever a config asks for, the other
// must still be found — otherwise a config and a dump folder that disagree
// fatal out ("cannot open BIOS file") even though the right ROM is sitting
// right there.
//
// Matching is on the MODEL TOKEN: the last '-'-separated component of the
// filename stem, compared case-insensitively.
//
//     "US-PSX-SCPH1001.BIN"    -> SCPH1001
//     "SCPH1001.BIN"           -> SCPH1001
//     "EUR-PSX-SCPH5552.bin"   -> SCPH5552
//
// That is convention-agnostic rather than a hardcoded alias table, so a ROM
// named with a region prefix nobody has thought of yet still resolves.
//
// Header-only, and deliberately placed in recompiler/include because both
// build trees already put that directory on the include path (see
// runtime/runtime.cmake) — the recompiler resolves the [program] rom field
// with it, the runtime resolves its BIOS search rungs with it, and neither can
// drift from the other.

#pragma once

#include <cctype>
#include <filesystem>
#include <string>
#include <system_error>

namespace PSXRecompV4 {

// The model token of a BIOS filename: the last '-'-separated piece of the
// stem, uppercased. "" for an empty stem.
inline std::string bios_model_token(const std::filesystem::path& p) {
    std::string stem = p.stem().string();
    const size_t dash = stem.find_last_of('-');
    if (dash != std::string::npos) stem = stem.substr(dash + 1);
    for (char& c : stem) c = (char)std::toupper((unsigned char)c);
    return stem;
}

// Does `candidate` name the same BIOS model as `wanted_token`, with a
// BIOS-ish extension? Extension is compared case-insensitively (.BIN/.bin).
inline bool bios_name_matches(const std::filesystem::path& candidate,
                              const std::string& wanted_token) {
    if (wanted_token.empty()) return false;
    std::string ext = candidate.extension().string();
    for (char& c : ext) c = (char)std::tolower((unsigned char)c);
    if (ext != ".bin" && ext != ".rom") return false;
    return bios_model_token(candidate) == wanted_token;
}

// Resolve a configured BIOS ROM path to something that exists, tolerating
// either filename convention. Returns `configured` unchanged when nothing
// better is found, so the caller's own "cannot open BIOS file" diagnostic
// still fires and still names what was asked for.
inline std::filesystem::path resolve_bios_rom(const std::filesystem::path& configured) {
    namespace fs = std::filesystem;
    std::error_code ec;

    if (configured.empty()) return configured;
    if (fs::exists(configured, ec) && !fs::is_directory(configured, ec)) return configured;

    const std::string want = bios_model_token(configured);

    // Same directory, other naming convention (either direction).
    auto scan = [&](const fs::path& dir) -> fs::path {
        std::error_code dec;
        if (dir.empty() || !fs::is_directory(dir, dec)) return {};
        dec.clear();
        for (fs::directory_iterator it(dir, dec), end; !dec && it != end; it.increment(dec)) {
            if (!it->is_regular_file(dec)) continue;
            if (bios_name_matches(it->path(), want)) return it->path();
        }
        return {};
    };

    if (fs::path hit = scan(configured.parent_path()); !hit.empty()) return hit;

    // A config that names the ROM without its "bios/" directory (master's
    // SCPH5552.toml does exactly this) still resolves against the conventional
    // location.
    const fs::path bios_dir = configured.parent_path() / "bios";
    if (fs::path hit = scan(bios_dir); !hit.empty()) return hit;

    return configured;
}

}  // namespace PSXRecompV4
