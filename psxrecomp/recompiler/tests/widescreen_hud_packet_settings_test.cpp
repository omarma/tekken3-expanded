#include "config_loader.h"

#include <cstdio>
#include <filesystem>
#include <fstream>
#include <functional>
#include <string>

namespace fs = std::filesystem;

static int failures;

static void check(bool condition, const char* message) {
    if (!condition) {
        std::fprintf(stderr, "FAIL: %s\n", message);
        ++failures;
    }
}

static fs::path write_game_toml(const std::string& name,
                                const std::string& widescreen_body) {
    const fs::path path = fs::temp_directory_path() / name;
    std::ofstream file(path, std::ios::binary | std::ios::trunc);
    file <<
        "[game]\n"
        "name = \"HUD packet probe\"\n"
        "exe = \"probe.exe\"\n"
        "load_address = \"0x80010000\"\n"
        "entry_pc = \"0x80010000\"\n"
        "text_size = \"0x1000\"\n"
        "[recompiler]\n"
        "seeds = \"seeds.json\"\n"
        "[runtime]\n"
        "[widescreen]\n" << widescreen_body;
    return path;
}

static void check_throws(const std::function<void()>& action,
                         const char* message) {
    try {
        action();
        check(false, message);
    } catch (const std::runtime_error&) {
    }
}

static void test_defaults_and_legacy_pair() {
    fs::path defaults = write_game_toml(
        "psxrecomp_ws_hud_packet_defaults.toml", "");
    auto empty = PSXRecompV4::load_game_config(defaults);
    check(empty.ws_nw_left_hud_packet_lo == 0 &&
          empty.ws_nw_left_hud_packet_hi == 0 &&
          empty.ws_nw_hud_packet2_lo == 0 &&
          empty.ws_nw_hud_packet2_hi == 0,
          "both HUD packet ranges default disabled");
    check(!empty.ws_nw_2d_edge_fill,
          "native-wide 2D edge fill defaults disabled");
    check(empty.ws_camera_zoom_num == 1 && empty.ws_camera_zoom_den == 1,
          "native-wide camera zoom defaults to identity");
    fs::remove(defaults);

    fs::path legacy = write_game_toml(
        "psxrecomp_ws_hud_packet_legacy.toml",
        "nw_left_hud_packet_lo = \"0x000DCC00\"\n"
        "nw_left_hud_packet_hi = \"0x000DD000\"\n");
    auto first = PSXRecompV4::load_game_config(legacy);
    check(first.ws_nw_left_hud_packet_lo == 0x000DCC00u &&
          first.ws_nw_left_hud_packet_hi == 0x000DD000u,
          "legacy HUD packet pair retains its values");
    check(first.ws_nw_hud_packet2_lo == 0 &&
          first.ws_nw_hud_packet2_hi == 0,
          "legacy config leaves the second range disabled");
    fs::remove(legacy);
}

static void test_2d_edge_fill_opt_in() {
    fs::path path = write_game_toml(
        "psxrecomp_ws_2d_edge_fill.toml",
        "nw_2d_edge_fill = true\n");
    auto config = PSXRecompV4::load_game_config(path);
    check(config.ws_nw_2d_edge_fill,
          "native-wide 2D edge fill reaches GameConfig");
    fs::remove(path);
}

static void test_camera_zoom_policy() {
    fs::path path = write_game_toml(
        "psxrecomp_ws_camera_zoom.toml",
        "camera_zoom_num = 3\n"
        "camera_zoom_den = 4\n");
    auto config = PSXRecompV4::load_game_config(path);
    check(config.ws_camera_zoom_num == 3 && config.ws_camera_zoom_den == 4,
          "native-wide camera zoom reaches GameConfig");
    fs::remove(path);

    fs::path invalid = write_game_toml(
        "psxrecomp_ws_camera_zoom_invalid.toml",
        "camera_zoom_num = 5\n"
        "camera_zoom_den = 4\n");
    check_throws([&] { (void)PSXRecompV4::load_game_config(invalid); },
                 "camera zoom rejects enlargement ratios");
    fs::remove(invalid);
}

static void test_dome_engine_projection_policy() {
    fs::path path = write_game_toml(
        "psxrecomp_ws_dome_policy.toml",
        "[widescreen.dome]\n"
        "call_sites = [\"0x80037A00\", \"0x80049AB4\"]\n"
        "overscan_num = 5\n"
        "overscan_den = 4\n"
        "min_sz = 4000\n");
    auto config = PSXRecompV4::load_game_config(path);
    check(config.ws_dome_call_sites.size() == 2 &&
          config.ws_dome_call_sites[0] == 0x80037A00u &&
          config.ws_dome_call_sites[1] == 0x80049AB4u,
          "dome call sites reach GameConfig");
    check(config.ws_dome_overscan_num == 5 &&
          config.ws_dome_overscan_den == 4 &&
          config.ws_dome_min_sz == 4000,
          "dome overscan and depth floor reach GameConfig");
    fs::remove(path);
}

static void test_full_visibility_aperture() {
    fs::path path = write_game_toml(
        "psxrecomp_ws_full_aperture.toml",
        "[[widescreen.cull.angle]]\n"
        "address = \"0x8006D1C4\"\n"
        "expected = \"0x24040258\"\n"
        "full_angle = true\n"
        "[[widescreen.cull.angle]]\n"
        "address = \"0x8006D24C\"\n"
        "expected = \"0x2404030C\"\n");
    auto config = PSXRecompV4::load_game_config(path);
    check(config.ws_cull_angle_sites.size() == 2,
          "both full and legacy visibility sites parse");
    check(config.ws_cull_angle_sites[0].full_angle &&
          !config.ws_cull_angle_sites[1].full_angle,
          "full aperture opt-in leaves legacy half-angle semantics unchanged");
    fs::remove(path);
}

static void test_two_ranges_parse_independently() {
    fs::path path = write_game_toml(
        "psxrecomp_ws_hud_packet_two_ranges.toml",
        "nw_left_hud_packet_lo = \"0x000DCC00\"\n"
        "nw_left_hud_packet_hi = \"0x000DD000\"\n"
        "nw_hud_packet2_lo = \"0x000ECC00\"\n"
        "nw_hud_packet2_hi = \"0x000ED000\"\n");
    auto config = PSXRecompV4::load_game_config(path);
    check(config.ws_nw_hud_packet2_lo == 0x000ECC00u &&
          config.ws_nw_hud_packet2_hi == 0x000ED000u,
          "second HUD packet pair reaches GameConfig");
    fs::remove(path);
}

static void test_second_pair_validation() {
    fs::path missing_hi = write_game_toml(
        "psxrecomp_ws_hud_packet_missing_hi.toml",
        "nw_hud_packet2_lo = \"0x000ECC00\"\n");
    check_throws(
        [&] { (void)PSXRecompV4::load_game_config(missing_hi); },
        "second HUD range requires its high bound");
    fs::remove(missing_hi);

    fs::path missing_lo = write_game_toml(
        "psxrecomp_ws_hud_packet_missing_lo.toml",
        "nw_hud_packet2_hi = \"0x000ED000\"\n");
    check_throws(
        [&] { (void)PSXRecompV4::load_game_config(missing_lo); },
        "second HUD range requires its low bound");
    fs::remove(missing_lo);

    fs::path reversed = write_game_toml(
        "psxrecomp_ws_hud_packet_reversed.toml",
        "nw_hud_packet2_lo = \"0x000ED000\"\n"
        "nw_hud_packet2_hi = \"0x000ECC00\"\n");
    check_throws(
        [&] { (void)PSXRecompV4::load_game_config(reversed); },
        "second HUD range rejects empty or reversed bounds");
    fs::remove(reversed);
}

int main() {
    test_full_visibility_aperture();
    test_defaults_and_legacy_pair();
    test_2d_edge_fill_opt_in();
    test_camera_zoom_policy();
    test_dome_engine_projection_policy();
    test_two_ranges_parse_independently();
    test_second_pair_validation();

    if (failures) return 1;
    std::puts("ALL PASS");
    return 0;
}
