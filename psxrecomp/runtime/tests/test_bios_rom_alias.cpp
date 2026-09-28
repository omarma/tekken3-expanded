// test_bios_rom_alias.cpp — both BIOS filename conventions resolve, both ways.
//
// Regression anchor for the multi-BIOS rename: master's SCPH*.toml name
// "US-PSX-SCPH1001.BIN" while every pre-existing dump folder, bios.cfg and
// tools/regen_bios.sh default name "SCPH1001.BIN". A config and a folder that
// disagree used to fatal with "cannot open BIOS file" despite the right ROM
// being present.

#include "bios_rom_alias.h"

#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>

namespace fs = std::filesystem;
using PSXRecompV4::bios_model_token;
using PSXRecompV4::resolve_bios_rom;

static int g_checks = 0;

static void check(bool cond, const char* what) {
    ++g_checks;
    if (!cond) { std::fprintf(stderr, "FAIL: %s\n", what); std::abort(); }
}

static void touch(const fs::path& p) {
    fs::create_directories(p.parent_path());
    std::ofstream(p, std::ios::binary).put('\0');
}

static bool same(const fs::path& a, const fs::path& b) {
    return a.lexically_normal() == b.lexically_normal();
}

int main() {
    // ---- model-token extraction -------------------------------------------
    check(bios_model_token("SCPH1001.BIN") == "SCPH1001", "bare stem token");
    check(bios_model_token("US-PSX-SCPH1001.BIN") == "SCPH1001", "qualified stem token");
    check(bios_model_token("US-PSOne-SCPH101.BIN") == "SCPH101", "PSOne token");
    check(bios_model_token("EUR-PSX-SCPH5552.bin") == "SCPH5552", "lowercase-ext token");
    check(bios_model_token("scph1001.bin") == "SCPH1001", "token is case-folded");

    const fs::path root = fs::temp_directory_path() / "psxrecomp-bios-alias-test";
    fs::remove_all(root);

    // ---- new config name, old folder layout --------------------------------
    {
        const fs::path dir = root / "old-folder" / "bios";
        touch(dir / "SCPH1001.BIN");
        const fs::path got = resolve_bios_rom(dir / "US-PSX-SCPH1001.BIN");
        check(same(got, dir / "SCPH1001.BIN"), "qualified request finds bare ROM");
    }

    // ---- old config name, new folder layout --------------------------------
    {
        const fs::path dir = root / "new-folder" / "bios";
        touch(dir / "US-PSX-SCPH1001.BIN");
        const fs::path got = resolve_bios_rom(dir / "SCPH1001.BIN");
        check(same(got, dir / "US-PSX-SCPH1001.BIN"), "bare request finds qualified ROM");
    }

    // ---- exact match always wins over an alias -----------------------------
    {
        const fs::path dir = root / "both" / "bios";
        touch(dir / "SCPH1001.BIN");
        touch(dir / "US-PSX-SCPH1001.BIN");
        check(same(resolve_bios_rom(dir / "SCPH1001.BIN"), dir / "SCPH1001.BIN"),
              "exact bare wins");
        check(same(resolve_bios_rom(dir / "US-PSX-SCPH1001.BIN"), dir / "US-PSX-SCPH1001.BIN"),
              "exact qualified wins");
    }

    // ---- lowercase extension + a different region prefix -------------------
    {
        const fs::path dir = root / "eur" / "bios";
        touch(dir / "EUR-PSX-SCPH5552.bin");
        check(same(resolve_bios_rom(dir / "SCPH5552.BIN"), dir / "EUR-PSX-SCPH5552.bin"),
              "lowercase .bin + EUR prefix resolves");
    }

    // ---- a config that omits the bios/ directory (master's SCPH5552.toml) --
    {
        const fs::path gameroot = root / "no-prefix";
        touch(gameroot / "bios" / "EUR-PSX-SCPH5552.bin");
        check(same(resolve_bios_rom(gameroot / "EUR-PSX-SCPH5552.bin"),
                   gameroot / "bios" / "EUR-PSX-SCPH5552.bin"),
              "missing bios/ prefix still resolves");
    }

    // ---- a different model must NOT be substituted -------------------------
    {
        const fs::path dir = root / "wrong-model" / "bios";
        touch(dir / "US-PSX-SCPH1001.BIN");
        const fs::path asked = dir / "SCPH101.BIN";
        check(same(resolve_bios_rom(asked), asked),
              "SCPH101 is not satisfied by SCPH1001");
    }

    // ---- non-BIOS files in the folder are ignored --------------------------
    {
        const fs::path dir = root / "noise" / "bios";
        touch(dir / "SCPH1001.json");
        touch(dir / "openbios.bin");
        const fs::path asked = dir / "SCPH1001.BIN";
        check(same(resolve_bios_rom(asked), asked), "wrong extension is not a match");
    }

    // ---- nothing found: return the request unchanged so the caller's own
    //      diagnostic still names what was asked for -------------------------
    {
        const fs::path asked = root / "empty" / "bios" / "SCPH1001.BIN";
        check(same(resolve_bios_rom(asked), asked), "unresolvable request passes through");
        check(resolve_bios_rom({}).empty(), "empty path passes through");
    }

    fs::remove_all(root);
    std::printf("bios_rom_alias: %d checks passed\n", g_checks);
    return 0;
}
