// launcher_imgui.cpp — Dear ImGui (MIT) backend for the next-gen launcher.
//
// Draws the shared LauncherModel with Dear ImGui + SDL3 + OpenGL3, at parity
// with the shipping legacy MMX launcher (box art, controller art, and all
// panels). Icons are drawn as vector primitives rather than font glyphs so they
// stay crisp at any DPI and don't depend on the text font's glyph coverage.
// Demonstrates the two hard requirements:
//   (1) DPI: fonts re-rasterize at (logical size * display_scale); style
//       re-scales on display-scale change -> crisp at 125/150/175% + monitors.
//   (2) Live resize: immediate mode redraws every frame; a logical-width
//       breakpoint switches the dashboard between two columns and one column.

#include "launcher_backend.h"
#include "launcher_boot_timing.h"
#include "launcher_gl.h"
#include "launcher_input.h"
#include "launcher_files.h"
#include "launcher_debug.h"
#include "launcher_binds.h"
#include "launcher_udp_port.h"
#include "launcher_panels.h"
#include "launcher_system.h"
#include "consoles/n64/n64_binds.h"   // RUI_N64_FIELD_* for the pad-capture path

#include "launcher_sdlcompat.h"   // pulls the right SDL header + event shim

#include "imgui.h"
#if defined(LNG_SDL3)
  #include "imgui_impl_sdl3.h"
  #define LNG_ImplSDL_InitForOpenGL  ImGui_ImplSDL3_InitForOpenGL
  #define LNG_ImplSDL_NewFrame       ImGui_ImplSDL3_NewFrame
  #define LNG_ImplSDL_ProcessEvent   ImGui_ImplSDL3_ProcessEvent
  #define LNG_ImplSDL_Shutdown       ImGui_ImplSDL3_Shutdown
#else
  #include "imgui_impl_sdl2.h"
  #define LNG_ImplSDL_InitForOpenGL  ImGui_ImplSDL2_InitForOpenGL
  #define LNG_ImplSDL_NewFrame       ImGui_ImplSDL2_NewFrame
  #define LNG_ImplSDL_ProcessEvent   ImGui_ImplSDL2_ProcessEvent
  #define LNG_ImplSDL_Shutdown       ImGui_ImplSDL2_Shutdown
#endif
#include "imgui_impl_opengl3.h"

#include <atomic>
#if defined(_MSC_VER)
  #include <intrin.h>
#endif

// ---- Dear ImGui version compatibility ----------------------------------------
// recomp-ui's vendored ImGui is 1.91.x, but a host can reuse its OWN single
// ImGui copy via recomp_ui.cmake HOST_IMGUI (e.g. gb-recompiled vendors 1.90.4;
// an rt64 host links 1.90.x). Map the few 1.91-renamed identifiers this file
// uses onto their 1.90 spellings so the same source compiles against either.
// (ConfigNavCursorVisibleAlways has no 1.90 equivalent — it is #if-guarded at
// its use site.)
#if !defined(IMGUI_VERSION_NUM) || IMGUI_VERSION_NUM < 19100
  #ifndef ImGuiChildFlags_Borders
  #define ImGuiChildFlags_Borders     ImGuiChildFlags_Border
  #endif
  #ifndef ImGuiCol_NavCursor
  #define ImGuiCol_NavCursor          ImGuiCol_NavHighlight
  #endif
  #ifndef ImGuiButtonFlags_EnableNav
  // 1.90's InvisibleButton participates in nav by default; the opt-in flag is 0.
  #define ImGuiButtonFlags_EnableNav  0
  #endif
#endif

#include <algorithm>
#include <cerrno>
#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <string>
#include <unordered_map>
#include <vector>
#if defined(_WIN32)
#include <direct.h>
#else
#include <sys/stat.h>
#endif

extern "C" const char* launcher_backend_name(void) { return "Dear ImGui"; }

// `volatile` on purpose. Under a host build with -Os -ffunction-sections
// -fdata-sections + -Wl,--gc-sections (gb-recompiled's generated projects),
// GCC 15.2 miscompiled the plain global: a store to g_th did not stick (read
// back NULL at the same address unless another statement intervened). Marking
// it volatile forces every read/write to hit memory and sidesteps the bug.
// The theme pointer is set once per launcher run and read every frame, so the
// volatile access cost is irrelevant.
const LauncherTheme* volatile g_th = nullptr;

namespace {

// ImGui coordinates are already DPI-independent: the SDL2 platform reports the
// window in points and the GL backend applies DisplayFramebufferScale when it
// submits vertices to the (Retina/HiDPI) drawable. Scaling widget geometry here
// too would DOUBLE every size on HiDPI (and make labels collide with their
// controls), so keep all layout tokens in logical units. Fonts are logical-
// sized as well; the renderer scales their atlas with the framebuffer.
// (Ported from launcher_ng's "Fix launcher DPI layout and text alignment".)
float  px(float logical) { return logical; }
ImVec4 col(const LngColor& c) { return ImVec4(c.r, c.g, c.b, c.a); }
// g_th moved to external linkage above the anonymous namespace (see note).

LauncherTexture g_boxart, g_pad, g_pad_analog, g_pad_digital, g_brand, g_memcard;
// Optional platform wordmark (SystemProfile.wordmark_image) — rendered in the
// header instead of the platform text when the asset is present. Absent => text.
LauncherTexture g_wordmark;
// N64 Transfer Pak cartridge art, indexed by host cart_kind: [0] empty/unknown
// (gray GB shell), [1] red, [2] blue, [3] yellow, [4] green. Loaded only for a
// tpak game; real GB cart PNGs from the legacy launchers (assets/consoles/n64).
LauncherTexture g_cart[5];
// Disc-verdict icons (verify.mode==1 systems, e.g. PSX) — keyed by
// VerifyResult.verdict (0 none,1 ok,2 warn,3 bad); see draw_verdict_block().
LauncherTexture g_verdict_ok, g_verdict_warn, g_verdict_bad, g_verdict_none;
ImTextureID tid(const LauncherTexture& t) { return (ImTextureID)(intptr_t)t.id; }

LauncherPad g_pads[LNG_MAX_PADS];   // live gamepad list (repolled every frame)
int         g_pad_count = 0;

char        g_pick_buf[512] = {};    // ROM picker result

enum class BuiltinPickerKind { Rom, Bios, SetupToolchainZip };

struct BuiltinRomPicker {
    bool active = false;
    bool from_setup = false;
    bool focus_path = false;
    BuiltinPickerKind kind = BuiltinPickerKind::Rom;
    char title[96] = "Select game file";
    char directory[1024] = {};
    char selected[1024] = {};
    char error[256] = {};
    std::vector<std::string> patterns;
    std::string description;
};
BuiltinRomPicker g_rom_picker;

static std::string lower_ascii(std::string s) {
    std::transform(s.begin(), s.end(), s.begin(),
                   [](unsigned char c) { return (char)std::tolower(c); });
    return s;
}

static bool builtin_picker_matches(const std::filesystem::path& path) {
    if (g_rom_picker.patterns.empty()) return true;
    const std::string filename = lower_ascii(path.filename().string());
    for (const std::string& raw : g_rom_picker.patterns) {
        const std::string pattern = lower_ascii(raw);
        if (pattern.empty() || pattern == "*" || pattern == "*.*") return true;
        if (pattern.size() > 1 && pattern[0] == '*' &&
            filename.size() >= pattern.size() - 1 &&
            filename.compare(filename.size() - (pattern.size() - 1),
                             pattern.size() - 1, pattern.substr(1)) == 0)
            return true;
        if (filename == pattern) return true;
    }
    return false;
}

static std::filesystem::path builtin_picker_initial_path(LauncherModel* m,
                                                         BuiltinPickerKind kind) {
    std::error_code ec;
    if (kind == BuiltinPickerKind::Bios && m && m->s.bios_path[0]) {
        std::filesystem::path current(m->s.bios_path);
        if (std::filesystem::is_regular_file(current, ec)) return current;
    }
    if (kind == BuiltinPickerKind::SetupToolchainZip && m && m->setup_tc_zip[0]) {
        std::filesystem::path current(m->setup_tc_zip);
        if (std::filesystem::is_regular_file(current, ec)) return current;
    }
    if (kind == BuiltinPickerKind::Rom && m && m->rom_full[0]) {
        std::filesystem::path current(m->rom_full);
        if (std::filesystem::is_regular_file(current, ec)) return current;
    }
    if (kind == BuiltinPickerKind::Rom) {
        if (const char* hint = std::getenv("RECOMP_DISC_HINT")) {
            std::filesystem::path hinted(hint);
            ec.clear();
            if (std::filesystem::is_regular_file(hinted, ec)) return hinted;
        }
    }
    if (const char* image = std::getenv("RECOMP_APPIMAGE_PATH")) {
        std::filesystem::path appimage(image);
        ec.clear();
        if (std::filesystem::exists(appimage.parent_path(), ec))
            return appimage.parent_path();
    }
    if (const char* home = std::getenv("HOME")) return std::filesystem::path(home);
    return std::filesystem::current_path(ec);
}

static void open_builtin_file_picker(LauncherModel* m, BuiltinPickerKind kind,
                                     const char* title,
                                     const char* const* patterns, int pattern_count,
                                     const char* description, bool from_setup) {
    g_rom_picker = BuiltinRomPicker{};
    g_rom_picker.active = true;
    g_rom_picker.from_setup = from_setup;
    g_rom_picker.kind = kind;
    const char* fallback_title =
        kind == BuiltinPickerKind::Bios             ? "Select BIOS file"
        : kind == BuiltinPickerKind::SetupToolchainZip ? "Select toolchain zip"
                                                    : "Select game file";
    std::snprintf(g_rom_picker.title, sizeof(g_rom_picker.title), "%s",
                  title && title[0] ? title : fallback_title);
    for (int i = 0; patterns && i < pattern_count; ++i)
        if (patterns[i]) g_rom_picker.patterns.emplace_back(patterns[i]);
    if (description) g_rom_picker.description = description;

    std::filesystem::path initial = builtin_picker_initial_path(m, kind);
    std::error_code ec;
    if (std::filesystem::is_regular_file(initial, ec)) {
        std::snprintf(g_rom_picker.selected, sizeof(g_rom_picker.selected), "%s",
                      initial.string().c_str());
        initial = initial.parent_path();
    }
    if (initial.empty() || !std::filesystem::is_directory(initial, ec))
        initial = std::filesystem::current_path(ec);
    std::snprintf(g_rom_picker.directory, sizeof(g_rom_picker.directory), "%s",
                  initial.string().c_str());
    g_rom_picker.focus_path = true;
}

/* Prefer native (zenity/kdialog on Linux, tinyfiledialogs elsewhere). Fall
 * back to the in-app browser when native is unavailable or returns -1. */
static bool prefer_builtin_file_picker(void) {
    return false;
}

static void apply_builtin_picker_selection(LauncherModel* m, const char* path) {
    if (!m || !path) return;
    if (g_rom_picker.kind == BuiltinPickerKind::Bios) {
        launcher_model_request_bios_path(m, path);
    } else if (g_rom_picker.kind == BuiltinPickerKind::SetupToolchainZip) {
        std::snprintf(m->setup_tc_zip, sizeof(m->setup_tc_zip), "%s", path);
        m->setup_error[0] = '\0';
    } else {
        launcher_model_set_rom(m, path);
    }
}

static void request_file_picker(LauncherModel* m, BuiltinPickerKind kind,
                                const char* title, const char* const* patterns,
                                int pattern_count, const char* description,
                                bool from_setup) {
    if (!prefer_builtin_file_picker() &&
        launcher_native_file_picker_available()) {
        const int r = launcher_try_pick_file(title, patterns, pattern_count,
                                             description, g_pick_buf,
                                             sizeof(g_pick_buf));
        if (r == 1) {
            g_rom_picker.kind = kind; /* apply_ uses kind */
            apply_builtin_picker_selection(m, g_pick_buf);
            return;
        }
        if (r == 0) return; /* user cancelled */
        /* r == -1: fall through to built-in browser */
    }
    open_builtin_file_picker(m, kind, title, patterns, pattern_count,
                             description, from_setup);
}

static void request_rom_picker(LauncherModel* m, const char* title,
                               const char* const* patterns, int pattern_count,
                               const char* description, bool from_setup) {
    request_file_picker(m, BuiltinPickerKind::Rom, title, patterns,
                        pattern_count, description, from_setup);
}

static void request_bios_picker(LauncherModel* m, const char* title,
                                bool from_setup) {
    static const char* kBiosPatterns[] = {"*.bin", "*.rom"};
    request_file_picker(m, BuiltinPickerKind::Bios, title, kBiosPatterns, 2,
                        "BIOS image (.bin .rom)", from_setup);
}

static void draw_builtin_rom_picker_contents(LauncherModel* m,
                                             const LauncherTheme& th,
                                             bool standalone_popup) {
    namespace fs = std::filesystem;
    ImGui::TextColored(col(th.accent), "%s", g_rom_picker.title);
    ImGui::TextColored(col(th.text_muted),
                       "Built-in browser (no desktop file-picker service required)");
    if (!g_rom_picker.description.empty())
        ImGui::TextColored(col(th.text_muted), "Showing: %s",
                           g_rom_picker.description.c_str());
    ImGui::Dummy(ImVec2(0, px(6)));

    ImGui::AlignTextToFramePadding();
    ImGui::TextUnformatted("Folder");
    ImGui::SameLine();
    ImGui::SetNextItemWidth(px(500));
    bool enter_dir = ImGui::InputText("##builtin_picker_directory",
                                      g_rom_picker.directory,
                                      sizeof(g_rom_picker.directory),
                                      ImGuiInputTextFlags_EnterReturnsTrue);
    if (enter_dir) {
        std::error_code ec;
        if (!fs::is_directory(fs::path(g_rom_picker.directory), ec))
            std::snprintf(g_rom_picker.error, sizeof(g_rom_picker.error),
                          "That folder does not exist or cannot be opened.");
        else
            g_rom_picker.error[0] = '\0';
    }

    if (ImGui::Button("Up", ImVec2(px(82), px(30)))) {
        fs::path parent = fs::path(g_rom_picker.directory).parent_path();
        if (!parent.empty()) {
            std::snprintf(g_rom_picker.directory, sizeof(g_rom_picker.directory),
                          "%s", parent.string().c_str());
            g_rom_picker.selected[0] = '\0';
            g_rom_picker.error[0] = '\0';
        }
    }
    ImGui::SameLine();
    if (ImGui::Button("Home", ImVec2(px(82), px(30)))) {
        if (const char* home = std::getenv("HOME")) {
            std::snprintf(g_rom_picker.directory, sizeof(g_rom_picker.directory),
                          "%s", home);
            g_rom_picker.selected[0] = '\0';
            g_rom_picker.error[0] = '\0';
        }
    }

    struct PickerEntry {
        fs::path path;
        bool directory;
    };
    std::vector<PickerEntry> entries;
    std::error_code ec;
    const fs::path directory(g_rom_picker.directory);
    fs::directory_iterator it(directory, fs::directory_options::skip_permission_denied, ec);
    if (!ec) {
        for (const fs::directory_entry& entry : it) {
            std::error_code type_ec;
            const bool is_dir = entry.is_directory(type_ec);
            if (type_ec) continue;
            if (is_dir || builtin_picker_matches(entry.path()))
                entries.push_back({entry.path(), is_dir});
        }
        std::sort(entries.begin(), entries.end(),
                  [](const PickerEntry& a, const PickerEntry& b) {
                      if (a.directory != b.directory) return a.directory > b.directory;
                      return lower_ascii(a.path.filename().string()) <
                             lower_ascii(b.path.filename().string());
                  });
    } else if (!g_rom_picker.error[0]) {
        std::snprintf(g_rom_picker.error, sizeof(g_rom_picker.error),
                      "Unable to open this folder.");
    }

    ImGui::BeginChild("##builtin_picker_entries", ImVec2(0, px(300)),
                      ImGuiChildFlags_Borders);
    for (const PickerEntry& entry : entries) {
        const std::string name = entry.path.filename().string();
        std::string label = entry.directory ? "[Folder] " + name : name;
        label += "##" + entry.path.string();
        const bool selected =
            !entry.directory && entry.path.string() == g_rom_picker.selected;
        if (ImGui::Selectable(label.c_str(), selected,
                              ImGuiSelectableFlags_AllowDoubleClick)) {
            if (entry.directory) {
                std::snprintf(g_rom_picker.directory,
                              sizeof(g_rom_picker.directory), "%s",
                              entry.path.string().c_str());
                g_rom_picker.selected[0] = '\0';
                g_rom_picker.error[0] = '\0';
            } else {
                std::snprintf(g_rom_picker.selected,
                              sizeof(g_rom_picker.selected), "%s",
                              entry.path.string().c_str());
                g_rom_picker.error[0] = '\0';
            }
        }
    }
    ImGui::EndChild();

    ImGui::AlignTextToFramePadding();
    ImGui::TextUnformatted("File");
    ImGui::SameLine();
    ImGui::SetNextItemWidth(-1);
    if (g_rom_picker.focus_path) {
        ImGui::SetKeyboardFocusHere();
        g_rom_picker.focus_path = false;
    }
    ImGui::InputText("##builtin_picker_selected", g_rom_picker.selected,
                     sizeof(g_rom_picker.selected));
    if (g_rom_picker.error[0])
        ImGui::TextColored(col(th.warn), "%s", g_rom_picker.error);

    ImGui::Dummy(ImVec2(0, px(6)));
    if (ImGui::Button("Use selected file", ImVec2(px(180), px(34)))) {
        std::error_code file_ec;
        fs::path selected(g_rom_picker.selected);
        if (fs::is_regular_file(selected, file_ec) &&
            builtin_picker_matches(selected)) {
            apply_builtin_picker_selection(m, selected.string().c_str());
            g_rom_picker.active = false;
            if (standalone_popup) ImGui::CloseCurrentPopup();
        } else {
            const char* err =
                g_rom_picker.kind == BuiltinPickerKind::Bios
                    ? "Select an existing BIOS image (.bin / .rom)."
                : g_rom_picker.kind == BuiltinPickerKind::SetupToolchainZip
                    ? "Select an existing toolchain .zip archive."
                    : "Select an existing file matching this game's file types.";
            std::snprintf(g_rom_picker.error, sizeof(g_rom_picker.error), "%s",
                          err);
        }
    }
    ImGui::SameLine();
    if (ImGui::Button("Cancel", ImVec2(px(110), px(34)))) {
        g_rom_picker.active = false;
        if (standalone_popup) ImGui::CloseCurrentPopup();
    }
}

static void draw_standalone_builtin_rom_picker(LauncherModel* m,
                                                const LauncherTheme& th) {
    if (!g_rom_picker.active || g_rom_picker.from_setup) return;
    const char* popup =
        g_rom_picker.kind == BuiltinPickerKind::Bios
            ? "Select BIOS file##builtin"
        : g_rom_picker.kind == BuiltinPickerKind::SetupToolchainZip
            ? "Select toolchain zip##builtin"
            : "Select game file##builtin";
    ImGui::OpenPopup(popup);
    ImGui::SetNextWindowPos(ImGui::GetMainViewport()->GetCenter(),
                            ImGuiCond_Always, ImVec2(0.5f, 0.5f));
    ImGui::SetNextWindowSize(ImVec2(px(720), 0), ImGuiCond_Always);
    if (ImGui::BeginPopupModal(popup, nullptr,
                               ImGuiWindowFlags_AlwaysAutoResize |
                               ImGuiWindowFlags_NoMove)) {
        draw_builtin_rom_picker_contents(m, th, true);
        ImGui::EndPopup();
    }
}

// Context flag the dashboard composer sets just before invoking the "game"
// panel's registered draw() — the LauncherPanelDrawFn signature (Model*,
// const Theme*) has no room for the layout-context fill_h flag that
// draw_game_panel needs (fill the column height in the wide 2-column
// dashboard vs hug its content in the narrow stacked layout). Same pattern as
// the other per-frame context globals below (g_th, g_pads).
bool g_game_fill_h = false;
// SAVE (memory-card) fill-height: multitap (3+) only — cards stretch in a
// reserved band under a scrolling controller stack. 2P hugs content; edge
// inset comes from Child WindowPadding (same top/bottom as other panels).
bool g_save_fill_h = false;

// ---- panel registry lookup helper ------------------------------------------
// Resolve `id` against a SystemProfile's NULL-terminated composition array:
// the panel must both be LISTED (this system composes it at all) and
// AVAILABLE (this game instance offers it) to be drawn. Returns nullptr
// otherwise — the caller simply skips that slot.
const LauncherPanel* find_composed(const char* const* ids, const char* id, LauncherModel* m) {
    if (!ids || !id) return nullptr;
    for (int i = 0; ids[i]; ++i) {
        if (strcmp(ids[i], id) != 0) continue;
        const LauncherPanel* p = launcher_panel_find(id);
        return (p && launcher_panel_available(p, m)) ? p : nullptr;
    }
    return nullptr;
}

// Merge an optional TTF over the active font when the file exists.
static void merge_font_if_present(const char* path, float size,
                                  const ImWchar* ranges) {
    if (!path || !path[0] || !ranges) return;
    if (FILE* f = fopen(path, "rb")) {
        fclose(f);
        ImFontConfig cfg;
        cfg.OversampleH = 2;
        cfg.OversampleV = 2;
        cfg.MergeMode = true;
        cfg.PixelSnapH = true;
        ImGui::GetIO().Fonts->AddFontFromFileTTF(path, size, &cfg, ranges);
    }
}

// ---- DPI: rebuild fonts + re-derive style from an unscaled baseline ----------
void apply_scale(const LauncherTheme& th, float scale, const char* font_path,
                 const char* jp_font_path, const char* symbols_font_path,
                 const char* emoji_font_path) {
    ImGuiIO& io = ImGui::GetIO();
    io.Fonts->Clear();
    ImFontConfig cfg; cfg.OversampleH = 2; cfg.OversampleV = 2;
    (void)scale;   // DPI is handled by the framebuffer scale, not by re-scaling layout/fonts
    const float body = th.font_body;
    // Cover Basic Latin + Latin-1 AND General Punctuation so em/en dashes and
    // curly quotes used in the game notes render as glyphs, not "?" tofu.
    static const ImWchar kRanges[] = {
        0x0020, 0x00FF,   // Basic Latin + Latin-1 Supplement
        0x2010, 0x2027,   // dashes, curly quotes, ellipsis (General Punctuation)
        0,
    };
    bool loaded = false;
    if (font_path && font_path[0])
        loaded = io.Fonts->AddFontFromFileTTF(font_path, body, &cfg, kRanges) != nullptr;
    if (!loaded) { cfg.SizePixels = body; io.Fonts->AddFontDefault(&cfg); }
    // Merge a Japanese subset atlas over the Latin base when the game ships one
    // (PMS-J's kana cart names / trainer strings). MergeMode folds the JP glyphs
    // into the same font so mixed Latin+kana strings render in one pass; absent
    // file => Latin-only, unchanged for every other console.
    if (jp_font_path && jp_font_path[0]) {
        if (FILE* jf = fopen(jp_font_path, "rb")) {
            fclose(jf);
            ImFontConfig jcfg; jcfg.OversampleH = 2; jcfg.OversampleV = 2;
            jcfg.MergeMode = true;
            io.Fonts->AddFontFromFileTTF(jp_font_path, body, &jcfg,
                                         io.Fonts->GetGlyphRangesJapanese());
        }
    }
    // Symbol / emoji fallbacks (kick 🥾, lock 🔒, etc.). Outline fonts only —
    // CBDT color emoji (Noto Color Emoji) is not supported by stb_truetype.
    static const ImWchar kSymbolRanges[] = {
        0x2000, 0x206F,   // General Punctuation
        0x2190, 0x21FF,   // Arrows
        0x2300, 0x23FF,   // Misc Technical
        0x2460, 0x24FF,   // Enclosed Alphanumerics
        0x25A0, 0x25FF,   // Geometric Shapes
        0x2600, 0x26FF,   // Misc Symbols
        0x2700, 0x27BF,   // Dingbats
        0x2B00, 0x2BFF,   // Misc Symbols and Arrows
        0,
    };
#ifdef IMGUI_USE_WCHAR32
    static const ImWchar kEmojiRanges[] = {
        0x1F300, 0x1F5FF, // Misc Symbols and Pictographs (incl. 🔒)
        0x1F600, 0x1F64F, // Emoticons
        0x1F680, 0x1F6FF, // Transport and Map
        0x1F900, 0x1F9FF, // Supplemental Symbols and Pictographs (incl. 🥾)
        0,
    };
    merge_font_if_present(symbols_font_path, body, kSymbolRanges);
    merge_font_if_present(emoji_font_path, body, kEmojiRanges);
#else
    merge_font_if_present(symbols_font_path, body, kSymbolRanges);
    (void)emoji_font_path;
#endif
    io.Fonts->Build();
    ImGui_ImplOpenGL3_DestroyFontsTexture();
    ImGui_ImplOpenGL3_CreateFontsTexture();

    ImGuiStyle style; ImGui::StyleColorsDark(&style);
    style.WindowRounding = th.radius_lg; style.ChildRounding = th.radius_lg;
    style.FrameRounding  = th.radius_sm; style.GrabRounding  = th.radius_sm;
    style.WindowPadding  = ImVec2(th.spacing_lg, th.spacing_lg);
    style.FramePadding   = ImVec2(th.spacing_md, th.spacing_sm);
    style.ItemSpacing    = ImVec2(th.spacing_md, th.spacing_sm);
#if defined(__ANDROID__)
    style.TouchExtraPadding = ImVec2(5.0f, 5.0f);
    style.ScrollbarSize = 24.0f;
#endif
    style.ChildBorderSize = 1.0f;
    style.FrameBorderSize = 1.0f;   // controls get a visible outline
    style.Colors[ImGuiCol_WindowBg]        = col(th.background);
    style.Colors[ImGuiCol_ChildBg]         = col(th.panel);
    style.Colors[ImGuiCol_PopupBg]         = col(th.panel);
    style.Colors[ImGuiCol_Border]          = col(th.border);
    style.Colors[ImGuiCol_FrameBg]         = col(th.control);
    style.Colors[ImGuiCol_FrameBgHovered]  = col(th.control_hovered);
    style.Colors[ImGuiCol_FrameBgActive]   = col(th.control_hovered);
    style.Colors[ImGuiCol_Button]          = col(th.control);
    style.Colors[ImGuiCol_ButtonHovered]   = col(th.control_hovered);
    style.Colors[ImGuiCol_ButtonActive]    = col(th.accent);
    style.Colors[ImGuiCol_Header]          = col(th.control_hovered);
    style.Colors[ImGuiCol_HeaderHovered]   = col(th.control_hovered);
    style.Colors[ImGuiCol_HeaderActive]    = col(th.accent);
    style.Colors[ImGuiCol_CheckMark]       = col(th.accent);
    style.Colors[ImGuiCol_Text]            = col(th.text);
    style.Colors[ImGuiCol_TextDisabled]    = col(th.text_muted);
#if defined(IMGUI_VERSION_NUM) && IMGUI_VERSION_NUM >= 19100
    style.Colors[ImGuiCol_TextLink]        = col(th.accent2);
#endif
    style.Colors[ImGuiCol_Separator]       = col(th.border);
    style.Colors[ImGuiCol_ScrollbarBg]     = col(th.panel);
    style.Colors[ImGuiCol_ScrollbarGrab]   = col(th.border);
    style.Colors[ImGuiCol_ScrollbarGrabHovered] = col(th.control_hovered);
    // Gamepad/keyboard focus ring: bright cyan so a Deck user always sees where
    // they are. NavCursor is the 1.91.4+ name; older ImGui (e.g. an rt64 host on
    // 1.90.x) calls the same slot NavHighlight.
#if defined(IMGUI_VERSION_NUM) && IMGUI_VERSION_NUM >= 19140
    style.Colors[ImGuiCol_NavCursor]       = col(th.focus_ring);
#else
    style.Colors[ImGuiCol_NavHighlight]    = col(th.focus_ring);
#endif
    ImGui::GetStyle() = style;
}

// ---- CRT / neon atmosphere (drawn with ImDrawList) ---------------------------
ImU32 imcol(const LngColor& c, float a = 1.0f) {
    return ImGui::GetColorU32(ImVec4(c.r, c.g, c.b, c.a * a));
}

// Vertical center-bright gradient (CRT ground) + faint scanlines. Drawn on the
// background/foreground draw lists so it sits behind/over the whole UI.
void draw_crt_background(ImVec2 origin, ImVec2 size) {
    const LauncherTheme& th = *g_th;
    ImDrawList* bg = ImGui::GetBackgroundDrawList();
    ImU32 ink = imcol(th.background), lift = imcol(th.background2);
    float midY = origin.y + size.y * 0.42f;
    // top: ink -> lift, bottom: lift -> ink  (soft horizontal glow band)
    bg->AddRectFilledMultiColor(origin, ImVec2(origin.x + size.x, midY),
                                ink, ink, lift, lift);
    bg->AddRectFilledMultiColor(ImVec2(origin.x, midY), ImVec2(origin.x + size.x, origin.y + size.y),
                                lift, lift, ink, ink);
    // a soft violet bloom behind the header (arcade marquee glow)
    bg->AddRectFilledMultiColor(origin, ImVec2(origin.x + size.x, origin.y + px(90)),
                                imcol(th.accent, 0.10f), imcol(th.accent, 0.10f),
                                imcol(th.accent, 0.0f),  imcol(th.accent, 0.0f));
    // scanlines over everything, very subtle — only for CRT-style themes (the PSX
    // theme sets scanlines = 0 for a flat, disc-era look).
    if (th.scanlines) {
        ImDrawList* fg = ImGui::GetForegroundDrawList();
        float step = px(3.0f); if (step < 2.0f) step = 2.0f;
        ImU32 sl = imcol(th.scanline);
        for (float y = origin.y; y < origin.y + size.y; y += step)
            fg->AddLine(ImVec2(origin.x, y), ImVec2(origin.x + size.x, y), sl, 1.0f);
    }
}

// Neon glow: concentric rounded rects fading outward behind [min,max].
void glow_rect(ImDrawList* dl, ImVec2 mn, ImVec2 mx, float rounding,
               const LngColor& c, float intensity, int layers = 5) {
    for (int i = layers; i >= 1; --i) {
        float grow = px(2.0f) * i;
        float a = intensity * (0.10f) * (float)(layers - i + 1) / layers;
        dl->AddRectFilled(ImVec2(mn.x - grow, mn.y - grow),
                          ImVec2(mx.x + grow, mx.y + grow),
                          imcol(c, a), rounding + grow);
    }
}

// Filled rounded rect with a vertical gradient (top -> bottom).
void grad_rect(ImDrawList* dl, ImVec2 mn, ImVec2 mx, float rounding,
               const LngColor& top, const LngColor& bot) {
    dl->AddRectFilled(mn, mx, imcol(bot), rounding);   // base (rounded)
    // overlay a gradient clipped to the rounded rect via a slightly-inset fill
    dl->PushClipRect(mn, mx, true);
    dl->AddRectFilledMultiColor(mn, mx, imcol(top), imcol(top), imcol(bot), imcol(bot));
    dl->PopClipRect();
}

// ---- primitive icons (crisp at any DPI, no font dependency) -------------------
void draw_check(const LngColor& c) {   // green check, advances cursor like text
    ImDrawList* dl = ImGui::GetWindowDrawList();
    ImVec2 p = ImGui::GetCursorScreenPos();
    float s = ImGui::GetTextLineHeight(), y = p.y + s * 0.5f;
    ImU32 u = ImGui::GetColorU32(col(c));
    dl->AddLine(ImVec2(p.x + s*0.15f, y), ImVec2(p.x + s*0.40f, y + s*0.28f), u, px(2.0f));
    dl->AddLine(ImVec2(p.x + s*0.40f, y + s*0.28f), ImVec2(p.x + s*0.85f, y - s*0.28f), u, px(2.0f));
    ImGui::Dummy(ImVec2(s, s)); ImGui::SameLine(0, px(6));
}
void draw_dot(bool on, const LngColor& good, const LngColor& off) {
    ImDrawList* dl = ImGui::GetWindowDrawList();
    ImVec2 p = ImGui::GetCursorScreenPos();
    float s = ImGui::GetTextLineHeight(), r = px(5.0f);
    ImVec2 c(p.x + r, p.y + s * 0.5f);
    if (on) dl->AddCircleFilled(c, r, ImGui::GetColorU32(col(good)));
    else    dl->AddCircle(c, r, ImGui::GetColorU32(col(off)), 0, px(1.5f));
    ImGui::Dummy(ImVec2(r * 2, s)); ImGui::SameLine(0, px(8));
}
// The primary neon CTA (PLAY): glow + violet gradient + play triangle. Fully
// custom-drawn over an InvisibleButton so it looks nothing like a stock button.
bool neon_cta(const char* id, const char* label, ImVec2 size, bool enabled = true) {
    const LauncherTheme& th = *g_th;
    ImVec2 p = ImGui::GetCursorScreenPos();
    // EnableNav is REQUIRED: ImGui::InvisibleButton() adds ImGuiItemFlags_NoNav by
    // default, which silently excludes the CTA from gamepad/keyboard nav — that was
    // why PLAY could never be focused at runtime (only via boot SetItemDefaultFocus)
    // while normal widgets (Skip, Settings) always could.
    if (!enabled) ImGui::BeginDisabled();
    bool clk = ImGui::InvisibleButton(id, size, ImGuiButtonFlags_EnableNav);
    bool hov = enabled && ImGui::IsItemHovered();
    bool act = ImGui::IsItemActive();
    bool foc = ImGui::IsItemFocused();   // gamepad/keyboard nav focus
    ImVec2 mn = p, mx = ImVec2(p.x + size.x, p.y + size.y);
    ImDrawList* dl = ImGui::GetWindowDrawList();
    float r = px(th.radius_sm);

    glow_rect(dl, mn, mx, r, th.accent, hov ? 1.6f : 1.0f, 6);
    LngColor top = hov ? th.accent : th.accent;
    LngColor bot = act ? th.accent_dim : th.accent_dim;
    grad_rect(dl, mn, mx, r, top, bot);
    dl->AddRect(mn, mx, imcol(th.accent, hov ? 0.9f : 0.5f), r, 0, px(1.0f));  // crisp edge
    // InvisibleButton draws no nav highlight itself — paint the cyan focus ring
    // when nav-focused so the CTA reads as selectable via controller/keyboard.
    if (foc) {
        ImVec2 om = ImVec2(mn.x - px(2), mn.y - px(2)), ox = ImVec2(mx.x + px(2), mx.y + px(2));
        dl->AddRect(om, ox, imcol(th.focus_ring), r + px(2), 0, px(th.focus_ring_width));
    }

    // centered "▶ label"
    float th_h = ImGui::GetTextLineHeight();
    float tw = ImGui::CalcTextSize(label).x;
    float tri = px(11.0f), gap = px(10.0f);
    float total = tri + gap + tw;
    float cx = p.x + (size.x - total) * 0.5f, cy = p.y + size.y * 0.5f;
    ImU32 fg = imcol(th.accent_text);
    dl->AddTriangleFilled(ImVec2(cx, cy - tri*0.55f), ImVec2(cx, cy + tri*0.55f),
                          ImVec2(cx + tri, cy), fg);
    dl->AddText(ImVec2(cx + tri + gap, cy - th_h*0.5f), fg, label);
    if (!enabled) ImGui::EndDisabled();
    return clk && enabled;
}

// Uppercase section eyebrow with letter-spacing + a short accent tick, e.g.
//   ▎ CONTROLLERS   — encodes "this is a section header", arcade panel style.
void eyebrow_tracked(const char* s) {
    const LauncherTheme& th = *g_th;
    ImDrawList* dl = ImGui::GetWindowDrawList();
    ImVec2 p = ImGui::GetCursorScreenPos();
    float h = ImGui::GetTextLineHeight();
    // accent tick (secondary accent — section headings read in the theme's
    // heading color, distinct from the primary CTA on dual-accent themes)
    dl->AddRectFilled(ImVec2(p.x, p.y + h*0.12f), ImVec2(p.x + px(3.0f), p.y + h*0.9f),
                      imcol(th.accent2), px(1.5f));
    // letter-spaced text
    float x = p.x + px(10.0f);
    ImU32 c = imcol(th.accent2);
    char buf[2] = {0,0};
    for (const char* q = s; *q; ++q) {
        buf[0] = *q;
        dl->AddText(ImVec2(x, p.y), c, buf);
        x += ImGui::CalcTextSize(buf).x + px(2.2f);
    }
    ImGui::Dummy(ImVec2(x - p.x, h));
    ImGui::Spacing();
}

// Draw a texture fit inside a logical box, preserving aspect.
void image_fit(const LauncherTexture& t, float box_w, float box_h) {
    if (!t.id || t.w <= 0 || t.h <= 0) { ImGui::Dummy(ImVec2(px(box_w), px(box_h))); return; }
    float bw = px(box_w), bh = px(box_h);
    float s = (bw / t.w < bh / t.h) ? bw / (float)t.w : bh / (float)t.h;
    ImGui::Image(tid(t), ImVec2(t.w * s, t.h * s));
}

// Like image_fit, but horizontally centers the FITTED image within avail_w.
// image_fit alone centers on the box width, so a near-square art (the N64 pad)
// fit into a landscape box draws narrow and sits left-of-center — this offsets
// by the real fitted width instead.
void image_fit_centered(const LauncherTexture& t, float box_w, float box_h, float avail_w) {
    float fitted_w = px(box_w);
    if (t.id && t.w > 0 && t.h > 0) {
        float bw = px(box_w), bh = px(box_h);
        float s = (bw / t.w < bh / t.h) ? bw / (float)t.w : bh / (float)t.h;
        fitted_w = t.w * s;
    }
    float off = (avail_w - fitted_w) * 0.5f;
    if (off > 0) ImGui::SetCursorPosX(ImGui::GetCursorPosX() + off);
    image_fit(t, box_w, box_h);
}

void eyebrow(const char* s) { eyebrow_tracked(s); }
// A card: filled + bordered. Hugs its content by default; `fill_h` stretches it
// to the remaining height (used by the dashboard columns so the layout doesn't
// leave a big empty gap under short cards).
bool begin_panel(const char* id, float logical_w = 0.0f, bool fill_h = false,
                 bool no_scroll = false) {
    ImGuiChildFlags flags = ImGuiChildFlags_Borders;
    if (!fill_h) flags |= ImGuiChildFlags_AutoResizeY;
    // A fill-height card (e.g. GAME) must SCROLL when the window is too short —
    // otherwise its folded-in content (SAVES) clips out of reach. Only the
    // fixed-size settings cards, which are sized to fit, suppress the scrollbar
    // (no_scroll) to avoid a stray bar. Content-hugging cards (AutoResizeY) never
    // overflow themselves, so scrollable-by-default is a no-op for them.
    ImGuiWindowFlags wflags = no_scroll ? (ImGuiWindowFlags_NoScrollbar |
                                           ImGuiWindowFlags_NoScrollWithMouse)
                                        : 0;
    return ImGui::BeginChild(id, ImVec2(px(logical_w), 0.0f), flags, wflags);
}
void end_panel() { ImGui::EndChild(); }

// A layout container: no fill, no border. Without this a nested child inherits
// ChildBg and paints a large panel-coloured rectangle behind the real cards,
// which reads as "dead space".
bool begin_container(const char* id, ImVec2 size, ImGuiChildFlags flags = ImGuiChildFlags_None,
                     ImGuiWindowFlags wflags = 0) {
    ImGui::PushStyleColor(ImGuiCol_ChildBg, ImVec4(0, 0, 0, 0));
    return ImGui::BeginChild(id, size, flags, wflags);
}
void end_container() { ImGui::EndChild(); ImGui::PopStyleColor(); }

void state_mark(bool ok, const LauncherTheme& th);   // fwd
void draw_save_row(LauncherModel* m, const LauncherTheme& th);   // fwd (Save module row-drawer)

// One metadata row inside a 3-column table: label | value | optional check.
// `show_mark` puts a mint check / amber cross in its own column instead of a
// text badge, so it can never crowd the panel edge.
void kv_row(const char* k, const char* v, const LauncherTheme& th,
            bool show_mark, bool ok) {
    ImGui::TableNextRow();
    ImGui::TableNextColumn();
    ImGui::PushStyleColor(ImGuiCol_Text, col(th.text_muted));
    ImGui::TextUnformatted(k);
    ImGui::PopStyleColor();
    ImGui::TableNextColumn();
    ImGui::TextUnformatted(v);
    ImGui::TableNextColumn();
    if (show_mark) state_mark(ok, th);
}

// Key/value row, drawn full width: muted label column, value, and an optional
// right-aligned badge. No wrapping — the row owns the whole panel width, so
// long values (CRC/SHA) have room instead of being clipped or char-wrapped.
void kv(const char* k, const char* v, const LauncherTheme& th,
        const char* badge = nullptr, bool good = true) {
    const float x0 = ImGui::GetCursorPosX();
    ImGui::PushStyleColor(ImGuiCol_Text, col(th.text_muted));
    ImGui::TextUnformatted(k); ImGui::PopStyleColor();
    ImGui::SameLine(x0 + px(84.0f));
    ImGui::TextUnformatted(v);
    if (badge) {
        char b[24]; snprintf(b, sizeof(b), "[%s]", badge);
        const float bw = ImGui::CalcTextSize(b).x;
        ImGui::SameLine(ImGui::GetCursorPosX() + ImGui::GetContentRegionAvail().x - bw);
        ImGui::PushStyleColor(ImGuiCol_Text, col(good ? th.good : th.warn));
        ImGui::TextUnformatted(b); ImGui::PopStyleColor();
    }
}
void stepper(const char* id, int value, const char* suffix, int* out_delta) {
    ImGui::PushID(id);
    const float bh = px(30), fw = px(58);
    if (ImGui::Button("-", ImVec2(px(32), bh))) *out_delta = -5;
    ImGui::SameLine(0, px(6));
    // value centered in a fixed-width field so "+" never shifts with the digits
    char buf[32]; snprintf(buf, sizeof(buf), "%d%s", value, suffix);
    float cx = ImGui::GetCursorPosX();
    ImVec2 ts = ImGui::CalcTextSize(buf);
    ImGui::SetCursorPosX(cx + (fw - ts.x) * 0.5f);
    ImGui::AlignTextToFramePadding();
    ImGui::TextUnformatted(buf);
    ImGui::SameLine(0, 0);
    ImGui::SetCursorPosX(cx + fw + px(6));
    if (ImGui::Button("+", ImVec2(px(32), bh))) *out_delta = +5;
    ImGui::PopID();
}

// ±1 stepper for the Genesis widescreen "extra cells per side" control. Unlike
// the ±5 `stepper` above it reads its display string from the model
// (launcher_model_ws_cells_label => "8 cells") so the clamp/format live in one
// place, and it steps by a single cell.
void ws_cells_stepper(const char* id, LauncherModel* m, int* out_delta) {
    ImGui::PushID(id);
    const float bh = px(30), fw = px(72);
    if (ImGui::Button("-", ImVec2(px(32), bh))) *out_delta = -1;
    ImGui::SameLine(0, px(6));
    const char* buf = launcher_model_ws_cells_label(m);
    float cx = ImGui::GetCursorPosX();
    ImVec2 ts = ImGui::CalcTextSize(buf);
    ImGui::SetCursorPosX(cx + (fw - ts.x) * 0.5f);
    ImGui::AlignTextToFramePadding();
    ImGui::TextUnformatted(buf);
    ImGui::SameLine(0, 0);
    ImGui::SetCursorPosX(cx + fw + px(6));
    if (ImGui::Button("+", ImVec2(px(32), bh))) *out_delta = +1;
    ImGui::PopID();
}

// "Label ......... [control]" row: label baseline-aligned to the control.
// col_w > 0 reserves a FIXED label column so the control starts at the same x
// on every row — the caller passes the widest label's width (+gap) to line all
// the controls up into a clean grid. col_w == 0 keeps the legacy flow layout
// (control hugs the label with a fixed gap).
void row_label(const char* text, const LauncherTheme& th, float col_w = 0.0f) {
    float x0 = ImGui::GetCursorPosX();
    ImGui::AlignTextToFramePadding();
    ImGui::TextColored(col(th.text_muted), "%s", text);
    if (col_w > 0.0f) {
        ImGui::SameLine(0.0f, 0.0f);
        ImGui::SetCursorPosX(x0 + col_w);          // fixed label column → controls align
    } else {
        ImGui::SameLine(0.0f, px(th.spacing_md));  // flow from label width (no fixed-x overlap)
    }
}

// ---- views -----------------------------------------------------------------
// Box art, centered, framed. No neon glow — the art is photographic content and
// a violet halo around it reads as a bug, not a design. Glow is reserved for
// the PLAY CTA, where it means "this is the action".
void hero_boxart_centered(const LauncherTexture& t, float box_h, float avail_w) {
    const LauncherTheme& th = *g_th;
    float bh = px(box_h);
    ImDrawList* dl = ImGui::GetWindowDrawList();
    if (t.id && t.w > 0 && t.h > 0) {
        float s = bh / (float)t.h;
        float iw = t.w * s, ih = bh;
        if (iw > avail_w) { s = avail_w / (float)t.w; iw = avail_w; ih = t.h * s; }
        ImGui::SetCursorPosX(ImGui::GetCursorPosX() + (avail_w - iw) * 0.5f);  // center
        ImVec2 p = ImGui::GetCursorScreenPos();
        ImVec2 mn = p, mx = ImVec2(p.x + iw, p.y + ih);
        dl->AddImageRounded(tid(t), mn, mx, ImVec2(0,0), ImVec2(1,1),
                            imcol(lng_rgba(1,1,1,1)), px(4.0f));
        dl->AddRect(mn, mx, imcol(th.border), px(4.0f), 0, px(1.0f));
        ImGui::Dummy(ImVec2(iw, ih));
    } else {
        // No box art was supplied for this game — draw a tasteful SNES-cartridge
        // placeholder so the GAME card never shows dead space. Game-agnostic: any
        // title that declares no boxart.tga gets this instead of an empty slot.
        float iw = bh * 0.72f;               // match a box-art portrait aspect
        if (iw > avail_w) iw = avail_w;
        float ih = bh;
        ImGui::SetCursorPosX(ImGui::GetCursorPosX() + (avail_w - iw) * 0.5f);  // center
        ImVec2 p = ImGui::GetCursorScreenPos();
        ImVec2 mn = p, mx = ImVec2(p.x + iw, p.y + ih);
        dl->AddRectFilled(mn, mx, imcol(th.panel_hovered), px(6.0f));
        dl->AddRect(mn, mx, imcol(th.border), px(6.0f), 0, px(1.0f));

        // cartridge body, centered in the slot
        float cw = iw * 0.52f, ch = cw * 1.04f;
        float cx = (mn.x + mx.x) * 0.5f, cy = (mn.y + mx.y) * 0.5f;
        ImVec2 bmn = ImVec2(cx - cw * 0.5f, cy - ch * 0.5f);
        ImVec2 bmx = ImVec2(cx + cw * 0.5f, cy + ch * 0.5f);
        dl->AddRectFilled(bmn, bmx, imcol(th.accent_dim), cw * 0.10f);
        // top ridges
        for (int i = 0; i < 3; i++) {
            float rx = bmn.x + cw * (0.20f + i * 0.24f);
            dl->AddRectFilled(ImVec2(rx, bmn.y - ch * 0.05f),
                              ImVec2(rx + cw * 0.12f, bmn.y + ch * 0.10f),
                              imcol(th.accent), cw * 0.03f);
        }
        // recessed label window
        dl->AddRectFilled(ImVec2(bmn.x + cw * 0.16f, bmn.y + ch * 0.30f),
                          ImVec2(bmx.x - cw * 0.16f, bmx.y - ch * 0.16f),
                          imcol(th.panel), cw * 0.04f);
        ImGui::Dummy(ImVec2(iw, ih));
    }
}

// A verified/failed state marker: mint check or amber cross. Replaces the
// [MATCH] badge that crowded the panel edge.
void state_mark(bool ok, const LauncherTheme& th) {
    ImDrawList* dl = ImGui::GetWindowDrawList();
    ImVec2 p = ImGui::GetCursorScreenPos();
    float s = ImGui::GetTextLineHeight();
    ImU32 c = imcol(ok ? th.good : th.warn);
    float y = p.y + s * 0.5f;
    if (ok) {
        dl->AddLine(ImVec2(p.x + s*0.16f, y), ImVec2(p.x + s*0.40f, y + s*0.26f), c, px(2.0f));
        dl->AddLine(ImVec2(p.x + s*0.40f, y + s*0.26f), ImVec2(p.x + s*0.84f, y - s*0.26f), c, px(2.0f));
    } else {
        dl->AddLine(ImVec2(p.x + s*0.22f, y - s*0.24f), ImVec2(p.x + s*0.78f, y + s*0.24f), c, px(2.0f));
        dl->AddLine(ImVec2(p.x + s*0.78f, y - s*0.24f), ImVec2(p.x + s*0.22f, y + s*0.24f), c, px(2.0f));
    }
    ImGui::Dummy(ImVec2(s, s));
}

// Pick the verdict icon for VerifyResult.verdict (0 none,1 ok,2 warn,3 bad).
const LauncherTexture& verdict_texture(int verdict) {
    switch (verdict) {
        case 1:  return g_verdict_ok;
        case 2:  return g_verdict_warn;
        case 3:  return g_verdict_bad;
        default: return g_verdict_none;
    }
}

// Disc-verdict block (verify.mode==1 systems, e.g. PSX): a verdict icon +
// headline, followed by a Serial/Region/ISO-header checklist. Replaces the
// CRC/SHA "verified" line that mode==0 (cart/ROM-hash) systems draw instead
// (see draw_game_panel) — same slot in the card, different module. Reads
// m->verify, populated by launcher_model_set_rom()/run_verify() in
// launcher_model.c (real probe when the SystemProfile has one, a synthesized
// placeholder verdict otherwise).
void draw_verdict_block(const LauncherModel* m, const LauncherTheme& th, float availw) {
    const VerifyResult& v = m->verify;
    // Keep the Serial/Region/ISO checklist mounted even before a disc is
    // picked (setup wizard) so AutoResize modals don't jump when verify runs.
    const bool pending = !m->rom_present;
    const char* headline =
        pending          ? "No disc selected" :
        v.verdict == 1   ? "Disc verified" :
        v.verdict == 2   ? "Disc verified (warnings)" :
        v.verdict == 3   ? "Disc verification failed" :
                           "Disc not recognized";
    // th has no dedicated "bad"/error slot (only good/warn) — reuse warn for
    // the warn AND none cases (both are cautionary, matching the ROM-hash
    // line's existing amber-for-"not recognized" convention) and fall back to
    // a plain red only for the explicit "bad" verdict. Pending = muted.
    LngColor headline_color = pending ? th.text_muted
                              : (v.verdict == 1) ? th.good
                              : (v.verdict == 3) ? lng_rgba(0.945f, 0.322f, 0.322f, 1.0f)
                              : th.warn;

    const LauncherTexture& icon = verdict_texture(pending ? 0 : v.verdict);
    float ih = ImGui::GetTextLineHeight() * 1.35f;
    float iw = (icon.id && icon.h > 0) ? ih * ((float)icon.w / (float)icon.h) : ih;
    float w = iw + px(6) + ImGui::CalcTextSize(headline).x;
    ImGui::SetCursorPosX(ImGui::GetCursorPosX() + (availw - w) * 0.5f);
    if (icon.id) {
        ImVec2 p = ImGui::GetCursorScreenPos();
        ImGui::GetWindowDrawList()->AddImage(tid(icon), p, ImVec2(p.x + iw, p.y + ih));
        ImGui::Dummy(ImVec2(iw, ih));
    } else if (!pending) {
        state_mark(v.verdict == 1, th);   // icon failed to load: vector fallback
    } else {
        ImGui::Dummy(ImVec2(iw, ih));
    }
    ImGui::SameLine(0, px(6));
    ImGui::TextColored(col(headline_color), "%s", headline);
    ImGui::Dummy(ImVec2(0, px(8)));

    // Checklist: Serial / Region / ISO header. Before a disc is chosen, show
    // em-dashes with no pass/fail marks so the layout still reserves the rows.
    if (ImGui::BeginTable("verdict_checklist", 3, ImGuiTableFlags_SizingStretchProp)) {
        ImGui::TableSetupColumn("k", ImGuiTableColumnFlags_WidthFixed, px(76));
        ImGui::TableSetupColumn("v", ImGuiTableColumnFlags_WidthStretch);
        ImGui::TableSetupColumn("m", ImGuiTableColumnFlags_WidthFixed, px(28));
        const char* dash = "\xE2\x80\x94";
        kv_row("Serial",     pending ? dash : (v.serial[0] ? v.serial : dash),
               th, !pending, v.serial[0] != '\0');
        kv_row("Region",     pending ? dash : (v.region[0] ? v.region : dash),
               th, !pending, v.region[0] != '\0');
        kv_row("ISO header", pending ? dash : (v.iso_ok ? "OK" : "Mismatch"),
               th, !pending, v.iso_ok);
        // TOC fingerprinting is a netplay capability, not part of ordinary
        // offline disc identification. Never expose it for offline titles,
        // even if a host accidentally leaves stale netplay fields populated.
        if (m->netplay_supported && !pending &&
            (v.track_count > 0 || v.netplay_detail[0])) {
            char tracks_buf[32];
            if (v.track_count > 0)
                std::snprintf(tracks_buf, sizeof(tracks_buf), "%d", v.track_count);
            else
                std::snprintf(tracks_buf, sizeof(tracks_buf), "%s", dash);
            kv_row("Tracks", tracks_buf, th, true, v.netplay_ok != 0);
        }
        ImGui::EndTable();
    }
    if (m->netplay_supported && !pending &&
        v.netplay_detail[0] && !v.netplay_ok) {
        ImGui::Dummy(ImVec2(0, px(4)));
        ImGui::PushTextWrapPos(ImGui::GetCursorPosX() + availw);
        ImGui::TextColored(col(th.warn), "%s", v.netplay_detail);
        ImGui::PopTextWrapPos();
    }
}

void draw_game_panel(LauncherModel* m, const LauncherTheme& th, bool fill_h = false) {
    if (!begin_panel("game", 0, fill_h)) { end_panel(); return; }
    // No "GAME" eyebrow: the box art itself tells the user this is the game.
    const float availw = ImGui::GetContentRegionAvail().x;

    // Verify module: verify.mode==1 systems (PSX) render a disc-verdict block
    // (icon + Serial/Region/ISO checklist) here instead of the CRC/SHA line;
    // mode==0 systems (SNES/cart) keep the CRC/SHA line exactly as before.
    const bool disc_verdict = m->profile && m->profile->verify.mode == 1;

    // Box art on top (centered), everything else BELOW it. Height is derived
    // from the space actually left after the metadata + button, so the art is
    // as large as it can be WITHOUT pushing the last row out of the card.
    {
        // Reserve space for everything under the art: verified line + 2 meta rows
        // + Change ROM, plus the SAVES block when this game has battery SRAM.
        float reserve = px(198.0f);
        if (disc_verdict) reserve += px(120.0f);          // taller: icon+headline + tracks row
        if (m->saves_supported) reserve += px(96.0f);    // compact SAVES row below Change ROM
        if (m->password_save_path) reserve += px(96.0f); // password-save row (same footprint)
        if (m->msu1_patch_available) reserve += px(198.0f);  // MSU-1 patch-available sub-block
                                                              // (title + up-to-3-line wrapped note + 2 stacked buttons)
        float art_h = ImGui::GetContentRegionAvail().y - reserve;
        if (art_h > px(368.0f)) art_h = px(368.0f);   // allow a larger hero box art (~15% bigger than before)
        if (art_h < px(248.0f)) art_h = px(248.0f);   // keep it big enough to balance the side column
        hero_boxart_centered(g_boxart, art_h, availw);
    }
    ImGui::Dummy(ImVec2(0, px(10)));

    // Region + verification state, centered under the art.
    const char* noun = (m->rom_noun && m->rom_noun[0]) ? m->rom_noun : "ROM";
    if (disc_verdict) {
        draw_verdict_block(m, th, availw);
    } else {
        const bool verified = launcher_model_rom_verified(m);
        char line[64];
        if (!m->rom_present)   snprintf(line, sizeof(line), "No %s loaded", noun);
        else if (verified)     snprintf(line, sizeof(line), "%s verified", noun);
        else                   snprintf(line, sizeof(line), "%s not recognized", noun);
        float w = ImGui::GetTextLineHeight() + px(6) + ImGui::CalcTextSize(line).x;
        ImGui::SetCursorPosX(ImGui::GetCursorPosX() + (availw - w) * 0.5f);
        state_mark(verified, th);
        ImGui::SameLine(0, px(6));
        ImGui::TextColored(verified ? col(th.good) : col(th.warn), "%s", line);
    }
    ImGui::Dummy(ImVec2(0, px(10)));

    // Metadata a PLAYER cares about — just Region + File. The "is my ROM good?"
    // question is answered by the ROM-verified line above; raw size and CRC/SHA
    // digests are developer noise, so they're not shown.
    if (ImGui::BeginTable("meta", 2, ImGuiTableFlags_SizingStretchProp)) {
        ImGui::TableSetupColumn("k", ImGuiTableColumnFlags_WidthFixed, px(76));
        ImGui::TableSetupColumn("v", ImGuiTableColumnFlags_WidthStretch);
        // The disc-verdict block already reports Region in its checklist, so
        // don't repeat it here. Otherwise show Region only when the host gave
        // one — an empty value would render a bare "Region" label with nothing
        // beside it, which reads as a bug.
        if (!disc_verdict && m->region[0])
            kv_row("Region", m->region, th, false, false);
        kv_row("File",   m->rom_file, th, false, false);
        ImGui::EndTable();
    }
    ImGui::Dummy(ImVec2(0, px(12)));
    char change_label[32];
    snprintf(change_label, sizeof(change_label), "Change %s", noun);
    if (ImGui::Button(change_label, ImVec2(availw, px(34)))) {
        // Native file dialog filter comes from the active console's
        // SystemProfile.rom_filter — never a hardcoded per-system set. Every
        // shipped profile supplies one; the fallback is console-NEUTRAL (all
        // files, titled with this console's own rom_noun) so a profile that
        // forgets rom_filter degrades to "any file" rather than prompting for
        // some other machine's media.
        const SystemProfile* prof = (const SystemProfile*)m->profile;
        char title[48];
        snprintf(title, sizeof(title), "Select %s", noun);
        if (prof && prof->rom_filter.patterns && prof->rom_filter.pattern_count > 0)
            request_rom_picker(m, title, prof->rom_filter.patterns,
                               prof->rom_filter.pattern_count,
                               prof->rom_filter.desc, false);
        else
            request_rom_picker(m, title, NULL, 0, NULL, false);
    }

    // MSU-1 patch-available sub-block: this game ships an IPS patch that
    // converts the verified vanilla ROM into its MSU-1 streamed-audio variant.
    // Ported from the legacy launcher's dashboard "MSU-1 patch available" card
    // (snesrecomp/runner/src/launcher/launcher_gui.cpp: msu1_patch_available +
    // do_patch()/patch_rom/skip_patch). "warn" amber styling — this is a
    // choice the player should notice, not a routine control.
    if (m->msu1_patch_available) {
        ImGui::Dummy(ImVec2(0, px(10)));
        ImGui::PushStyleColor(ImGuiCol_ChildBg, col(th.panel_hovered));
        ImGui::PushStyleColor(ImGuiCol_Border, col(th.warn));
        if (ImGui::BeginChild("msu1_patch_block", ImVec2(availw, 0),
                              ImGuiChildFlags_Borders | ImGuiChildFlags_AutoResizeY,
                              ImGuiWindowFlags_NoScrollbar | ImGuiWindowFlags_NoScrollWithMouse)) {
            ImGui::TextColored(col(th.warn), "MSU-1 patch available");
            const float inner_w = ImGui::GetContentRegionAvail().x;
            ImGui::PushTextWrapPos(ImGui::GetCursorPosX() + inner_w);
            ImGui::TextColored(col(th.text_muted), "%s",
                (m->msu1_note && m->msu1_note[0])
                    ? m->msu1_note
                    : "An MSU-1 patch exists for this game. Patch a copy beside "
                      "your ROM (the original is never modified)?");
            ImGui::PopTextWrapPos();
            ImGui::Dummy(ImVec2(0, px(8)));
            // Stacked full-width buttons, not side-by-side: "Skip (Play Unpatched)"
            // is long enough that splitting the row in half clips its label at
            // common card widths (verified via the LNG_DEMO_MSU harness).
            if (ImGui::Button("Patch ROM", ImVec2(inner_w, px(32))))
                launcher_model_apply_msu1_patch(m);
            ImGui::Dummy(ImVec2(0, px(th.spacing_xs)));
            if (ImGui::Button("Skip (Play Unpatched)", ImVec2(inner_w, px(32))))
                launcher_model_skip_msu1_patch(m);
        }
        ImGui::EndChild();
        ImGui::PopStyleColor(2);
    }

    // SAVES lives in the GAME card as a compact row (no separate card / eyebrow).
    // Present only for games with battery SRAM — data-driven, never by name.
    // Content lives in draw_save_row() (the Save module's shared row-drawer,
    // also used standalone by panel_save's own card — see below); folding it
    // in here, uncarded, is what preserves today's exact GAME-card layout.
    if (m->saves_supported || m->password_save_path) {
        ImGui::Dummy(ImVec2(0, px(8)));
        ImGui::PushStyleColor(ImGuiCol_Separator, col(th.border));
        ImGui::Separator();
        ImGui::PopStyleColor();
        ImGui::Dummy(ImVec2(0, px(6)));
        draw_save_row(m, th);
    }
    end_panel();
}

// Save module (docs/ARCHITECTURE.md): one reusable picker row — label + path +
// Import/Clear. SAVE_SRAM and (until the block-grid UI lands) SAVE_MEMCARD
// both render this same compact row: kind-switched data, one widget.
void draw_save_row(LauncherModel* m, const LauncherTheme& th) {
    // Password/mantra save variant (e.g. Faxanadu): the row shows the current
    // password text instead of a binary save file. Editable behind an Edit ->
    // type -> Save confirm step, mirroring the legacy NES launcher's flow.
    if (m->password_save_path) {
        static bool s_pw_editing = false;
        static char s_pw_buf[128];
        const char* label = (m->password_save_label && m->password_save_label[0])
                              ? m->password_save_label : "Password";
        ImGui::PushStyleColor(ImGuiCol_Text, col(th.text_muted));
        ImGui::AlignTextToFramePadding();
        ImGui::TextUnformatted(label);
        ImGui::PopStyleColor();
        // Value sits right after the label's actual end with comfortable
        // padding — a RELATIVE gap, not an absolute column, so a wider label
        // ("Password") never clips under the value regardless of row indent.
        ImGui::SameLine(0.0f, px(th.spacing_lg));
        const float bw = px(84);
        if (!s_pw_editing) {
            ImGui::AlignTextToFramePadding();
            if (m->password_text[0]) ImGui::TextUnformatted(m->password_text);
            else ImGui::TextColored(col(th.text_muted), "(Not set)");
            ImGui::SameLine(ImGui::GetCursorPosX() + ImGui::GetContentRegionAvail().x - bw);
            if (ImGui::Button("Edit", ImVec2(bw, px(30)))) {
                snprintf(s_pw_buf, sizeof(s_pw_buf), "%s", m->password_text);
                s_pw_editing = true;
            }
        } else {
            float avail = ImGui::GetContentRegionAvail().x - bw * 2 - px(th.spacing_sm) * 2;
            if (avail < px(80)) avail = px(80);
            ImGui::SetNextItemWidth(avail);
            ImGui::InputText("##pwedit", s_pw_buf, sizeof(s_pw_buf));
            ImGui::SameLine(0, px(th.spacing_sm));
            if (ImGui::Button("Save", ImVec2(bw, px(30)))) {
                launcher_model_password_commit(m, s_pw_buf);
                s_pw_editing = false;
            }
            ImGui::SameLine(0, px(th.spacing_sm));
            if (ImGui::Button("Cancel", ImVec2(bw, px(30))))
                s_pw_editing = false;
        }
        if (!m->saves_supported) return;   // password-only game: no SRAM row below
        ImGui::Dummy(ImVec2(0, px(4)));
    }
    const char* sp = m->sram_path ? m->sram_path : "";
    const char* base = sp;
    for (const char* q = sp; *q; ++q) if (*q == '/' || *q == '\\') base = q + 1;

    // Reflect the ACTUAL save file state, not just the configured path. Showing
    // the filename unconditionally made a present and an absent save look
    // identical — so Clear (which correctly no-ops when there's nothing to
    // delete) read as "broken". Stat the file each frame: show its size when it
    // exists, "no save yet" when it doesn't, and disable Clear when empty so the
    // button's effect is always visible.
    long sz = -1;
    if (sp[0]) { FILE* f = fopen(sp, "rb"); if (f) { fseek(f, 0, SEEK_END); sz = ftell(f); fclose(f); } }
    const bool has_save = sz >= 0;

    const float bw = px(84);
    ImGui::PushStyleColor(ImGuiCol_Text, col(th.text_muted));
    ImGui::AlignTextToFramePadding();
    ImGui::TextUnformatted("Save");
    ImGui::PopStyleColor();
    ImGui::SameLine(px(76));
    ImGui::AlignTextToFramePadding();
    if (has_save) {
        // Just the file name (no size annotation) — right-elided with "…" so a
        // long name never runs under the Import/Clear buttons to its right.
        const float buttons_w = bw * 2 + px(th.spacing_sm);
        const float avail = ImGui::GetContentRegionAvail().x - buttons_w - px(th.spacing_md);
        char shown[128];
        snprintf(shown, sizeof shown, "%s", base);
        if (avail > 0 && ImGui::CalcTextSize(shown).x > avail) {
            size_t n = strlen(base);
            while (n > 0) {
                char tmp[132];
                snprintf(tmp, sizeof tmp, "%.*s\xE2\x80\xA6", (int)n, base);  // "<head>…"
                if (ImGui::CalcTextSize(tmp).x <= avail) { snprintf(shown, sizeof shown, "%s", tmp); break; }
                --n;
            }
            if (n == 0) snprintf(shown, sizeof shown, "\xE2\x80\xA6");
        }
        ImGui::TextUnformatted(shown);
    } else {
        ImGui::TextColored(col(th.text_muted), "no save yet");
    }
    ImGui::SameLine(ImGui::GetCursorPosX() + ImGui::GetContentRegionAvail().x - bw*2 - px(th.spacing_sm));
    static const char* kSramPatterns[] = { "*.srm", "*.sav" };
    if (ImGui::Button("Import", ImVec2(bw, px(30)))) {
        char buf[512];
        if (launcher_pick_file("Import SRAM save", kSramPatterns, 2,
                               "Battery save (.srm .sav)", buf, sizeof(buf)))
            launcher_model_import_sram(m, buf);   // backs up existing to .bak, then copies in
    }
    ImGui::SameLine(0, px(th.spacing_sm));
    ImGui::BeginDisabled(!has_save);              // nothing to clear when no save exists
    if (ImGui::Button("Clear", ImVec2(bw, px(30))))
        launcher_model_clear_sram(m);             // backs up to .bak, then deletes
    ImGui::EndDisabled();
}

// ---- panel adapters: LauncherPanelDrawFn = void(LauncherModel*, const LauncherTheme*) ----
void panel_game_draw(LauncherModel* m, const LauncherTheme* th) {
    draw_game_panel(m, *th, g_game_fill_h);
}

// ---- Save module, SAVE_MEMCARD half (PSX) -----------------------------------
// SAVE_SRAM keeps the compact row above, folded into the GAME card (SNES,
// unchanged). SAVE_MEMCARD (PSX) is a standalone WIDE dashboard panel (see
// kPanelsDashboardPsx in launcher_system.h): one sub-section per card slot —
// icon + path picker (Browse/New) + a real 15-block usage grid, matching PS1
// memory-card conventions (each card holds 15 save blocks).

// One compact memory-card slot: icon + name, inline block count, and Browse/
// New actions. `probe` (SystemProfile.save.probe) is the host hook that
// would refresh m->memcard_blocks_used[slot] from the real card image; it is
// NULL in every profile today (unimplemented proto hook), so this falls back to
// a representative placeholder count rather than an all-empty slot.
// Draws the CONTENT of one small memory-card card (the caller supplies the card
// chrome + width). Vertical stack so nothing crowds at a controller-narrow
// width: icon + label, block count, then a Browse/New button pair.
void draw_memcard_slot(LauncherModel* m, const LauncherTheme& th, int slot) {
    const SystemProfile* prof = (const SystemProfile*)m->profile;
    ImGui::PushID(slot);

    const bool enabled = m->s.memcard_enabled[slot] != 0;

    const float slotw   = ImGui::GetContentRegionAvail().x;
    const float start_x = ImGui::GetCursorPosX();
    const float top_y   = ImGui::GetCursorPosY();

    // Block usage source, most-authoritative first: a host memcard_inspect
    // callback (REAL card contents) → a card we just formatted blank (0) → a
    // SystemProfile SaveProbeFn → a representative placeholder pattern.
    uint16_t used;
    if (m->memcard_inspected[slot])
        used = m->memcard_blocks_used[slot];
    else if (m->memcard_freshly_formatted[slot])
        used = 0;
    else if (prof && prof->save.probe && prof->save.probe(m, slot))
        used = m->memcard_blocks_used[slot];
    else
        used = (uint16_t)(slot == 0 ? 0x0025u : 0x0009u);
    int used_count = 0;
    for (int i = 0; i < 15; ++i) if (used & (1u << i)) ++used_count;

    // --- Header: memory-card image on the LEFT; the Enabled toggle (top-right)
    // and the card name + block count (under the toggle) on the RIGHT. The
    // block grid + Browse/New sit BELOW the image, full width. ---
    // Image is fit by height (memcard.tga is 148x164 portrait). In the
    // fill-height (wide PSX) layout it grows to fill the card, reserving room
    // below for the grid + buttons and capping its width to ~half the card so
    // the right column keeps room for the toggle and name.
    float img_h;
    if (g_save_fill_h) {
        const float avail_h = ImGui::GetContentRegionAvail().y;
        // Grid + gap + Browse/New + bottom pad — keep buttons clear of the frame.
        img_h = avail_h - px(110.0f);
        const float img_h_by_w = (0.50f * slotw) * (164.0f / 148.0f);  // cap width ~half
        if (img_h > img_h_by_w) img_h = img_h_by_w;
        if (img_h < px(92.0f))  img_h = px(92.0f);
        if (img_h > px(200.0f)) img_h = px(200.0f);
    } else {
        img_h = px(108.0f);
    }
    float iw = img_h * (148.0f / 164.0f), ih = img_h;
    if (g_memcard.w > 0 && g_memcard.h > 0) {
        const float s = img_h / (float)g_memcard.h;
        iw = g_memcard.w * s;
        ImGui::Image(tid(g_memcard), ImVec2(iw, ih));
    } else {
        ImGui::Dummy(ImVec2(iw, ih));
    }

    const float rc_x    = start_x + iw + px(14.0f);   // right column x
    const float frame_h = ImGui::GetFrameHeight();
    const float line_h  = ImGui::GetTextLineHeight();

    // Enabled toggle at the top of the right column — left-aligned at rc_x so
    // it lines up vertically with the card name and block count below it.
    {
        ImGui::SetCursorPos(ImVec2(rc_x, top_y));
        bool enabled_box = enabled;
        if (ImGui::Checkbox("Enabled", &enabled_box))
            launcher_model_toggle_memcard(m, slot);
    }

    // Card name, on its own line under the toggle.
    const char* mp = m->s.memcard_path[slot];
    const char* base = mp;
    for (const char* q = mp; *q; ++q) if (*q == '/' || *q == '\\') base = q + 1;
    char label[40];
    if (base[0]) snprintf(label, sizeof(label), "%s", base);
    else         snprintf(label, sizeof(label), "Memory Card %d", slot + 1);
    ImGui::SetCursorPos(ImVec2(rc_x, top_y + frame_h + px(10.0f)));
    ImGui::PushStyleColor(ImGuiCol_Text, col(enabled ? th.accent : th.text_muted));
    ImGui::TextUnformatted(label);
    ImGui::PopStyleColor();

    // Block count under the name.
    char cap[16]; snprintf(cap, sizeof(cap), "%d / 15", used_count);
    ImGui::SetCursorPos(ImVec2(rc_x, top_y + frame_h + px(10.0f) + line_h + px(6.0f)));
    ImGui::PushStyleColor(ImGuiCol_Text, col(th.text_muted));
    ImGui::TextUnformatted(cap);
    ImGui::PopStyleColor();

    // Resume the card body BELOW the image, full width.
    ImGui::SetCursorPos(ImVec2(start_x, top_y + ih + px(14.0f)));

    // Dim the rest of the slot body when disabled (visual only; the Browse/New
    // controls stay clickable so the slot can be re-configured while off).
    const float body_alpha = enabled ? 1.0f : 0.4f;
    ImGui::PushStyleVar(ImGuiStyleVar_Alpha, ImGui::GetStyle().Alpha * body_alpha);

    // 15-block usage grid, full width under the image.
    {
        const int   kB   = 15;
        const float bgap = px(4.0f);
        const float availw = ImGui::GetContentRegionAvail().x;
        float cell = (availw - bgap * (kB - 1)) / (float)kB;
        if (cell > px(18.0f)) cell = px(18.0f);
        ImDrawList* dl = ImGui::GetWindowDrawList();
        const ImVec2 p0 = ImGui::GetCursorScreenPos();
        for (int i = 0; i < kB; ++i) {
            const bool onb = (used & (1u << i)) != 0;
            const ImVec2 mn(p0.x + i * (cell + bgap), p0.y);
            const ImVec2 mx(mn.x + cell, mn.y + cell);
            dl->AddRectFilled(mn, mx, imcol(onb ? th.accent : th.control), px(3.0f));
            dl->AddRect(mn, mx, imcol(th.border), px(3.0f), 0, px(1.0f));
        }
        ImGui::Dummy(ImVec2(cell * kB + bgap * (kB - 1), cell));
    }

    // Gap above Browse/New only — bottom inset is Child WindowPadding (same as
    // the top). An extra bottom Dummy doubled the pad and looked top-heavy.
    static const char* kCardPatterns[] = { "*.mcd", "*.mcr", "*.mc" };
    const float cw = ImGui::GetContentRegionAvail().x;
    const float bw = (cw - px(th.spacing_sm)) * 0.5f;
    const float btn_h = px(32.0f);
    const float btn_gap = px(16.0f);
    if (g_save_fill_h) {
        const float slack = ImGui::GetContentRegionAvail().y - btn_h;
        ImGui::Dummy(ImVec2(0, slack > btn_gap ? slack : btn_gap));
    } else {
        ImGui::Dummy(ImVec2(0, btn_gap));
    }
    if (ImGui::Button("Browse", ImVec2(bw, btn_h))) {
        char buf[512];
        if (launcher_pick_file("Select memory card image", kCardPatterns, 3,
                               "PS1 memory card (.mcd .mcr .mc)", buf, sizeof(buf)))
            launcher_model_set_memcard_path(m, slot, buf);
    }
    ImGui::SameLine(0, px(th.spacing_sm));
    if (ImGui::Button("New", ImVec2(bw, btn_h))) {
        char buf[512];
        // "New" picks a DESTINATION (the file need not exist yet — a save
        // dialog, not the open dialog Browse uses), then writes a real,
        // freshly formatted blank 128KB card there and adopts it.
        if (launcher_pick_save_file("Create new memory card", kCardPatterns, 3,
                                    "PS1 memory card (.mcd)", buf, sizeof(buf)))
            launcher_model_new_memcard(m, slot, buf);
    }

    ImGui::PopStyleVar();  // body_alpha
    ImGui::PopID();
}

// Available whenever this system's SaveSpec says there's something to show:
// SAVE_MEMCARD (PSX) always offers the panel — the memory-card slots exist
// independent of whether the GAME itself also has legacy SRAM — while
// SAVE_SRAM keeps the original per-GAME gate (sram_path != NULL) and
// SAVE_NONE stays hidden.
int avail_save(const LauncherModel* m) {
    const SystemProfile* prof = (const SystemProfile*)m->profile;
    const SaveKind kind = prof ? prof->save.kind : SAVE_NONE;
    if (kind == SAVE_MEMCARD) return 1;
    if (kind == SAVE_SRAM)    return m->saves_supported;
    return 0;
}

// Fixed logical width for dashboard player / memcard cards. Extra horizontal
// space adds more columns instead of stretching each card.
static float dash_card_width(float availw, float gap, int count) {
    const float pref = px(300.0f);
    if (count < 1) count = 1;
    int cols = (int)((availw + gap) / (pref + gap));
    if (cols < 1) cols = 1;
    if (cols > count) cols = count;
    float cardw = pref;
    if (cols == 1 && availw < pref) cardw = availw;  // narrow: shrink to fit
    return cardw;
}

static int dash_card_columns(float availw, float gap, float cardw, int count) {
    if (count < 1) return 1;
    int cols = (int)((availw + gap) / (cardw + gap));
    if (cols < 1) cols = 1;
    if (cols > count) cols = count;
    return cols;
}

void panel_save_draw(LauncherModel* m, const LauncherTheme* th) {
    const SystemProfile* prof = (const SystemProfile*)m->profile;
    const SaveKind kind = prof ? prof->save.kind : SAVE_NONE;
    if (kind == SAVE_MEMCARD) {
        // No outer "MEMORY CARDS" card/eyebrow: the small per-slot cards ARE the
        // UI. Fixed width (same as player cards); wider windows add columns
        // instead of stretching the pair across the column.
        const int slots = (prof->save.slots > 0 && prof->save.slots <= 2) ? prof->save.slots : 2;
        const float gap = px(th->spacing_sm);
        const float avail = ImGui::GetContentRegionAvail().x;
        const float cw = dash_card_width(avail, gap, slots);
        const int cols = dash_card_columns(avail, gap, cw, slots);
        // Multitap fill-height: slot cards take the reserved band under the
        // controller stack. 2P / narrow leave g_save_fill_h false and hug.
        const float fill_h = ImGui::GetContentRegionAvail().y;
        const bool do_fill = g_save_fill_h && fill_h > px(180.0f);
        g_save_fill_h = do_fill;   // draw_memcard_slot reads this for the bottom slack
        for (int slot = 0; slot < slots; ++slot) {
            if (slot % cols) ImGui::SameLine(0, gap);
            else if (slot) ImGui::Dummy(ImVec2(0, gap));
            char cid[16]; snprintf(cid, sizeof(cid), "mcc%d", slot);
            char pid[16]; snprintf(pid, sizeof(pid), "mcp%d", slot);
            begin_container(cid, ImVec2(cw, do_fill ? fill_h : 0.0f),
                            do_fill ? ImGuiChildFlags_None : ImGuiChildFlags_AutoResizeY);
                if (begin_panel(pid, cw, do_fill, do_fill))
                    draw_memcard_slot(m, *th, slot);
                end_panel();
            end_container();
        }
        g_save_fill_h = false;
        return;
    }
    if (!begin_panel("save", 0)) { end_panel(); return; }
    eyebrow("SAVES");
    draw_save_row(m, *th);
    end_panel();
}

// ---- N64 Transfer Pak: one card per controller port -----------------------
// Composes only for games whose GameInfo passes tpak_slots > 0 (the Stadium
// titles) — the availability gate below keeps it off every other console/game.
static const char* elide_left(const char* s, float max_w, char* out, size_t cap);  // fwd (defined below)

int avail_tpak(const LauncherModel* m) { return m->tpak_slots > 0; }

// Real GB-cartridge art for a Transfer Pak slot, picked by the host-reported
// cart kind (1 red / 2 blue / 3 yellow / 4 green); the gray empty shell for an
// empty slot or a recognized-but-uncolored cart. Falls back to a blank box if
// the art didn't load. `box` is the logical fit size.
void draw_tpak_cart(int cart_kind, bool present, float box) {
    const int idx = (present && cart_kind >= 1 && cart_kind <= 4) ? cart_kind : 0;
    image_fit(g_cart[idx], box, box);   // image_fit Dummies when the texture is absent
}

static const char* rui_basename(const char* path) {
    const char* base = path;
    for (const char* q = path; *q; ++q)
        if (*q == '/' || *q == '\\') base = q + 1;
    return base;
}

// Transfer Pak config modal state. A tile click stages a request (open_req);
// the modal itself is drawn once per frame at root scope (draw_tpak_modal) so
// OpenPopup and BeginPopupModal share the same ID stack from wherever a tile
// was clicked (dashboard row OR the Controller page).
static int g_tpak_open_req  = -1;
static int g_tpak_modal_slot = -1;

// One compact port tile: the cartridge (gray shell when empty, colored R/B/Y
// once a cart is set), the cart name, and a Configure button — clicking either
// the cart or Configure opens the config modal. This is ALL that shows inline
// now; picking cart + save happens in the modal, so the dashboard row stays a
// short strip of carts instead of tall cards that push the layout into a
// scroll.
void draw_tpak_tile(LauncherModel* m, const LauncherTheme& th, int slot) {
    char eb[24]; snprintf(eb, sizeof(eb), "TRANSFER PAK %d", slot + 1);
    eyebrow(eb);

    const bool has_cart  = m->s.tpak_rom_path[slot][0] != '\0';
    const bool inspected = m->tpak_inspected[slot];
    const RecompLauncherCTpak* info = &m->tpak_info[slot];
    const float inner = ImGui::GetContentRegionAvail().x;

    // Centered cartridge art, itself a click target that opens the modal.
    ImGui::PushID(slot);
    const float art = px(66);
    ImVec2 art_cursor = ImGui::GetCursorScreenPos();
    image_fit_centered(g_cart[(has_cart && inspected && info->cart_kind >= 1 &&
                               info->cart_kind <= 4) ? info->cart_kind : 0], 60, 66, inner);
    // invisible hit-box over the art
    ImGui::SetCursorScreenPos(art_cursor);
    if (ImGui::InvisibleButton("cart_hit", ImVec2(inner, art))) g_tpak_open_req = slot;

    // name line (centered), muted "Empty" when nothing inserted
    const char* label = !has_cart ? "Empty"
                        : (inspected && info->cart_label[0])
                            ? info->cart_label : rui_basename(m->s.tpak_rom_path[slot]);
    float lw = ImGui::CalcTextSize(label).x;
    if (lw < inner) ImGui::SetCursorPosX(ImGui::GetCursorPosX() + (inner - lw) * 0.5f);
    ImGui::TextColored(has_cart ? col(th.text) : col(th.text_muted), "%s", label);
    ImGui::Dummy(ImVec2(0, px(4)));

    if (ImGui::Button(has_cart ? "Configure" : "Insert...",
                      ImVec2(ImGui::GetContentRegionAvail().x, px(28))))
        g_tpak_open_req = slot;
    ImGui::PopID();
}

// The per-port config surface, drawn as a modal. Everything cartridge-related
// lives here: a large live cart preview, the cartridge/trainer facts, and the
// Change / Remove / save-file actions. Reached from any tile (dashboard or
// Controller page). Draw ONCE per frame at root scope.
void draw_tpak_modal(LauncherModel* m, const LauncherTheme& th) {
    if (g_tpak_open_req >= 0) {
        g_tpak_modal_slot = g_tpak_open_req;
        g_tpak_open_req = -1;
        ImGui::OpenPopup("Transfer Pak");
    }
    ImGui::SetNextWindowSize(ImVec2(px(440), 0), ImGuiCond_Appearing);
    // No OS-style title bar (it renders in ImGui's un-themed blue) — the card's
    // own "TRANSFER PAK · PORT n" eyebrow is the heading.
    if (!ImGui::BeginPopupModal("Transfer Pak", nullptr,
                                ImGuiWindowFlags_NoResize | ImGuiWindowFlags_NoMove |
                                ImGuiWindowFlags_NoTitleBar))
        return;
    const int slot = g_tpak_modal_slot;
    if (slot < 0 || slot >= m->tpak_slots) { ImGui::CloseCurrentPopup(); ImGui::EndPopup(); return; }

    const bool has_cart  = m->s.tpak_rom_path[slot][0] != '\0';
    const bool inspected = m->tpak_inspected[slot];
    const RecompLauncherCTpak* info = &m->tpak_info[slot];

    ImGui::PushStyleColor(ImGuiCol_Text, col(th.accent2));
    ImGui::Text("TRANSFER PAK  \xC2\xB7  PORT %d", slot + 1);
    ImGui::PopStyleColor();
    ImGui::Separator();
    ImGui::Dummy(ImVec2(0, px(6)));

    // Large live cart preview, centered — turns from the gray shell into the
    // colored cart the moment a recognized ROM is picked.
    const float avail = ImGui::GetContentRegionAvail().x;
    image_fit_centered(g_cart[(has_cart && inspected && info->cart_kind >= 1 &&
                               info->cart_kind <= 4) ? info->cart_kind : 0], 132, 138, avail);
    ImGui::Dummy(ImVec2(0, px(6)));

    // name + trainer, centered
    auto centered = [&](ImU32 c, const char* s) {
        float w = ImGui::CalcTextSize(s).x;
        if (w < avail) ImGui::SetCursorPosX(ImGui::GetCursorPosX() + (avail - w) * 0.5f);
        ImGui::PushStyleColor(ImGuiCol_Text, c); ImGui::TextUnformatted(s); ImGui::PopStyleColor();
    };
    if (!has_cart) {
        centered(ImGui::GetColorU32(col(th.text_muted)), "No cartridge inserted");
    } else {
        const char* label = (inspected && info->cart_label[0])
                              ? info->cart_label : rui_basename(m->s.tpak_rom_path[slot]);
        centered(ImGui::GetColorU32(col(th.text)), label);
        char line[80];
        if (inspected && info->trainer_name[0]) {
            if (info->trainer_id[0])
                snprintf(line, sizeof(line), "Trainer %s  \xC2\xB7  ID %s",
                         info->trainer_name, info->trainer_id);
            else snprintf(line, sizeof(line), "Trainer %s", info->trainer_name);
        } else snprintf(line, sizeof(line), "No save data");
        centered(ImGui::GetColorU32(col(th.text_muted)), line);
    }

    ImGui::Dummy(ImVec2(0, px(10)));
    // Change / Remove cartridge
    const float full = ImGui::GetContentRegionAvail().x;
    if (ImGui::Button(has_cart ? "Change cartridge..." : "Insert cartridge...",
                      ImVec2(full, px(32)))) {
        static const char* kGbPatterns[] = { "*.gb", "*.gbc" };
        char buf[512];
        if (launcher_pick_file("Select Game Boy cartridge", kGbPatterns, 2,
                               "Game Boy cartridge (.gb .gbc)", buf, sizeof(buf)))
            launcher_model_set_tpak_rom(m, slot, buf);
    }
    if (has_cart) {
        if (ImGui::Button("Remove cartridge", ImVec2(full, px(28))))
            launcher_model_clear_tpak(m, slot);

        // Battery-save row: label + value + Browse / Reset.
        ImGui::Dummy(ImVec2(0, px(8)));
        ImGui::TextColored(col(th.text_muted), "Battery save");
        const char* sv = m->s.tpak_save_path[slot][0]
                           ? rui_basename(m->s.tpak_save_path[slot])
                           : "Default (runtime chooses)";
        char elided[128];
        elide_left(sv, ImGui::GetContentRegionAvail().x, elided, sizeof(elided));
        ImGui::TextUnformatted(elided);
        const float bw = (ImGui::GetContentRegionAvail().x - px(th.spacing_sm)) * 0.5f;
        if (ImGui::Button("Browse save...", ImVec2(bw, px(26)))) {
            static const char* kSavPatterns[] = { "*.sav", "*.srm" };
            char buf[512];
            if (launcher_pick_file("Select battery save", kSavPatterns, 2,
                                   "Battery save (.sav)", buf, sizeof(buf)))
                launcher_model_set_tpak_save(m, slot, buf);
        }
        ImGui::SameLine(0, px(th.spacing_sm));
        if (ImGui::Button("Use default", ImVec2(bw, px(26))))
            launcher_model_set_tpak_save(m, slot, "");
    }

    ImGui::Dummy(ImVec2(0, px(10)));
    ImGui::Separator();
    ImGui::Dummy(ImVec2(0, px(4)));
    if (ImGui::Button("Done", ImVec2(ImGui::GetContentRegionAvail().x, px(30))))
        ImGui::CloseCurrentPopup();
    ImGui::EndPopup();
}

void panel_tpak_draw(LauncherModel* m, const LauncherTheme* th) {
    // Compact per-port tiles in one full-width row (click a cart to configure).
    const int slots = m->tpak_slots;
    const float gap = px(th->spacing_sm);
    const float avail = ImGui::GetContentRegionAvail().x;
    const float cw = (avail - gap * (slots - 1)) / (float)slots;
    static const char* kCid[RECOMP_LAUNCHER_MAX_TPAKS] = { "tpc0", "tpc1", "tpc2", "tpc3" };
    static const char* kPid[RECOMP_LAUNCHER_MAX_TPAKS] = { "tpp0", "tpp1", "tpp2", "tpp3" };
    for (int slot = 0; slot < slots; ++slot) {
        if (slot) ImGui::SameLine(0, gap);
        begin_container(kCid[slot], ImVec2(cw, 0), ImGuiChildFlags_AutoResizeY);
            if (begin_panel(kPid[slot], cw, false))
                draw_tpak_tile(m, *th, slot);
            end_panel();
        end_container();
    }
}

// PSX-style pad-mode selector: Analog / D-Pad segmented row. Caller only draws
// this when pad_mode_supported && pad_mode_selectable (a locked mode draws
// nothing — there's nothing to pick). Hybrid is deliberately absent: it is a
// mod-only mode a trusted game plugin requests at runtime, never a player
// choice.
void pad_mode_selector(LauncherModel* m, const LauncherTheme& th, int p, float w) {
    struct Seg { int mode; const char* label; };
    Seg segs[8];
    int n = 0;
    // A console with a custom pad-mode list (ControllerSpec.modes, e.g. Genesis
    // 3-Button/6-Button) drives the segments from that list; otherwise the
    // legacy PSX-shaped Analog/D-Pad set.
    const SystemProfile* prof = (const SystemProfile*)m->profile;
    if (prof && prof->controller.modes && prof->controller.mode_count > 0) {
        int mc = prof->controller.mode_count;
        if (mc > (int)(sizeof(segs) / sizeof(segs[0]))) mc = (int)(sizeof(segs) / sizeof(segs[0]));
        for (int i = 0; i < mc; ++i)
            segs[n++] = { prof->controller.modes[i].mode, prof->controller.modes[i].label };
    } else {
        segs[n++] = { 1, "Analog" };
        segs[n++] = { 2, "D-Pad" };
    }

    // Keyboard has no analog sticks — Analog is unavailable (PSX modes).
    const bool kb_digital_only =
        m->s.player_src[p] == 1 &&
        !(prof && prof->controller.modes && prof->controller.mode_count > 0);

    const float gap = px(4.0f);
    const float seg_w = (w - gap * (n - 1)) / n;
    for (int i = 0; i < n; ++i) {
        if (i) ImGui::SameLine(0, gap);
        bool sel = m->s.pad_mode[p] == segs[i].mode;
        // Analog needs sticks; grey out on keyboard.
        const bool stick_mode = (segs[i].mode == 1);
        const bool disabled = kb_digital_only && stick_mode;
        ImGui::PushID(i);
        if (disabled) {
            ImGui::BeginDisabled();
            ImGui::PushStyleColor(ImGuiCol_Button, col(th.control));
            ImGui::PushStyleColor(ImGuiCol_ButtonHovered, col(th.control));
            ImGui::PushStyleColor(ImGuiCol_ButtonActive, col(th.control));
            ImGui::PushStyleColor(ImGuiCol_Text, col(th.text_muted));
            ImGui::Button(segs[i].label, ImVec2(seg_w, px(28)));
            ImGui::PopStyleColor(4);
            ImGui::EndDisabled();
        } else {
            ImGui::PushStyleColor(ImGuiCol_Button, sel ? col(th.accent) : col(th.control));
            ImGui::PushStyleColor(ImGuiCol_ButtonHovered, sel ? col(th.accent) : col(th.control_hovered));
            ImGui::PushStyleColor(ImGuiCol_ButtonActive, col(th.accent));
            ImGui::PushStyleColor(ImGuiCol_Text, sel ? col(th.accent_text) : col(th.text));
            if (ImGui::Button(segs[i].label, ImVec2(seg_w, px(28))))
                launcher_model_set_pad_mode(m, p, segs[i].mode);
            ImGui::PopStyleColor(4);
        }
        ImGui::PopID();
    }
}

// Each player is its OWN self-contained card ("PLAYER 1" as its eyebrow), not a
// floating column inside one big CONTROLLERS box. A 1-player game shows a
// single card (no wasted width); a 2-player game shows two identical cards side
// by side. Same module, composed per the game's declared player count.
// Input-source Selectables shared by the player card (##src) and the Controller
// config (##csrc) combos. When the game sets has_mouse_controls, player 0's
// keyboard entry splits into "Keyboard + Mouse" (mouse-aim on) and "Keyboard"
// (off); otherwise it is the single legacy "Keyboard" entry, byte-for-byte
// identical to before for every non-mouse game.
void draw_source_selectables(LauncherModel* m, int p) {
    const SystemProfile* src_prof = (const SystemProfile*)m->profile;
    const bool psx = src_prof && src_prof->id && !strcmp(src_prof->id, "psx");
    if (ImGui::Selectable("None", m->s.player_src[p] == 0)) {
        launcher_model_set_source(m, p, 0, 0, nullptr, nullptr);
        if (psx) launcher_binds_refresh(m);
    }
    if (m->has_mouse_controls && p == 0) {
        const bool kbm = m->s.player_src[p] == 1 && m->s.mouse_enabled;
        const bool kb  = m->s.player_src[p] == 1 && !m->s.mouse_enabled;
        if (ImGui::Selectable("Keyboard + Mouse", kbm))
            launcher_model_set_mouse_source(m, 1);
        if (ImGui::Selectable("Keyboard", kb))
            launcher_model_set_mouse_source(m, 0);
    } else {
        if (ImGui::Selectable("Keyboard", m->s.player_src[p] == 1)) {
            launcher_model_set_source(m, p, 1, 0, nullptr, nullptr);
            if (psx) launcher_binds_refresh(m);
        }
    }

    // Unified pad list (no duplicates): saved mappings + live devices.
    // Pads already selected on another player are disabled (keyboard is not).
    struct PadOpt {
        char guid[40];
        char name[64];
        uint32_t id;
        bool live;
    };
    constexpr int kMaxOpts = LNG_MAX_PADS + 16 + LNG_MAX_PLAYERS;
    PadOpt opts[kMaxOpts]{};
    int nopt = 0;
    auto already = [&](const char* guid) -> bool {
        if (!guid || !guid[0]) return true;
        for (int i = 0; i < nopt; ++i)
            if (std::strcmp(opts[i].guid, guid) == 0) return true;
        return false;
    };
    auto push_opt = [&](const char* guid, const char* name, uint32_t id,
                        bool live) {
        if (!guid || !guid[0] || already(guid) || nopt >= kMaxOpts) return;
        std::snprintf(opts[nopt].guid, sizeof(opts[nopt].guid), "%s", guid);
        const char* nm = (name && name[0] && std::strcmp(name, "Gamepad") != 0)
                             ? name : "Controller";
        std::snprintf(opts[nopt].name, sizeof(opts[nopt].name), "%s", nm);
        opts[nopt].id = id;
        opts[nopt].live = live;
        ++nopt;
    };

    if (psx) {
        const int known = launcher_binds_psx_known_count();
        for (int i = 0; i < known; ++i) {
            char guid[40] = {}, name[64] = {};
            if (!launcher_binds_psx_known_at(i, guid, (int)sizeof(guid),
                                             name, (int)sizeof(name)))
                continue;
            uint32_t id = 0;
            bool live = false;
            const bool custom = launcher_binds_psx_name_is_custom(guid) != 0;
            for (int j = 0; j < g_pad_count; ++j) {
                if (g_pads[j].guid[0] &&
                    std::strcmp(g_pads[j].guid, guid) == 0) {
                    live = true;
                    id = g_pads[j].id;
                    // Custom rename wins; otherwise prefer the live driver name.
                    if (!custom && g_pads[j].name[0] &&
                        std::strcmp(g_pads[j].name, "Gamepad") != 0)
                        std::snprintf(name, sizeof(name), "%s", g_pads[j].name);
                    break;
                }
            }
            push_opt(guid, name, id, live);
        }
        // Settings-restored GUID that isn't in the registry yet.
        if (m->s.player_src[p] == 2 && m->s.player_gamepad_guid[p][0]) {
            bool live = false;
            uint32_t id = m->player_pad_id[p];
            for (int j = 0; j < g_pad_count; ++j) {
                if (g_pads[j].guid[0] &&
                    std::strcmp(g_pads[j].guid,
                                m->s.player_gamepad_guid[p]) == 0) {
                    live = true;
                    id = g_pads[j].id;
                    break;
                }
            }
            push_opt(m->s.player_gamepad_guid[p], m->player_pad_name[p], id,
                     live);
        }
    }

    for (int i = 0; i < g_pad_count; ++i)
        push_opt(g_pads[i].guid, g_pads[i].name, g_pads[i].id, true);

    const int claim_n = launcher_model_visible_player_count(m);
    for (int i = 0; i < nopt; ++i) {
        bool claimed = false;
        for (int o = 0; o < claim_n; ++o) {
            if (o == p) continue;
            if (m->s.player_src[o] == 2 && m->s.player_gamepad_guid[o][0] &&
                std::strcmp(m->s.player_gamepad_guid[o], opts[i].guid) == 0) {
                claimed = true;
                break;
            }
        }
        char label[96];
        if (opts[i].live)
            std::snprintf(label, sizeof(label), "%s", opts[i].name);
        else
            std::snprintf(label, sizeof(label), "%s (disconnected)",
                          opts[i].name);
        const bool sel = m->s.player_src[p] == 2 &&
                         m->s.player_gamepad_guid[p][0] &&
                         std::strcmp(m->s.player_gamepad_guid[p],
                                     opts[i].guid) == 0;
        if (claimed) ImGui::BeginDisabled();
        if (ImGui::Selectable(label, sel) && !claimed) {
            launcher_model_set_source(m, p, 2, opts[i].id, opts[i].name,
                                     opts[i].guid);
            if (psx) {
                launcher_binds_apply_psx_pad_profile(m, p);
                launcher_binds_refresh(m);
            }
        }
        if (claimed) ImGui::EndDisabled();
    }

    if (nopt == 0) {
        ImGui::BeginDisabled();
        ImGui::Selectable("(no gamepad connected)");
        ImGui::EndDisabled();
    }
}

/* Best-effort local lobby seat (0-based) for the NETPLAY pad card label.
 * Prefers fill_launch.local_slot, else display_name match, else host→0.
 * Label only — runtime netplay always samples dashboard card 0. */
static int np_guess_local_seat(const LauncherModel* m) {
    if (!m || !m->netplay_supported) return 0;
    const auto* np = m->netplay;
    if (!np || !np->ctx) return 0;
    if (np->fill_launch) {
        RecompLauncherCNetplayLaunch launch{};
        if (np->fill_launch(np->ctx, &launch) && launch.enabled &&
            launch.local_slot >= 0)
            return launch.local_slot;
    }
    const char* me = m->s.netplay_player_name;
    if ((!me || !me[0]) && np->player_name)
        me = np->player_name(np->ctx);
    if (np->member_count && np->member_get && me && me[0]) {
        const int n = np->member_count(np->ctx);
        for (int i = 0; i < n; ++i) {
            RecompLauncherCNetplayMember mem{};
            if (!np->member_get(np->ctx, i, &mem)) continue;
            if (mem.display_name[0] && std::strcmp(mem.display_name, me) == 0)
                return mem.slot >= 0 ? mem.slot : i;
        }
    }
    if (np->is_host && np->is_host(np->ctx)) return 0;
    return 0;
}

void draw_player_panel(LauncherModel* m, const LauncherTheme& th, int p, float w) {
    char id[24];  snprintf(id, sizeof(id), "player%d", p);
    char eb[40];
    if (p == 0 && m->netplay_supported) {
        const int seat = np_guess_local_seat(m);
        snprintf(eb, sizeof(eb), "PLAYER %d / NETPLAY", seat + 1);
    } else {
        snprintf(eb, sizeof(eb), "PLAYER %d", p + 1);
    }

    if (!begin_panel(id, w, false)) { end_panel(); return; }
    ImGui::PushID(p);
    eyebrow(eb);

    const float inner = ImGui::GetContentRegionAvail().x;
    const float cw    = inner;   // controls span the card => flush by construction

    // pad art centered in the card: PSX-style games swap analog/digital art
    // with the mode; consoles without a mode-swap art PAIR (SNES, and Genesis —
    // which has pad modes but a SINGLE pad image) always show the generic
    // g_pad. The swap only happens when the profile actually ships the pair.
    {
        const SystemProfile* aprof = (const SystemProfile*)m->profile;
        const bool has_swap_art = aprof && aprof->controller.image_analog != nullptr;
        // Show the digital pad ONLY for a game LOCKED to D-Pad mode. pad_mode
        // selects which controller PROTOCOL the game is given, not which
        // hardware the player is holding: on a title that offers analog at all,
        // the player has an analog-capable pad in hand, and picking D-Pad mode
        // does not turn their DualShock into a 1994 digital controller. Keying
        // the art off the mode made Ape Escape — a dual-analog game — show the
        // original PSX pad whenever the saved mode happened to be digital.
        const bool digital_only = !m->pad_mode_selectable && m->locked_pad_mode == 2;
        const bool digital = has_swap_art && digital_only;
        const LauncherTexture& art = has_swap_art
            ? (digital ? g_pad_digital : g_pad_analog) : g_pad;
        // Center on the FITTED width so a near-square pad (N64) or a portrait
        // handheld (GB/GBC) sits centered, not left-shifted by the landscape
        // box's spare width.
        image_fit_centered(art, 120, 78, inner);
    }
    ImGui::Dummy(ImVec2(0, px(6)));

    // Pad-mode selector: only when the game supports pad modes AND the mode
    // is user-selectable (not locked to a single mode).
    if (m->pad_mode_supported && m->pad_mode_selectable) {
        pad_mode_selector(m, th, p, cw);
        ImGui::Dummy(ImVec2(0, px(6)));
    }

    ImGui::SetNextItemWidth(cw);
    if (ImGui::BeginCombo("##src", launcher_model_player_src_label(m, p))) {
        draw_source_selectables(m, p);
        ImGui::EndCombo();
    }
    ImGui::Dummy(ImVec2(0, px(4)));
    // Configure + connection status share ONE half/half row (Configure left,
    // status right) so the card stays short — that keeps the memory cards below
    // it from being pushed off the bottom. (Analog-stick deadzone lives on the
    // Configure page's per-player Deadzone stepper, not on this card.)
    {
        const float gap  = px(th.spacing_sm);
        const float half = (cw - gap) * 0.5f;
        const float btnh = px(32);
        if (ImGui::Button("Configure", ImVec2(half, btnh))) launcher_model_open_config(m, p);
        ImGui::SameLine(0, gap);
        const bool on = m->s.player_src[p] != 0;
        const char* st = on ? "connected" : "not assigned";
        const float sw = px(10) + px(8) + ImGui::CalcTextSize(st).x;
        // center the dot+label within the right half, vertically on the button
        ImGui::SetCursorPosX(ImGui::GetCursorPosX() + (half - sw) * 0.5f);
        ImGui::SetCursorPosY(ImGui::GetCursorPosY() + (btnh - ImGui::GetTextLineHeight()) * 0.5f);
        draw_dot(on, th.good, th.text_muted);
        ImGui::TextColored(on ? col(th.good) : col(th.text_muted), "%s", st);
    }
    ImGui::PopID();
    end_panel();
}

// Lays out player cards: stretch to fill the row until there is room for
// another card at the standard width, then bump the column count (memcards
// stay fixed-width via dash_card_width).
void draw_controllers_row(LauncherModel* m, const LauncherTheme& th) {
    if (m->lock_device) return;   // fixed pad: hide the player controller cards entirely
    int n = launcher_model_visible_player_count(m);
    if (n < 1) n = 1;
    if (n > LNG_MAX_PLAYERS) n = LNG_MAX_PLAYERS;
    const float gap = px(th.spacing_md);
    const float availw = ImGui::GetContentRegionAvail().x;
    const float pref = px(300.0f);
    int cols = (int)((availw + gap) / (pref + gap));
    if (cols < 1) cols = 1;
    if (cols > n) cols = n;
    float cardw = (availw - gap * (float)(cols - 1)) / (float)cols;
    if (cardw < 1.0f) cardw = availw;
    for (int p = 0; p < n; ++p) {
        if (p % cols) ImGui::SameLine(0, gap);
        else if (p) ImGui::Dummy(ImVec2(0, gap));   // new row of cards
        char cid[16];
        std::snprintf(cid, sizeof(cid), "pc%d", p);
        begin_container(cid, ImVec2(cardw, 0), ImGuiChildFlags_AutoResizeY);
        draw_player_panel(m, th, p, cardw);
        end_container();
    }
}

void panel_controller_draw(LauncherModel* m, const LauncherTheme* th) {
    draw_controllers_row(m, *th);
}

// The dashboard COMPOSES whichever panels this game's SystemProfile lists in
// panels_dashboard — it does not hardcode a fixed set. GAME is always
// present; the side column stacks CONTROLLERS plus any optional modules
// (SAVES only when the game has SRAM, folded into the GAME card — see
// draw_save_row). A different system's profile simply contributes a
// different panel list.
void draw_dashboard(LauncherModel* m, const LauncherTheme& th, int logical_w) {
    const SystemProfile* prof = (const SystemProfile*)m->profile;
    const LauncherPanel* game_p = find_composed(prof->panels_dashboard, "game", m);
    const LauncherPanel* ctrl_p = find_composed(prof->panels_dashboard, "controller", m);
    const LauncherPanel* save_p = find_composed(prof->panels_dashboard, "save", m);
    const LauncherPanel* tpak_p = find_composed(prof->panels_dashboard, "tpak", m);

    if (logical_w >= 820) {
        const float gap = px(th.spacing_md);
        // When a WIDE panel (save/tpak) follows this row, the columns must hug
        // their own content (AutoResizeY) instead of stretching to fill the
        // whole scrollable "body" — otherwise there's never any room left
        // below them and the WIDE panel silently draws off the bottom edge.
        // SNES's composition never lists "save" here (save_p == nullptr), so
        // it keeps the original fill-to-height columns byte-identical.
        const bool has_save = (save_p != nullptr);
        const bool has_tpak = (tpak_p != nullptr);
        if (has_save) {
            // Capture body height before the row so multitap can grow the right
            // column to the footer.
            const float row_h = ImGui::GetContentRegionAvail().y;
            // 2P: AutoResizeY the right column so hug-height memcards (with
            // even Browse/New pad) are never clipped by a boxart-height cap.
            // Multitap (3+): fill to footer and scroll controllers when they
            // would crush the save band.
            const bool many_players = launcher_model_visible_player_count(m) > 2;
            if (game_p) {
                g_game_fill_h = false;
                begin_container("dash_l", ImVec2(px(400), 0), ImGuiChildFlags_AutoResizeY);
                game_p->draw(m, &th);
                end_container();
            }
            if (game_p && ctrl_p) ImGui::SameLine(0, gap);
            if (ctrl_p) {
                if (many_players) {
                    const float right_h = row_h > px(80.0f) ? row_h : px(80.0f);
                    begin_container("dash_r", ImVec2(0, right_h),
                                    ImGuiChildFlags_None, ImGuiWindowFlags_NoScrollbar);
                    // Tall enough for a clean fill-height memcard pair (icon,
                    // grid, Browse/New with padding) while controllers scroll
                    // in the space above.
                    const float save_reserve = save_p ? px(300.0f) : 0.0f;
                    float ctrl_h = ImGui::GetContentRegionAvail().y
                                   - save_reserve - (save_p ? gap : 0.0f);
                    if (ctrl_h < px(100.0f)) ctrl_h = px(100.0f);
                    begin_container("dash_ctrl", ImVec2(0, ctrl_h));
                        ctrl_p->draw(m, &th);
                    end_container();
                    if (save_p) {
                        ImGui::Dummy(ImVec2(0, gap));
                        g_save_fill_h = true;
                        save_p->draw(m, &th);
                        g_save_fill_h = false;
                    }
                    end_container();
                } else {
                    begin_container("dash_r", ImVec2(0, 0), ImGuiChildFlags_AutoResizeY);
                    ctrl_p->draw(m, &th);
                    if (save_p) {
                        ImGui::Dummy(ImVec2(0, gap));
                        save_p->draw(m, &th);
                    }
                    end_container();
                }
            }
        } else if (has_tpak) {
            // N64: no SRAM save panel, but a FULL-WIDTH Transfer Pak row follows
            // below. Both columns must hug their own content (AutoResizeY) so
            // there's room left underneath for that row — otherwise the tpak row
            // draws off the bottom edge.
            if (game_p) {
                g_game_fill_h = false;
                begin_container("dash_l", ImVec2(px(400), 0), ImGuiChildFlags_AutoResizeY);
                game_p->draw(m, &th);
                end_container();
            }
            if (game_p && ctrl_p) ImGui::SameLine(0, gap);
            if (ctrl_p) {
                begin_container("dash_r", ImVec2(0, 0), ImGuiChildFlags_AutoResizeY);
                    ctrl_p->draw(m, &th);
                end_container();
            }
        } else {
            // No WIDE save panel (SNES): original fill-to-height columns,
            // byte-identical.
            if (game_p) {
                g_game_fill_h = true;
                begin_container("dash_l", ImVec2(px(400), 0), ImGuiChildFlags_None);
                game_p->draw(m, &th);
                end_container();
            }
            if (game_p && ctrl_p) ImGui::SameLine(0, gap);
            if (ctrl_p) {
                begin_container("dash_r", ImVec2(0, 0), ImGuiChildFlags_None);
                    ctrl_p->draw(m, &th);
                end_container();
            }
        }
        // Transfer Pak: a genuinely FULL-WIDTH row under both columns — four
        // per-port cards need the whole window, not the side column.
        if (tpak_p) {
            ImGui::Dummy(ImVec2(0, gap));
            tpak_p->draw(m, &th);
        }
    } else {
        if (game_p) { g_game_fill_h = false; game_p->draw(m, &th); }
        if (game_p && ctrl_p) ImGui::Spacing();
        if (ctrl_p) ctrl_p->draw(m, &th);
        // Narrow single-column layout: memcards stack under the controller.
        if (save_p) { ImGui::Spacing(); save_p->draw(m, &th); }
        if (tpak_p) { ImGui::Spacing(); tpak_p->draw(m, &th); }
    }
}

// Trim a path from the LEFT to fit max_w, prefixing "…" so the meaningful tail
// stays visible (e.g. "…\build\bin-x64-Release\msu"). Same idea as the old hash
// ellipsis.
static const char* elide_left(const char* s, float max_w, char* out, size_t cap) {
    if (ImGui::CalcTextSize(s).x <= max_w) { snprintf(out, cap, "%s", s); return out; }
    size_t n = strlen(s);
    for (size_t start = 1; start < n; ++start) {
        char tmp[320];
        snprintf(tmp, sizeof(tmp), "\xE2\x80\xA6%s", s + start);   // "…" + tail
        if (ImGui::CalcTextSize(tmp).x <= max_w) { snprintf(out, cap, "%s", tmp); return out; }
    }
    snprintf(out, cap, "\xE2\x80\xA6");
    return out;
}

// True when this game exposes ANY of the deeper PSX-style DISPLAY controls.
// SNES (and any console leaving every has_* flag 0) takes the legacy-only
// branch below and gets the fixed-band DISPLAY card. Fullscreen is NOT part
// of this predicate: it is a universal row drawn on BOTH branches (the ABI's
// has_fullscreen_toggle no longer gates anything — see recomp_launcher.h).
bool any_deep_display(const LauncherModel* m) {
    return m->has_window_size || m->has_renderer || m->has_supersampling ||
           m->has_antialiasing || m->has_texture_filter || m->has_screen_kind ||
           m->has_frame_interp || m->has_skip_fmv ||
           m->has_geometry_precision;   /* has_turbo_loads draws no row — see below */
}

// Whether the DISPLAY card should grow to fit its content (AutoResizeY) rather
// than sit at the legacy fixed band height. True for the deep PSX surface, and
// also for a console that renders the extra widescreen-cells row (Genesis) once
// widescreen is on — that row is a 4th line the 3-row fixed height would clip.
// Gated exactly like the row itself so the SNES legacy surface stays pinned to
// the fixed height (byte-identical to before this console existed).
bool video_card_grows(const LauncherModel* m) {
    if (any_deep_display(m)) return true;
    if (m->adaptive_view_supported) return true;
    if (m->has_sharp_filter || m->has_affine_filter) return true;
    if (m->num_display_layouts > 0) return true;
    // NES legacy-surface additions (Integer scaling row, HD texture pack block)
    // add extra rows the fixed no_scroll band wasn't sized for.
    if (m->has_integer_scale || m->hdpack_supported) return true;
    const SystemProfile* prof = (const SystemProfile*)m->profile;
    return prof && prof->video.widescreen_cells &&
           m->widescreen_supported && m->s.widescreen != 0;
}

// Inline amber "EXPERIMENTAL" tag, drawn on the same row right after a control
// whose feature is not yet production-ready. Currently every SNES 16:9
// widescreen path is experimental (per-game rendering still maturing), so the
// widescreen checkbox always carries this marker. Uses the same th.warn amber
// as the other cautionary labels (e.g. the MSU-1 notice).
static void experimental_tag(const LauncherTheme& th) {
    ImGui::SameLine(0, px(8));
    ImGui::TextColored(col(th.warn), "EXPERIMENTAL");
}

void draw_display_controls(LauncherModel* m, const LauncherTheme& th) {
    eyebrow("DISPLAY");

    if (!any_deep_display(m)) {
        // ---- legacy minimal surface (SNES/NES etc.) — aligned label grid -------
        float cw = ImGui::CalcTextSize("Linear filtering").x;
        if (m->has_sharp_filter) {
            float t = ImGui::CalcTextSize("Scaling filter").x;
            if (t > cw) cw = t;
        }
        if (m->has_affine_filter) {
            float t = ImGui::CalcTextSize("Affine background smoothing").x;
            if (t > cw) cw = t;
        }
        { float t = ImGui::CalcTextSize("View mode").x; if (t > cw) cw = t; }
        if (m->has_integer_scale) { float t = ImGui::CalcTextSize("Integer scaling").x; if (t > cw) cw = t; }
        cw += px(18.0f);
        row_label("Window scale", th, cw);
        ImGui::PushID("window_scale");
        if (ImGui::Button(launcher_model_scale_label(m), ImVec2(px(120), px(30))))
            launcher_model_cycle_scale(m);
        ImGui::PopID();
        // Universal fullscreen row (every console; tri-state cycle restoring
        // the legacy launcher's Off/Borderless/Exclusive vocabulary). Sits
        // right under Window scale, matching the old Display panel order.
        row_label("Fullscreen", th, cw);
        ImGui::PushID("fullscreen");
        if (ImGui::Button(launcher_model_fullscreen_label(m), ImVec2(px(120), px(30))))
            launcher_model_cycle_fullscreen(m);
        ImGui::PopID();
        if (m->num_display_layouts > 0) {
            row_label("Screen layout", th, cw);
            ImGui::PushID("screen_layout");
            if (ImGui::Button(launcher_model_display_layout_label(m),
                              ImVec2(px(180), px(30))))
                launcher_model_cycle_display_layout(m);
            ImGui::PopID();
        }
        if (m->has_integer_scale) {   // NES module: snap the image to integer multiples
            row_label("Integer scaling", th, cw);
            bool is = m->s.integer_scale != 0;
            if (ImGui::Checkbox("##intscale", &is)) launcher_model_toggle_integer_scale(m);
        }
        if (m->has_sharp_filter) {
            row_label("Scaling filter", th, cw);
            if (ImGui::Button(launcher_model_scaling_filter_label(m),
                              ImVec2(px(180), px(30))))
                launcher_model_cycle_scaling_filter(m);
        } else {
            row_label("Linear filtering", th, cw);
            bool filter = m->s.linear_filter != 0;
            if (ImGui::Checkbox("##filter", &filter))
                launcher_model_toggle_filter(m);
        }
        if (m->has_affine_filter) {
            row_label("Affine background smoothing", th, cw);
            bool affine = m->s.affine_filter != 0;
            if (ImGui::Checkbox("##affine_filter", &affine))
                launcher_model_toggle_affine_filter(m);
        }
        if (m->aspect_mask || m->num_aspect_labels > 0 ||
            m->widescreen_supported || m->adaptive_view_supported) {
            row_label(m->aspect_setting_label ? m->aspect_setting_label : "View mode",
                      th, cw);
            if (ImGui::Button(launcher_model_view_mode_label(m),
                              ImVec2(px(180), px(30)))) {
                launcher_model_cycle_view_mode(m);
            }
            if (m->aspect_setting_help && ImGui::IsItemHovered())
                ImGui::SetTooltip("%s", m->aspect_setting_help);
            if (!m->aspect_labels || m->aspect_experimental)
                experimental_tag(th);
            // Genesis-style "extra cells per side" stepper: only when the
            // console opts in (video.widescreen_cells) AND widescreen is on.
            const SystemProfile* wprof = (const SystemProfile*)m->profile;
            if (wprof && wprof->video.widescreen_cells &&
                m->s.widescreen != 0 && !m->s.adaptive_view) {
                row_label("Extra cells / side", th, cw);
                int d = 0; ws_cells_stepper("wscells", m, &d);
                if (d) launcher_model_ws_cells_delta(m, d);
            }
        }
        // HD texture packs (NES module, Mesen hires.txt format): one line —
        //   [x] HD texture pack   …folder tail   [Browse]
        // Mirrors the MSU-1 row in Audio (same enable + folder pattern).
        if (m->hdpack_supported) {
            bool on = m->s.hdpack_enabled != 0;
            if (ImGui::Checkbox("HD texture pack", &on))
                launcher_model_toggle_hdpack(m);
            const float bw = px(78);
            ImGui::SameLine(0, px(14));
            float avail = ImGui::GetContentRegionAvail().x - bw - px(th.spacing_sm);
            if (avail < px(50)) avail = px(50);
            const char* dir = m->s.hdpack_dir[0] ? m->s.hdpack_dir : "(not set)";
            char elided[192]; elide_left(dir, avail, elided, sizeof(elided));
            ImGui::AlignTextToFramePadding();
            ImGui::TextColored(col(th.text_muted), "%s", elided);
            ImGui::SameLine(ImGui::GetCursorPosX() + ImGui::GetContentRegionAvail().x - bw);
            if (ImGui::Button("Browse", ImVec2(bw, px(30)))) {
                char buf[512];
                if (launcher_pick_folder("Select HD pack folder (contains hires.txt)", buf, sizeof(buf)))
                    launcher_model_set_hdpack_dir(m, buf);
            }
        }
        return;
    }

    // ---- deeper PSX-style surface, capability-gated per control -----------
    // Order matches the original PSX launcher: Window size, Renderer,
    // Supersampling, Aspect ratio, Texture filtering, Antialiasing, Screen
    // model, Frame interpolation (+Presentation target), Skip FMVs, Turbo
    // loads, Fullscreen.
    if (m->has_window_size) {
        row_label("Window size", th);
        if (ImGui::Button(launcher_model_window_size_label(m), ImVec2(px(150), px(30))))
            launcher_model_cycle_window_size(m);
    } else {
        row_label("Window scale", th);
        ImGui::PushID("window_scale");
        if (ImGui::Button(launcher_model_scale_label(m), ImVec2(px(120), px(30))))
            launcher_model_cycle_scale(m);
        ImGui::PopID();
    }

    // NES module rows can appear on this branch too (has_renderer puts NES
    // on the deep surface): integer scaling right under the window row,
    // mirroring the legacy branch's ordering.
    if (m->has_integer_scale) {
        row_label("Integer scaling", th);
        bool is = m->s.integer_scale != 0;
        if (ImGui::Checkbox("##intscale", &is)) launcher_model_toggle_integer_scale(m);
    }

    if (m->has_renderer) {
        row_label("Renderer", th);
        if (ImGui::Button(launcher_model_renderer_label(m), ImVec2(px(220), px(30))))
            launcher_model_toggle_renderer(m);
    }

    if (m->has_supersampling) {
        row_label("Supersampling", th);
        ImGui::PushID("supersampling");
        if (ImGui::Button(launcher_model_supersampling_label(m), ImVec2(px(120), px(30))))
            launcher_model_cycle_supersampling(m);
        ImGui::PopID();
        if (ImGui::IsItemHovered(ImGuiHoveredFlags_DelayNormal)) {
            ImGui::SetTooltip(
                "Internal-resolution SSAA.\n"
                "Offline: full software/GL supersampling.\n"
                "Netplay (OpenGL): present quality via GPU FBO;\n"
                "CPU VRAM authority stays at 1x for snaps/digests.");
        }
    }

    // Universal fullscreen row (every console — no longer gated on the
    // vestigial has_fullscreen_toggle). Tri-state cycle replaces the old
    // binary checkbox so Exclusive mode is reachable again.
    row_label("Fullscreen", th);
    ImGui::PushID("fullscreen");
    if (ImGui::Button(launcher_model_fullscreen_label(m), ImVec2(px(120), px(30))))
        launcher_model_cycle_fullscreen(m);
    ImGui::PopID();
    if (m->num_display_layouts > 0) {
        row_label("Screen layout", th);
        ImGui::PushID("screen_layout");
        if (ImGui::Button(launcher_model_display_layout_label(m),
                          ImVec2(px(180), px(30))))
            launcher_model_cycle_display_layout(m);
        ImGui::PopID();
    }

    if (m->aspect_mask || m->num_aspect_labels > 0 ||
        m->widescreen_supported || m->adaptive_view_supported) {
        row_label(m->aspect_setting_label ? m->aspect_setting_label : "View mode", th);
        if (ImGui::Button(launcher_model_view_mode_label(m),
                          ImVec2(px(180), px(30)))) {
            launcher_model_cycle_view_mode(m);
        }
        if (m->aspect_setting_help && ImGui::IsItemHovered())
            ImGui::SetTooltip("%s", m->aspect_setting_help);
        if (!m->aspect_labels || m->aspect_experimental)
            experimental_tag(th);
    }

    if (m->has_sharp_filter) {
        row_label("Scaling filter", th);
        if (ImGui::Button(launcher_model_scaling_filter_label(m),
                          ImVec2(px(180), px(30))))
            launcher_model_cycle_scaling_filter(m);
    } else if (m->has_texture_filter) {
        row_label("Texture filtering", th);
        if (ImGui::Button(launcher_model_texture_filter_label(m), ImVec2(px(120), px(30))))
            launcher_model_toggle_texture_filter(m);
    } else {
        row_label("Linear filtering", th);
        bool filter = m->s.linear_filter != 0;
        if (ImGui::Checkbox("##filter", &filter)) launcher_model_toggle_filter(m);
    }

    if (m->has_antialiasing) {
        row_label("Antialiasing", th);
        ImGui::PushID("antialiasing");
        if (ImGui::Button(launcher_model_aa_label(m), ImVec2(px(90), px(30))))
            launcher_model_cycle_aa(m);
        ImGui::PopID();
    }

    if (m->has_affine_filter) {
        row_label("Affine background smoothing", th);
        bool affine = m->s.affine_filter != 0;
        if (ImGui::Checkbox("##affine_filter", &affine))
            launcher_model_toggle_affine_filter(m);
    }

    if (m->has_geometry_precision) {
        // Geometry correction deliberately draws NO row. It moves vertices, and
        // the runtime can only recover the sub-pixel original for ~5% of them
        // (93% of lookups are ambiguous), so a corrected triangle meets an
        // uncorrected neighbour and their shared edge splits open. Measured on
        // Ape Escape; see psxrecomp ENHANCEMENTS.md G1.8/G1.9. The setting stays
        // in the ABI and remains readable from game.toml/settings.toml so the
        // work is still testable, exactly as has_turbo_loads/Settings.turbo_loads
        // stayed after their row was dropped — it simply has no control.
        //
        // Perspective textures are unaffected by that problem: they only change
        // UV interpolation inside a polygon whose provenance is already proven,
        // so no vertex moves and adjacent polygons cannot disagree about an edge.
        row_label("Perspective textures", th);
        bool persp = m->s.perspective_texturing != 0;
        if (ImGui::Checkbox("##persptex", &persp))
            launcher_model_toggle_perspective_texturing(m);
        if (ImGui::IsItemHovered())
            ImGui::SetTooltip("Interpolates textures with perspective, which "
                              "stops large floors and walls from warping as the "
                              "camera moves.\n\nApplied only to polygons the "
                              "runtime can prove came from the 3D pipeline, so "
                              "2D art and menus are left alone.");
    }

    if (m->has_screen_kind) {
        row_label("Screen model", th);
        // Wide enough for the longest label ("Super Game Boy (No Border)");
        // shorter models (e.g. "DMG") center within the same fixed box.
        if (ImGui::Button(launcher_model_screen_kind_label(m), ImVec2(px(220), px(30))))
            launcher_model_cycle_screen_kind(m);
    }

    // Frame interpolation is only meaningful under OpenGL (Software has no
    // interpolation pass); Presentation target only matters once frame
    // interpolation is actually on.
    if (m->has_frame_interp && m->s.renderer) {
        row_label("Frame interpolation", th);
        bool fi = m->s.frame_interp != 0;
        if (ImGui::Checkbox("##fi", &fi)) launcher_model_toggle_frame_interp(m);
        if (m->s.frame_interp) {
            row_label("Presentation target", th);
            if (ImGui::Button(launcher_model_interp_fps_label(m), ImVec2(px(150), px(30))))
                launcher_model_cycle_interp_fps(m);
        }
    }

    if (m->has_skip_fmv) {
        row_label("Skip FMVs", th);
        bool sk = m->s.auto_skip_fmv != 0;
        if (ImGui::Checkbox("##skipfmv", &sk)) launcher_model_toggle_skip_fmv(m);
    }

    /* Turbo loads is deliberately NOT a Display row on any console. Load
     * acceleration is owned by the framework's Mods catalog (Fast Loading /
     * CD Speed), which exposes the multiplier, the instant scheduler and the
     * distinction between host pacing and drive speed. A single opaque
     * checkbox here duplicated that at lower fidelity and let the two
     * surfaces disagree. The has_turbo_loads capability and
     * Settings.turbo_loads remain in the ABI for hosts that still persist the
     * value; they simply no longer draw a control. */

    // HD texture packs (NES module) — same enable + folder row as the legacy
    // branch renders; kept last, below the console-shape rows.
    if (m->hdpack_supported) {
        bool on = m->s.hdpack_enabled != 0;
        if (ImGui::Checkbox("HD texture pack", &on))
            launcher_model_toggle_hdpack(m);
        const float bw = px(78);
        ImGui::SameLine(0, px(14));
        float avail = ImGui::GetContentRegionAvail().x - bw - px(th.spacing_sm);
        if (avail < px(50)) avail = px(50);
        const char* dir = m->s.hdpack_dir[0] ? m->s.hdpack_dir : "(not set)";
        char elided[192]; elide_left(dir, avail, elided, sizeof(elided));
        ImGui::AlignTextToFramePadding();
        ImGui::TextColored(col(th.text_muted), "%s", elided);
        ImGui::SameLine(ImGui::GetCursorPosX() + ImGui::GetContentRegionAvail().x - bw);
        if (ImGui::Button("Browse", ImVec2(bw, px(30)))) {
            char buf[512];
            if (launcher_pick_folder("Select HD pack folder (contains hires.txt)", buf, sizeof(buf)))
                launcher_model_set_hdpack_dir(m, buf);
        }
    }
}

// Video/Display module (docs/ARCHITECTURE.md): base window-scale/fullscreen
// row set, specialized per system — SNES adds linear-filter + widescreen,
// PSX adds the full deep surface (window size/renderer/supersampling/aspect/
// texture-filter/AA/screen-model/frame-interp/skip-fmv/turbo/fullscreen).
// draw_display_controls() gates each row on the model's has_* caps (sourced
// from the ABI, unchanged); this adapter supplies the card chrome, choosing
// AutoResizeY (deep surface, more rows than the fixed band fits) vs a fixed
// row_h band with no_scroll (legacy minimal surface) — exactly the sizing
// draw_settings used to pick inline, now co-located with its own content.
void panel_video_draw(LauncherModel* m, const LauncherTheme* th) {
    // video_card_grows() folds in NES's legacy-surface additions (Integer
    // scaling row, HD texture pack block) alongside the deep/widescreen surfaces.
    if (video_card_grows(m)) {
        if (begin_panel("disp", 0, false)) draw_display_controls(m, *th);
        end_panel();
    } else {
        if (begin_panel("disp", 0, true, /*no_scroll*/true)) draw_display_controls(m, *th);
        end_panel();
    }
}

void draw_audio_controls(LauncherModel* m, const LauncherTheme& th) {
    eyebrow("AUDIO");
    // Fixed label column so the sample-rate button, the volume stepper's "-",
    // and the SPU toggle all share the same left edge (aligned grid).
    float cw = ImGui::CalcTextSize("Sample rate").x;
    if (m->has_spu_hq) { float t = ImGui::CalcTextSize("High-quality SPU").x; if (t > cw) cw = t; }
    cw += px(18.0f);
    // Sample rate: hidden for consoles whose runtime has no audio-frequency
    // setting (SystemProfile.hide_audio_freq — NES has Volume only).
    const SystemProfile* audio_prof = (const SystemProfile*)m->profile;
    if (!audio_prof || !audio_prof->hide_audio_freq) {
        row_label("Sample rate", th, cw);
        if (ImGui::Button(launcher_model_freq_label(m), ImVec2(px(120), px(30))))
            launcher_model_cycle_freq(m);
    }
    row_label("Volume", th, cw);
    int dv = 0; stepper("vol", m->s.volume, "%", &dv);
    if (dv) launcher_model_volume_delta(m, dv);

    // Output-device pick (host-enumerated names; N64/RT64 hosts) — "(system
    // default)" first, committing "" so an unplugged device degrades sanely.
    if (m->num_audio_devices > 0 && m->audio_device_labels) {
        row_label("Output device", th, cw);
        ImGui::SetNextItemWidth(ImGui::GetContentRegionAvail().x);
        if (ImGui::BeginCombo("##audiodev", launcher_model_audio_device_label(m))) {
            if (ImGui::Selectable("(system default)", m->s.audio_device[0] == '\0'))
                launcher_model_set_audio_device(m, NULL);
            for (int i = 0; i < m->num_audio_devices; ++i) {
                const char* name = m->audio_device_labels[i];
                if (!name || !name[0]) continue;
                bool sel = strcmp(m->s.audio_device, name) == 0;
                if (ImGui::Selectable(name, sel))
                    launcher_model_set_audio_device(m, name);
            }
            ImGui::EndCombo();
        }
    }

    if (m->has_spu_hq) {
        row_label("High-quality SPU", th, cw);
        bool hq = m->s.spu_hq != 0;
        if (ImGui::Checkbox("##spuhq", &hq)) launcher_model_toggle_spu_hq(m);
    }

    // NOTE: analog deadzone is NOT here — it belongs to the input device, so it
    // lives on each controller card (draw_player_panel), gated on
    // has_deadzone_pct. Kept out of Audio deliberately.

    // MSU-1: no header/subsection — just one line under the rows above:
    //   [x] Enable MSU-1 music (?)   …folder tail     [Browse]
    if (m->msu1_supported) {
        bool on = m->s.msu1_enabled != 0;
        if (ImGui::Checkbox("Enable MSU-1 music", &on))
            launcher_model_toggle_msu1(m);
        if (m->msu1_note && m->msu1_note[0]) {
            ImGui::SameLine(0, px(6));
            ImGui::TextColored(col(th.accent), "(?)");
            if (ImGui::IsItemHovered()) {
                ImGui::BeginTooltip();
                ImGui::PushTextWrapPos(px(360));
                ImGui::TextUnformatted(m->msu1_note);
                ImGui::PopTextWrapPos();
                ImGui::EndTooltip();
            }
        }
        const float bw = px(78);
        ImGui::SameLine(0, px(14));
        float avail = ImGui::GetContentRegionAvail().x - bw - px(th.spacing_sm);
        if (avail < px(50)) avail = px(50);
        const char* dir = m->s.msu1_dir[0] ? m->s.msu1_dir : "(not set)";
        char elided[192]; elide_left(dir, avail, elided, sizeof(elided));
        ImGui::AlignTextToFramePadding();
        ImGui::TextColored(col(th.text_muted), "%s", elided);
        ImGui::SameLine(ImGui::GetCursorPosX() + ImGui::GetContentRegionAvail().x - bw);
        if (ImGui::Button("Browse", ImVec2(bw, px(30)))) {  // px(30) matches the other settings buttons + the row's frame height (px(28) sat the label high)
            char buf[512];
            if (launcher_pick_folder("Select MSU-1 music folder", buf, sizeof(buf)))
                launcher_model_set_msu1_dir(m, buf);
        }
    }

    // Localization: only games that declare a language list get this
    // mini-section (mirrors the real PSX launcher's Language cycle).
    if (m->num_languages > 0) {
        ImGui::Dummy(ImVec2(0, px(6)));
        eyebrow("LOCALIZATION");
        row_label("Language", th);
        if (ImGui::Button(launcher_model_language_label(m), ImVec2(px(140), px(30))))
            launcher_model_cycle_language(m);
    }
}

// Audio module adapter — same AutoResizeY-vs-fixed-row_h sizing pattern as
// panel_video_draw, decided from the same "deep" predicate draw_settings used
// to compute inline.
void panel_audio_draw(LauncherModel* m, const LauncherTheme* th) {
    const bool deep_audio = m->has_spu_hq || m->num_languages > 0 || m->num_audio_devices > 0;   /* deadzone moved to controller card */
    if (deep_audio) {
        if (begin_panel("audio", 0, false)) draw_audio_controls(m, *th);
        end_panel();
    } else {
        if (begin_panel("audio", 0, true, /*no_scroll*/true)) draw_audio_controls(m, *th);
        end_panel();
    }
}

// INPUT module: multitap / pad-bus options — half-width card stacked under
// AUDIO and above SYSTEM in the right column (see draw_settings). Composed
// for PSX; shown when the title can use multitap seats or the analog hack.
int avail_input(const LauncherModel* m) {
    return launcher_model_multitap_available(m) ||
           launcher_model_multitap_analog_available(m);
}
void draw_input_controls(LauncherModel* m, const LauncherTheme& th) {
    eyebrow("INPUT");
    if (launcher_model_multitap_available(m)) {
        bool on = launcher_model_multitap_enabled(m) != 0;
        if (ImGui::Checkbox("Multitap", &on) &&
            (on ? 1 : 0) != launcher_model_multitap_enabled(m))
            launcher_model_toggle_multitap(m);
        if (ImGui::IsItemHovered(ImGuiHoveredFlags_DelayNormal)) {
            ImGui::BeginTooltip();
            ImGui::PushTextWrapPos(px(320));
            ImGui::TextUnformatted(
                "Enable SCPH-1070 multitap for 3+ player seats. "
                "Off limits Play Local to two native controller ports. "
                "Netplay lobbies with 3 or more players always use multitap.");
            ImGui::PopTextWrapPos();
            ImGui::EndTooltip();
        }
    }
    if (launcher_model_multitap_analog_available(m)) {
        if (launcher_model_multitap_available(m))
            ImGui::Dummy(ImVec2(0, px(th.spacing_sm)));
        bool on = launcher_model_multitap_analog_enabled(m) != 0;
        if (ImGui::Checkbox("Multitap analog (hack)", &on) &&
            (on ? 1 : 0) != launcher_model_multitap_analog_enabled(m))
            launcher_model_toggle_multitap_analog(m);
        if (ImGui::IsItemHovered(ImGuiHoveredFlags_DelayNormal)) {
            ImGui::BeginTooltip();
            ImGui::PushTextWrapPos(px(320));
            ImGui::TextUnformatted(
                "Allow DualShock sticks on multitap tap seats (not faithful — "
                "many titles expect digital taps). Saved to game.toml / "
                "settings. Netplay hosts can enforce this for the lobby.");
            ImGui::PopTextWrapPos();
            ImGui::EndTooltip();
        }
    }
}
void panel_input_draw(LauncherModel* m, const LauncherTheme* th) {
    if (begin_panel("input", 0)) draw_input_controls(m, *th);
    end_panel();
}

// SYSTEM module: BIOS path picker — a half-width card stacked under AUDIO in
// the right column (see draw_settings), composed only for systems whose
// profile lists "system" (PSX, GBA) AND only shown for a game instance that
// needs one (has_bios) — composition + availability, both layers, matching
// the architecture.
int avail_system(const LauncherModel* m) { return m->has_bios; }
void draw_system_controls(LauncherModel* m, const LauncherTheme& th) {
    eyebrow("SYSTEM");
    const SystemProfile* prof = (const SystemProfile*)m->profile;
    const bool is_gba = prof && prof->id && std::strcmp(prof->id, "gba") == 0;
    const bool is_psx = prof && prof->id && std::strcmp(prof->id, "psx") == 0;
    // Empty means "use the BIOS this build ships with" — not "unset". Runtimes
    // that bundle a redistributable BIOS (PSX/OpenBIOS, GBA) boot straight from
    // it, so the row states that outcome instead of the old "(default)", which
    // read as a missing setting the player still had to deal with.
    const bool has_pick = m->s.bios_path[0] != 0;
    ImGui::PushStyleVar(ImGuiStyleVar_FramePadding, ImVec2(px(14), px(8)));
    const float btn_h = px(34);
    const float browse_w = px(96);

    // Line 1: BIOS label + path + Browse
    row_label("BIOS", th);
    float avail = ImGui::GetContentRegionAvail().x - browse_w - px(th.spacing_sm);
    if (avail < px(50)) avail = px(50);
    const char* bp = has_pick ? m->s.bios_path
                              : (is_gba ? "Retail GBA BIOS required"
                                        : "OpenBIOS");
    char elided[192]; elide_left(bp, avail, elided, sizeof(elided));
    ImGui::AlignTextToFramePadding();
    ImGui::TextColored(col(has_pick ? th.text : th.text_muted), "%s", elided);
    ImGui::SameLine(ImGui::GetCursorPosX() + ImGui::GetContentRegionAvail().x -
                    browse_w);
    if (ImGui::Button("Browse", ImVec2(browse_w, btn_h))) {
        request_bios_picker(m,
                            is_gba ? "Select Game Boy Advance BIOS (gba_bios.bin)"
                                   : "Select BIOS file",
                            false);
    }

    // Line 2: secondary action under the path (PSX OpenBIOS / GBA Clear).
    if (is_psx || has_pick) {
        const float indent = ImGui::CalcTextSize("BIOS").x + px(th.spacing_md);
        ImGui::SetCursorPosX(ImGui::GetCursorPosX() + indent);
        if (is_psx) {
            if (!has_pick) ImGui::BeginDisabled();
            if (ImGui::Button("Use OpenBIOS", ImVec2(0, btn_h)))
                launcher_model_request_bios_path(m, "");
            if (!has_pick) ImGui::EndDisabled();
            if (ImGui::IsItemHovered(ImGuiHoveredFlags_AllowWhenDisabled))
                ImGui::SetTooltip(has_pick
                                      ? "Switch to bundled OpenBIOS (no rebuild)."
                                      : "OpenBIOS is already selected.");
        } else {
            if (ImGui::Button("Clear", ImVec2(0, btn_h)))
                launcher_model_request_bios_path(m, "");
            if (ImGui::IsItemHovered()) {
                if (is_gba)
                    ImGui::SetTooltip("Remove this selection. A retail GBA BIOS "
                                      "is required before the game can launch.");
                else
                    ImGui::SetTooltip("Stop using this BIOS and go back to the one "
                                      "included with this build.");
            }
        }
    }

    /* MotK codegen host: local PGO train under SYSTEM (no separate VIDEO card). */
    if (is_psx && m->pgo_optimize_with_progress_cb) {
        ImGui::Dummy(ImVec2(0, px(14)));
        ImGui::PushTextWrapPos(ImGui::GetCursorPosX() +
                               ImGui::GetContentRegionAvail().x);
        ImGui::TextColored(col(th.text_muted),
                           "Train this PC on the intro FMV, then rebuild with "
                           "profile-guided optimization. Safe for rollback "
                           "netplay — each peer may optimize independently.");
        ImGui::PopTextWrapPos();
        ImGui::Dummy(ImVec2(0, px(8)));
        const bool can_pgo = m->rom_present && m->rom_full[0] &&
                             strcmp(m->rom_size, "--") != 0 &&
                             !m->setup_preparing;
        if (!can_pgo) ImGui::BeginDisabled();
        if (ImGui::Button("Optimize FMV Playback", ImVec2(0, btn_h)))
            launcher_model_request_pgo_optimize(m);
        if (!can_pgo) {
            ImGui::EndDisabled();
            if (ImGui::IsItemHovered(ImGuiHoveredFlags_AllowWhenDisabled))
                ImGui::SetTooltip(m->setup_preparing
                                      ? "A build job is already running."
                                      : "Select a disc image first.");
        } else if (ImGui::IsItemHovered()) {
            ImGui::SetTooltip(
                "Instrument → play intro (~3 min) → rebuild with PGO. "
                "Uses existing generated C (no setup wizard).");
        }
    }
    ImGui::PopStyleVar();
}
void panel_system_draw(LauncherModel* m, const LauncherTheme* th) {
    if (begin_panel("system", 0)) draw_system_controls(m, *th);
    end_panel();
}

// SOLAR SENSOR module: a few GBA cartridges carry a photodiode the game reads
// as gameplay input (Boktai's Gun del Sol charges from real sunlight), so the
// player has to be able to say WHERE that brightness is measured. Composed only
// for a system whose profile lists "solar" AND a game that has the hardware.
//
// The postal code is edited behind an Edit/Save step, the same shape as the
// password-save row, so a half-typed code never reaches the host mid-keystroke
// and the row still shows the working value while editing is abandoned.
int avail_solar(const LauncherModel* m) { return m->has_solar_sensor; }

void draw_solar_controls(LauncherModel* m, const LauncherTheme& th) {
    eyebrow("SOLAR SENSOR");

    // Light source first: it decides whether the rest of the card is live.
    row_label("Light source", th);
    {
        const bool manual = m->s.solar_source != 0;
        const float bw = px(96);
        ImGui::SameLine(ImGui::GetCursorPosX() +
                        ImGui::GetContentRegionAvail().x - bw * 2 -
                        px(th.spacing_sm));
        if (ImGui::Button(manual ? "Live" : "Live ✓", ImVec2(bw, px(28))))
            launcher_model_set_solar_source(m, 0);
        if (ImGui::IsItemHovered())
            ImGui::SetTooltip("Read the current sunlight where you are.");
        ImGui::SameLine(0.0f, px(th.spacing_sm));
        if (ImGui::Button(manual ? "Fixed ✓" : "Fixed", ImVec2(bw, px(28))))
            launcher_model_set_solar_source(m, 1);
        if (ImGui::IsItemHovered())
            ImGui::SetTooltip("Hold a chosen level. Makes no network request.");
    }

    if (m->s.solar_source != 0) {
        // Fixed level: the location rows below would be inert, so offer the
        // level instead of greying out three rows the player cannot use.
        ImGui::Dummy(ImVec2(0, px(4)));
        row_label("Level", th);
        int step = m->s.solar_manual_step;
        const float sw = px(200);
        ImGui::SameLine(ImGui::GetCursorPosX() +
                        ImGui::GetContentRegionAvail().x - sw);
        ImGui::SetNextItemWidth(sw);
        if (ImGui::SliderInt("##solarlevel", &step, 0, 8, "%d / 8"))
            launcher_model_set_solar_manual_step(m, step);
        return;
    }

    ImGui::Dummy(ImVec2(0, px(4)));
    row_label("Postal code", th);
    {
        static bool s_zip_editing = false;
        static char s_zip_buf[16];
        const float bw = px(78);
        if (!s_zip_editing) {
            ImGui::AlignTextToFramePadding();
            const bool set = m->s.solar_zip[0] != 0;
            ImGui::TextColored(col(set ? th.text : th.text_muted), "%s",
                               set ? m->s.solar_zip : "(not set — sensor stays dark)");
            ImGui::SameLine(ImGui::GetCursorPosX() +
                            ImGui::GetContentRegionAvail().x - bw);
            if (ImGui::Button("Edit", ImVec2(bw, px(28)))) {
                snprintf(s_zip_buf, sizeof(s_zip_buf), "%s", m->s.solar_zip);
                s_zip_editing = true;
            }
        } else {
            float avail = ImGui::GetContentRegionAvail().x - bw * 2 -
                          px(th.spacing_sm) * 2;
            if (avail < px(80)) avail = px(80);
            ImGui::SetNextItemWidth(avail);
            const bool submitted =
                ImGui::InputText("##solarzip", s_zip_buf, sizeof(s_zip_buf),
                                 ImGuiInputTextFlags_EnterReturnsTrue);
            ImGui::SameLine(0, px(th.spacing_sm));
            if (submitted || ImGui::Button("Save", ImVec2(bw, px(28)))) {
                launcher_model_set_solar_zip(m, s_zip_buf);
                s_zip_editing = false;
            }
            ImGui::SameLine(0, px(th.spacing_sm));
            if (ImGui::Button("Cancel", ImVec2(bw, px(28))))
                s_zip_editing = false;
        }
    }

    ImGui::Dummy(ImVec2(0, px(4)));
    row_label("Country", th);
    {
        static bool s_cc_editing = false;
        static char s_cc_buf[8];
        const float bw = px(78);
        if (!s_cc_editing) {
            ImGui::AlignTextToFramePadding();
            const bool set = m->s.solar_country[0] != 0;
            ImGui::TextColored(col(set ? th.text : th.text_muted), "%s",
                               set ? m->s.solar_country : "us");
            ImGui::SameLine(ImGui::GetCursorPosX() +
                            ImGui::GetContentRegionAvail().x - bw);
            if (ImGui::Button("Edit##cc", ImVec2(bw, px(28)))) {
                snprintf(s_cc_buf, sizeof(s_cc_buf), "%s", m->s.solar_country);
                s_cc_editing = true;
            }
        } else {
            float avail = ImGui::GetContentRegionAvail().x - bw * 2 -
                          px(th.spacing_sm) * 2;
            if (avail < px(60)) avail = px(60);
            ImGui::SetNextItemWidth(avail);
            const bool submitted =
                ImGui::InputText("##solarcc", s_cc_buf, sizeof(s_cc_buf),
                                 ImGuiInputTextFlags_EnterReturnsTrue);
            ImGui::SameLine(0, px(th.spacing_sm));
            if (submitted || ImGui::Button("Save##cc", ImVec2(bw, px(28)))) {
                launcher_model_set_solar_country(m, s_cc_buf);
                s_cc_editing = false;
            }
            ImGui::SameLine(0, px(th.spacing_sm));
            if (ImGui::Button("Cancel##cc", ImVec2(bw, px(28))))
                s_cc_editing = false;
        }
    }

    ImGui::Dummy(ImVec2(0, px(4)));
    row_label("Full sun", th);
    {
        // Clear-sky midday is ~900 W/m^2 at mid latitudes but far less in
        // winter or at high latitude, where leaving this at 900 would mean the
        // gauge could never fill on a genuinely sunny day.
        int wm2 = m->s.solar_full_sun > 0 ? m->s.solar_full_sun : 900;
        const float sw = px(200);
        ImGui::SameLine(ImGui::GetCursorPosX() +
                        ImGui::GetContentRegionAvail().x - sw);
        ImGui::SetNextItemWidth(sw);
        if (ImGui::SliderInt("##solarfullsun", &wm2, 300, 1200, "%d W/m²"))
            launcher_model_set_solar_full_sun(m, wm2);
        if (ImGui::IsItemHovered())
            ImGui::SetTooltip("Irradiance that reads as a full gauge. Lower it "
                              "in winter or at high latitude.");
    }
}

void panel_solar_draw(LauncherModel* m, const LauncherTheme* th) {
    if (begin_panel("solar", 0)) draw_solar_controls(m, *th);
    end_panel();
}

// Hotkeys module: the universal emulator-hotkeys catalog, opt-in per system
// via SystemProfile.hotkeys_mask. SNES opts into LNG_HOTKEYS_ALL — the full
// catalog, grid byte-identical to the original hardcoded panel. PSX opts into
// a narrower everyday-transport subset (launcher_system.h), so its grid packs
// only the set bits — no holes, columns re-wrap around the smaller count.
void draw_hotkeys_controls(LauncherModel* m, const LauncherTheme& th) {
    eyebrow("HOTKEYS");
    const SystemProfile* prof = (const SystemProfile*)m->profile;
    uint32_t mask = prof ? prof->hotkeys_mask : LNG_HOTKEYS_ALL;
    // Solar controls are a per-cartridge capability, not part of the GBA-wide
    // catalog. They remain absent for every existing game and have no default
    // binding when the capability is enabled.
    if (m->has_solar_sensor) mask |= LNG_HOTKEYS_SOLAR;
    // Same responsive grid treatment as the bindings list.
    const float cell_w = px(280.0f);
    int cols = (int)(ImGui::GetContentRegionAvail().x / cell_w);
    cols = cols < 1 ? 1 : (cols > 3 ? 3 : cols);
    // Uniform label column: measure the widest bound hotkey name up front so
    // every bind button in the grid starts at the same x within its cell —
    // aligned left edges (and, since the buttons are fixed-width, aligned right
    // edges too), instead of hugging each variable-width label.
    float label_w = 0.0f;
    for (int h = 0; h < LNG_HK_COUNT; ++h) {
        if (!(mask & (1u << h))) continue;
        float w = ImGui::CalcTextSize(launcher_hotkey_name((LngHotkey)h)).x;
        if (w > label_w) label_w = w;
    }
    label_w += px(16.0f);   // gap between label and its bind button
    if (ImGui::BeginTable("hk", cols)) {
        for (int h = 0; h < LNG_HK_COUNT; ++h) {
            if (!(mask & (1u << h))) continue;
            ImGui::TableNextColumn();
            ImGui::PushID(h);
            const char* hkname = launcher_hotkey_name((LngHotkey)h);
            ImGui::AlignTextToFramePadding();
            ImGui::TextColored(col(th.text_muted), "%s", hkname);
            // Pad with RELATIVE spacing (not absolute x) so the bind button
            // starts at a uniform offset within every table cell — absolute
            // SameLine() fights ImGui's per-cell cursor tracking and spills
            // buttons into the wrong column.
            ImGui::SameLine(0.0f, label_w - ImGui::CalcTextSize(hkname).x);
            const bool cap = m->hk_capturing && m->capture_hk == (LngHotkey)h;
            const char* lbl = cap ? "[ press... ]"
                            : m->hotkeys[h][0] ? m->hotkeys[h] : "(unbound)";
            if (cap) ImGui::PushStyleColor(ImGuiCol_Button, col(th.accent));
            if (ImGui::Button(lbl, ImVec2(px(130), 0)))
                launcher_model_begin_hk_capture(m, (LngHotkey)h);
            if (cap) ImGui::PopStyleColor();
            ImGui::PopID();
        }
        ImGui::EndTable();
    }
}
void panel_hotkeys_draw(LauncherModel* m, const LauncherTheme* th) {
    if (begin_panel("hotkeys", 0)) draw_hotkeys_controls(m, *th);
    end_panel();
}

// The settings VIEW composes whichever panels this game's SystemProfile
// lists in panels_settings, in order: DISPLAY (MAIN) + AUDIO (SIDE) share the
// top band; further SIDE cards (INPUT, SYSTEM, SOLAR, …) then stack under
// AUDIO in the same right column in composition order; WIDE panels (HOTKEYS)
// still stack full-width below that — driven by the composition array + the
// registry's available() gate.
void draw_settings(LauncherModel* m, const LauncherTheme& th) {
    // Row 1: DISPLAY | AUDIO share the top band. For the legacy minimal
    // surface (no deep caps set — e.g. SNES) both cards are pinned to the
    // SAME fixed height, exactly as before, so that screenshot is unchanged.
    // A PSX-style game with the deeper capability set has far more rows than
    // that fixed height fits — rather than clip (or reintroduce a stray
    // scrollbar via no_scroll on an overflowing fixed-height card), those
    // cards switch to AutoResizeY so they simply grow to fit their content.
    // (Same "deep" predicates panel_video_draw/panel_audio_draw use for their
    // OWN inner card — computed twice, independently, so outer/inner sizing
    // never has to be threaded through the generic draw(model,theme) signature.)
    const SystemProfile* prof = (const SystemProfile*)m->profile;
    const float gap  = px(th.spacing_md);
    const float half = (ImGui::GetContentRegionAvail().x - gap) * 0.5f;
    const float row_h = px(240.0f);   // legacy fixed band height (4 rows: the
                                      // universal Fullscreen row joined scale/
                                      // filter/widescreen on the legacy surface)

    const bool deep_display = video_card_grows(m);   // superset of any_deep_display: folds in NES + widescreen (N64 covered too)
    const bool deep_audio   = m->has_spu_hq || m->num_languages > 0 || m->num_audio_devices > 0;   /* deadzone moved to controller card */

    const LauncherPanel* video_p   = find_composed(prof->panels_settings, "video", m);
    const LauncherPanel* audio_p   = find_composed(prof->panels_settings, "audio", m);
    const LauncherPanel* hotkeys_p = find_composed(prof->panels_settings, "hotkeys", m);

    // Left content edge in SCREEN space — where DISPLAY starts and where any
    // full-width content (HOTKEYS) below both columns must resume.
    const float content_left_x = ImGui::GetCursorScreenPos().x;

    float left_bottom = 0.0f;   // DISPLAY's bottom edge (screen space)
    if (video_p) {
        if (deep_display) begin_container("set_l", ImVec2(half, 0), ImGuiChildFlags_AutoResizeY);
        else               begin_container("set_l", ImVec2(half, row_h));
        video_p->draw(m, &th);
        end_container();
        left_bottom = ImGui::GetItemRectMax().y;
    }
    if (video_p && audio_p) ImGui::SameLine(0, gap);
    // Capture the right column's SCREEN x BEFORE opening AUDIO's child, so
    // additional SIDE cards (INPUT/SYSTEM/…) can reopen at the same x once
    // AUDIO's child ends (a finished child returns the cursor to the LEFT
    // edge of the row on the next line, not to its own column).
    const float right_x = ImGui::GetCursorScreenPos().x;
    float audio_bottom = 0.0f;   // AUDIO's bottom edge (screen space)
    if (audio_p) {
        if (deep_audio) begin_container("set_r", ImVec2(half, 0), ImGuiChildFlags_AutoResizeY);
        else             begin_container("set_r", ImVec2(half, row_h));
        audio_p->draw(m, &th);
        end_container();
        audio_bottom = ImGui::GetItemRectMax().y;
    }

    // Remaining SIDE-slot cards (INPUT, SYSTEM, SOLAR, …) stack under AUDIO
    // in panels_settings order. Falls back to full width only if a profile
    // composes them without "audio".
    float stack_bottom = audio_bottom;
    bool stacked_side = false;
    if (prof->panels_settings) {
        for (int i = 0; prof->panels_settings[i]; ++i) {
            const char* id = prof->panels_settings[i];
            if (!id || !id[0]) continue;
            if (strcmp(id, "video") == 0 || strcmp(id, "audio") == 0 ||
                strcmp(id, "hotkeys") == 0)
                continue;
            const LauncherPanel* side_p =
                find_composed(prof->panels_settings, id, m);
            if (!side_p || side_p->slot != LNG_SLOT_SIDE) continue;
            if (audio_p) {
                ImGui::SetCursorScreenPos(
                    ImVec2(right_x, stack_bottom + gap));
                char cname[48];
                snprintf(cname, sizeof(cname), "set_r_%s", id);
                begin_container(cname, ImVec2(half, 0),
                                ImGuiChildFlags_AutoResizeY);
                side_p->draw(m, &th);
                end_container();
                stack_bottom = ImGui::GetItemRectMax().y;
                stacked_side = true;
            } else {
                side_p->draw(m, &th);
                stack_bottom = ImGui::GetItemRectMax().y;
                stacked_side = true;
            }
        }
    }
    if (stacked_side && audio_p) {
        // Manual SetCursorScreenPos pulled SIDE cards out of row flow — resume
        // below the taller column so HOTKEYS never overlaps DISPLAY.
        const float below_y =
            (left_bottom > stack_bottom) ? left_bottom : stack_bottom;
        ImGui::SetCursorScreenPos(ImVec2(content_left_x, below_y + gap));
    }
    if (hotkeys_p) hotkeys_p->draw(m, &th);
}

static bool enabled_camera_controls(const LauncherModel* m) {
    const auto* mods = m ? m->mods : nullptr;
    if (!mods || !mods->feature_count || !mods->feature_get) return false;
    const int count = mods->feature_count(mods->ctx);
    for (int index = 0; index < count; ++index) {
        RecompLauncherCModFeature feature{};
        if (mods->feature_get(mods->ctx, index, &feature) &&
            feature.enabled && feature.camera_controls)
            return true;
    }
    return false;
}

const char* settings_key_label(int scancode) {
    if (scancode <= 0) return "(unbound)";
    const char* name = SDL_GetScancodeName((SDL_Scancode)scancode);
    return (name && name[0]) ? name : "(unbound)";
}

void settings_pad_label(int binding, char* out, size_t capacity) {
    if (!out || !capacity) return;
    const char* name = nullptr;
    char text[48] = {};
    if (RECOMP_LAUNCHER_PAD_IS_BUTTON(binding)) {
        int code = RECOMP_LAUNCHER_PAD_BUTTON_CODE(binding);
        name = SDL_GetGamepadStringForButton((LNG_GamepadButton)code);
        snprintf(text, sizeof text, "%s", (name && name[0]) ? name : "button");
    } else if (RECOMP_LAUNCHER_PAD_IS_AXIS(binding)) {
        int code = RECOMP_LAUNCHER_PAD_AXIS_CODE(binding);
        name = SDL_GetGamepadStringForAxis((LNG_GamepadAxis)code);
        snprintf(text, sizeof text, "%s%c",
                 (name && name[0]) ? name : "axis",
                 RECOMP_LAUNCHER_PAD_AXIS_POSITIVE(binding) ? '+' : '-');
    } else {
        snprintf(text, sizeof text, "(unbound)");
    }
    snprintf(out, capacity, "%s", text);
}

void draw_assist_binding_editor(LauncherModel* m, const LauncherTheme& th,
                                const char* table_id, int action_limit,
                                bool show_reset) {
    if (!m->settings_bindings || m->assist_binding_count <= 0 ||
        !m->assist_binding_labels)
        return;
    ImGui::PushStyleColor(ImGuiCol_Text, col(th.accent2));
    ImGui::TextUnformatted("ASSIST CONTROLS");
    ImGui::PopStyleColor();
    ImGui::TextColored(col(th.text_muted),
                       "Global controls; they only operate while Assist Tools is enabled.");
    if (ImGui::BeginTable(table_id, 3, ImGuiTableFlags_SizingFixedFit |
                                      ImGuiTableFlags_RowBg)) {
        ImGui::TableSetupColumn("Action", ImGuiTableColumnFlags_WidthFixed,
                                px(150));
        ImGui::TableSetupColumn("Keyboard", ImGuiTableColumnFlags_WidthFixed,
                                px(180));
        ImGui::TableSetupColumn("Controller", ImGuiTableColumnFlags_WidthFixed,
                                px(180));
        ImGui::TableHeadersRow();
        int count = m->assist_binding_count;
        if (action_limit > 0 && count > action_limit) count = action_limit;
        for (int action = 0; action < count; ++action) {
            ImGui::PushID(action);
            ImGui::TableNextRow();
            ImGui::TableSetColumnIndex(0);
            ImGui::AlignTextToFramePadding();
            ImGui::TextUnformatted(m->assist_binding_labels[action]);
            ImGui::TableSetColumnIndex(1);
            bool capture_key = m->capturing && m->capture_assist &&
                               !m->capture_pad && m->capture_btn == action;
            if (ImGui::Button(
                    capture_key ? "[ press a key... ]" :
                        settings_key_label(m->s.assist_key_bind[action]),
                    ImVec2(px(170), 0)))
                launcher_model_begin_assist_capture(m, action, false);
            ImGui::TableSetColumnIndex(2);
            bool capture_pad = m->capturing && m->capture_assist &&
                               m->capture_pad && m->capture_btn == action;
            char pad[48];
            settings_pad_label(m->s.assist_pad_bind[action], pad, sizeof pad);
            if (ImGui::Button(
                    capture_pad ? "[ press a button... ]" : pad,
                    ImVec2(px(170), 0)))
                launcher_model_begin_assist_capture(m, action, true);
            ImGui::PopID();
        }
        ImGui::EndTable();
    }
    if (show_reset && ImGui::Button("Reset Assist Controls"))
        launcher_model_reset_assist_bindings(m);
    if (m->capturing && m->capture_assist)
        ImGui::TextColored(col(th.warn), "Listening... (Esc cancels)");
}

void draw_controller_assist_shortcuts(LauncherModel* m,
                                      const LauncherTheme& th) {
    ImGui::PushStyleColor(ImGuiCol_Text, col(th.accent2));
    ImGui::TextUnformatted("ASSIST SHORTCUTS");
    ImGui::PopStyleColor();
    ImGui::SameLine();
    ImGui::TextColored(col(th.text_muted),
                       "(global; requires Assist Tools)");
    if (ImGui::BeginTable("controller_assist_binds", 2,
                          ImGuiTableFlags_SizingStretchSame)) {
        for (int action = 0;
             action < m->assist_binding_count && action < 2; ++action) {
            ImGui::TableNextColumn();
            ImGui::PushID(action);
            ImGui::AlignTextToFramePadding();
            ImGui::TextUnformatted(m->assist_binding_labels[action]);
            ImGui::SameLine(0, px(8));
            bool capture_key = m->capturing && m->capture_assist &&
                               !m->capture_pad && m->capture_btn == action;
            if (ImGui::Button(
                    capture_key ? "[ key... ]" :
                        settings_key_label(m->s.assist_key_bind[action]),
                    ImVec2(px(105), 0)))
                launcher_model_begin_assist_capture(m, action, false);
            ImGui::SameLine(0, px(5));
            bool capture_pad = m->capturing && m->capture_assist &&
                               m->capture_pad && m->capture_btn == action;
            char pad[48];
            settings_pad_label(m->s.assist_pad_bind[action], pad, sizeof pad);
            if (ImGui::Button(capture_pad ? "[ button... ]" : pad,
                              ImVec2(px(135), 0)))
                launcher_model_begin_assist_capture(m, action, true);
            ImGui::PopID();
        }
        ImGui::EndTable();
    }
    if (m->capturing && m->capture_assist)
        ImGui::TextColored(col(th.warn), "Listening... (Esc cancels)");
}

void draw_assist_tools(LauncherModel* m, const LauncherTheme& th) {
    if (!begin_panel("assist_tools_page", 0, false)) {
        end_panel();
        return;
    }
    eyebrow("ASSIST TOOLS / CHEATS");
    bool enabled = m->s.assist_tools != 0;
    if (ImGui::Checkbox("Enable Assist Tools / Cheats", &enabled))
        m->s.assist_tools = enabled ? 1 : 0;
    ImGui::Dummy(ImVec2(0, px(6)));
    ImGui::PushStyleColor(ImGuiCol_Text, col(th.text_muted));
    ImGui::PushTextWrapPos();
    ImGui::TextWrapped("%s",
        (m->assist_tools_note && m->assist_tools_note[0])
            ? m->assist_tools_note
            : "This optional host mode enables game-specific convenience "
              "features. The game window should disclose when it is active.");
    ImGui::PopTextWrapPos();
    ImGui::PopStyleColor();
    if (m->settings_bindings) {
        ImGui::Dummy(ImVec2(0, px(8)));
        draw_assist_binding_editor(m, th, "assist_binds", 0, true);
    }
    end_panel();
}

void draw_credits(LauncherModel* m, const LauncherTheme& th) {
    if (!begin_panel("credits_page", 0, false)) {
        end_panel();
        return;
    }
    eyebrow("CREDITS");
    ImGui::PushStyleColor(ImGuiCol_Text, col(th.text));
    ImGui::PushTextWrapPos();
    ImGui::TextWrapped("%s",
        (m->credits_text && m->credits_text[0])
            ? m->credits_text
            : "Credits have not been supplied for this title.");
    ImGui::PopTextWrapPos();
    ImGui::PopStyleColor();
    end_panel();
}

// CONTROLLER-view rebind page: input source + deadzone, and the keyboard
// bindings grid — reached from the dashboard CONTROLLER panel's Configure
// button. The bindings grid walks the ACTIVE SystemProfile's
// ControllerSpec.buttons[]/button_count (launcher_system.h) so each system
// renders its own real vocabulary (SNES: A/B/X/Y/L/R/...; PSX: Triangle/
// Circle/Cross/Square/L1/L2/R1/R2/L3/R3/...) instead of a hardcoded SNES set.
void draw_controller_config_view(LauncherModel* m, const LauncherTheme& th) {
    const int p = m->cfg_player;
    const SystemProfile* cfg_prof = (const SystemProfile*)m->profile;
    const bool cfg_psx = cfg_prof && cfg_prof->id && !strcmp(cfg_prof->id, "psx");
    if (cfg_psx && m->s.player_src[p] == 2 &&
        m->s.player_gamepad_guid[p][0] && !m->player_pad_name[p][0])
        launcher_binds_hydrate_psx_pad_names(m);

    if (begin_panel("cfg_src", 0)) {
        ImGui::PushStyleColor(ImGuiCol_Text, col(th.accent2));
        ImGui::Text("CONTROLLER - PLAYER %d", p + 1); ImGui::PopStyleColor(); ImGui::Spacing();
        row_label("Input source", th);
        ImGui::SetNextItemWidth(px(200));
        if (ImGui::BeginCombo("##csrc", launcher_model_player_src_label(m, p))) {
            draw_source_selectables(m, p);
            ImGui::EndCombo();
        }
        if (cfg_psx) {
            static bool s_rename_open = false;
            static char s_rename_buf[64] = {};
            const bool can_pad = m->s.player_src[p] == 2 &&
                                 m->s.player_gamepad_guid[p][0];
            ImGui::SameLine();
            if (!can_pad) ImGui::BeginDisabled();
            if (ImGui::Button("Rename Gamepad")) {
                std::snprintf(s_rename_buf, sizeof(s_rename_buf), "%s",
                              m->player_pad_name[p]);
                s_rename_open = true;
            }
            if (!can_pad) ImGui::EndDisabled();

            // Delete sits on the right of the Input source row.
            {
                const float del_w = px(130.0f);
                const float right = ImGui::GetWindowContentRegionMax().x;
                ImGui::SameLine(right - del_w);
                if (!can_pad) ImGui::BeginDisabled();
                if (ImGui::Button("Delete Gamepad", ImVec2(del_w, 0)))
                    launcher_binds_delete_psx_gamepad(m, p + 1);
                if (!can_pad) ImGui::EndDisabled();
            }

            if (s_rename_open) ImGui::OpenPopup("Rename Gamepad");
            ImVec2 center = ImGui::GetMainViewport()->GetCenter();
            ImGui::SetNextWindowPos(center, ImGuiCond_Appearing, ImVec2(0.5f, 0.5f));
            if (ImGui::BeginPopupModal("Rename Gamepad", &s_rename_open,
                                       ImGuiWindowFlags_AlwaysAutoResize)) {
                ImGui::TextUnformatted("Display name for this gamepad:");
                ImGui::SetNextItemWidth(px(320));
                bool enter = ImGui::InputText(
                    "##rename_pad", s_rename_buf, sizeof(s_rename_buf),
                    ImGuiInputTextFlags_EnterReturnsTrue);
                ImGui::Spacing();
                if (ImGui::Button("Cancel", ImVec2(px(120), 0))) {
                    s_rename_open = false;
                    ImGui::CloseCurrentPopup();
                }
                ImGui::SameLine();
                const bool ok = s_rename_buf[0] != '\0';
                ImGui::BeginDisabled(!ok);
                if ((ImGui::Button("OK", ImVec2(px(120), 0)) || enter) && ok) {
                    launcher_binds_rename_psx_gamepad(m, p + 1, s_rename_buf);
                    s_rename_open = false;
                    ImGui::CloseCurrentPopup();
                }
                ImGui::EndDisabled();
                ImGui::EndPopup();
            }
        }
        row_label("Deadzone", th);
        int dz = 0; stepper("dz", m->s.deadzone[p], "%", &dz);
        if (dz) launcher_model_deadzone_delta(m, p, dz);
    } end_panel();

    // Transfer Pak for THIS controller port (N64 tpak games), so it's reachable
    // from the Controller page without scrolling the dashboard. Same compact
    // tile + config modal; the port is the player being configured.
    if (m->tpak_slots > p) {
        if (begin_panel("cfg_tpak", 0)) {
            draw_tpak_tile(m, th, p);
        } end_panel();
    }

    // MOUSE card (opt-in, has_mouse_controls games only — Snap): shown whenever
    // this player's source is a keyboard family. Sensitivity + Invert X/Y +
    // three rebindable mouse buttons, each mapping to an N64 action. Placed
    // after the source/deadzone card and before the bindings card. Entirely
    // absent for every non-mouse game (has_mouse_controls == 0).
    if (m->has_mouse_controls && m->s.player_src[p] == 1) {
        if (begin_panel("cfg_mouse", 0)) {
            eyebrow("MOUSE");

            // Sensitivity: a float slider over the model's clamp range. The
            // model re-clamps on set, so the slider can never commit a value
            // outside [0.01, 0.50].
            row_label("Sensitivity", th);
            ImGui::SetNextItemWidth(px(200));
            float sens = m->s.mouse_sensitivity;
            if (ImGui::SliderFloat("##msens", &sens, 0.01f, 0.50f, "%.2f"))
                launcher_model_set_mouse_sensitivity(m, sens);

            // Invert toggles.
            bool ix = m->s.mouse_invert_x != 0;
            if (ImGui::Checkbox("Invert X", &ix)) launcher_model_toggle_mouse_invert_x(m);
            bool iy = m->s.mouse_invert_y != 0;
            if (ImGui::Checkbox("Invert Y", &iy)) launcher_model_toggle_mouse_invert_y(m);

            // Three rebindable mouse buttons -> an N64 action (or None). The
            // vocabulary is the active profile's ControllerSpec.buttons[].
            const SystemProfile* prof = (const SystemProfile*)m->profile;
            const ControllerSpec& spec = prof->controller;
            static const char* kMouseRows[3] = { "Left click", "Right click", "Middle click" };
            for (int i = 0; i < 3; ++i) {
                ImGui::PushID(i);
                row_label(kMouseRows[i], th);
                const int cur = m->s.mouse_bind[i];
                const char* cur_label = (cur >= 0 && cur < spec.button_count)
                                        ? spec.buttons[cur].label : "None";
                ImGui::SetNextItemWidth(px(200));
                if (ImGui::BeginCombo("##mbtn", cur_label)) {
                    if (ImGui::Selectable("None", cur < 0))
                        launcher_model_set_mouse_bind(m, i, -1);
                    for (int b = 0; b < spec.button_count; ++b) {
                        if (ImGui::Selectable(spec.buttons[b].label, cur == b))
                            launcher_model_set_mouse_bind(m, i, b);
                    }
                    ImGui::EndCombo();
                }
                ImGui::PopID();
            }
        } end_panel();
    }

    // MOTION card (opt-in): the host owns controller discovery and axis
    // mapping; recomp-ui owns only the portable sensitivity setting.
    if (m->has_gyro_controls && p == 0) {
        if (begin_panel("cfg_motion", 0)) {
            eyebrow("MOTION");
            row_label("Gyro sensitivity", th);
            ImGui::SetNextItemWidth(px(200));
            float sens = m->s.gyro_sensitivity;
            if (ImGui::SliderFloat("##gyrosens", &sens, 0.25f, 4.00f, "%.2fx"))
                launcher_model_set_gyro_sensitivity(m, sens);

            // Prefer the explicitly selected Player 1 pad; while the source
            // is still Keyboard, preview the first connected gyro-capable pad
            // so motion can be verified before changing the source dropdown.
            const LauncherPad* motion_pad = nullptr;
            if (m->s.player_src[p] == 2) {
                for (int i = 0; i < g_pad_count; ++i) {
                    const bool id_match =
                        m->player_pad_id[p] &&
                        g_pads[i].id == m->player_pad_id[p];
                    const bool guid_match =
                        m->s.player_gamepad_guid[p][0] &&
                        g_pads[i].guid[0] &&
                        std::strcmp(m->s.player_gamepad_guid[p],
                                    g_pads[i].guid) == 0;
                    if (id_match || guid_match) {
                        motion_pad = &g_pads[i];
                        break;
                    }
                }
            }

            const float rate = motion_pad && motion_pad->has_gyro
                                 ? motion_pad->gyro_z : 0.0f;
            // Match gbarecomp's PC mapping exactly: negate face-normal Z,
            // apply the gentler 128-units/rad/s DualSense base gain, then the
            // launcher multiplier, and clamp to the cartridge's +/-0x600.
            const float cartridge = std::clamp(
                -rate * 128.0f * m->s.gyro_sensitivity,
                -1536.0f, 1536.0f);
            const float level = cartridge / 1536.0f;

            ImGui::Spacing();
            ImGui::TextUnformatted(
                motion_pad
                    ? (motion_pad->has_gyro
                           ? motion_pad->name
                           : "Selected controller has no gyro sensor")
                    : "No gyro controller detected");

            // Centered live gauge. The moving needle and colored fill show the
            // exact signed value the host will send to the cartridge; reaching
            // either edge means the configured sensitivity is saturating.
            const float meter_w = std::min(px(360.0f),
                                           ImGui::GetContentRegionAvail().x);
            const ImVec2 meter_min = ImGui::GetCursorScreenPos();
            const ImVec2 meter_max(meter_min.x + meter_w,
                                   meter_min.y + px(26.0f));
            ImGui::InvisibleButton("##gyro_meter",
                                   ImVec2(meter_w, px(26.0f)));
            ImDrawList* dl = ImGui::GetWindowDrawList();
            dl->AddRectFilled(meter_min, meter_max, imcol(th.control),
                              px(th.radius_sm));
            dl->AddRect(meter_min, meter_max, imcol(th.border),
                        px(th.radius_sm));
            const float center = (meter_min.x + meter_max.x) * 0.5f;
            for (int tick = -2; tick <= 2; ++tick) {
                const float x = center + tick * meter_w * 0.20f;
                dl->AddLine(ImVec2(x, meter_min.y + px(7.0f)),
                            ImVec2(x, meter_max.y - px(7.0f)),
                            imcol(tick == 0 ? th.text_muted : th.border),
                            tick == 0 ? px(2.0f) : px(1.0f));
            }
            const float needle = center + level * meter_w * 0.5f;
            if (level != 0.0f) {
                dl->AddRectFilled(
                    ImVec2(std::min(center, needle), meter_min.y + px(9.0f)),
                    ImVec2(std::max(center, needle), meter_max.y - px(9.0f)),
                    imcol(th.accent), px(3.0f));
            }
            dl->AddLine(ImVec2(needle, meter_min.y + px(3.0f)),
                        ImVec2(needle, meter_max.y - px(3.0f)),
                        imcol(motion_pad && motion_pad->has_gyro
                                  ? th.good : th.warn),
                        px(3.0f));
            ImGui::Text("Output %+.0f / 1536   Sensor %+.2f rad/s",
                        cartridge, rate);

            ImGui::PushStyleColor(ImGuiCol_Text, col(th.text_muted));
            ImGui::TextWrapped(
                "A compatible controller motion sensor is used automatically. "
                "Mouse drag remains available as a fallback.");
            ImGui::PopStyleColor();
        } end_panel();
    }

    /* Voxel/3D camera bindings are feature-driven, not a permanent NES
     * capability. The card appears only while at least one enabled feature
     * advertises camera_controls, and only on Player 1's page because the
     * presentation camera is global. */
    if (p == 0 && enabled_camera_controls(m)) {
        static const char* kActionLabels[LNG_CAMERA_BIND_COUNT] = {
            "Look up", "Look down", "Look left", "Look right",
            "Roll left", "Roll right", "Zoom in", "Zoom out",
            "Sprites smaller", "Sprites larger", "Reset view",
            "Toggle Voxel 3D",
        };
        static const char* kPadDefaults[LNG_CAMERA_BIND_COUNT] = {
            "Right stick up", "Right stick down",
            "Right stick left", "Right stick right",
            "-", "-", "-", "-", "-", "-", "-", "-",
        };
        launcher_binds_refresh_camera(m);
        if (begin_panel("cfg_camera", 0)) {
            eyebrow("3D CAMERA");
            ImGui::TextColored(
                col(th.text_muted),
                "Active while the enabled Voxel mod is running. Right-stick "
                "look is the gamepad default; keyboard actions use the numpad.");
            ImGui::Spacing();
            if (ImGui::BeginTable(
                    "camera_binds", 3,
                    ImGuiTableFlags_SizingStretchProp |
                    ImGuiTableFlags_RowBg)) {
                ImGui::TableSetupColumn("Action",
                                        ImGuiTableColumnFlags_WidthStretch,
                                        1.2f);
                ImGui::TableSetupColumn("Keyboard",
                                        ImGuiTableColumnFlags_WidthStretch,
                                        1.0f);
                ImGui::TableSetupColumn("Gamepad default",
                                        ImGuiTableColumnFlags_WidthStretch,
                                        1.0f);
                ImGui::TableHeadersRow();
                for (int action = 0; action < LNG_CAMERA_BIND_COUNT;
                     ++action) {
                    ImGui::PushID(action);
                    ImGui::TableNextRow();
                    ImGui::TableSetColumnIndex(0);
                    ImGui::AlignTextToFramePadding();
                    ImGui::TextUnformatted(kActionLabels[action]);
                    ImGui::TableSetColumnIndex(1);
                    const bool capturing =
                        m->camera_capturing &&
                        m->capture_camera == action;
                    if (capturing)
                        ImGui::PushStyleColor(
                            ImGuiCol_Button, col(th.accent));
                    if (ImGui::Button(
                            capturing ? "[ press a key... ]"
                                      : m->camera_binds[action],
                            ImVec2(-FLT_MIN, 0)))
                        launcher_model_begin_camera_capture(m, action);
                    if (capturing) ImGui::PopStyleColor();
                    ImGui::TableSetColumnIndex(2);
                    ImGui::AlignTextToFramePadding();
                    ImGui::TextColored(
                        col(th.text_muted), "%s",
                        kPadDefaults[action]);
                    ImGui::PopID();
                }
                ImGui::EndTable();
            }
            ImGui::Spacing();
            if (ImGui::Button("Reset Camera Bindings"))
                launcher_binds_reset_camera(m);
            if (m->camera_capturing)
                ImGui::TextColored(
                    col(th.warn), "Listening... (Esc cancels)");
        } end_panel();
    }

    // Some systems ship no rebindable input layer (N64 Snap / PMS-J read no
    // input.cfg): GameInfo.hide_rebind drops the bindings card entirely and the
    // Controller view is source+deadzone only.
    if (m->hide_rebind) return;

    if (begin_panel("cfg_binds", 0)) {
        // Responsive grid: fit as many label+chip columns as the width allows
        // (1..4) instead of one tall column with dead space to the right.
        const SystemProfile* prof = (const SystemProfile*)m->profile;
        const ControllerSpec& spec = prof->controller;
        const bool is_psx = prof && prof->id && !strcmp(prof->id, "psx");

        // ---- PSX: Gamepad Bindings (per selected SDL GUID) -----------------
        // Replaces the keyboard grid on Configure. Column-major layout
        // (top→bottom then next column) matching kPsxGamepadBindOrder.
        if (is_psx) {
            ImGui::PushStyleColor(ImGuiCol_Text, col(th.accent2));
            ImGui::Text("GAMEPAD BINDINGS - PLAYER %d", p + 1);
            ImGui::PopStyleColor();
            ImGui::Spacing();

            const bool has_pad_src = m->s.player_src[p] == 2 &&
                                     m->s.player_gamepad_guid[p][0];
            if (!has_pad_src) {
                ImGui::TextColored(col(th.text_muted),
                    "Select a gamepad as Input source to configure bindings.");
            } else {
                float label_col_w = px(90.0f);
                for (int i = 0; i < LNG_PSX_PAD_BUTTON_COUNT; ++i) {
                    float w = ImGui::CalcTextSize(spec.buttons[i].label).x + px(20.0f);
                    if (w > label_col_w) label_col_w = w;
                }
                const float chip_w = px(140.0f);
                const float cell_w = label_col_w + chip_w + px(16.0f);
                if (ImGui::BeginTable("psx_pad_binds", LNG_PSX_GAMEPAD_BIND_COLS,
                                      ImGuiTableFlags_SizingFixedFit)) {
                    for (int c = 0; c < LNG_PSX_GAMEPAD_BIND_COLS; ++c)
                        ImGui::TableSetupColumn(nullptr,
                            ImGuiTableColumnFlags_WidthFixed, cell_w);
                    for (int row = 0; row < LNG_PSX_GAMEPAD_BIND_ROWS; ++row) {
                        for (int c = 0; c < LNG_PSX_GAMEPAD_BIND_COLS; ++c) {
                            const int order_i = c * LNG_PSX_GAMEPAD_BIND_ROWS + row;
                            const int b = kPsxGamepadBindOrder[order_i];
                            ImGui::TableNextColumn();
                            ImGui::PushID(b);
                            ImGui::AlignTextToFramePadding();
                            ImGui::TextColored(col(th.text_muted), "%s",
                                               spec.buttons[b].label);
                            ImGui::SameLine(label_col_w);
                            const bool cap = m->capturing && m->capture_pad &&
                                             m->capture_btn == b;
                            const bool wait_rel = cap && m->map_all_wait_release;
                            const char* pl = m->pad_binds[p][b][0]
                                               ? m->pad_binds[p][b]
                                               : "(unbound)";
                            if (cap) ImGui::PushStyleColor(ImGuiCol_Button, col(th.accent));
                            const char* chip = wait_rel ? "[ release button... ]"
                                              : cap     ? "[ press a button... ]"
                                                        : pl;
                            if (ImGui::Button(chip, ImVec2(chip_w, 0))) {
                                m->map_all_active = false;
                                m->map_all_wait_release = false;
                                launcher_model_begin_pad_capture(m, b);
                                // If they start a bind while still holding the
                                // prior input, wait for a full release first.
                                if (m->capturing && m->player_pad_id[p] &&
                                    !launcher_input_gamepad_at_rest(
                                        m->player_pad_id[p]))
                                    m->map_all_wait_release = true;
                            }
                            if (cap) ImGui::PopStyleColor();
                            ImGui::PopID();
                        }
                    }
                    ImGui::EndTable();
                }
                ImGui::Spacing();
                if (ImGui::Button("Map All Bindings")) {
                    launcher_model_begin_map_all(m);
                    if (m->capturing && m->player_pad_id[p] &&
                        !launcher_input_gamepad_at_rest(m->player_pad_id[p]))
                        m->map_all_wait_release = true;
                }
                ImGui::SameLine();
                if (ImGui::Button("Reset to Defaults"))
                    launcher_binds_reset_player(m, m->cfg_player + 1);
                // Save Profile — name, choice, mappings, and deadzone for this GUID.
                static double s_profile_saved_until = 0.0;
                {
                    const float save_w = px(120.0f);
                    const float right = ImGui::GetWindowContentRegionMax().x;
                    ImGui::SameLine(right - save_w);
                    if (ImGui::Button("Save Profile", ImVec2(save_w, 0))) {
                        launcher_binds_save_psx_gamepad(m, p + 1);
                        s_profile_saved_until = ImGui::GetTime() + 2.5;
                    }
                }
                if (m->capturing && m->capture_pad) {
                    const char* label =
                        (m->capture_btn >= 0 &&
                         m->capture_btn < LNG_PSX_PAD_BUTTON_COUNT)
                            ? spec.buttons[m->capture_btn].label : "?";
                    if (m->map_all_wait_release) {
                        ImGui::TextColored(col(th.warn),
                            "Release Button (Esc cancels)%s",
                            m->map_all_active ? " — Map All" : "");
                    } else {
                        ImGui::TextColored(col(th.warn),
                            "Map an input to %s (Esc cancels)%s",
                            label,
                            m->map_all_active ? " — Map All" : "");
                    }
                }
                if (ImGui::GetTime() < s_profile_saved_until)
                    ImGui::TextColored(col(th.accent2), "Input Profile Saved!");
            }
        } else {
        // Alternate binds per input (N64's input.cfg keeps two; SNES/GBA
        // keep one). 0 in the spec reads as 1 (older positional initializers).
        // Host-owned settings arrays have one keyboard and one controller
        // value per action, independent of a console bridge's alternate-slot
        // format (for example N64 input.cfg). Keep that opt-in store on its
        // own two-chip path instead of accidentally editing the native store.
        const int bpi = m->settings_bindings
            ? 1 : (spec.binds_per_input < 1 ? 1 : spec.binds_per_input);

        // Stores that follow the input SOURCE (N64: one shared table per device
        // TYPE) must re-read display strings on entry so switching
        // Keyboard<->pad shows the table actually in effect. Single-bind stores
        // are per-player and unaffected by the source, so skip the refresh to
        // keep their behaviour byte-identical.
        if (bpi >= 2) launcher_binds_refresh(m);

        // A pad-bind console (Genesis) offers a KEY chip AND a GAMEPAD chip per
        // row — the legacy launcher's "Set key" / "Set pad" pair. Otherwise the
        // grid is keyboard-only, exactly as before.
        const bool has_pad = spec.has_pad_binds != 0 || m->settings_bindings;

        // When the player's source is a gamepad the N64 store captures pad
        // fields, not keys — reflect that in the card title and the capture
        // placeholder.
        const bool pad_cap = launcher_binds_wants_pad_capture(m, p + 1) != 0;

        // Heading uses accent2 so each console's title tints in ITS logo colour
        // (N64 blue; single-accent consoles set accent2 == accent).
        ImGui::PushStyleColor(ImGuiCol_Text, col(th.accent2));
        if (has_pad)      ImGui::Text("INPUT BINDINGS - PLAYER %d", p + 1);
        else if (pad_cap) ImGui::TextUnformatted("CONTROLLER BINDINGS");
        else              ImGui::Text("KEYBOARD BINDINGS - PLAYER %d", p + 1);
        ImGui::PopStyleColor(); ImGui::Spacing();

        // Rows shown follow the player's ACTIVE pad mode (Genesis 3-Button hides
        // X/Y/Z/Mode); non-mode systems get their full button_count.
        const int nbtn = launcher_model_active_button_count(m, p);

        // Label column width is sized to the WIDEST label this system's spec
        // actually uses (e.g. PSX's "Triangle") instead of a constant tuned
        // for SNES's shorter names ("Select") — otherwise longer per-system
        // vocab overlaps the bind-chip button next to it.
        float label_col_w = px(70.0f);
        for (int b = 0; b < nbtn; ++b) {
            float w = ImGui::CalcTextSize(spec.buttons[b].label).x + px(20.0f);
            if (w > label_col_w) label_col_w = w;
        }
        // Two chips per row when either the N64 keeps two binds per input
        // (bpi>=2) OR a pad-bind console pairs a KEY + GAMEPAD chip (has_pad);
        // narrower chips then. Single-chip cells keep the wider chip AND the
        // exact legacy cell width (label + 170) so non-pad/single-bind consoles
        // (SNES/GBA) pack columns byte-identically to before this existed.
        const bool two_chip = (bpi >= 2) || has_pad;
        const float chip_w   = two_chip ? px(118.0f) : px(160.0f);
        const float chip_gap = px(6.0f);
        const float cell_w = two_chip
            ? (label_col_w + chip_w + chip_gap + chip_w + px(16.0f))
            : (label_col_w + px(170.0f));
        int cols = (int)(ImGui::GetContentRegionAvail().x / cell_w);
        if (cols < 1) cols = 1;
        if (cols > 4) cols = 4;
        // Fixed-width columns, explicitly sized to cell_w: the default
        // stretch policy divides available width evenly across `cols`
        // regardless of our computed cell_w, which reintroduces the very
        // overlap/clip this sizing pass exists to avoid.
        if (ImGui::BeginTable("binds", cols, ImGuiTableFlags_SizingFixedFit)) {
            for (int c = 0; c < cols; ++c)
                ImGui::TableSetupColumn(nullptr, ImGuiTableColumnFlags_WidthFixed, cell_w);
            for (int b = 0; b < nbtn; ++b) {
                ImGui::TableNextColumn();
                ImGui::PushID(b);
                ImGui::AlignTextToFramePadding();
                ImGui::TextColored(col(th.text_muted), "%s", spec.buttons[b].label);
                ImGui::SameLine(label_col_w);
                if (bpi >= 2) {
                    // N64: two chips per input (slot 0 primary, slot 1 alt); the
                    // shared store captures a key or pad field per pad_cap.
                    for (int slot = 0; slot < bpi; ++slot) {
                        if (slot) ImGui::SameLine(0, chip_gap);
                        ImGui::PushID(slot);
                        const bool cap = m->capturing && m->capture_btn == b
                                                      && m->capture_slot == slot;
                        const char* txt = cap
                            ? (pad_cap ? "[ press a key / pad... ]" : "[ press a key... ]")
                            : (slot == 0 ? m->binds[p][b] : m->binds_alt[p][b]);
                        if (cap) ImGui::PushStyleColor(ImGuiCol_Button, col(th.accent));
                        if (ImGui::Button(txt, ImVec2(chip_w, 0)))
                            launcher_model_begin_capture_slot(m, b, slot);
                        if (cap) ImGui::PopStyleColor();
                        ImGui::PopID();
                    }
                } else {
                    // KEY chip
                    const bool cap_key = m->capturing && !m->capture_pad && m->capture_btn == b;
                    if (cap_key) ImGui::PushStyleColor(ImGuiCol_Button, col(th.accent));
                    const char* key_text = m->settings_bindings
                        ? settings_key_label(m->s.player_key_bind[p][b])
                        : m->binds[p][b];
                    if (ImGui::Button(cap_key ? "[ press a key... ]" : key_text, ImVec2(chip_w, 0)))
                        launcher_model_begin_capture(m, b);
                    if (cap_key) ImGui::PopStyleColor();
                    // GAMEPAD chip (pad-bind consoles only: Genesis)
                    if (has_pad) {
                        ImGui::SameLine(0, chip_gap);
                        ImGui::PushID("pad");
                        const bool cap_pad = m->capturing && m->capture_pad && m->capture_btn == b;
                        char settings_pad[48];
                        settings_pad_label(m->s.player_pad_bind[p][b],
                                           settings_pad, sizeof settings_pad);
                        const char* pl = m->settings_bindings
                            ? settings_pad
                            : (m->pad_binds[p][b][0]
                                ? m->pad_binds[p][b] : "(unbound)");
                        if (cap_pad) ImGui::PushStyleColor(ImGuiCol_Button, col(th.accent));
                        if (ImGui::Button(cap_pad ? "[ press a button... ]" : pl, ImVec2(chip_w, 0)))
                            launcher_model_begin_pad_capture(m, b);
                        if (cap_pad) ImGui::PopStyleColor();
                        ImGui::PopID();
                    }
                }
                ImGui::PopID();
            }
            ImGui::EndTable();
        }
        ImGui::Spacing();
        if (ImGui::Button("Reset to Defaults")) {
            if (m->settings_bindings)
                launcher_model_reset_player_bindings(m, m->cfg_player);
            else
                launcher_binds_reset_player(m, m->cfg_player + 1);
        }
        if (m->capturing) ImGui::TextColored(col(th.warn), "Listening... (Esc cancels)");
        } // !is_psx
    } end_panel();

    // Zapper (light gun) block — NES Zapper games only (gi.zapper). The mouse
    // is the gun on a PC: position aims, left click pulls the trigger. Both
    // switches persist to keybinds.ini's [zapper] section immediately (same
    // file the game's runtime reads; the rest of the file is preserved).
    if (m->zapper) {
        if (begin_panel("cfg_zapper", 0)) {
            ImGui::PushStyleColor(ImGuiCol_Text, col(th.accent));
            ImGui::TextUnformatted("ZAPPER (LIGHT GUN)");
            ImGui::PopStyleColor(); ImGui::Spacing();
            ImGui::TextColored(col(th.text_muted),
                "The mouse is the Zapper: move to aim, left-click to fire.");
            ImGui::Dummy(ImVec2(0, px(4)));
            bool mouse = m->zapper_mouse;
            if (ImGui::Checkbox("Mouse acts as the Zapper", &mouse))
                launcher_model_toggle_zapper_mouse(m);
            bool ch = m->zapper_crosshair;
            if (ImGui::Checkbox("Show crosshair (hides the OS cursor)", &ch))
                launcher_model_toggle_zapper_crosshair(m);
        } end_panel();
    }

    if (m->settings_bindings && m->has_assist_tools) {
        if (begin_panel("cfg_assist_binds", 0)) {
            draw_controller_assist_shortcuts(m, th);
        } end_panel();
    }
}

void panel_controller_config_draw(LauncherModel* m, const LauncherTheme* th) {
    draw_controller_config_view(m, *th);
}

// The CONTROLLER view composes whichever panel(s) this game's SystemProfile
// lists in panels_controller — today always the single "controller_config"
// page (source+deadzone card, then the bindings grid card), matching the
// architecture's "Binds ... page reached from the Controller panel's
// Configure" note.
void draw_controller(LauncherModel* m, const LauncherTheme& th) {
    const SystemProfile* prof = (const SystemProfile*)m->profile;
    const LauncherPanel* p = find_composed(prof->panels_controller, "controller_config", m);
    if (p) p->draw(m, &th);
}

const RecompLauncherCNetplayCallbacks* np_cb(LauncherModel* m) {
    return (m && m->netplay_supported) ? m->netplay : nullptr;
}

bool np_connected(LauncherModel* m) {
    const auto* np = np_cb(m);
    return np && np->connected && np->connected(np->ctx);
}

bool np_valid_port(const char* text) {
    if (!text || !text[0]) return false;
    unsigned value = 0;
    for (const char* p = text; *p; ++p) {
        if (*p < '0' || *p > '9') return false;
        value = value * 10u + (unsigned)(*p - '0');
        if (value > 65535u) return false;
    }
    return value != 0;
}

bool np_prepare_guest_bind(char* out, size_t cap, char* status, size_t status_cap) {
    if (launcher_udp_prepare_guest_bind(out, cap) != 0) {
        if (status && status_cap)
            std::snprintf(status, status_cap, "No free UDP port near 7778. Try again.");
        return false;
    }
    return true;
}

void np_connect_and_list(LauncherModel* m) {
    const auto* np = np_cb(m);
    if (!np) return;
    if (np->set_player_name && m->s.netplay_player_name[0])
        np->set_player_name(np->ctx, m->s.netplay_player_name);
    const bool already = np->connected && np->connected(np->ctx);
    const bool in_flight = np->connecting && np->connecting(np->ctx);
    if (np->connect && !already && !in_flight)
        (void)np->connect(np->ctx);
    if (np->request_list)
        np->request_list(np->ctx);
    m->netplay_list_fresh = true;
    if (!already)
        std::snprintf(m->netplay_status, sizeof(m->netplay_status),
                      "Connecting to lobby server…");
}

/* Reload server lobby table + UDP-browse LAN hosts (BEACON) / file registry. */
void np_refresh_lobby_list(LauncherModel* m) {
    np_connect_and_list(m);
    m->netplay_selected_lobby = -1;
    /* Keep Connecting… status from np_connect_and_list; clear only when
     * the caller is an explicit Refresh after a prior error. */
}

static void mod_note_error(LauncherModel* m);
static bool mod_commit_launch(LauncherModel* m);

/* Netplay must stay vanilla while mod sync is unproven. Prefer the optional
 * provider commit_netplay hook (clears an in-session plan without touching
 * offline selections); otherwise skip mod commit entirely. */
static bool mod_commit_netplay_launch(LauncherModel* m) {
    if (!m) return true;
    const auto* mods = m->mods;
    if (!mods) return true;
    if (mods->commit_netplay) {
        if (mods->commit_netplay(mods->ctx, launcher_model_rom_path(m)))
            return true;
        mod_note_error(m);
        return false;
    }
    return true;
}

void np_try_launch(LauncherModel* m) {
    const auto* np = np_cb(m);
    if (!np || !np->fill_launch) return;
    RecompLauncherCNetplayLaunch launch{};
    if (!np->fill_launch(np->ctx, &launch) || !launch.enabled) return;
    if (mod_commit_netplay_launch(m)) {
        m->s.netplay_launch = launch;
        if (np->clear_launch_pending) np->clear_launch_pending(np->ctx);
        m->action = LNG_ACTION_LAUNCH;
    }
}

void np_refresh_host_ip(LauncherModel* m) {
    const auto* np = np_cb(m);
    if (!np) return;
    m->netplay_local_address_count = 0;

    /* Enumerate local interfaces for the Host Lobby "Advertised IP Address"
     * dropdown (LAN-only and online). Online also uses the pick as host_bind /
     * preferred LAN advertise; STUN still publishes a public endpoint. */
    if (np->local_address_get) {
        for (int index = 0; index < LNG_NETPLAY_MAX_LOCAL_ADDRESSES; ++index) {
            RecompLauncherCNetplayLocalAddress candidate{};
            if (!np->local_address_get(np->ctx, index, &candidate)) break;
            candidate.address[sizeof(candidate.address) - 1] = '\0';
            candidate.label[sizeof(candidate.label) - 1] = '\0';
            if (!candidate.address[0]) continue;

            bool duplicate = false;
            for (int existing = 0; existing < m->netplay_local_address_count; ++existing) {
                if (std::strcmp(m->netplay_local_addresses[existing].address,
                                candidate.address) == 0) {
                    duplicate = true;
                    break;
                }
            }
            if (!duplicate) {
                m->netplay_local_addresses[m->netplay_local_address_count++] = candidate;
            }
        }
    }

    // Older hosts expose one preferred address through local_ip only.
    if (m->netplay_local_address_count == 0 && np->local_ip) {
        RecompLauncherCNetplayLocalAddress candidate{};
        if (np->local_ip(np->ctx, candidate.address, sizeof(candidate.address)) &&
            candidate.address[0]) {
            candidate.address[sizeof(candidate.address) - 1] = '\0';
            std::snprintf(candidate.label, sizeof(candidate.label), "Local network");
            m->netplay_local_addresses[m->netplay_local_address_count++] = candidate;
        }
    }

    if (m->netplay_local_address_count > 0) {
        int selected = 0;
        const char* preferred = m->netplay_host_local_ip[0]
            ? m->netplay_host_local_ip : m->netplay_host_ip;
        for (int index = 0; index < m->netplay_local_address_count; ++index) {
            if (std::strcmp(preferred, m->netplay_local_addresses[index].address) == 0) {
                selected = index;
                break;
            }
        }
        std::snprintf(m->netplay_host_ip, sizeof(m->netplay_host_ip), "%s",
                      m->netplay_local_addresses[selected].address);
        std::snprintf(m->netplay_host_local_ip, sizeof(m->netplay_host_local_ip), "%s",
                      m->netplay_local_addresses[selected].address);
        return;
    }

    std::snprintf(m->netplay_host_ip, sizeof(m->netplay_host_ip), "Unavailable");
}

void np_format_local_address(const RecompLauncherCNetplayLocalAddress& address,
                             char* out, size_t out_len) {
    if (address.label[0])
        std::snprintf(out, out_len, "%s (%s)", address.label, address.address);
    else
        std::snprintf(out, out_len, "%s", address.address);
}

/* Matches snes_lobby_default_url() when SNES_NET_LOBBY_URL is unset. */
static const char kNpDefaultLobbyUrl[] =
    "ws://netplay.retcomm.net:8765";
/* Persisted next to guest netplay saves (cwd-relative). */
static const char kNpNetworkSettingsPath[] = "saves/netplay/network settings";

static void np_ensure_netplay_dir(void) {
#if defined(_WIN32)
    _mkdir("saves");
    _mkdir("saves\\netplay");
#else
    mkdir("saves", 0755);
    mkdir("saves/netplay", 0755);
#endif
}

/* Read-only + greyed, but still allows click-drag select / Ctrl+C. */
static void np_copyable_readonly_input(const char* id, char* buf, size_t buf_len,
                                       const LauncherTheme& th) {
    ImGui::PushStyleColor(ImGuiCol_Text, col(th.text_muted));
    ImGui::PushStyleColor(ImGuiCol_FrameBg,
                          ImVec4(th.control.r * 0.65f, th.control.g * 0.65f,
                                 th.control.b * 0.65f, th.control.a));
    ImGui::PushStyleColor(ImGuiCol_FrameBgHovered,
                          ImVec4(th.control.r * 0.65f, th.control.g * 0.65f,
                                 th.control.b * 0.65f, th.control.a));
    ImGui::PushStyleColor(ImGuiCol_FrameBgActive,
                          ImVec4(th.control.r * 0.65f, th.control.g * 0.65f,
                                 th.control.b * 0.65f, th.control.a));
    ImGui::InputText(id, buf, buf_len, ImGuiInputTextFlags_ReadOnly);
    ImGui::PopStyleColor(4);
}

static void np_save_network_settings(const LauncherModel* m) {
    if (!m) return;
    np_ensure_netplay_dir();
    FILE* f = std::fopen(kNpNetworkSettingsPath, "wb");
    if (!f) return;
    std::fprintf(f, "lobby_url=%s\n", m->netplay_lobby_url);
    std::fprintf(f, "preferred_ip=%s\n",
                 m->netplay_host_local_ip[0] ? m->netplay_host_local_ip
                                             : m->netplay_host_ip);
    std::fprintf(f, "preferred_port=%s\n", m->netplay_host_port);
    std::fclose(f);
}

static void np_load_network_settings(LauncherModel* m) {
    if (!m) return;
    FILE* f = std::fopen(kNpNetworkSettingsPath, "rb");
    if (!f) return;
    char line[320];
    while (std::fgets(line, sizeof(line), f)) {
        char* nl = std::strchr(line, '\n');
        if (nl) *nl = '\0';
        char* cr = std::strchr(line, '\r');
        if (cr) *cr = '\0';
        char* eq = std::strchr(line, '=');
        if (!eq) continue;
        *eq = '\0';
        const char* key = line;
        const char* val = eq + 1;
        if (std::strcmp(key, "lobby_url") == 0 && val[0]) {
            std::snprintf(m->netplay_lobby_url, sizeof(m->netplay_lobby_url), "%s",
                          val);
        } else if (std::strcmp(key, "preferred_ip") == 0 && val[0]) {
            std::snprintf(m->netplay_host_ip, sizeof(m->netplay_host_ip), "%s",
                          val);
            std::snprintf(m->netplay_host_local_ip,
                          sizeof(m->netplay_host_local_ip), "%s", val);
        } else if (std::strcmp(key, "preferred_port") == 0 && val[0]) {
            std::snprintf(m->netplay_host_port, sizeof(m->netplay_host_port),
                          "%s", val);
        }
        /* Legacy force_turn= lines are ignored — Lobby Settings owns relay. */
    }
    std::fclose(f);
    const auto* np = np_cb(m);
    if (np && np->set_lobby_url && m->netplay_lobby_url[0])
        np->set_lobby_url(np->ctx, m->netplay_lobby_url);
}

static void np_ensure_public_ip(LauncherModel* m) {
    if (!m || m->netplay_public_ip_resolved) return;
    const auto* np = np_cb(m);
    m->netplay_public_ip_resolved = true;
    if (np && np->external_ip &&
        np->external_ip(np->ctx, m->netplay_public_ip,
                        sizeof(m->netplay_public_ip)) &&
        m->netplay_public_ip[0]) {
        return;
    }
    std::snprintf(m->netplay_public_ip, sizeof(m->netplay_public_ip),
                  "Unavailable");
}

void draw_netplay_player_modal(LauncherModel* m) {
    if (m->netplay_name_modal_open) ImGui::OpenPopup("Player Name");
    ImVec2 center = ImGui::GetMainViewport()->GetCenter();
    ImGui::SetNextWindowPos(center, ImGuiCond_Appearing, ImVec2(0.5f, 0.5f));
    if (ImGui::BeginPopupModal("Player Name", nullptr, ImGuiWindowFlags_AlwaysAutoResize)) {
        ImGui::SetNextItemWidth(px(320));
        bool save = ImGui::InputText("##player_name", m->netplay_name_edit,
                                     sizeof(m->netplay_name_edit),
                                     ImGuiInputTextFlags_EnterReturnsTrue);
        ImGui::Spacing();
        if (ImGui::Button("Cancel", ImVec2(px(120), 0))) {
            const bool required_name = m->s.netplay_player_name[0] == '\0';
            std::snprintf(m->netplay_name_edit, sizeof(m->netplay_name_edit), "%s",
                          m->s.netplay_player_name);
            m->netplay_name_modal_open = false;
            if (required_name) {
                m->netplay_name_prompted = false;
                launcher_model_set_view(m, LNG_VIEW_DASHBOARD);
            }
            ImGui::CloseCurrentPopup();
        }
        ImGui::SameLine();
        const bool valid_name = m->netplay_name_edit[0] != '\0';
        ImGui::BeginDisabled(!valid_name);
        if ((ImGui::Button("Save", ImVec2(px(120), 0)) || save) && valid_name) {
            char previous_default[96];
            std::snprintf(previous_default, sizeof(previous_default), "%s's Lobby",
                          m->s.netplay_player_name);
            const bool update_lobby_name = !m->netplay_host_name[0] ||
                std::strcmp(m->netplay_host_name, previous_default) == 0;
            std::snprintf(m->s.netplay_player_name, sizeof(m->s.netplay_player_name), "%s",
                          m->netplay_name_edit);
            if (update_lobby_name)
                std::snprintf(m->netplay_host_name, sizeof(m->netplay_host_name),
                              "%s's Lobby", m->s.netplay_player_name);
            const auto* np = np_cb(m);
            if (np && np->set_player_name) np->set_player_name(np->ctx, m->s.netplay_player_name);
            m->netplay_name_modal_open = false;
            ImGui::CloseCurrentPopup();
        }
        ImGui::EndDisabled();
        ImGui::EndPopup();
    }
}

/* Delay-sync only (no rollback / prediction runway). At ~60 Hz, one frame is
 * ~16.67 ms, so one-way RTT coverage is ceil(RTT_ms / 33.33) frames. Add a
 * jitter/TURN pad — Battleship's lower tiers assume prediction absorbs the
 * rest of the path and are too aggressive here. */
static int np_delay_frames_from_rtt_ms(int rtt_ms) {
    if (rtt_ms < 0) rtt_ms = 0;
    /* ceil(rtt / 33.333) via integer ceil: (rtt + 32) / 33, floor at 1. */
    int one_way_frames = (rtt_ms + 32) / 33;
    if (one_way_frames < 1) one_way_frames = 1;
    const int kJitterPad = 3; /* ICE/TURN variance + scheduling slack */
    int delay = one_way_frames + kJitterPad;
    if (delay < 3) delay = 3;   /* delay-only floor (above Battleship's D=2) */
    if (delay > 20) delay = 20;
    return delay;
}

/* Rollback D from measured lobby RTT (§59: WAN-aware tiers).
 *
 * Pre-§59 table was BattleShip-feel aggressive (50–80 ms → D=3). MotK §56/§57
 * soaks showed a TURN WAN link with lobby RTT in that band still needs D=5–6
 * once transit+jitter are counted (lead ≈ D−1−transit), and the session spent
 * its first minute invent-storming until arrival-driven auto-delay caught up.
 * Tiers are +1..+2 vs the old table; floor 3. Callers apply an extra TURN
 * floor (see Play) because lobby UDP RTT underestimates the game path. */
static int np_rb_delay_frames_from_rtt_ms(int rtt_ms) {
    if (rtt_ms < 0) rtt_ms = 0;
    int d;
    if (rtt_ms < 20) d = 3;
    else if (rtt_ms < 50) d = 3;
    else if (rtt_ms < 80) d = 4;
    else if (rtt_ms < 120) d = 5;
    else if (rtt_ms < 160) d = 6;
    else if (rtt_ms < 200) d = 7;
    else if (rtt_ms < 260) d = 8;
    else d = 9;
    if (d < 3) d = 3;
    if (d > 12) d = 12;
    return d;
}

/* Invent runway: P = 4 + D (deterministic; matches the MotK RTT table). */
static int np_rb_prediction_frames_from_rtt_ms(int rtt_ms, int delay_frames) {
    (void)rtt_ms;
    if (delay_frames < 2) delay_frames = 2;
    int p = 4 + delay_frames;
    if (p < 6) p = 6;
    if (p > 16) p = 16;
    return p;
}

static int np_lobby_max_peer_rtt_ms(LauncherModel* m,
                                    const RecompLauncherCNetplayCallbacks* np) {
    int max_rtt = 0;
    if (!np || !np->member_count || !np->member_get) return 0;
    const int nmem = np->member_count(np->ctx);
    for (int mi = 0; mi < nmem; ++mi) {
        RecompLauncherCNetplayMember mem{};
        if (!np->member_get(np->ctx, mi, &mem)) continue;
        if (mem.is_local) continue;
        if (mem.latency_ms > max_rtt) max_rtt = mem.latency_ms;
    }
    (void)m;
    return max_rtt;
}

static int np_game_max_players(const LauncherModel* m) {
    int n = (m && m->player_count > 0) ? m->player_count : 2;
    if (n < 2) n = 2;
    if (n > RECOMP_LAUNCHER_NETPLAY_MAX_MEMBERS)
        n = RECOMP_LAUNCHER_NETPLAY_MAX_MEMBERS;
    return n;
}

static int np_clamp_host_max_players(LauncherModel* m) {
    const int game_max = np_game_max_players(m);
    /* Lobby/delay-sync ceiling: RECOMP_LAUNCHER_NETPLAY_MAX_MEMBERS / RNET_MAX_SLOTS. */
    const int sync_max = game_max < RECOMP_LAUNCHER_NETPLAY_MAX_MEMBERS
                             ? game_max : RECOMP_LAUNCHER_NETPLAY_MAX_MEMBERS;
    int n = m->netplay_host_max_players;
    if (n < 2) n = 2;
    if (n > sync_max) n = sync_max;
    m->netplay_host_max_players = n;
    return n;
}

void draw_netplay_direct_modal(LauncherModel* m, const LauncherTheme& th) {
    if (m->netplay_direct_modal_open) ImGui::OpenPopup("Join Direct");
    ImVec2 center = ImGui::GetMainViewport()->GetCenter();
    ImGui::SetNextWindowPos(center, ImGuiCond_Appearing, ImVec2(0.5f, 0.5f));
    if (ImGui::BeginPopupModal("Join Direct", nullptr, ImGuiWindowFlags_AlwaysAutoResize)) {
        ImGui::TextWrapped(
            "Join a LAN/Direct IP lobby by IP (or pick a LAN row from the "
            "lobby list after Refresh — hosts announce via UDP broadcast). "
            "The host must create with LAN/Direct IP Only checked and keep "
            "the waiting room open. Use their LAN IP on the same network, or "
            "their Public IP with UDP port-forwarded to the host PC. Online "
            "(MotK) lobbies: join from the server list instead.");
        ImGui::Spacing();
        ImGui::SetNextItemWidth(px(280));
        ImGui::InputText("Host IP", m->netplay_direct_ip, sizeof(m->netplay_direct_ip));
        ImGui::SetNextItemWidth(px(160));
        ImGui::InputText("Port", m->netplay_direct_port, sizeof(m->netplay_direct_port),
                         ImGuiInputTextFlags_CharsDecimal);
        ImGui::SetNextItemWidth(px(280));
        ImGui::InputText("Password (optional)", m->netplay_password,
                         sizeof(m->netplay_password),
                         ImGuiInputTextFlags_Password);
        ImGui::Spacing();
        if (m->netplay_status[0])
            ImGui::TextColored(col(th.warn), "%s", m->netplay_status);
        if (ImGui::Button("Cancel", ImVec2(px(120), 0))) {
            m->netplay_direct_modal_open = false;
            ImGui::CloseCurrentPopup();
        }
        ImGui::SameLine();
        const bool can_join = m->netplay_direct_ip[0] && np_valid_port(m->netplay_direct_port);
        ImGui::BeginDisabled(!can_join);
        if (ImGui::Button("Join Direct", ImVec2(px(140), 0))) {
            const auto* np = np_cb(m);
            if (np && np->join) {
                char lobby_id[96];
                char guest_bind[64];
                std::snprintf(lobby_id, sizeof(lobby_id), "lan:%s:%s",
                              m->netplay_direct_ip[0] ? m->netplay_direct_ip : "127.0.0.1",
                              m->netplay_direct_port[0] ? m->netplay_direct_port : "7777");
                if (np_prepare_guest_bind(guest_bind, sizeof(guest_bind),
                                          m->netplay_status, sizeof(m->netplay_status))) {
                const int rc = np->join(np->ctx, lobby_id, m->netplay_password, guest_bind);
                if (rc == 0) {
                    m->netplay_local_room = true;
                    std::snprintf(m->netplay_host_endpoint, sizeof(m->netplay_host_endpoint),
                                  "%s", lobby_id + 4);
                    m->netplay_lobby_max_slots = np_game_max_players(m);
                    m->netplay_status[0] = '\0';
                    m->netplay_direct_modal_open = false;
                    ImGui::CloseCurrentPopup();
                } else if (rc == -2) {
                    std::snprintf(m->netplay_status, sizeof(m->netplay_status),
                                  "Incorrect password.");
                } else if (rc == -3) {
                    std::snprintf(m->netplay_status, sizeof(m->netplay_status),
                                  "No response from that IP:port. Check the host is in "
                                  "the LAN waiting room, UDP is forwarded, and the "
                                  "firewall allows the game port.");
                } else {
                    std::snprintf(m->netplay_status, sizeof(m->netplay_status),
                                  "Could not join (lobby full, already started, or "
                                  "game/version mismatch).");
                }
                }
            }
        }
        ImGui::EndDisabled();
        ImGui::EndPopup();
    }
}

void draw_netplay_network_modal(LauncherModel* m, const LauncherTheme& th) {
    if (m->netplay_network_modal_open) ImGui::OpenPopup("Network Settings");
    ImVec2 center = ImGui::GetMainViewport()->GetCenter();
    ImGui::SetNextWindowPos(center, ImGuiCond_Appearing, ImVec2(0.5f, 0.5f));
    ImGui::SetNextWindowSize(ImVec2(px(520), 0), ImGuiCond_Appearing);
    if (ImGui::BeginPopupModal("Network Settings", nullptr,
                               ImGuiWindowFlags_AlwaysAutoResize)) {
        ImGui::TextColored(col(th.text_muted), "Lobby server URL");
        ImGui::SetNextItemWidth(px(440));
        bool save = ImGui::InputText("##lobby_server_url", m->netplay_lobby_url,
                                     sizeof(m->netplay_lobby_url),
                                     ImGuiInputTextFlags_EnterReturnsTrue);
        ImGui::Spacing();
        if (ImGui::Button("Cancel", ImVec2(px(120), 0))) {
            const auto* np = np_cb(m);
            const char* current = np && np->default_url ? np->default_url(np->ctx) : "";
            std::snprintf(m->netplay_lobby_url, sizeof(m->netplay_lobby_url), "%s",
                          current ? current : "");
            m->netplay_network_modal_open = false;
            ImGui::CloseCurrentPopup();
        }
        ImGui::SameLine();
        const bool valid_url = m->netplay_lobby_url[0] != '\0';
        ImGui::BeginDisabled(!valid_url);
        if ((ImGui::Button("Save", ImVec2(px(120), 0)) || save) && valid_url) {
            const auto* np = np_cb(m);
            if (np && np->set_lobby_url)
                np->set_lobby_url(np->ctx, m->netplay_lobby_url);
            np_save_network_settings(m);
            np_connect_and_list(m);
            m->netplay_network_modal_open = false;
            ImGui::CloseCurrentPopup();
        }
        ImGui::EndDisabled();
        ImGui::EndPopup();
    }
}

void draw_netplay_host_modal(LauncherModel* m, const LauncherTheme& th) {
    /* Create errors stay in this modal — not m->netplay_status (list banner). */
    static char host_create_status[160] = "";
    if (m->netplay_host_modal_open) ImGui::OpenPopup("Host Lobby");
    ImVec2 center = ImGui::GetMainViewport()->GetCenter();
    ImGui::SetNextWindowPos(center, ImGuiCond_Appearing, ImVec2(0.5f, 0.5f));
    ImGui::SetNextWindowSize(ImVec2(px(520), 0), ImGuiCond_Appearing);
    if (ImGui::BeginPopupModal("Host Lobby", nullptr, ImGuiWindowFlags_AlwaysAutoResize)) {
        ImGui::TextColored(col(th.text_muted), "Lobby name");
        ImGui::SetNextItemWidth(px(430));
        ImGui::InputText("##host_lobby_name", m->netplay_host_name,
                         sizeof(m->netplay_host_name));
        ImGui::Spacing();
        {
            const int game_max = np_game_max_players(m);
            const int sync_max = game_max < RECOMP_LAUNCHER_NETPLAY_MAX_MEMBERS
                                     ? game_max : RECOMP_LAUNCHER_NETPLAY_MAX_MEMBERS;
            const bool game_locked = sync_max <= 2;
            const int max_players = np_clamp_host_max_players(m);
            ImGui::TextColored(col(th.text_muted), "Max Players");
            ImGui::SetNextItemWidth(px(140));
            ImGui::BeginDisabled(game_locked);
            char preview[8];
            std::snprintf(preview, sizeof(preview), "%d", max_players);
            if (ImGui::BeginCombo("##host_max_players", preview)) {
                for (int n = 2; n <= sync_max; ++n) {
                    char label[8];
                    std::snprintf(label, sizeof(label), "%d", n);
                    const bool selected = n == max_players;
                    if (ImGui::Selectable(label, selected))
                        m->netplay_host_max_players = n;
                    if (selected) ImGui::SetItemDefaultFocus();
                }
                ImGui::EndCombo();
            }
            ImGui::EndDisabled();
            if (game_locked) {
                ImGui::SameLine();
                ImGui::TextColored(col(th.text_muted), "(this game is 2-player)");
            }
        }
        ImGui::Spacing();
        bool lan = m->netplay_lan_only;
        if (ImGui::Checkbox("LAN/Direct IP Only", &lan)) {
            m->netplay_lan_only = lan;
            /* Keep the enumerated interfaces + selection; only the enabled
             * state changes. Refresh if we somehow have no list yet. */
            if (m->netplay_local_address_count == 0)
                np_refresh_host_ip(m);
        }
        /* Advertised IP/Port: which NIC + port peers should use for LAN RTT /
         * Direct IP. Online still STUNs for a public endpoint; this pick is the
         * preferred LAN advertise / bind address. */
        if (ImGui::BeginTable("##host_lan_conn", 2, ImGuiTableFlags_SizingFixedFit)) {
            ImGui::TableSetupColumn("ip", ImGuiTableColumnFlags_WidthFixed, px(300));
            ImGui::TableSetupColumn("port", ImGuiTableColumnFlags_WidthFixed, px(120));
            ImGui::TableNextRow();
            ImGui::TableSetColumnIndex(0);
            ImGui::TextColored(col(th.text_muted), "Advertised IP Address");
            ImGui::TableSetColumnIndex(1);
            ImGui::TextColored(col(th.text_muted), "Port");
            ImGui::TableNextRow();
            ImGui::TableSetColumnIndex(0);
            ImGui::SetNextItemWidth(-1.0f);
            if (m->netplay_local_address_count > 1) {
                int selected = 0;
                for (int index = 0; index < m->netplay_local_address_count; ++index) {
                    if (std::strcmp(m->netplay_host_ip,
                                    m->netplay_local_addresses[index].address) == 0) {
                        selected = index;
                        break;
                    }
                }
                char preview[144];
                np_format_local_address(m->netplay_local_addresses[selected],
                                        preview, sizeof(preview));
                if (ImGui::BeginCombo("##host_ip", preview)) {
                    for (int index = 0; index < m->netplay_local_address_count; ++index) {
                        char choice[144];
                        np_format_local_address(m->netplay_local_addresses[index],
                                                choice, sizeof(choice));
                        const bool is_selected = index == selected;
                        if (ImGui::Selectable(choice, is_selected)) {
                            std::snprintf(m->netplay_host_ip, sizeof(m->netplay_host_ip),
                                          "%s", m->netplay_local_addresses[index].address);
                            std::snprintf(m->netplay_host_local_ip,
                                          sizeof(m->netplay_host_local_ip), "%s",
                                          m->netplay_local_addresses[index].address);
                            np_save_network_settings(m);
                        }
                        if (is_selected) ImGui::SetItemDefaultFocus();
                    }
                    ImGui::EndCombo();
                }
            } else {
                ImGui::InputText("##host_ip", m->netplay_host_ip,
                                 sizeof(m->netplay_host_ip),
                                 ImGuiInputTextFlags_ReadOnly);
            }
            ImGui::TableSetColumnIndex(1);
            ImGui::SetNextItemWidth(-1.0f);
            ImGui::InputText("##host_port", m->netplay_host_port,
                             sizeof(m->netplay_host_port),
                             ImGuiInputTextFlags_CharsDecimal);
            if (ImGui::IsItemDeactivatedAfterEdit())
                np_save_network_settings(m);
            ImGui::EndTable();
        }
        ImGui::Spacing();
        ImGui::TextColored(col(th.text_muted), "Password (optional)");
        ImGui::SetNextItemWidth(px(430));
        ImGui::InputText("##host_password", m->netplay_host_password,
                         sizeof(m->netplay_host_password), ImGuiInputTextFlags_Password);
        ImGui::Spacing();
        if (ImGui::Button("Cancel", ImVec2(px(120), 0))) {
            host_create_status[0] = '\0';
            m->netplay_host_modal_open = false;
            ImGui::CloseCurrentPopup();
        }
        ImGui::SameLine();
        const bool can_create =
            np_valid_port(m->netplay_host_port) &&
            m->netplay_host_ip[0] &&
            std::strcmp(m->netplay_host_ip, "Unavailable") != 0 &&
            std::strcmp(m->netplay_host_ip, "Detecting...") != 0 &&
            launcher_model_netplay_disc_ok(m);
        ImGui::BeginDisabled(!can_create);
        if (ImGui::Button("Create Lobby", ImVec2(px(150), 0))) {
            if (!launcher_model_netplay_disc_ok(m)) {
                std::snprintf(host_create_status, sizeof(host_create_status), "%s",
                              m->verify.netplay_detail[0]
                                  ? m->verify.netplay_detail
                                  : "Disc TOC not valid for netplay.");
            } else {
            const auto* np = np_cb(m);
            if (np && np->create) {
                /* Online create needs the lobby WebSocket. LAN/Direct IP only
                 * publishes the local registry — do not connect or advertise
                 * there, or the same room would appear twice in the list. */
                if (!m->netplay_lan_only)
                    np_connect_and_list(m);
                /* Selected NIC:port is the advertised / preferred bind address
                 * for both LAN-only and online (online may bump the port). */
                char endpoint[96];
                const char* port_label = m->netplay_host_port[0]
                    ? m->netplay_host_port : "7777";
                std::snprintf(endpoint, sizeof(endpoint), "%s:%s",
                              m->netplay_host_ip[0] ? m->netplay_host_ip : "127.0.0.1",
                              port_label);
                /* LAN requires the exact UI port; online auto-picks nearby if
                 * the preferred port is busy. */
                const int want_port = launcher_endpoint_port(endpoint);
                bool port_ok = true;
                if (m->netplay_lan_only) {
                    if (!launcher_udp_port_available(want_port)) {
                        std::snprintf(host_create_status, sizeof(host_create_status),
                                      "Port %s is already in use. Choose a "
                                      "different port for this LAN lobby.",
                                      port_label);
                        port_ok = false;
                    }
                } else {
                    const int free_port =
                        launcher_udp_find_free_port(/*preferred=*/want_port, 32);
                    if (free_port < 0 ||
                        (free_port != want_port &&
                         launcher_endpoint_set_port(endpoint, sizeof(endpoint),
                                                    free_port) != 0)) {
                        std::snprintf(host_create_status, sizeof(host_create_status),
                                      "No free UDP port near %s. Try again.",
                                      port_label);
                        port_ok = false;
                    }
                }
                if (port_ok) {
                    const char* lobby = m->netplay_host_name[0]
                        ? m->netplay_host_name : "Netplay Lobby";
                    const int max_slots = np_clamp_host_max_players(m);
                    /* Seed host match_caps from UI defaults before create. */
                    if (np->rollback_set)
                        (void)np->rollback_set(np->ctx,
                                               m->netplay_rollback ? 1 : 0);
                    if (np->input_prediction_set)
                        (void)np->input_prediction_set(
                            np->ctx, m->netplay_lobby_input_prediction);
                    if (np->input_delay_set)
                        (void)np->input_delay_set(np->ctx,
                                                  m->netplay_lobby_input_delay);
                    const int rc = np->create(np->ctx, lobby, endpoint,
                                              m->netplay_host_password, &m->s,
                                              m->netplay_lan_only ? 1 : 0,
                                              max_slots);
                    if (rc == -4) {
                        std::snprintf(host_create_status, sizeof(host_create_status),
                                      m->netplay_lan_only
                                          ? "Port %s is already in use. Choose a "
                                            "different port for this LAN lobby."
                                          : "No free UDP port near %s. Try again.",
                                      port_label);
                    } else if (rc != 0) {
                        std::snprintf(host_create_status, sizeof(host_create_status),
                                      "Could not create lobby.");
                    } else {
                        if (const char* colon = std::strrchr(endpoint, ':')) {
                            std::snprintf(m->netplay_host_port,
                                          sizeof(m->netplay_host_port), "%s",
                                          colon + 1);
                        }
                        std::snprintf(m->netplay_host_endpoint,
                                      sizeof(m->netplay_host_endpoint), "%s",
                                      endpoint);
                        std::snprintf(m->netplay_host_local_ip,
                                      sizeof(m->netplay_host_local_ip), "%s",
                                      m->netplay_host_ip);
                        np_save_network_settings(m);
                        m->netplay_lobby_max_slots = max_slots;
                        host_create_status[0] = '\0';
                        /* LAN/Direct IP is a local room (file registry). Online
                         * create seats on the WebSocket lobby when connected. */
                        m->netplay_local_room =
                            m->netplay_lan_only || !np_connected(m);
                        m->netplay_host_modal_open = false;
                        ImGui::CloseCurrentPopup();
                    }
                }
            }
            } /* else disc ok */
        }
        ImGui::EndDisabled();
        if (!launcher_model_netplay_disc_ok(m) && ImGui::IsItemHovered(ImGuiHoveredFlags_AllowWhenDisabled))
            ImGui::SetTooltip("%s",
                              m->verify.netplay_detail[0]
                                  ? m->verify.netplay_detail
                                  : "Mount the supported .cue dump for netplay.");
        if (host_create_status[0])
            ImGui::TextColored(col(th.warn), "%s", host_create_status);
        ImGui::EndPopup();
    } else {
        host_create_status[0] = '\0';
    }
}

void draw_netplay_password_modal(LauncherModel* m, const LauncherTheme& th) {
    if (m->netplay_password_modal_open) ImGui::OpenPopup("Join Lobby");
    ImVec2 center = ImGui::GetMainViewport()->GetCenter();
    ImGui::SetNextWindowPos(center, ImGuiCond_Appearing, ImVec2(0.5f, 0.5f));
    if (ImGui::BeginPopupModal("Join Lobby", nullptr, ImGuiWindowFlags_AlwaysAutoResize)) {
        ImGui::SetNextItemWidth(px(320));
        ImGui::InputText("Password", m->netplay_password, sizeof(m->netplay_password),
                         ImGuiInputTextFlags_Password);
        if (m->netplay_status[0])
            ImGui::TextColored(col(th.warn), "%s", m->netplay_status);
        ImGui::Spacing();
        if (ImGui::Button("Cancel", ImVec2(px(120), 0))) {
            m->netplay_password_modal_open = false;
            ImGui::CloseCurrentPopup();
        }
        ImGui::SameLine();
        if (ImGui::Button("Join", ImVec2(px(120), 0))) {
            const auto* np = np_cb(m);
            RecompLauncherCNetplayLobby row{};
            if (np && np->list_get && np->join &&
                np->list_get(np->ctx, m->netplay_selected_lobby, &row)) {
                char guest_bind[64];
                if (np_prepare_guest_bind(guest_bind, sizeof(guest_bind),
                                          m->netplay_status, sizeof(m->netplay_status))) {
                int rc = np->join(np->ctx, row.lobby_id, m->netplay_password, guest_bind);
                if (rc == 0) {
                    if (strncmp(row.lobby_id, "lan:", 4) == 0) {
                        m->netplay_local_room = true;
                        std::snprintf(m->netplay_host_endpoint,
                                      sizeof(m->netplay_host_endpoint), "%s",
                                      row.lobby_id + 4);
                    } else {
                        /* Server list join — never inherit LAN header state. */
                        m->netplay_local_room = false;
                        m->netplay_host_endpoint[0] = '\0';
                    }
                    m->netplay_lobby_max_slots =
                        row.max_slots >= 2 ? row.max_slots : np_game_max_players(m);
                    m->netplay_password_modal_open = false;
                    m->netplay_status[0] = '\0';
                    ImGui::CloseCurrentPopup();
                } else if (rc == -2) {
                    std::snprintf(m->netplay_status, sizeof(m->netplay_status),
                                  "Incorrect password.");
                } else if (rc == -3) {
                    std::snprintf(m->netplay_status, sizeof(m->netplay_status),
                                  "No LAN/Direct IP lobby at that address.");
                } else {
                    std::snprintf(m->netplay_status, sizeof(m->netplay_status),
                                  "Could not join lobby.");
                }
                }
            }
        }
        ImGui::EndPopup();
    }
}

/* Vertically center the next widget inside a fixed-height table row. */
static void table_row_vcenter(float row_h, float content_h) {
    const ImVec2 p = ImGui::GetCursorScreenPos();
    const float y = p.y + (row_h - content_h) * 0.5f;
    ImGui::SetCursorScreenPos(ImVec2(p.x, y));
}

static void np_ingest_last_error(LauncherModel* m, const RecompLauncherCNetplayCallbacks* np) {
    if (!m || !np || !np->last_error) return;
    const char* err = np->last_error(np->ctx);
    if (!err || !err[0]) return;
    if (std::strcmp(err, "need_players") == 0)
        std::snprintf(m->netplay_status, sizeof(m->netplay_status),
                      "Need two players before starting.");
    else if (std::strcmp(err, "missing_endpoints") == 0)
        std::snprintf(m->netplay_status, sizeof(m->netplay_status),
                      "Peer connection info missing — have guests rejoin, then "
                      "retry Play.");
    else if (std::strcmp(err, "relay_unavailable") == 0)
        std::snprintf(m->netplay_status, sizeof(m->netplay_status),
                      "Lobby UDP SFU is unavailable. Fix INPUT_RELAY_* on "
                      "the lobby server (online matches require it).");
    else if (std::strcmp(err, "host_slot_fixed") == 0)
        std::snprintf(m->netplay_status, sizeof(m->netplay_status),
                      "Host stays in seat 1. Rearrange guests among the "
                      "other seats.");
    else if (std::strcmp(err, "not_host") == 0)
        std::snprintf(m->netplay_status, sizeof(m->netplay_status),
                      "Only the host can start the match.");
    else if (std::strcmp(err, "not_all_ready") == 0)
        std::snprintf(m->netplay_status, sizeof(m->netplay_status),
                      "Lobby server is outdated (ready gate). Retry Play, or "
                      "redeploy recomp-net-server main.");
    else if (std::strcmp(err, "connect_timeout_ice") == 0)
        std::snprintf(m->netplay_status, sizeof(m->netplay_status),
                      "Online connection timed out. Allow the game through "
                      "your firewall, then rejoin and retry.");
    else if (std::strcmp(err, "connect_timeout_lan") == 0)
        std::snprintf(m->netplay_status, sizeof(m->netplay_status),
                      "LAN connection timed out. Check the address, firewall, "
                      "and that both players are still in the lobby.");
    else if (std::strcmp(err, "peer_disconnected") == 0)
        std::snprintf(m->netplay_status, sizeof(m->netplay_status),
                      "The other player stopped responding. Rejoin to retry.");
    else if (std::strcmp(err, "transport_unavailable") == 0)
        std::snprintf(m->netplay_status, sizeof(m->netplay_status),
                      "Online transport could not start. This build must "
                      "include ICE/NAT traversal.");
    else if (std::strcmp(err, "netplay_start_failed") == 0)
        std::snprintf(m->netplay_status, sizeof(m->netplay_status),
                      "Netplay could not start. Check the log and retry.");
    else if (std::strcmp(err, "disc_mismatch") == 0)
        std::snprintf(m->netplay_status, sizeof(m->netplay_status),
                      "Disc dump does not match the host (TOC / tracks). "
                      "Mount the same supported .cue dump.");
    else if (std::strcmp(err, "version_mismatch") == 0)
        std::snprintf(m->netplay_status, sizeof(m->netplay_status),
                      "Game version does not match the lobby.");
    else if (std::strcmp(err, "game_mismatch") == 0)
        std::snprintf(m->netplay_status, sizeof(m->netplay_status),
                      "This lobby is for a different game.");
    else
        std::snprintf(m->netplay_status, sizeof(m->netplay_status),
                      "Lobby error: %s", err);
    if (np->clear_last_error) np->clear_last_error(np->ctx);
}

void draw_netplay_room_modal(LauncherModel* m, const LauncherTheme& th) {
    const auto* np = np_cb(m);
    if (!np) return;
    /* Keep membership live while the room modal is up (join/leave/move/kick). */
    if (np->pump) np->pump(np->ctx);
    np_ingest_last_error(m, np);
    if (np->launch_pending && np->launch_pending(np->ctx))
        np_try_launch(m);
    /* Prefer backend seat; sticky local_room alone kept kicked LAN joiners open. */
    const bool seated = np->in_lobby ? (np->in_lobby(np->ctx) != 0)
                                     : m->netplay_local_room;
    if (!seated) {
        m->netplay_local_room = false;
        m->netplay_lobby_settings_open = false;
        /* Keep netplay_lobby_max_slots across create/join races: online create
         * can report unseated for a few frames, and wiping this falls back to
         * game num_players (e.g. 5P) while the list correctly shows 1/2. */
        if (ImGui::BeginPopupModal("LOBBY", nullptr, ImGuiWindowFlags_AlwaysAutoResize)) {
            ImGui::CloseCurrentPopup();
            ImGui::EndPopup();
        }
        return;
    }

    ImGui::OpenPopup("LOBBY");
    ImVec2 center = ImGui::GetMainViewport()->GetCenter();
    /* Always recenter: content height changes as members join/leave, and
     * ImGuiCond_Appearing left the room modal stuck off-center after join. */
    ImGui::SetNextWindowPos(center, ImGuiCond_Always, ImVec2(0.5f, 0.5f));
    ImGui::SetNextWindowSize(ImVec2(px(640), 0), ImGuiCond_Always);
    const ImGuiWindowFlags lobby_flags =
        ImGuiWindowFlags_AlwaysAutoResize | ImGuiWindowFlags_NoMove;
    if (!ImGui::BeginPopupModal("LOBBY", nullptr, lobby_flags)) return;

    /* Only file-backed LAN/Direct rooms show IP/Port. Server-list joins always
     * show the lobby URL — do not use Host Lobby's LAN checkbox or a stale
     * host_endpoint (e.g. from a prior LAN host) as a signal. */
    const bool show_lan_endpoint = m->netplay_local_room;
    if (show_lan_endpoint) {
        char room_ip[64] = "";
        char room_port[16] = "7777";
        if (m->netplay_host_endpoint[0]) {
            std::snprintf(room_ip, sizeof(room_ip), "%s", m->netplay_host_endpoint);
            char* colon = strrchr(room_ip, ':');
            if (colon) {
                std::snprintf(room_port, sizeof(room_port), "%s", colon + 1);
                *colon = '\0';
            }
        }
        np_ensure_public_ip(m);
        if (ImGui::BeginTable("##lobby_lan_conn", 2, ImGuiTableFlags_SizingFixedFit)) {
            ImGui::TableSetupColumn("ip", ImGuiTableColumnFlags_WidthFixed, px(360));
            ImGui::TableSetupColumn("port", ImGuiTableColumnFlags_WidthFixed, px(120));
            ImGui::TableNextRow();
            ImGui::TableSetColumnIndex(0);
            ImGui::TextColored(col(th.text_muted), "LAN IP Address");
            ImGui::TableSetColumnIndex(1);
            ImGui::TextColored(col(th.text_muted), "Port");
            ImGui::TableNextRow();
            ImGui::TableSetColumnIndex(0);
            ImGui::SetNextItemWidth(-1.0f);
            np_copyable_readonly_input("##lobby_ip", room_ip, sizeof(room_ip), th);
            ImGui::TableSetColumnIndex(1);
            ImGui::SetNextItemWidth(-1.0f);
            np_copyable_readonly_input("##lobby_port", room_port, sizeof(room_port),
                                       th);
            ImGui::EndTable();
        }
        ImGui::Spacing();
        ImGui::TextColored(col(th.text_muted), "Public IP Address");
        if (ImGui::BeginTable("##lobby_public_ip", 2, ImGuiTableFlags_SizingFixedFit)) {
            ImGui::TableSetupColumn("ip", ImGuiTableColumnFlags_WidthFixed, px(440));
            ImGui::TableSetupColumn("help", ImGuiTableColumnFlags_WidthFixed, px(36));
            ImGui::TableNextRow();
            ImGui::TableSetColumnIndex(0);
            ImGui::SetNextItemWidth(-1.0f);
            np_copyable_readonly_input("##lobby_public_ip", m->netplay_public_ip,
                                       sizeof(m->netplay_public_ip), th);
            ImGui::TableSetColumnIndex(1);
            const float help_sz = ImGui::GetFrameHeight();
            if (ImGui::Button("?", ImVec2(help_sz, help_sz))) {
                /* tooltip on hover only */
            }
            if (ImGui::IsItemHovered(ImGuiHoveredFlags_DelayNormal)) {
                ImGui::BeginTooltip();
                ImGui::PushTextWrapPos(px(360));
                ImGui::TextUnformatted(
                    "Direct IP over the internet needs UDP port forwarding on "
                    "your router.\n\n"
                    "1. On your router, forward the Port shown above (UDP) from "
                    "the Public IP Address to this PC's LAN IP Address.\n"
                    "2. Remote friends Join Direct with your Public IP and that "
                    "Port.\n"
                    "3. Players on your local network can keep using the LAN IP "
                    "Address.\n\n"
                    "Router menus differ (Port Forwarding, Virtual Server, or "
                    "NAT). Leave the lobby open while they connect.");
                ImGui::PopTextWrapPos();
                ImGui::EndTooltip();
            }
            ImGui::EndTable();
        }
    } else {
        char lobby_server[256];
        const char* url = np->default_url ? np->default_url(np->ctx) : "";
        if (!url || !url[0]) url = m->netplay_lobby_url;
        std::snprintf(lobby_server, sizeof(lobby_server), "%s",
                      (url && url[0]) ? url : "lobby server");
        ImGui::TextColored(col(th.text_muted), "Lobby Server");
        ImGui::SetNextItemWidth(px(480));
        np_copyable_readonly_input("##lobby_server", lobby_server,
                                   sizeof(lobby_server), th);
    }
    ImGui::Spacing();
    ImGui::Separator();
    ImGui::Spacing();
#if RECOMP_UI_ENABLE_MODS
    if (m->mods) {
        ImGui::TextColored(col(th.text_muted),
                           "Mods are disabled for netplay (vanilla match).");
        ImGui::Spacing();
    }
#endif
    if (m->netplay_status[0]) {
        ImGui::TextColored(col(th.warn), "%s", m->netplay_status);
        ImGui::Spacing();
    }

    RecompLauncherCNetplayMember slots[RECOMP_LAUNCHER_NETPLAY_MAX_MEMBERS]{};
    bool occupied[RECOMP_LAUNCHER_NETPLAY_MAX_MEMBERS] = {};
    const bool is_host = np->is_host && np->is_host(np->ctx);
    const int count = np->member_count ? np->member_count(np->ctx) : 0;
    /* Prefer backend room ceiling, then sticky create/join value, then game max. */
    int max_slots = 0;
    if (np->lobby_max_slots) {
        max_slots = np->lobby_max_slots(np->ctx);
        if (max_slots >= 2) m->netplay_lobby_max_slots = max_slots;
    }
    if (max_slots < 2)
        max_slots = m->netplay_lobby_max_slots > 0
                        ? m->netplay_lobby_max_slots
                        : np_game_max_players(m);
    if (max_slots < 2) max_slots = 2;
    if (max_slots > RECOMP_LAUNCHER_NETPLAY_MAX_MEMBERS)
        max_slots = RECOMP_LAUNCHER_NETPLAY_MAX_MEMBERS;
    for (int i = 0; i < count; ++i) {
        RecompLauncherCNetplayMember mem{};
        if (!np->member_get || !np->member_get(np->ctx, i, &mem)) continue;
        if (mem.slot < 0 || mem.slot >= RECOMP_LAUNCHER_NETPLAY_MAX_MEMBERS) continue;
        slots[mem.slot] = mem;
        occupied[mem.slot] = mem.display_name[0] != '\0';
    }
    int seated_players = 0;
    for (int slot = 0; slot < max_slots; ++slot)
        if (occupied[slot]) ++seated_players;
    if (ImGui::BeginTable("lobby_players", 6,
                          ImGuiTableFlags_RowBg | ImGuiTableFlags_BordersInnerH |
                          ImGuiTableFlags_SizingStretchProp)) {
        ImGui::TableSetupColumn("##move", ImGuiTableColumnFlags_WidthFixed, px(32));
        ImGui::TableSetupColumn("Slot", ImGuiTableColumnFlags_WidthFixed, px(40));
        ImGui::TableSetupColumn("Player", ImGuiTableColumnFlags_WidthStretch);
        ImGui::TableSetupColumn("Status", ImGuiTableColumnFlags_WidthFixed, px(100));
        ImGui::TableSetupColumn("Latency", ImGuiTableColumnFlags_WidthFixed, px(72));
        ImGui::TableSetupColumn("Kick", ImGuiTableColumnFlags_WidthFixed, px(56));
        ImGui::TableHeadersRow();
        const float text_h = ImGui::GetTextLineHeight();
        for (int slot = 0; slot < max_slots; ++slot) {
            const float member_row_h = px(42);
            ImGui::PushID(slot);
            ImGui::TableNextRow(ImGuiTableRowFlags_None, member_row_h);
            ImGui::TableSetColumnIndex(0);
            ImVec2 row_pos = ImGui::GetCursorScreenPos();
            ImGui::Selectable("##member_row_drop", false,
                              ImGuiSelectableFlags_SpanAllColumns |
                              ImGuiSelectableFlags_AllowOverlap,
                              ImVec2(0, member_row_h));
            /* Slot 0 = session host / sim authority — guests rearrange only. */
            if (is_host && np->move_member && slot != 0 &&
                ImGui::BeginDragDropTarget()) {
                if (const ImGuiPayload* payload =
                        ImGui::AcceptDragDropPayload("NETPLAY_MEMBER_SLOT")) {
                    const int from_slot = *(const int*)payload->Data;
                    if (from_slot != slot && from_slot != 0)
                        (void)np->move_member(np->ctx, from_slot, slot);
                }
                ImGui::EndDragDropTarget();
            }
            ImGui::SetCursorScreenPos(row_pos);
            ImGui::InvisibleButton("##member_drag_handle", ImVec2(px(28), member_row_h));
            ImVec2 grip_min = ImGui::GetItemRectMin();
            ImVec2 grip_max = ImGui::GetItemRectMax();
            const float grip_cx = (grip_min.x + grip_max.x) * 0.5f;
            const float grip_cy = (grip_min.y + grip_max.y) * 0.5f;
            const int can_drag =
                is_host && occupied[slot] && slot != 0 && np->move_member;
            ImU32 grip_col = imcol(can_drag ? th.text_muted : th.border);
            ImDrawList* grip_dl = ImGui::GetWindowDrawList();
            for (int line = -1; line <= 1; ++line) {
                const float y = grip_cy + px(4) * line;
                grip_dl->AddLine(ImVec2(grip_cx - px(7), y),
                                 ImVec2(grip_cx + px(7), y), grip_col, px(1.5f));
            }
            if (can_drag) {
                if (ImGui::IsItemHovered()) ImGui::SetMouseCursor(ImGuiMouseCursor_Hand);
                if (ImGui::BeginDragDropSource(ImGuiDragDropFlags_SourceAllowNullID)) {
                    ImGui::SetDragDropPayload("NETPLAY_MEMBER_SLOT", &slot, sizeof(slot));
                    ImGui::BeginGroup();
                    ImGui::Text("P%d", slot + 1);
                    ImGui::SameLine(0, px(28));
                    ImGui::TextUnformatted(slots[slot].display_name);
                    ImGui::SameLine(0, px(28));
                    ImGui::TextColored(col(th.good), "%s",
                                       slots[slot].is_host ? "Host" : "Connected");
                    ImGui::EndGroup();
                    ImGui::EndDragDropSource();
                }
            }
            ImGui::TableSetColumnIndex(1);
            table_row_vcenter(member_row_h, text_h);
            ImGui::Text("P%d", slot + 1);
            ImGui::TableSetColumnIndex(2);
            table_row_vcenter(member_row_h, text_h);
            if (!occupied[slot]) ImGui::PushStyleColor(ImGuiCol_Text, col(th.text_muted));
            ImGui::TextUnformatted(occupied[slot] ? slots[slot].display_name : "Open slot");
            if (!occupied[slot]) ImGui::PopStyleColor();
            ImGui::TableSetColumnIndex(3);
            table_row_vcenter(member_row_h, text_h);
            if (occupied[slot] && slots[slot].is_host)
                ImGui::TextColored(col(th.good), "Host");
            else if (occupied[slot])
                ImGui::TextColored(col(th.good), "Connected");
            else
                ImGui::TextColored(col(th.text_muted), "Waiting");
            if (occupied[slot] && slots[slot].bios_offer_valid &&
                ImGui::IsItemHovered()) {
                ImGui::SetTooltip(
                    "BIOS: %s%s",
                    slots[slot].bios_prefer_openbios ? "OpenBIOS" : "SCPH-1001",
                    slots[slot].bios_can_scph1001 ? "" : " (no SCPH dump)");
            }
            ImGui::TableSetColumnIndex(4);
            table_row_vcenter(member_row_h, text_h);
            /* RTT to that seat from local peer — never on the local row. */
            if (occupied[slot] && !slots[slot].is_local &&
                slots[slot].latency_ms >= 0) {
                ImGui::Text("%d ms", slots[slot].latency_ms);
            } else {
                ImGui::TextColored(col(th.text_muted), "—");
            }
            ImGui::TableSetColumnIndex(5);
            {
                const float kick_btn = px(34);
                const bool can_kick = is_host && occupied[slot] &&
                                      !slots[slot].is_host && np->kick_member;
                ImVec2 cell = ImGui::GetCursorScreenPos();
                const float avail_x = ImGui::GetContentRegionAvail().x;
                ImGui::SetCursorScreenPos(ImVec2(
                    cell.x + (avail_x - kick_btn) * 0.5f,
                    cell.y + (member_row_h - kick_btn) * 0.5f));
                if (can_kick) {
                    /* Empty label + manual glyph draw: emoji fonts have uneven
                     * metrics so ButtonTextAlign alone leaves the boot off-center. */
                    const bool pressed =
                        ImGui::Button("##kick", ImVec2(kick_btn, kick_btn));
                    {
                        const char* boot = u8"\U0001F97E";
                        const ImVec2 rmin = ImGui::GetItemRectMin();
                        const ImVec2 rmax = ImGui::GetItemRectMax();
                        const ImVec2 ts = ImGui::CalcTextSize(boot);
                        const ImVec2 tp((rmin.x + rmax.x - ts.x) * 0.5f,
                                        (rmin.y + rmax.y - ts.y) * 0.5f);
                        ImGui::GetWindowDrawList()->AddText(
                            tp, ImGui::GetColorU32(ImGuiCol_Text), boot);
                    }
                    if (pressed)
                        (void)np->kick_member(np->ctx, slot);
                    if (ImGui::IsItemHovered())
                        ImGui::SetTooltip("Kick player");
                } else {
                    /* Non-interactive placeholder — BeginDisabled still animates. */
                    ImGui::Dummy(ImVec2(kick_btn, kick_btn));
                    ImDrawList* dl = ImGui::GetWindowDrawList();
                    const ImVec2 rmin = ImGui::GetItemRectMin();
                    const ImVec2 rmax = ImGui::GetItemRectMax();
                    dl->AddRect(rmin, rmax, ImGui::GetColorU32(ImGuiCol_Border),
                                ImGui::GetStyle().FrameRounding);
                    const char* boot = u8"\U0001F97E";
                    const ImVec2 ts = ImGui::CalcTextSize(boot);
                    dl->AddText(ImVec2((rmin.x + rmax.x - ts.x) * 0.5f,
                                       (rmin.y + rmax.y - ts.y) * 0.5f),
                                ImGui::GetColorU32(ImGuiCol_TextDisabled), boot);
                    if (ImGui::IsItemHovered(ImGuiHoveredFlags_AllowWhenDisabled)) {
                        if (!is_host)
                            ImGui::SetTooltip("Only the host can kick");
                        else if (!occupied[slot])
                            ImGui::SetTooltip("Open slot");
                        else if (slots[slot].is_host)
                            ImGui::SetTooltip("Cannot kick the host");
                        else if (!np->kick_member)
                            ImGui::SetTooltip("Kick unavailable");
                        else
                            ImGui::SetTooltip("Open slot");
                    }
                }
            }
            ImGui::PopID();
        }
        ImGui::EndTable();
    }
    /* Session BIOS notice (OpenBIOS vs SCPH1001). Keep copy plain — hosts care
     * about save-state compatibility, not kernel-RAM details.
     * Orange OpenBIOS override only when a peer cannot run SCPH; host retail
     * preference otherwise settles SCPH (even if a guest prefers OpenBIOS). */
    {
        int host_prefer_open = 0;
        int host_found = 0;
        int all_can_scph = 1;
        int saw = 0;
        for (int slot = 0; slot < max_slots; ++slot) {
            if (!occupied[slot]) continue;
            ++saw;
            const int offer_ok = slots[slot].bios_offer_valid;
            const int prefer_open = !offer_ok || slots[slot].bios_prefer_openbios;
            const int can_scph = offer_ok && slots[slot].bios_can_scph1001;
            if (slots[slot].is_host) {
                host_found = 1;
                host_prefer_open = prefer_open ? 1 : 0;
            }
            if (!can_scph) all_can_scph = 0;
        }
        if (saw >= 1 && host_found) {
            ImGui::Spacing();
            ImGui::PushTextWrapPos(0.0f);
            if (host_prefer_open) {
                ImGui::TextColored(
                    col(th.good),
                    "Host has selected OpenBIOS for this session.\n"
                    "Note: Save states are not cross compatible with SCPH1001 "
                    "and OpenBIOS sessions");
            } else if (all_can_scph) {
                ImGui::TextColored(
                    col(th.good),
                    "All users agree on proprietary BIOS SCPH1001.bin for this "
                    "session.\n"
                    "Note: Save states are not cross compatible with SCPH1001 "
                    "and OpenBIOS sessions");
            } else {
                ImGui::TextColored(
                    col(th.warn),
                    "1 or more users lacks proprietary BIOS, using OpenBIOS for "
                    "this session instead.\n"
                    "Note: Save states are not cross compatible with SCPH1001 "
                    "and OpenBIOS sessions");
            }
            ImGui::PopTextWrapPos();
        }
    }
    ImGui::Spacing();
    {
        const float btn_h = px(36);
        const float leave_w = px(130);
        const float settings_w = px(110);
        const float play_w = px(150);
        const float gap = px(10);
        const float row_w = ImGui::GetContentRegionAvail().x;
        const float row_x = ImGui::GetCursorPosX();
        const float row_y = ImGui::GetCursorPosY();

        /* Leave — red, pinned left. */
        const LngColor leave_bg = {0.72f, 0.20f, 0.24f, 1.0f};
        const LngColor leave_hov = {0.84f, 0.28f, 0.32f, 1.0f};
        const LngColor leave_act = {0.58f, 0.14f, 0.18f, 1.0f};
        ImGui::SetCursorPos(ImVec2(row_x, row_y));
        ImGui::PushStyleColor(ImGuiCol_Button, col(leave_bg));
        ImGui::PushStyleColor(ImGuiCol_ButtonHovered, col(leave_hov));
        ImGui::PushStyleColor(ImGuiCol_ButtonActive, col(leave_act));
        ImGui::PushStyleColor(ImGuiCol_Text, ImVec4(1, 1, 1, 1));
        if (ImGui::Button("Leave Lobby", ImVec2(leave_w, btn_h))) {
            m->netplay_local_room = false;
            m->netplay_lobby_settings_open = false;
            m->netplay_lobby_max_slots = 0;
            if (np->leave) (void)np->leave(np->ctx);
            ImGui::CloseCurrentPopup();
        }
        ImGui::PopStyleColor(4);

        if (is_host) {
            ImGui::SetCursorPos(ImVec2(row_x + leave_w + gap, row_y));
            if (ImGui::Button("Settings", ImVec2(settings_w, btn_h))) {
                if (np->input_delay_get)
                    m->netplay_lobby_input_delay = np->input_delay_get(np->ctx);
                if (m->netplay_lobby_input_delay < 2)
                    m->netplay_lobby_input_delay = 2;
                if (m->netplay_lobby_input_delay > 20)
                    m->netplay_lobby_input_delay = 20;
                if (np->input_prediction_get)
                    m->netplay_lobby_input_prediction =
                        np->input_prediction_get(np->ctx);
                if (m->netplay_lobby_input_prediction < 2)
                    m->netplay_lobby_input_prediction = 2;
                if (m->netplay_lobby_input_prediction > 16)
                    m->netplay_lobby_input_prediction = 16;
                if (np->rollback_get)
                    m->netplay_rollback = np->rollback_get(np->ctx) != 0;
                if (m->netplay_local_room) {
                    m->netplay_force_input_relay = false;
                    m->netplay_force_turn = false;
                } else {
                    if (np->force_input_relay_get) {
                        m->netplay_force_input_relay =
                            np->force_input_relay_get(np->ctx) != 0;
                    }
                    if (np->force_turn_get) {
                        m->netplay_force_turn =
                            np->force_turn_get(np->ctx) != 0;
                    }
                }
                m->netplay_lobby_settings_open = true;
            }

            /* ▶ Play — green, pinned right. */
            const LngColor play_bg = th.good;
            auto clamp01 = [](float v) { return v > 1.0f ? 1.0f : v; };
            const LngColor play_hov = {
                clamp01(th.good.r * 1.15f),
                clamp01(th.good.g * 1.15f),
                clamp01(th.good.b * 1.15f),
                1.0f};
            const LngColor play_act = {
                th.good.r * 0.85f, th.good.g * 0.85f, th.good.b * 0.85f, 1.0f};
            ImGui::SetCursorPos(ImVec2(row_x + row_w - play_w, row_y));
            ImGui::PushStyleColor(ImGuiCol_Button, col(play_bg));
            ImGui::PushStyleColor(ImGuiCol_ButtonHovered, col(play_hov));
            ImGui::PushStyleColor(ImGuiCol_ButtonActive, col(play_act));
            ImGui::PushStyleColor(ImGuiCol_Text, ImVec4(1, 1, 1, 1));
            /* Require two seated players, without waiting for every open seat.
             * Count only visible game slots: a host sitting alone in P2 after a
             * seat swap must not satisfy the start gate. */
            const bool can_start = seated_players >= 2;
            ImGui::BeginDisabled(!can_start);
            if (ImGui::Button(u8"\u25B6 Play", ImVec2(play_w, btn_h))) {
                /* Ensure engine match_caps.rollback matches UI before start. */
                if (np->rollback_set)
                    (void)np->rollback_set(np->ctx, m->netplay_rollback ? 1 : 0);
                const bool use_rb = m->netplay_rollback;
                const int max_rtt = np_lobby_max_peer_rtt_ms(m, np);
                /* Auto D: rollback uses §59 WAN-aware tiers; delay-sync uses
                 * the padded one-way formula. Manual keeps Lobby Settings.
                 * Forced TURN: lobby ICE underestimates match-path load —
                 * pad RTT before the tier table and floor D at 6. */
                if (!m->netplay_manual_input_delay && np->input_delay_set) {
                    bool force_turn = m->netplay_force_turn;
                    if (np->force_turn_get)
                        force_turn = np->force_turn_get(np->ctx) != 0;
                    int rtt_for_d = max_rtt;
                    if (use_rb && force_turn) {
                        /* Relay jitter + pump asymmetry; soak §587 host
                         * mid-match rtt_raw≈90 while lobby guest REPORT≈30. */
                        if (rtt_for_d < 80)
                            rtt_for_d = 80;
                        rtt_for_d += 40;
                    }
                    int delay = use_rb
                        ? np_rb_delay_frames_from_rtt_ms(rtt_for_d)
                        : np_delay_frames_from_rtt_ms(max_rtt);
                    if (use_rb && force_turn && delay < 6)
                        delay = 6;
                    m->netplay_lobby_input_delay = delay;
                    (void)np->input_delay_set(np->ctx, delay);
                }
                /* Auto P (rollback only): invent runway from RTT + committed D. */
                if (use_rb && !m->netplay_manual_input_prediction &&
                    np->input_prediction_set) {
                    const int pred = np_rb_prediction_frames_from_rtt_ms(
                        max_rtt, m->netplay_lobby_input_delay);
                    m->netplay_lobby_input_prediction = pred;
                    (void)np->input_prediction_set(np->ctx, pred);
                }
                if (np->set_ready)
                    (void)np->set_ready(np->ctx, 1);
                const int rc = np->request_start
                    ? np->request_start(np->ctx, &m->s) : -1;
                if (rc != 0) {
                    std::snprintf(m->netplay_status, sizeof(m->netplay_status),
                                  "Could not start lobby (need at least two "
                                  "players, or server rejected start).");
                } else {
                    m->netplay_status[0] = '\0';
                    /* LAN arms launch_pending inside request_start so host can
                     * leave this frame. Online must wait for the server's
                     * op:launch (drawn frames keep calling launch_pending) so
                     * every peer boots together — do not fill from lobby seat. */
                    if (np->launch_pending && np->launch_pending(np->ctx))
                        np_try_launch(m);
                    else
                        std::snprintf(m->netplay_status, sizeof(m->netplay_status),
                                      "Starting match…");
                }
            }
            ImGui::EndDisabled();
            ImGui::PopStyleColor(4);
        }
        /* Advance layout past the button row. */
        ImGui::SetCursorPos(ImVec2(row_x, row_y + btn_h));
        ImGui::Dummy(ImVec2(row_w, 0));
    }

    if (is_host && m->netplay_lobby_settings_open)
        ImGui::OpenPopup("Lobby Settings");
    if (ImGui::BeginPopupModal("Lobby Settings", &m->netplay_lobby_settings_open,
                               ImGuiWindowFlags_AlwaysAutoResize)) {
        /* Disable Rollback first — gates Manual Input Prediction below. */
        {
            bool disable_rb = !m->netplay_rollback;
            if (np->rollback_get)
                disable_rb = np->rollback_get(np->ctx) == 0;
            if (ImGui::Checkbox("Disable Rollback", &disable_rb)) {
                m->netplay_rollback = !disable_rb;
                if (np->rollback_set)
                    (void)np->rollback_set(np->ctx, m->netplay_rollback ? 1 : 0);
            }
            if (ImGui::IsItemHovered(ImGuiHoveredFlags_DelayNormal)) {
                ImGui::BeginTooltip();
                ImGui::PushTextWrapPos(px(360));
                ImGui::TextUnformatted(
                    "Off (default): invent missing remote inputs and correct "
                    "with rollback episodes (match_caps.rollback=1).\n\n"
                    "On: force delay-sync for the match. Manual Input "
                    "Prediction is locked out; only Input Delay applies.");
                ImGui::PopTextWrapPos();
                ImGui::EndTooltip();
            }
        }
        ImGui::Spacing();
        ImGui::TextUnformatted("Manual Input Delay");
        ImGui::SameLine();
        ImGui::TextColored(col(th.text_muted), "(frames)");
        {
            bool manual = m->netplay_manual_input_delay;
            if (ImGui::Checkbox("##manual_input_delay", &manual))
                m->netplay_manual_input_delay = manual;
            if (ImGui::IsItemHovered(ImGuiHoveredFlags_DelayNormal)) {
                ImGui::BeginTooltip();
                ImGui::PushTextWrapPos(px(360));
                ImGui::TextUnformatted(
                    "Off (default): at match start the host sets input delay "
                    "from the highest peer latency in the lobby.\n\n"
                    "On: use the frame value to the right for every player.");
                ImGui::PopTextWrapPos();
                ImGui::EndTooltip();
            }
            ImGui::SameLine();
            ImGui::BeginDisabled(!m->netplay_manual_input_delay);
            ImGui::SetNextItemWidth(px(140));
            int delay = m->netplay_lobby_input_delay;
            if (ImGui::InputInt("##lobby_input_delay", &delay, 1, 1)) {
                if (delay < 2) delay = 2;
                if (delay > 20) delay = 20;
                m->netplay_lobby_input_delay = delay;
                if (np->input_delay_set)
                    (void)np->input_delay_set(np->ctx, delay);
            }
            if (ImGui::IsItemDeactivatedAfterEdit()) {
                delay = m->netplay_lobby_input_delay;
                if (delay < 2) delay = 2;
                if (delay > 20) delay = 20;
                m->netplay_lobby_input_delay = delay;
                if (np->input_delay_set)
                    (void)np->input_delay_set(np->ctx, delay);
            }
            ImGui::SameLine();
            {
                const float help_sz = ImGui::GetFrameHeight();
                if (ImGui::Button("?##input_delay_help", ImVec2(help_sz, help_sz))) {
                }
                if (ImGui::IsItemHovered(ImGuiHoveredFlags_DelayNormal)) {
                    ImGui::BeginTooltip();
                    ImGui::PushTextWrapPos(px(360));
                    ImGui::TextUnformatted(
                        "Committed input delay D (send lead / buffer).\n\n"
                        "With rollback (Disable Rollback off), auto D from "
                        "max peer RTT (§59 WAN-aware):\n"
                        "  0–50 ms → 3, 50–80 → 4, 80–120 → 5,\n"
                        "  120–160 → 6, then steps up (floor 3).\n"
                        "Forced TURN floors at 5 (lobby RTT underestimates "
                        "the relay path).\n\n"
                        "With delay-sync (Disable Rollback on), auto D covers "
                        "one-way RTT at 60 Hz plus a 3-frame jitter pad:\n"
                        "  D = ceil(RTT_ms / 33.3) + 3  (min 3, max 20)\n\n"
                        "Too low stalls when packets arrive late. Too high adds "
                        "input lag for everyone.");
                    ImGui::PopTextWrapPos();
                    ImGui::EndTooltip();
                }
            }
            ImGui::EndDisabled();
        }
        ImGui::Spacing();
        ImGui::TextUnformatted("Manual Input Prediction");
        ImGui::SameLine();
        ImGui::TextColored(col(th.text_muted), "(frames)");
        {
            const bool rb_on = m->netplay_rollback;
            ImGui::BeginDisabled(!rb_on);
            bool manual_p = m->netplay_manual_input_prediction;
            if (ImGui::Checkbox("##manual_input_prediction", &manual_p))
                m->netplay_manual_input_prediction = manual_p;
            if (ImGui::IsItemHovered(ImGuiHoveredFlags_DelayNormal)) {
                ImGui::BeginTooltip();
                ImGui::PushTextWrapPos(px(360));
                ImGui::TextUnformatted(
                    "Rollback invent runway P. Off (default): host sets P from "
                    "peer RTT at match start. On: use the frame value to the "
                    "right.\n\n"
                    "Locked when Disable Rollback is on (delay-sync).");
                ImGui::PopTextWrapPos();
                ImGui::EndTooltip();
            }
            ImGui::SameLine();
            ImGui::BeginDisabled(!rb_on || !m->netplay_manual_input_prediction);
            ImGui::SetNextItemWidth(px(140));
            int pred = m->netplay_lobby_input_prediction;
            if (ImGui::InputInt("##lobby_input_prediction", &pred, 1, 1)) {
                if (pred < 2) pred = 2;
                if (pred > 16) pred = 16;
                m->netplay_lobby_input_prediction = pred;
                if (np->input_prediction_set)
                    (void)np->input_prediction_set(np->ctx, pred);
            }
            if (ImGui::IsItemDeactivatedAfterEdit()) {
                pred = m->netplay_lobby_input_prediction;
                if (pred < 2) pred = 2;
                if (pred > 16) pred = 16;
                m->netplay_lobby_input_prediction = pred;
                if (np->input_prediction_set)
                    (void)np->input_prediction_set(np->ctx, pred);
            }
            ImGui::SameLine();
            {
                const float help_sz = ImGui::GetFrameHeight();
                if (ImGui::Button("?##input_prediction_help",
                                 ImVec2(help_sz, help_sz))) {
                }
                if (ImGui::IsItemHovered(ImGuiHoveredFlags_DelayNormal)) {
                    ImGui::BeginTooltip();
                    ImGui::PushTextWrapPos(px(360));
                    ImGui::TextUnformatted(
                        "How far ahead of the remote tip a peer may invent "
                        "hold-last inputs before stalling (phase_lock).\n\n"
                        "Tip: prediction should be 4 + delay.\n\n"
                        "Auto (checkbox off): P = 4 + D (clamped 6..16).\n"
                        "Manual: keep the same relationship unless you are "
                        "deliberately tuning.\n\n"
                        "Outside this window the fast peer freezes until the "
                        "buffer refills; sustained freezes raise delay.");
                    ImGui::PopTextWrapPos();
                    ImGui::EndTooltip();
                }
            }
            ImGui::EndDisabled();
            ImGui::EndDisabled();
        }
        ImGui::Spacing();
        if (launcher_model_multitap_analog_available(m)) {
            bool analog_hack = m->s.multitap_analog != 0;
            if (np->multitap_analog_get)
                analog_hack = np->multitap_analog_get(np->ctx) != 0;
            if (ImGui::Checkbox("Multitap analog (hack)", &analog_hack)) {
                m->s.multitap_analog = analog_hack ? 1 : 0;
                if (np->multitap_analog_set)
                    (void)np->multitap_analog_set(np->ctx, analog_hack ? 1 : 0);
            }
            if (ImGui::IsItemHovered(ImGuiHoveredFlags_DelayNormal)) {
                ImGui::BeginTooltip();
                ImGui::PushTextWrapPos(px(360));
                ImGui::TextUnformatted(
                    "Host-enforced DualShock sticks on multitap tap seats for "
                    "this match (match_caps.multitap_analog). Off = faithful "
                    "digital taps. Peers apply the host setting at launch.");
                ImGui::PopTextWrapPos();
                ImGui::EndTooltip();
            }
            ImGui::Spacing();
        }
        if (ImGui::Button("Close", ImVec2(px(120), 0))) {
            m->netplay_lobby_settings_open = false;
            ImGui::CloseCurrentPopup();
        }
        ImGui::EndPopup();
    }
    ImGui::EndPopup();
}

void np_join_selected(LauncherModel* m) {
    const auto* np = np_cb(m);
    if (!np) return;
    if (m->netplay_selected_lobby < 0) {
        std::snprintf(m->netplay_status, sizeof(m->netplay_status),
                      "Select a lobby from the server list.");
        return;
    }
    RecompLauncherCNetplayLobby row{};
    if (!np->list_get || !np->list_get(np->ctx, m->netplay_selected_lobby, &row)) {
        std::snprintf(m->netplay_status, sizeof(m->netplay_status),
                      "Selected lobby is no longer available.");
        return;
    }
    if (row.has_password) {
        m->netplay_password[0] = '\0';
        m->netplay_password_modal_open = true;
    } else if (np->join) {
        char guest_bind[64];
        if (!np_prepare_guest_bind(guest_bind, sizeof(guest_bind),
                                   m->netplay_status, sizeof(m->netplay_status)))
            return;
        const int rc = np->join(np->ctx, row.lobby_id, "", guest_bind);
        if (rc == 0) {
            if (strncmp(row.lobby_id, "lan:", 4) == 0) {
                m->netplay_local_room = true;
                std::snprintf(m->netplay_host_endpoint, sizeof(m->netplay_host_endpoint),
                              "%s", row.lobby_id + 4);
            } else {
                m->netplay_local_room = false;
                m->netplay_host_endpoint[0] = '\0';
            }
            m->netplay_lobby_max_slots =
                row.max_slots >= 2 ? row.max_slots : np_game_max_players(m);
        } else if (rc == -3) {
            std::snprintf(m->netplay_status, sizeof(m->netplay_status),
                          "No LAN/Direct IP lobby at that address. If the host "
                          "is online, join from the server list.");
        } else if (rc != 0) {
            std::snprintf(m->netplay_status, sizeof(m->netplay_status),
                          "Could not join lobby.");
        }
    }
}

void draw_netplay(LauncherModel* m, const LauncherTheme& th) {
    const auto* np = np_cb(m);
    if (!np) return;
    static bool network_settings_loaded = false;
    if (!network_settings_loaded) {
        network_settings_loaded = true;
        np_load_network_settings(m);
        np_refresh_host_ip(m);
    }
    if (!m->s.netplay_player_name[0] && !m->netplay_name_modal_open && !m->netplay_name_prompted) {
        m->netplay_name_prompted = true;
        m->netplay_name_modal_open = true;
    }
    if (!m->netplay_list_fresh)
        np_refresh_lobby_list(m);
    if (np->pump) np->pump(np->ctx);
    np_ingest_last_error(m, np);
    if (np->launch_pending && np->launch_pending(np->ctx))
        np_try_launch(m);

    const bool np_online = np->connected && np->connected(np->ctx);
    const bool np_connecting = np->connecting && np->connecting(np->ctx);
    if (np_online && m->netplay_status[0] &&
        std::strncmp(m->netplay_status, "Connecting", 10) == 0) {
        m->netplay_status[0] = '\0';
    } else if (!np_online && !np_connecting && m->netplay_list_fresh &&
               m->netplay_status[0] &&
               std::strncmp(m->netplay_status, "Connecting", 10) == 0) {
        std::snprintf(m->netplay_status, sizeof(m->netplay_status),
                      "Could not reach lobby server.");
    }

    begin_container("netplay_lobbies", ImVec2(0, 0), ImGuiChildFlags_None);
    ImGui::TextColored(col(th.accent2), "LOBBIES");
    if (m->netplay_status[0])
        ImGui::TextColored(col(th.warn), "%s", m->netplay_status);
    ImGui::Spacing();
    int rows = np->list_count ? np->list_count(np->ctx) : 0;
    const float lobby_row_h = px(48);
    const float join_btn_w = px(72);
    const float join_btn_h = px(30);
    const float text_h = ImGui::GetTextLineHeight();
    /* Extra left inset so Lobby column text isn't flush with the panel edge. */
    ImGui::PushStyleVar(ImGuiStyleVar_CellPadding, ImVec2(px(14), px(6)));
    if (ImGui::BeginTable("netplay_lobby_table", 5,
                          ImGuiTableFlags_RowBg | ImGuiTableFlags_BordersInnerH |
                          ImGuiTableFlags_SizingStretchProp)) {
        /* Lobby/Game stretch; Players/Latency/Join stay fixed to content. */
        ImGui::TableSetupColumn("Lobby", ImGuiTableColumnFlags_WidthStretch, 1.0f);
        ImGui::TableSetupColumn("Game", ImGuiTableColumnFlags_WidthStretch, 0.7f);
        ImGui::TableSetupColumn("Players", ImGuiTableColumnFlags_WidthFixed, px(72));
        ImGui::TableSetupColumn("Latency", ImGuiTableColumnFlags_WidthFixed, px(72));
        ImGui::TableSetupColumn("Join", ImGuiTableColumnFlags_WidthFixed, px(88));
        ImGui::TableHeadersRow();
        if (rows <= 0) {
            ImGui::TableNextRow(ImGuiTableRowFlags_None, lobby_row_h);
            ImGui::TableSetColumnIndex(0);
            table_row_vcenter(lobby_row_h, text_h);
            ImGui::Text("No lobbies yet - host one.");
            ImGui::TableSetColumnIndex(1);
            ImGui::TextUnformatted("");
            ImGui::TableSetColumnIndex(2);
            ImGui::TextUnformatted("");
            ImGui::TableSetColumnIndex(3);
            ImGui::TextUnformatted("");
            ImGui::TableSetColumnIndex(4);
            ImGui::TextUnformatted("");
        }
        for (int i = 0; i < rows; ++i) {
            RecompLauncherCNetplayLobby row{};
            if (!np->list_get || !np->list_get(np->ctx, i, &row)) continue;
            ImGui::PushID(i);
            ImGui::TableNextRow(ImGuiTableRowFlags_None, lobby_row_h);
            ImGui::TableSetColumnIndex(0);
            ImVec2 row_pos = ImGui::GetCursorScreenPos();
            const bool selected = (m->netplay_selected_lobby == i);
            /* Anonymous selectable for hit-testing only — a labeled Selectable
             * was rendering like a full-width text field ("Lobby"). */
            if (ImGui::Selectable("##lobby_row", selected,
                                  ImGuiSelectableFlags_SpanAllColumns |
                                  ImGuiSelectableFlags_AllowOverlap |
                                  ImGuiSelectableFlags_AllowDoubleClick,
                                  ImVec2(0, lobby_row_h))) {
                m->netplay_selected_lobby = i;
                m->netplay_status[0] = '\0';
                if (ImGui::IsMouseDoubleClicked(ImGuiMouseButton_Left))
                    np_join_selected(m);
            }
            ImGui::SetCursorScreenPos(row_pos);
            table_row_vcenter(lobby_row_h, text_h);
            char lobby_label[96];
            std::snprintf(lobby_label, sizeof(lobby_label), "%s%s",
                          row.name[0] ? row.name : "Unnamed lobby",
                          row.has_password ? "  [locked]" : "");
            ImGui::TextUnformatted(lobby_label);
            ImGui::TableSetColumnIndex(1);
            table_row_vcenter(lobby_row_h, text_h);
            ImGui::TextColored(col(th.text_muted), "%s",
                               row.game_name[0] ? row.game_name : "—");
            ImGui::TableSetColumnIndex(2);
            table_row_vcenter(lobby_row_h, text_h);
            ImGui::Text("%d / %d", row.player_count, row.max_slots);
            ImGui::TableSetColumnIndex(3);
            table_row_vcenter(lobby_row_h, text_h);
            if (row.latency_ms >= 0)
                ImGui::Text("%d ms", row.latency_ms);
            else
                ImGui::TextColored(col(th.text_muted), "—");
            ImGui::TableSetColumnIndex(4);
            {
                ImVec2 cell = ImGui::GetCursorScreenPos();
                const float avail_x = ImGui::GetContentRegionAvail().x;
                ImGui::SetCursorScreenPos(ImVec2(
                    cell.x + (avail_x - join_btn_w) * 0.5f,
                    cell.y + (lobby_row_h - join_btn_h) * 0.5f));
                ImGui::BeginDisabled(!launcher_model_netplay_disc_ok(m));
                if (ImGui::Button("Join", ImVec2(join_btn_w, join_btn_h))) {
                    if (!launcher_model_netplay_disc_ok(m)) {
                        std::snprintf(m->netplay_status, sizeof(m->netplay_status),
                                      "%s",
                                      m->verify.netplay_detail[0]
                                          ? m->verify.netplay_detail
                                          : "Mount the supported .cue dump before joining.");
                    } else {
                        m->netplay_selected_lobby = i;
                        m->netplay_status[0] = '\0';
                        np_join_selected(m);
                    }
                }
                ImGui::EndDisabled();
            }
            ImGui::PopID();
        }
        ImGui::EndTable();
    }
    ImGui::PopStyleVar();
    end_container();
}

static bool mod_text_matches(const char* search, const RecompLauncherCModPackage& package) {
    if (!search || !search[0]) return true;
    std::string needle(search), haystack = std::string(package.name) + " " +
        package.id + " " + package.author + " " + package.description;
    std::transform(needle.begin(), needle.end(), needle.begin(),
        [](unsigned char c) { return (char)std::tolower(c); });
    std::transform(haystack.begin(), haystack.end(), haystack.begin(),
        [](unsigned char c) { return (char)std::tolower(c); });
    return haystack.find(needle) != std::string::npos;
}

static bool mod_feature_text_matches(const char* search,
                                     const RecompLauncherCModFeature& feature) {
    if (!search || !search[0]) return true;
    std::string needle(search), haystack = std::string(feature.name) + " " +
        feature.id + " " + feature.group + " " + feature.author + " " +
        feature.description + " " + feature.package_name + " " +
        feature.package_id + " " + feature.status;
    std::transform(needle.begin(), needle.end(), needle.begin(),
        [](unsigned char c) { return (char)std::tolower(c); });
    std::transform(haystack.begin(), haystack.end(), haystack.begin(),
        [](unsigned char c) { return (char)std::tolower(c); });
    return haystack.find(needle) != std::string::npos;
}

static void mod_note_error(LauncherModel* m) {
    const auto* mods = m ? m->mods : nullptr;
    const char* error = mods && mods->last_error ? mods->last_error(mods->ctx) : nullptr;
    std::snprintf(m->mod_status, sizeof(m->mod_status), "%s",
                  error && error[0] ? error : "The mod operation failed.");
}

static bool mod_commit_launch(LauncherModel* m) {
    if (!m || !m->mods || !m->mods->commit ||
        m->mods->commit(m->mods->ctx, launcher_model_rom_path(m))) {
        return true;
    }
    mod_note_error(m);
    return false;
}

struct ModIntegerEditState {
    int64_t value = 0;
    std::string provider_value;
};

static void draw_linkified_mod_author(
    const char* author_text,
    const RecompLauncherCModAuthorLink* author_links,
    int author_link_count,
    const LauncherTheme& th) {
    if (!author_text || !author_text[0]) return;
    const std::string author(author_text);
    size_t cursor = 0;
    ImGui::TextColored(col(th.text_muted), "by: ");
    ImGui::SameLine(0, 0);
    while (cursor < author.size()) {
        size_t next = std::string::npos;
        const RecompLauncherCModAuthorLink* link = nullptr;
        for (int i = 0; i < author_link_count; ++i) {
            const auto& candidate = author_links[i];
            if (!candidate.name[0] || !candidate.url[0]) continue;
            const size_t found = author.find(candidate.name, cursor);
            if (found < next) {
                next = found;
                link = &candidate;
            }
        }
        if (!link) {
            ImGui::TextColored(col(th.text_muted), "%s", author.c_str() + cursor);
            break;
        }
        if (next > cursor) {
            const std::string prefix = author.substr(cursor, next - cursor);
            ImGui::TextColored(col(th.text_muted), "%s", prefix.c_str());
            ImGui::SameLine(0, 0);
        }
        ImGui::TextLinkOpenURL(link->name, link->url);
        cursor = next + std::strlen(link->name);
        if (cursor < author.size()) ImGui::SameLine(0, 0);
    }
}

static bool draw_mod_integer_option(const RecompLauncherCModOption& option,
                                    char* next, size_t next_size) {
    ImGui::TextUnformatted(option.label);
    ImGui::SameLine(px(260));
    ImGui::SetNextItemWidth(px(230));

    errno = 0;
    char* end = nullptr;
    const long long parsed = std::strtoll(option.value, &end, 10);
    int64_t provider_value =
        errno == 0 && end && *end == '\0'
            ? static_cast<int64_t>(parsed)
            : option.min_value;
    provider_value = std::max(
        option.min_value, std::min(option.max_value, provider_value));

    static std::unordered_map<ImGuiID, ModIntegerEditState> edits;
    const ImGuiID id = ImGui::GetID("##integer");
    ModIntegerEditState& edit = edits[id];
    if (edit.provider_value != option.value) {
        edit.value = provider_value;
        edit.provider_value = option.value;
    }

    const int64_t step = option.step > 0 ? option.step : 1;
    const bool edited = ImGui::InputScalar(
        "##integer", ImGuiDataType_S64, &edit.value, &step, nullptr, nullptr,
        ImGuiInputTextFlags_None);
    const bool commit = ImGui::IsItemDeactivatedAfterEdit() ||
                        (edited && !ImGui::IsItemActive());
    if (!commit) return false;

    edit.value = std::max(
        option.min_value, std::min(option.max_value, edit.value));
    const uint64_t distance =
        static_cast<uint64_t>(edit.value) -
        static_cast<uint64_t>(option.min_value);
    edit.value -= static_cast<int64_t>(
        distance % static_cast<uint64_t>(step));
    std::snprintf(next, next_size, "%lld",
                  static_cast<long long>(edit.value));
    edit.provider_value = next;
    return true;
}

static void draw_mod_packages(LauncherModel* m, const LauncherTheme& th) {
    const auto* mods = m ? m->mods : nullptr;
    if (!mods || !mods->package_count || !mods->package_get) return;
    const bool feature_provider =
        mods->feature_count && mods->feature_get &&
        mods->feature_option_get && mods->feature_enable &&
        mods->feature_set_option;

    const char* archive_extension =
        mods->archive_extension && mods->archive_extension[0]
            ? mods->archive_extension : ".psxmod";
    const char* archive_description =
        mods->archive_description && mods->archive_description[0]
            ? mods->archive_description
            : "PSXRecomp mod package (.psxmod)";
    char install_label[96];
    char archive_pattern[64];
    std::snprintf(install_label, sizeof(install_label),
                  "Install %s", archive_extension);
    std::snprintf(archive_pattern, sizeof(archive_pattern),
                  "*%s", archive_extension);
    if (ImGui::Button(install_label)) {
        const char* patterns[] = { archive_pattern };
        char path[1024];
        if (launcher_pick_file("Install Mod Package", patterns, 1,
                               archive_description,
                               path, sizeof(path))) {
            if (!mods->install_archive || !mods->install_archive(mods->ctx, path))
                mod_note_error(m);
            else
                std::snprintf(m->mod_status, sizeof(m->mod_status),
                              "Package installed. Changes apply when you press PLAY.");
        }
    }
    ImGui::SameLine();
    ImGui::SetNextItemWidth(px(300));
    ImGui::InputTextWithHint("##mod_search", "Search mods and options...",
                             m->mod_search, sizeof(m->mod_search));
    if (m->mod_status[0]) {
        ImGui::SameLine();
        ImGui::TextColored(col(th.warn), "%s", m->mod_status);
    }
    ImGui::Spacing();

    const float list_w = px(300);
    if (ImGui::BeginChild("##mod_list", ImVec2(list_w, 0), ImGuiChildFlags_Borders)) {
        const int count = mods->package_count(mods->ctx);
        int visible = 0;
        for (int i = 0; i < count; ++i) {
            RecompLauncherCModPackage package{};
            if (!mods->package_get(mods->ctx, i, &package) ||
                !mod_text_matches(m->mod_search, package)) continue;
            visible++;
            ImGui::PushID(i);
            const bool selected = m->mod_package_selected == i;
            char label[196];
            if (feature_provider) {
                std::snprintf(label, sizeof(label), "%s\n%s",
                              package.name, package.version);
            } else {
                std::snprintf(label, sizeof(label), "%s\n%s  %s",
                              package.name, package.version,
                              package.enabled ? "[enabled]" : "[disabled]");
            }
            if (ImGui::Selectable(label, selected, 0, ImVec2(0, px(52))))
                m->mod_package_selected = i;
            if (package.has_error)
                ImGui::TextColored(col(th.warn), "%s", package.status);
            ImGui::PopID();
        }
        if (!visible) ImGui::TextColored(col(th.text_muted), "No matching packages.");
    }
    ImGui::EndChild();
    ImGui::SameLine();

    if (ImGui::BeginChild("##mod_detail", ImVec2(0, 0), ImGuiChildFlags_Borders)) {
        RecompLauncherCModPackage package{};
        if (mods->package_get(mods->ctx, m->mod_package_selected, &package)) {
            ImGui::TextColored(col(th.accent2), "%s", package.name);
            ImGui::SameLine();
            ImGui::TextColored(col(th.text_muted), "%s", package.version);
            if (package.author[0])
                draw_linkified_mod_author(
                    package.author, package.author_links,
                    package.author_link_count, th);
            if (package.description[0]) ImGui::TextWrapped("%s", package.description);
            if (package.source_url[0]) {
                ImGui::TextColored(col(th.text_muted), "Source: ");
                ImGui::SameLine(0, 0);
                ImGui::TextLinkOpenURL(
                    package.source_name[0] ? package.source_name : "Project page",
                    package.source_url);
            }
            if (package.license[0])
                ImGui::TextColored(col(th.text_muted), "License: %s", package.license);
            ImGui::Spacing();

            if (!feature_provider) {
                bool enabled = package.enabled != 0;
                if (ImGui::Checkbox("Enabled", &enabled)) {
                    if (!mods->set_enabled ||
                        !mods->set_enabled(mods->ctx, package.id, enabled ? 1 : 0))
                        mod_note_error(m);
                }
            }
            if (mods->version_count && mods->version_get && mods->select_version) {
                const int version_count = mods->version_count(mods->ctx, package.id);
                if (version_count > 1) {
                    ImGui::SameLine();
                    ImGui::SetNextItemWidth(px(170));
                    if (ImGui::BeginCombo("##mod_version", package.version)) {
                        for (int version_index = 0; version_index < version_count;
                             ++version_index) {
                            RecompLauncherCModVersion version{};
                            if (!mods->version_get(mods->ctx, package.id,
                                                   version_index, &version)) continue;
                            if (ImGui::Selectable(version.version,
                                                  version.selected != 0)) {
                                if (!mods->select_version(
                                        mods->ctx, package.id, version.version))
                                    mod_note_error(m);
                            }
                            if (version.selected) ImGui::SetItemDefaultFocus();
                        }
                        ImGui::EndCombo();
                    }
                    if (ImGui::IsItemHovered())
                        ImGui::SetTooltip("Select an installed version (rollback)");
                }
            }
            if (package.removable) {
                ImGui::SameLine();
                if (ImGui::Button("Remove")) ImGui::OpenPopup("Remove mod package?");
                if (ImGui::BeginPopupModal("Remove mod package?", nullptr,
                                           ImGuiWindowFlags_AlwaysAutoResize)) {
                    ImGui::TextWrapped("Remove %s %s from this installation?",
                                       package.name, package.version);
                    if (ImGui::Button("Cancel", ImVec2(px(110), 0)))
                        ImGui::CloseCurrentPopup();
                    ImGui::SameLine();
                    if (ImGui::Button("Remove", ImVec2(px(110), 0))) {
                        if (!mods->remove_package ||
                            !mods->remove_package(mods->ctx, package.id, package.version))
                            mod_note_error(m);
                        else if (m->mod_package_selected > 0)
                            m->mod_package_selected--;
                        ImGui::CloseCurrentPopup();
                    }
                    ImGui::EndPopup();
                }
            }
            ImGui::Separator();

            std::string last_group;
            for (int i = 0; !feature_provider && i < package.option_count; ++i) {
                RecompLauncherCModOption option{};
                if (!mods->option_get ||
                    !mods->option_get(mods->ctx, package.id, i, &option)) continue;
                if (m->mod_search[0]) {
                    RecompLauncherCModPackage searchable = package;
                    std::snprintf(searchable.name, sizeof(searchable.name), "%s", option.label);
                    std::snprintf(searchable.description, sizeof(searchable.description),
                                  "%s %s", option.description, option.group);
                    if (!mod_text_matches(m->mod_search, searchable)) continue;
                }
                if (last_group != option.group) {
                    last_group = option.group;
                    ImGui::Spacing();
                    ImGui::TextColored(col(th.accent), "%s",
                                       last_group.empty() ? "General" : last_group.c_str());
                    ImGui::Separator();
                }
                ImGui::PushID(option.id);
                bool changed = false;
                char next[RECOMP_LAUNCHER_MOD_VALUE_MAX];
                std::snprintf(next, sizeof(next), "%s", option.value);
                if (option.type == RECOMP_MOD_OPTION_BOOLEAN) {
                    bool value = std::strcmp(option.value, "true") == 0;
                    if (ImGui::Checkbox(option.label, &value)) {
                        std::snprintf(next, sizeof(next), "%s", value ? "true" : "false");
                        changed = true;
                    }
                } else if (option.type == RECOMP_MOD_OPTION_CHOICE) {
                    ImGui::TextUnformatted(option.label);
                    ImGui::SameLine(px(260));
                    ImGui::SetNextItemWidth(px(230));
                    char preview[128];
                    std::snprintf(preview, sizeof(preview), "%s", option.value);
                    for (int c = 0; c < option.choice_count; ++c) {
                        RecompLauncherCModChoice choice{};
                        if (mods->choice_get &&
                            mods->choice_get(mods->ctx, package.id, option.id,
                                             c, &choice) &&
                            std::strcmp(choice.value, option.value) == 0) {
                            std::snprintf(preview, sizeof(preview), "%s",
                                          choice.label[0] ? choice.label
                                                          : choice.value);
                            break;
                        }
                    }
                    if (ImGui::BeginCombo("##choice", preview)) {
                        for (int c = 0; c < option.choice_count; ++c) {
                            RecompLauncherCModChoice choice{};
                            if (!mods->choice_get ||
                                !mods->choice_get(mods->ctx, package.id, option.id, c, &choice))
                                continue;
                            const bool selected = std::strcmp(choice.value, option.value) == 0;
                            if (ImGui::Selectable(choice.label, selected)) {
                                std::snprintf(next, sizeof(next), "%s", choice.value);
                                changed = true;
                            }
                            if (selected) ImGui::SetItemDefaultFocus();
                        }
                        ImGui::EndCombo();
                    }
                } else {
                    changed = draw_mod_integer_option(
                        option, next, sizeof(next));
                }
                if (ImGui::IsItemHovered() && option.description[0])
                    ImGui::SetTooltip("%s", option.description);
                if (changed && (!mods->set_option ||
                    !mods->set_option(mods->ctx, package.id, option.id, next)))
                    mod_note_error(m);
                ImGui::PopID();
            }
        } else {
            ImGui::TextColored(col(th.text_muted),
                               "Install or select a package to configure it.");
        }
    }
    ImGui::EndChild();
}

struct ModFeatureListItem {
    int index;
    RecompLauncherCModFeature feature;
};

static bool mod_feature_less(const ModFeatureListItem& lhs,
                             const ModFeatureListItem& rhs) {
    const int group = std::strcmp(lhs.feature.group, rhs.feature.group);
    if (group != 0) return group < 0;
    const int name = std::strcmp(lhs.feature.name, rhs.feature.name);
    if (name != 0) return name < 0;
    const int package = std::strcmp(lhs.feature.package_id, rhs.feature.package_id);
    if (package != 0) return package < 0;
    return std::strcmp(lhs.feature.id, rhs.feature.id) < 0;
}

static void draw_mod_feature_option(LauncherModel* m,
                                    const RecompLauncherCModFeature& feature,
                                    const RecompLauncherCModOption& option) {
    const auto* mods = m->mods;
    ImGui::PushID(option.id);
    bool changed = false;
    char next[RECOMP_LAUNCHER_MOD_VALUE_MAX];
    std::snprintf(next, sizeof(next), "%s", option.value);

    /* Another option currently overrides this one (e.g. "Instant" ticked makes
     * a speed box meaningless). Show it, greyed, so the player can see the
     * value they will get back when they untick -- hiding it would make the
     * row jump around and lose the setting from view. */
    const bool inert = option.disabled != 0;
    if (inert) ImGui::BeginDisabled();

    if (option.type == RECOMP_MOD_OPTION_BOOLEAN) {
        bool value = std::strcmp(option.value, "true") == 0;
        if (ImGui::Checkbox(option.label, &value)) {
            std::snprintf(next, sizeof(next), "%s", value ? "true" : "false");
            changed = true;
        }
    } else if (option.type == RECOMP_MOD_OPTION_CHOICE) {
        ImGui::TextUnformatted(option.label);
        ImGui::SameLine(px(260));
        ImGui::SetNextItemWidth(px(230));
        char preview[128];
        std::snprintf(preview, sizeof(preview), "%s", option.value);
        for (int choice_index = 0; choice_index < option.choice_count;
             ++choice_index) {
            RecompLauncherCModChoice choice{};
            if (mods->feature_choice_get &&
                mods->feature_choice_get(mods->ctx, feature.package_id,
                                          feature.id, option.id,
                                          choice_index, &choice) &&
                std::strcmp(choice.value, option.value) == 0) {
                std::snprintf(preview, sizeof(preview), "%s",
                              choice.label[0] ? choice.label : choice.value);
                break;
            }
        }
        if (ImGui::BeginCombo("##choice", preview)) {
            for (int choice_index = 0; choice_index < option.choice_count;
                 ++choice_index) {
                RecompLauncherCModChoice choice{};
                if (!mods->feature_choice_get ||
                    !mods->feature_choice_get(mods->ctx, feature.package_id,
                                              feature.id, option.id,
                                              choice_index, &choice)) {
                    continue;
                }
                const bool selected =
                    std::strcmp(choice.value, option.value) == 0;
                if (ImGui::Selectable(choice.label, selected)) {
                    std::snprintf(next, sizeof(next), "%s", choice.value);
                    changed = true;
                }
                if (selected) ImGui::SetItemDefaultFocus();
            }
            ImGui::EndCombo();
        }
    } else {
        changed = draw_mod_integer_option(option, next, sizeof(next));
    }

    const bool hovered = ImGui::IsItemHovered();
    if (inert) ImGui::EndDisabled();

    if (hovered && option.description[0])
        ImGui::SetTooltip("%s", option.description);
    /* A disabled control cannot report a change, but guard anyway so a future
     * widget that stays interactive can never write through an inert option. */
    if (changed && !inert &&
        !mods->feature_set_option(mods->ctx, feature.package_id, feature.id,
                                  option.id, next)) {
        mod_note_error(m);
    }
    ImGui::PopID();
}

static void draw_mod_feature_diagnostics(
    LauncherModel* m, const LauncherTheme& th,
    const RecompLauncherCModFeature& feature) {
    const auto* mods = m->mods;
    if (feature.status[0]) {
        ImGui::Spacing();
        ImGui::TextColored(feature.has_error ? col(th.warn) : col(th.text_muted),
                           "%s", feature.status);
    }
    if (!mods->diagnostic_count || !mods->diagnostic_get) return;

    const int count = mods->diagnostic_count(
        mods->ctx, feature.package_id, feature.id);
    if (count <= 0) return;
    ImGui::Spacing();
    ImGui::TextColored(col(th.accent), "Validation");
    ImGui::Separator();
    for (int index = 0; index < count; ++index) {
        RecompLauncherCModDiagnostic diagnostic{};
        if (!mods->diagnostic_get(mods->ctx, feature.package_id, feature.id,
                                  index, &diagnostic)) {
            continue;
        }
        const ImVec4 color = diagnostic.severity == RECOMP_MOD_DIAGNOSTIC_ERROR
            ? col(th.warn) : col(th.text_muted);
        ImGui::PushID(index);
        ImGui::TextColored(color, "%s", diagnostic.message);
        if (diagnostic.resource[0])
            ImGui::TextColored(col(th.text_muted), "Resource: %s",
                               diagnostic.resource);
        if (diagnostic.related_feature_id[0]) {
            ImGui::TextColored(
                col(th.text_muted), "Also involved: %s%s%s",
                diagnostic.related_package_id,
                diagnostic.related_package_id[0] ? " / " : "",
                diagnostic.related_feature_id);
        }
        ImGui::PopID();
    }
}

static bool set_all_mod_features(LauncherModel* m, bool enabled) {
    const auto* mods = m ? m->mods : nullptr;
    if (!mods || !mods->feature_count || !mods->feature_get ||
        !mods->feature_enable) {
        return false;
    }

    const int count = mods->feature_count(mods->ctx);
    std::vector<RecompLauncherCModFeature> features;
    features.reserve(count > 0 ? (size_t)count : 0);
    for (int index = 0; index < count; ++index) {
        RecompLauncherCModFeature feature{};
        if (!mods->feature_get(mods->ctx, index, &feature)) {
            mod_note_error(m);
            return false;
        }
        features.push_back(feature);
    }

    std::vector<size_t> changed;
    changed.reserve(features.size());
    for (size_t index = 0; index < features.size(); ++index) {
        const RecompLauncherCModFeature& feature = features[index];
        if ((feature.enabled != 0) == enabled) continue;
        if (!mods->feature_enable(mods->ctx, feature.package_id, feature.id,
                                  enabled ? 1 : 0)) {
            char failure[sizeof(m->mod_status)] = {};
            const char* error =
                mods->last_error ? mods->last_error(mods->ctx) : nullptr;
            if (error && error[0])
                std::snprintf(failure, sizeof(failure), "%s", error);
            // Treat the bulk action as one edit. Best-effort rollback prevents
            // a failed feature from leaving an unexpected half-toggled set.
            for (auto rollback = changed.rbegin(); rollback != changed.rend();
                 ++rollback) {
                const RecompLauncherCModFeature& prior = features[*rollback];
                mods->feature_enable(mods->ctx, prior.package_id, prior.id,
                                     prior.enabled ? 1 : 0);
            }
            if (failure[0]) {
                std::snprintf(m->mod_status, sizeof(m->mod_status), "%s",
                              failure);
            } else {
                mod_note_error(m);
            }
            return false;
        }
        changed.push_back(index);
    }
    std::snprintf(m->mod_status, sizeof(m->mod_status),
                  enabled ? "All mod features enabled. Changes apply on PLAY."
                          : "All mod features disabled. Changes apply on PLAY.");
    return true;
}

static void draw_mod_features(LauncherModel* m, const LauncherTheme& th) {
    const auto* mods = m ? m->mods : nullptr;
    if (!mods || !mods->feature_count || !mods->feature_get ||
        !mods->feature_option_get || !mods->feature_enable ||
        !mods->feature_set_option) {
        return;
    }

    const int feature_count = mods->feature_count(mods->ctx);
    const char* archive_extension =
        mods->archive_extension && mods->archive_extension[0]
            ? mods->archive_extension : ".psxmod";
    const char* archive_description =
        mods->archive_description && mods->archive_description[0]
            ? mods->archive_description
            : "PSXRecomp mod package (.psxmod)";
    char install_label[96];
    char archive_pattern[64];
    std::snprintf(install_label, sizeof(install_label),
                  "Install %s", archive_extension);
    std::snprintf(archive_pattern, sizeof(archive_pattern),
                  "*%s", archive_extension);
    if (ImGui::Button(install_label)) {
        const char* patterns[] = { archive_pattern };
        char path[1024];
        if (launcher_pick_file("Install Mod Package", patterns, 1,
                               archive_description,
                               path, sizeof(path))) {
            if (!mods->install_archive ||
                !mods->install_archive(mods->ctx, path)) {
                mod_note_error(m);
            } else {
                std::snprintf(m->mod_status, sizeof(m->mod_status),
                              "Package installed. Changes apply when you press PLAY.");
            }
        }
    }
    ImGui::SameLine();
    if (ImGui::Button("Enable all"))
        set_all_mod_features(m, true);
    if (ImGui::IsItemHovered())
        ImGui::SetTooltip("Enable every installed mod feature");
    ImGui::SameLine();
    if (ImGui::Button("Disable all"))
        set_all_mod_features(m, false);
    if (ImGui::IsItemHovered())
        ImGui::SetTooltip("Disable every installed mod feature");
    ImGui::SameLine();
    ImGui::SetNextItemWidth(px(300));
    ImGui::InputTextWithHint("##mod_search", "Search features, groups, packages...",
                             m->mod_search, sizeof(m->mod_search));
    if (m->mod_status[0]) {
        ImGui::PushStyleColor(ImGuiCol_Text, col(th.warn));
        ImGui::PushTextWrapPos(ImGui::GetCursorPosX() + ImGui::GetContentRegionAvail().x);
        ImGui::TextWrapped("%s", m->mod_status);
        ImGui::PopTextWrapPos();
        ImGui::PopStyleColor();
    }
    ImGui::Spacing();

    if (feature_count <= 0) m->mod_selected = 0;
    else if (m->mod_selected >= feature_count)
        m->mod_selected = feature_count - 1;

    std::vector<ModFeatureListItem> visible_features;
    visible_features.reserve(feature_count > 0 ? (size_t)feature_count : 0);
    for (int index = 0; index < feature_count; ++index) {
        ModFeatureListItem item{};
        item.index = index;
        if (!mods->feature_get(mods->ctx, index, &item.feature) ||
            !mod_feature_text_matches(m->mod_search, item.feature)) {
            continue;
        }
        visible_features.push_back(item);
    }
    std::stable_sort(visible_features.begin(), visible_features.end(),
                     mod_feature_less);

    const float list_w = px(330);
    if (ImGui::BeginChild("##mod_feature_list", ImVec2(list_w, 0),
                          ImGuiChildFlags_Borders)) {
        size_t first = 0;
        while (first < visible_features.size()) {
            const char* raw_group = visible_features[first].feature.group;
            const char* group = raw_group[0] ? raw_group : "General";
            size_t last = first + 1;
            while (last < visible_features.size()) {
                const char* candidate = visible_features[last].feature.group;
                if (std::strcmp(raw_group, candidate) != 0) break;
                ++last;
            }

            ImGui::PushID(raw_group[0] ? raw_group : "##general");
            if (m->mod_search[0])
                ImGui::SetNextItemOpen(true, ImGuiCond_Always);
            const bool open = ImGui::CollapsingHeader(
                group, ImGuiTreeNodeFlags_DefaultOpen);
            if (open) {
                for (size_t item_index = first; item_index < last; ++item_index) {
                    const ModFeatureListItem& item = visible_features[item_index];
                    const RecompLauncherCModFeature& feature = item.feature;
                    ImGui::PushID(feature.package_id);
                    ImGui::PushID(feature.id);

                    bool enabled = feature.enabled != 0;
                    if (ImGui::Checkbox("##enabled", &enabled)) {
                        if (!mods->feature_enable(
                                mods->ctx, feature.package_id, feature.id,
                                enabled ? 1 : 0)) {
                            mod_note_error(m);
                        }
                    }
                    if (ImGui::IsItemHovered())
                        ImGui::SetTooltip("%s %s", enabled ? "Disable" : "Enable",
                                          feature.name);
                    ImGui::SameLine();
                    if (feature.has_error) {
                        ImGui::TextColored(col(th.warn), "!");
                        if (ImGui::IsItemHovered() && feature.status[0])
                            ImGui::SetTooltip("%s", feature.status);
                        ImGui::SameLine();
                    }

                    char label[320];
                    std::snprintf(label, sizeof(label), "%s\n%s%s%s",
                                  feature.name,
                                  feature.package_name[0] ? feature.package_name
                                                          : feature.package_id,
                                  feature.package_version[0] ? "  " : "",
                                  feature.package_version);
                    if (ImGui::Selectable(
                            label, m->mod_selected == item.index, 0,
                            ImVec2(0, px(44)))) {
                        m->mod_selected = item.index;
                    }
                    ImGui::PopID();
                    ImGui::PopID();
                }
            }
            ImGui::PopID();
            first = last;
        }
        if (visible_features.empty()) {
            ImGui::TextColored(col(th.text_muted),
                               feature_count ? "No matching features."
                                             : "No mod features installed.");
        }
    }
    ImGui::EndChild();
    ImGui::SameLine();

    if (ImGui::BeginChild("##mod_feature_detail", ImVec2(0, 0),
                          ImGuiChildFlags_Borders)) {
        RecompLauncherCModFeature feature{};
        if (feature_count > 0 &&
            mods->feature_get(mods->ctx, m->mod_selected, &feature)) {
            ImGui::TextColored(col(th.accent2), "%s", feature.name);
            if (feature.group[0]) {
                ImGui::SameLine();
                ImGui::TextColored(col(th.text_muted), "%s", feature.group);
            }
            ImGui::TextColored(
                col(th.text_muted), "From %s%s%s",
                feature.package_name[0] ? feature.package_name
                                        : feature.package_id,
                feature.package_version[0] ? " " : "",
                feature.package_version);
            if (feature.author[0])
                draw_linkified_mod_author(
                    feature.author, feature.author_links,
                    feature.author_link_count, th);
            if (feature.source_url[0]) {
                ImGui::TextColored(col(th.text_muted), "Source: ");
                ImGui::SameLine(0, 0);
                ImGui::TextLinkOpenURL(
                    feature.source_name[0] ? feature.source_name : "Project page",
                    feature.source_url);
            }
            if (feature.description[0])
                ImGui::TextWrapped("%s", feature.description);
            ImGui::Spacing();

            if (feature.camera_controls) {
                ImGui::Separator();
                ImGui::Spacing();
                ImGui::TextColored(col(th.accent), "3D camera controls");
                ImGui::TextWrapped(
                    feature.enabled
                        ? "This mod adds live camera input. Review the current "
                          "right-stick and keyboard bindings before playing."
                        : "Enable this feature to expose its camera bindings "
                          "on the Controller page.");
                if (feature.enabled &&
                    ImGui::Button("Review Camera Bindings")) {
                    launcher_model_open_config(m, 0);
                }
                ImGui::Spacing();
            }

            // The list-row checkbox is the single enable/disable control.
            // The detail pane owns configuration values only.
            if (mods->feature_resource_count &&
                mods->feature_resource_get &&
                mods->feature_resource_set_path) {
                const int resource_count = mods->feature_resource_count(
                    mods->ctx, feature.package_id, feature.id);
                if (resource_count > 0) {
                    ImGui::Spacing();
                    ImGui::Separator();
                    ImGui::Spacing();
                    ImGui::TextColored(col(th.accent), "Required owner files");
                    for (int resource_index = 0;
                         resource_index < resource_count; ++resource_index) {
                        RecompLauncherCModResource resource{};
                        if (!mods->feature_resource_get(
                                mods->ctx, feature.package_id, feature.id,
                                resource_index, &resource))
                            continue;
                        ImGui::PushID(resource.id);
                        ImGui::TextUnformatted(resource.label);
                        if (resource.description[0])
                            ImGui::TextWrapped("%s", resource.description);
                        ImGui::TextColored(
                            resource.verified ? col(th.accent2) : col(th.warn),
                            "%s", resource.status[0]
                                      ? resource.status : "Not selected");
                        if (resource.path[0]) {
                            const char* basename = resource.path;
                            for (const char* p = resource.path; *p; ++p)
                                if (*p == '/' || *p == '\\') basename = p + 1;
                            ImGui::TextColored(col(th.text_muted), "%s", basename);
                            if (ImGui::IsItemHovered())
                                ImGui::SetTooltip("%s", resource.path);
                        }
                        if (ImGui::Button(resource.path[0] ? "Change file"
                                                           : "Select file")) {
                            std::vector<std::string> owned_patterns;
                            std::vector<const char*> patterns;
                            std::string remaining = resource.file_patterns;
                            size_t start = 0;
                            while (start <= remaining.size()) {
                                const size_t comma = remaining.find(',', start);
                                std::string pattern = remaining.substr(
                                    start, comma == std::string::npos
                                               ? std::string::npos
                                               : comma - start);
                                if (!pattern.empty())
                                    owned_patterns.push_back(pattern);
                                if (comma == std::string::npos) break;
                                start = comma + 1;
                            }
                            for (const std::string& pattern : owned_patterns)
                                patterns.push_back(pattern.c_str());
                            char path[RECOMP_LAUNCHER_MOD_PATH_MAX] = {};
                            if (launcher_pick_file(
                                    resource.label,
                                    patterns.empty() ? nullptr : patterns.data(),
                                    (int)patterns.size(),
                                    resource.file_description[0]
                                        ? resource.file_description : nullptr,
                                    path, sizeof(path))) {
                                if (!mods->feature_resource_set_path(
                                        mods->ctx, feature.package_id,
                                        feature.id, resource.id, path)) {
                                    mod_note_error(m);
                                } else {
                                    std::snprintf(
                                        m->mod_status,
                                        sizeof(m->mod_status),
                                        "%s verified. Changes apply on PLAY.",
                                        resource.label);
                                }
                            }
                        }
                        ImGui::PopID();
                        ImGui::Spacing();
                    }
                }
            }
            draw_mod_feature_diagnostics(m, th, feature);
            if (feature.option_count > 0) {
                ImGui::Spacing();
                ImGui::Separator();
            }
            std::string last_group;
            for (int index = 0; index < feature.option_count; ++index) {
                RecompLauncherCModOption option{};
                if (!mods->feature_option_get(
                        mods->ctx, feature.package_id, feature.id,
                        index, &option)) {
                    continue;
                }
                if (last_group != option.group) {
                    last_group = option.group;
                    ImGui::Spacing();
                    ImGui::TextColored(
                        col(th.accent), "%s",
                        last_group.empty() ? "Configuration"
                                           : last_group.c_str());
                    ImGui::Separator();
                }
                draw_mod_feature_option(m, feature, option);
            }
        } else {
            ImGui::TextColored(col(th.text_muted),
                               "Install or select a feature to configure it.");
        }
    }
    ImGui::EndChild();
}

void draw_mods(LauncherModel* m, const LauncherTheme& th) {
    const auto* mods = m ? m->mods : nullptr;
    if (!mods) return;
    const bool feature_provider =
        mods->feature_count && mods->feature_get &&
        mods->feature_option_get && mods->feature_enable &&
        mods->feature_set_option;
    if (!feature_provider) m->mod_show_packages = true;

    if (feature_provider) {
        if (ImGui::RadioButton("Features", !m->mod_show_packages))
            m->mod_show_packages = false;
        ImGui::SameLine();
        if (ImGui::RadioButton("Installed packages", m->mod_show_packages))
            m->mod_show_packages = true;
        ImGui::Spacing();
    }

    if (m->mod_show_packages)
        draw_mod_packages(m, th);
    else
        draw_mod_features(m, th);
}

// ---- panel registry: id -> {view, slot, available, draw} --------------------
// The single implementation table for every panel this backend draws. A
// SystemProfile's panels_dashboard/panels_settings/panels_controller arrays
// (launcher_system.h) list which of these ids compose into each view, in
// slot order; draw_dashboard/draw_settings/draw_controller above look each id
// up here via find_composed() and draw whatever's both listed and available().
const LauncherPanel kPanelRegistry[] = {
    { "game",              LNG_VIEW_DASHBOARD,  LNG_SLOT_MAIN, nullptr,      panel_game_draw },
    { "controller",        LNG_VIEW_DASHBOARD,  LNG_SLOT_SIDE, nullptr,      panel_controller_draw },
    { "save",              LNG_VIEW_DASHBOARD,  LNG_SLOT_WIDE, avail_save,   panel_save_draw },
    { "tpak",              LNG_VIEW_DASHBOARD,  LNG_SLOT_WIDE, avail_tpak,   panel_tpak_draw },
    { "video",             LNG_VIEW_SETTINGS,   LNG_SLOT_MAIN, nullptr,      panel_video_draw },
    { "audio",             LNG_VIEW_SETTINGS,   LNG_SLOT_SIDE, nullptr,      panel_audio_draw },
    { "input",             LNG_VIEW_SETTINGS,   LNG_SLOT_SIDE, avail_input,  panel_input_draw },
    { "system",            LNG_VIEW_SETTINGS,   LNG_SLOT_SIDE, avail_system, panel_system_draw },
    { "solar",             LNG_VIEW_SETTINGS,   LNG_SLOT_SIDE, avail_solar,  panel_solar_draw },
    { "hotkeys",           LNG_VIEW_SETTINGS,   LNG_SLOT_WIDE, nullptr,      panel_hotkeys_draw },
    { "controller_config", LNG_VIEW_CONTROLLER, LNG_SLOT_WIDE, nullptr,      panel_controller_config_draw },
    { nullptr,              LNG_VIEW_DASHBOARD,  0,             nullptr,      nullptr },   // sentinel
};

// Footer: a fixed-height band with the neon divider pinned to its TOP and the
// CTA vertically centred inside it. Laid out from an explicit origin (not the
// running cursor) so it is pixel-identical on every view and the CTA's glow
// always has clearance below the divider — Settings has less body content, and
// a cursor-relative footer let the glow ride up into the rule.
void draw_footer(LauncherModel* m, const LauncherTheme& th, float footer_h) {
    const ImVec2 origin = ImGui::GetCursorScreenPos();
    const float  fullw  = ImGui::GetContentRegionAvail().x;
    const float  play_w = px(210), play_h = px(46);

    // divider at the very top of the band
    ImGui::GetWindowDrawList()->AddRectFilledMultiColor(
        origin, ImVec2(origin.x + fullw, origin.y + px(1.5f)),
        imcol(th.border, 0.2f), imcol(th.accent2, 0.7f),
        imcol(th.accent2, 0.7f), imcol(th.border, 0.2f));

    // CTA centred in the remaining band height (glow clears the rule on both sides)
    const float band_y = origin.y + px(1.5f);
    const float band_h = footer_h - px(1.5f);
    const float cta_y  = band_y + (band_h - play_h) * 0.5f;

    const ImVec2 win = ImGui::GetWindowPos();
    if (m->view == LNG_VIEW_DASHBOARD) {
        bool skip = m->s.skip_launcher != 0;
        ImGui::SetCursorScreenPos(ImVec2(origin.x, cta_y + (play_h - ImGui::GetFrameHeight()) * 0.5f));
        if (ImGui::Checkbox("Skip launcher on boot", &skip))
            launcher_model_request_skip_toggle(m);
    } else if (m->view == LNG_VIEW_SETTINGS &&
               launcher_model_can_restore_defaults(m)) {
        ImGui::SetCursorScreenPos(
            ImVec2(origin.x, cta_y + (play_h - px(34.0f)) * 0.5f));
        if (ImGui::Button("Restore Defaults", ImVec2(px(150.0f), px(34.0f))))
            launcher_model_request_restore_defaults(m);
    }
    if (m->view == LNG_VIEW_NETPLAY) {
        const float action_w = px(190.0f);
        const float settings_w = px(170.0f);
        const float refresh_w = px(120.0f);
        const float gap = px(10);
        const float row_need =
            action_w + gap + settings_w + gap + refresh_w + gap + action_w;
        const bool compact = fullw < row_need + px(8);

        auto open_host = [&]() {
            if (!launcher_model_netplay_disc_ok(m)) {
                const char* why = m->verify.netplay_detail[0]
                                      ? m->verify.netplay_detail
                                      : "Mount the supported .cue dump before hosting.";
                std::snprintf(m->netplay_status, sizeof(m->netplay_status), "%s", why);
                return;
            }
            if (!m->s.netplay_player_name[0]) {
                m->netplay_name_modal_open = true;
                return;
            }
            np_connect_and_list(m);
            m->netplay_lan_only = false;
            np_refresh_host_ip(m);
            if (!m->netplay_host_name[0]) {
                std::snprintf(m->netplay_host_name, sizeof(m->netplay_host_name),
                              "%s's Lobby", m->s.netplay_player_name);
            }
            m->netplay_host_password[0] = '\0';
            m->netplay_host_modal_open = true;
        };
        auto open_network = [&]() {
            const auto* np = np_cb(m);
            const char* current = np && np->default_url ? np->default_url(np->ctx) : "";
            std::snprintf(m->netplay_lobby_url, sizeof(m->netplay_lobby_url), "%s",
                          current ? current : "");
            m->netplay_network_modal_open = true;
        };

        if (!compact) {
            ImGui::SetCursorScreenPos(ImVec2(origin.x, cta_y));
            if (ImGui::Button("Host Lobby", ImVec2(action_w, play_h)))
                open_host();
            ImGui::SetCursorScreenPos(ImVec2(origin.x + action_w + gap, cta_y));
            if (ImGui::Button("Network Settings", ImVec2(settings_w, play_h)))
                open_network();
            ImGui::SetCursorScreenPos(
                ImVec2(origin.x + action_w + gap + settings_w + gap, cta_y));
            if (ImGui::Button("Refresh", ImVec2(refresh_w, play_h)))
                np_refresh_lobby_list(m);
            if (ImGui::IsItemHovered())
                ImGui::SetTooltip("Reload server lobbies and rescan LAN/Direct IP");
            ImGui::SetCursorScreenPos(ImVec2(origin.x + fullw - action_w, cta_y));
            if (ImGui::Button("Join Direct", ImVec2(action_w, play_h)))
                m->netplay_direct_modal_open = true;
        } else {
            /* Narrow window: collapse into a scrollable Actions menu. */
            const float menu_btn_w = px(160.0f);
            ImGui::SetCursorScreenPos(ImVec2(origin.x, cta_y));
            if (ImGui::Button("Actions##np_footer", ImVec2(menu_btn_w, play_h)))
                ImGui::OpenPopup("##netplay_footer_menu");
            if (ImGui::BeginPopup("##netplay_footer_menu")) {
                const float menu_w = px(220.0f);
                const float menu_h = px(168.0f);
                if (ImGui::BeginChild("##np_footer_scroll", ImVec2(menu_w, menu_h),
                                      ImGuiChildFlags_None,
                                      ImGuiWindowFlags_AlwaysVerticalScrollbar)) {
                    if (ImGui::Selectable("Host Lobby")) {
                        open_host();
                    }
                    if (ImGui::Selectable("Network Settings")) {
                        open_network();
                    }
                    if (ImGui::Selectable("Refresh")) {
                        np_refresh_lobby_list(m);
                    }
                    if (ImGui::IsItemHovered())
                        ImGui::SetTooltip(
                            "Reload server lobbies and rescan LAN/Direct IP");
                    if (ImGui::Selectable("Join Direct")) {
                        m->netplay_direct_modal_open = true;
                    }
                }
                ImGui::EndChild();
                ImGui::EndPopup();
            }
        }
        return;
    }
    // Back/Cancel (Circle/O on a DualSense, B on Xbox, Backspace on keyboard) AND
    // Start re-home the focus ring to PLAY. Directional nav through the card child
    // windows is easy to wander out of with no way back; these are the forcing
    // functions that snap the highlight back to the primary action. Start
    // deliberately only HIGHLIGHTS PLAY (does not launch), so it can't fire the
    // game by accident — the launch is the activate button (A/Cross) on the
    // focused PLAY, or a mouse click. SetKeyboardFocusHere() targets the NEXT
    // submitted item — PLAY's button.
    if (ImGui::IsKeyPressed(ImGuiKey_GamepadFaceRight, false) ||
        ImGui::IsKeyPressed(ImGuiKey_GamepadStart, false) ||
        ImGui::IsKeyPressed(ImGuiKey_Backspace, false))
        ImGui::SetKeyboardFocusHere();
    float play_x = origin.x + fullw - play_w;
    if (m->netplay_supported &&
        (m->view == LNG_VIEW_DASHBOARD || m->view == LNG_VIEW_SETTINGS ||
         m->view == LNG_VIEW_CONTROLLER)) {
        const float net_w = px(170.0f);
        ImGui::SetCursorScreenPos(ImVec2(play_x - net_w - px(12.0f), cta_y));
        if (ImGui::Button("NETPLAY", ImVec2(net_w, play_h))) {
            /* Open the page immediately; connect/list runs on first draw
             * (and continues off-thread) so Windows DNS/TCP never freezes UI. */
            m->netplay_list_fresh = false;
            std::snprintf(m->netplay_status, sizeof(m->netplay_status),
                          "Connecting to lobby server…");
            launcher_model_set_view(m, LNG_VIEW_NETPLAY);
        }
    }
    ImGui::SetCursorScreenPos(ImVec2(play_x, cta_y));
    const bool can_play = launcher_model_can_launch(m);
    const bool bios_block = launcher_model_bios_blocks_play(m);
    const bool play_enabled = can_play || bios_block;
    if (neon_cta("##play", "PLAY", ImVec2(play_w, play_h), play_enabled)) {
        /* Prefer mismatch prompt over launch even if can_play races true. */
        if (bios_block)
            launcher_model_bios_play_prompt(m);
        else if (mod_commit_launch(m))
            m->action = LNG_ACTION_LAUNCH;
    } else if (!play_enabled && ImGui::IsItemHovered(ImGuiHoveredFlags_AllowWhenDisabled)) {
        const char* noun = m->rom_noun ? m->rom_noun : "ROM";
        if (m->has_bios && !m->setup_bios_ok) {
            ImGui::SetTooltip(
                "Select a valid BIOS first (or Use OpenBIOS when this build "
                "allows it).");
        } else if (!m->rom_present || strcmp(m->rom_size, "--") == 0) {
            ImGui::SetTooltip("Select a valid %s first", noun);
        } else if (m->profile && m->profile->verify.mode == 1 &&
                   (m->verify.verdict == 0 || m->verify.verdict == 3)) {
            ImGui::SetTooltip("Select a verified %s first", noun);
        } else if (m->setup_preparing) {
            ImGui::SetTooltip("Wait for the current setup job to finish");
        } else {
            ImGui::SetTooltip("Select a valid %s first", noun);
        }
    }
    if (!play_enabled && ImGui::IsItemClicked() && m->setup_wizard_supported)
        m->setup_wizard_open = true;
    ImGui::SetItemDefaultFocus();   // gamepad/keyboard start on the primary action
    (void)win;
}

/* Compact progress-only modal while a setup job runs — closes the full
 * first-run form so nothing else is interactive. */
enum SetupPlatKind {
    SETUP_PLAT_GENERIC = 0,
    SETUP_PLAT_PSX,
    SETUP_PLAT_GBA,
    SETUP_PLAT_SNES,
};

static bool setup_plat_contains_ci(const char* hay, const char* needle) {
    if (!hay || !needle || !needle[0]) return false;
    for (const char* h = hay; *h; ++h) {
        const char* a = h;
        const char* b = needle;
        while (*a && *b) {
            char ca = *a, cb = *b;
            if (ca >= 'A' && ca <= 'Z') ca = (char)(ca - 'A' + 'a');
            if (cb >= 'A' && cb <= 'Z') cb = (char)(cb - 'A' + 'a');
            if (ca != cb) break;
            ++a;
            ++b;
        }
        if (!*b) return true;
    }
    return false;
}

static SetupPlatKind setup_platform_kind(const char* platform) {
    if (setup_plat_contains_ci(platform, "PLAYSTATION") ||
        setup_plat_contains_ci(platform, "PSX") ||
        setup_plat_contains_ci(platform, "PS1"))
        return SETUP_PLAT_PSX;
    if (setup_plat_contains_ci(platform, "GAME BOY ADVANCE") ||
        setup_plat_contains_ci(platform, "GBA"))
        return SETUP_PLAT_GBA;
    if (setup_plat_contains_ci(platform, "SUPER NINTENDO") ||
        setup_plat_contains_ci(platform, "SNES"))
        return SETUP_PLAT_SNES;
    return SETUP_PLAT_GENERIC;
}

static const char* kRetcommToolchainsUrl =
    "https://github.com/TechnicallyComputers/retcomm-toolchains";
static const char* kRetcommToolchainsReleasesUrl =
    "https://github.com/TechnicallyComputers/retcomm-toolchains/releases";

/* TextLinkOpenURL is 1.91+; HOST_IMGUI may be older — fall back to a button. */
static void setup_url_link(const char* label, const char* url) {
#if defined(IMGUI_VERSION_NUM) && IMGUI_VERSION_NUM >= 19100
    ImGui::TextLinkOpenURL(label, url);
#else
    if (ImGui::SmallButton(label))
        SDL_OpenURL(url);
#endif
    if (ImGui::IsItemHovered())
        ImGui::SetTooltip("%s", url);
}

/* Compact progress-only modal while a setup job runs — closes the full
 * first-run form so nothing else is interactive. */
static void draw_setup_progress_modal(LauncherModel* m, const LauncherTheme& th) {
    static const char* kProgPopup = "Setup progress";
    ImGui::OpenPopup(kProgPopup);
    ImVec2 center = ImGui::GetMainViewport()->GetCenter();
    ImGui::SetNextWindowPos(center, ImGuiCond_Always, ImVec2(0.5f, 0.5f));
    ImGui::SetNextWindowSize(ImVec2(px(480), 0), ImGuiCond_Always);
    const ImGuiWindowFlags flags =
        ImGuiWindowFlags_NoResize | ImGuiWindowFlags_NoMove |
        ImGuiWindowFlags_NoCollapse | ImGuiWindowFlags_AlwaysAutoResize;
    if (!ImGui::BeginPopupModal(kProgPopup, nullptr, flags))
        return;

    const float wrap_x = ImGui::GetCursorPosX() + ImGui::GetContentRegionAvail().x;
    const char* game =
        (m->game_name && m->game_name[0]) ? m->game_name : "this game";
    const char* job =
        (m->setup_progress_title[0])
            ? m->setup_progress_title
            : ((m->prepare_disc_label && m->prepare_disc_label[0])
                   ? m->prepare_disc_label
                   : "Setup");
    ImGui::TextColored(col(th.accent), "%s", job);
    ImGui::PushTextWrapPos(wrap_x);
    ImGui::TextColored(col(th.text_muted),
                       "Please wait — %s is working. Do not close this window.",
                       game);
    ImGui::PopTextWrapPos();
    ImGui::Dummy(ImVec2(0, px(14)));

    ImGui::PushTextWrapPos(wrap_x);
    const char* st = m->setup_status[0] ? m->setup_status : "Working…";
    const bool warn_st =
        (strncmp(st, "WARNING", 7) == 0) ||
        (strstr(st, "Do not close") != nullptr) ||
        (strstr(st, "DO NOT") != nullptr);
    if (warn_st) {
        ImGui::PushStyleColor(ImGuiCol_Text, col(th.warn));
        ImGui::TextWrapped("%s", st);
        ImGui::PopStyleColor();
    } else {
        ImGui::TextColored(col(th.accent), "%s", st);
    }
    ImGui::PopTextWrapPos();
    ImGui::Dummy(ImVec2(0, px(8)));
    const float bar = (m->setup_prepare_fraction >= 0.0f)
                          ? m->setup_prepare_fraction
                          : m->setup_prepare_pulse;
    ImGui::ProgressBar(bar, ImVec2(-1.0f, px(14)), "");

    if (m->setup_error[0]) {
        ImGui::Dummy(ImVec2(0, px(8)));
        ImGui::PushTextWrapPos(wrap_x);
        ImGui::TextColored(col(th.warn), "%s", m->setup_error);
        ImGui::PopTextWrapPos();
    }

    ImGui::EndPopup();
    /* Esc / outside click must not dismiss while the job is running. */
    if (m->setup_preparing && !ImGui::IsPopupOpen(kProgPopup))
        ImGui::OpenPopup(kProgPopup);
}

void draw_setup_wizard_modal(LauncherModel* m, const LauncherTheme& th) {
    if (!m->setup_wizard_supported) return;
    if (!m->setup_wizard_open && !m->setup_preparing) return;
    launcher_model_poll_prepare_disc(m);

    /* While a prepare/rebuild/toolchain job runs, show only the progress window.
     * Skipping BeginPopupModal on "First-run setup" lets ImGui dismiss it. */
    if (m->setup_preparing) {
        draw_setup_progress_modal(m, th);
        return;
    }

    ImGui::OpenPopup("First-run setup");
    const ImGuiViewport* vp = ImGui::GetMainViewport();
    // Auto-sized setup content changes height as validation details appear.
    // Recenter against its current size every frame so it cannot drift or clip.
    ImGui::SetNextWindowPos(vp->GetCenter(), ImGuiCond_Always, ImVec2(0.5f, 0.5f));
    /* Prefer content height (AlwaysAutoResize). Clamp to the work area. */
    const float max_h = vp->WorkSize.y * 0.92f;
    ImGui::SetNextWindowSize(
        ImVec2(px(g_rom_picker.active && g_rom_picker.from_setup ? 720.0f : 640.0f), 0),
        ImGuiCond_Always);
    ImGui::SetNextWindowSizeConstraints(ImVec2(px(520), 0),
                                        ImVec2(FLT_MAX, max_h));
    if (!ImGui::BeginPopupModal("First-run setup", nullptr,
                                ImGuiWindowFlags_AlwaysAutoResize |
                                ImGuiWindowFlags_NoMove))
        return;

    const float wrap_x = ImGui::GetCursorPosX() + ImGui::GetContentRegionAvail().x;
    const char* noun = (m->rom_noun && m->rom_noun[0]) ? m->rom_noun : "ROM";
    const char* game = (m->game_name && m->game_name[0]) ? m->game_name : "this game";
    if (g_rom_picker.active && g_rom_picker.from_setup) {
        draw_builtin_rom_picker_contents(m, th, false);
        ImGui::EndPopup();
        return;
    }

    /* ---- Page 0: portable toolchain ------------------------------------ */
    if (m->setup_needs_toolchain && m->setup_page == 0) {
        const bool want_update =
            m->setup_tc_ready && m->setup_tc_update_available &&
            !m->setup_tc_update_skipped;
        ImGui::TextColored(col(th.accent),
                           want_update ? "Toolchain update" : "Build tools");
        ImGui::PushTextWrapPos(wrap_x);
        if (want_update) {
            ImGui::TextColored(col(th.text_muted),
                "%s found a newer portable cmake/clang pack. Update now "
                "(recommended), keep your current install for this session, "
                "or install from an offline zip.",
                game);
        } else {
            ImGui::TextColored(col(th.text_muted),
                "%s builds game sources on your machine. Install the portable "
                "cmake/clang pack (cmake-clang-v1), or provide a matching zip "
                "for offline setup.",
                game);
        }
        ImGui::PopTextWrapPos();
        ImGui::Dummy(ImVec2(0, px(12)));

        ImGui::TextUnformatted("1. Portable toolchain");
        ImGui::PushTextWrapPos(wrap_x);
        ImGui::TextColored(col(th.text_muted),
            "Automatic download pulls the latest cmake-clang-v1 release and "
            "caches it for reuse across titles (no per-game version pin). "
            "Uncheck to browse a local zip instead "
            "(for offline machines, grab a release asset from the repo below).");
        ImGui::PopTextWrapPos();
        if (want_update || m->setup_tc_local_ver[0] ||
            m->setup_tc_remote_ver[0]) {
            ImGui::Dummy(ImVec2(0, px(4)));
            char ver_line[160];
            std::snprintf(
                ver_line, sizeof(ver_line), "Installed: %s   Latest: %s",
                m->setup_tc_local_ver[0] ? m->setup_tc_local_ver : "—",
                m->setup_tc_remote_ver[0] ? m->setup_tc_remote_ver : "—");
            ImGui::TextColored(col(want_update ? th.warn : th.good), "%s",
                               ver_line);
        }
        ImGui::Dummy(ImVec2(0, px(4)));
        ImGui::TextColored(col(th.text_muted), "Source / manual download:");
        ImGui::SameLine();
        setup_url_link("TechnicallyComputers/retcomm-toolchains",
                       kRetcommToolchainsUrl);
        ImGui::Dummy(ImVec2(0, px(6)));

        if (ImGui::Checkbox(want_update
                                ? "Download toolchain update##tc"
                                : "Download latest portable toolchain##tc",
                            &m->setup_tc_auto)) {
            if (m->setup_tc_auto)
                m->setup_error[0] = '\0';
        }

        if (!m->setup_tc_auto) {
            ImGui::Dummy(ImVec2(0, px(8)));
            ImGui::TextUnformatted("Toolchain zip");
            ImGui::PushTextWrapPos(wrap_x);
            ImGui::TextColored(col(th.text_muted),
                "Select a cmake-clang-v1-*.zip from "
                "TechnicallyComputers/retcomm-toolchains releases.");
            ImGui::PopTextWrapPos();
            setup_url_link("Open retcomm-toolchains releases",
                           kRetcommToolchainsReleasesUrl);
            ImGui::Dummy(ImVec2(0, px(4)));
            const char* zp = m->setup_tc_zip[0] ? m->setup_tc_zip
                                                : "(none selected)";
            char zelided[220];
            elide_left(zp, px(320), zelided, sizeof(zelided));
            ImGui::AlignTextToFramePadding();
            ImGui::TextColored(col(m->setup_tc_zip[0] ? th.good : th.warn), "%s",
                               m->setup_tc_zip[0] ? "OK" : "Needed");
            ImGui::SameLine();
            ImGui::TextColored(
                col(m->setup_tc_zip[0] ? th.text : th.text_muted), "%s",
                zelided);
            ImGui::SameLine();
            ImGui::PushStyleVar(ImGuiStyleVar_FramePadding, ImVec2(px(12), px(6)));
            if (ImGui::Button("Browse zip…##tc", ImVec2(px(128), px(32)))) {
                static const char* kZipPatterns[] = {"*.zip"};
                request_file_picker(
                    m, BuiltinPickerKind::SetupToolchainZip,
                    "Select cmake-clang-v1 toolchain zip", kZipPatterns, 1,
                    "Toolchain zip archives", true);
            }
            ImGui::PopStyleVar();
        }

        if (m->setup_status[0]) {
            ImGui::Dummy(ImVec2(0, px(8)));
            ImGui::PushTextWrapPos(wrap_x);
            ImGui::TextColored(col(th.good), "%s", m->setup_status);
            ImGui::PopTextWrapPos();
        }
        if (m->setup_error[0]) {
            ImGui::Dummy(ImVec2(0, px(6)));
            ImGui::PushTextWrapPos(wrap_x);
            ImGui::TextColored(col(th.warn), "%s", m->setup_error);
            ImGui::PopTextWrapPos();
        }

        ImGui::Dummy(ImVec2(0, px(14)));
        const bool can_next = launcher_model_can_advance_toolchain(m);
        if (!can_next) ImGui::BeginDisabled();
        if (ImGui::Button(want_update ? "Update##tc_next" : "Next##tc_next",
                          ImVec2(px(140), px(34)))) {
            launcher_model_start_ensure_toolchain(m);
            if (m->setup_preparing) {
                ImGui::CloseCurrentPopup();
                ImGui::EndPopup();
                draw_setup_progress_modal(m, th);
                return;
            }
        }
        if (!can_next) {
            ImGui::EndDisabled();
            if (ImGui::IsItemHovered(ImGuiHoveredFlags_AllowWhenDisabled))
                ImGui::SetTooltip(
                    "Enable automatic download or select a toolchain zip");
        }
        if (want_update) {
            ImGui::SameLine();
            if (ImGui::Button("Skip for now##tc_skip", ImVec2(px(140), px(34))))
                launcher_model_skip_toolchain_update(m);
            if (ImGui::IsItemHovered())
                ImGui::SetTooltip(
                    "Keep the installed toolchain for this session.");
        }
        ImGui::SameLine();
        if (ImGui::Button("Quit", ImVec2(px(100), px(34))))
            m->action = LNG_ACTION_QUIT;

        if (m->setup_wizard_open && !ImGui::IsPopupOpen("First-run setup"))
            ImGui::OpenPopup("First-run setup");
        ImGui::EndPopup();
        return;
    }

    /* ---- Page 1: BIOS / disc / generate -------------------------------- */
    const SetupPlatKind plat = setup_platform_kind(m->platform);
    const bool media_confirm = launcher_model_setup_media_confirm_only(m);

    if (media_confirm) {
        ImGui::TextColored(col(th.accent),
                           m->has_bios ? "Confirm BIOS and disc"
                                       : "Confirm disc");
        ImGui::PushTextWrapPos(wrap_x);
        if (plat == SETUP_PLAT_PSX && m->has_bios) {
            ImGui::TextColored(col(th.text_muted),
                "This build is already generated. Select a PlayStation BIOS "
                "(or keep OpenBIOS) and a Redump-style .cue with sibling .bin "
                "tracks so %s can launch. Your previous disc/BIOS picks were "
                "cleared from settings.",
                game);
        } else if (m->has_bios) {
            ImGui::TextColored(col(th.text_muted),
                "This build is already ready. Confirm a BIOS image and a "
                "playable %s below — previous picks were cleared from settings.",
                noun);
        } else {
            ImGui::TextColored(col(th.text_muted),
                "This build is already ready. Confirm a playable %s below — "
                "the previous pick was cleared from settings.",
                noun);
        }
        ImGui::PopTextWrapPos();
    } else {
        ImGui::TextColored(col(th.accent), "Setup required");
        ImGui::PushTextWrapPos(wrap_x);
        if (plat == SETUP_PLAT_PSX && m->has_bios) {
            ImGui::TextColored(col(th.text_muted),
                "%s needs a playable %s before you can launch. This build includes "
                "a bundled BIOS (OpenBIOS) by default. Setup also looks for a "
                "retail SCPH1001.BIN beside the install and uses it when found; "
                "otherwise OpenBIOS stays selected. Use a Redump-style .cue with "
                "sibling .bin tracks (.iso is not accepted). Pick your %s below "
                "(you must legally own these dumps).",
                game, noun, noun);
        } else if (plat == SETUP_PLAT_GBA && m->has_bios) {
            ImGui::TextColored(col(th.text_muted),
                "%s needs a Game Boy Advance BIOS dump and a playable %s before "
                "you can launch. Pick both below (you must legally own these dumps).",
                game, noun);
        } else if (plat == SETUP_PLAT_SNES) {
            ImGui::TextColored(col(th.text_muted),
                "%s needs a playable Super Nintendo %s before you can launch. "
                "Pick your file below (you must legally own this dump).",
                game, noun);
        } else if (m->has_bios) {
            ImGui::TextColored(col(th.text_muted),
                "%s needs a BIOS image and a playable %s before you can launch. "
                "Pick both below (you must legally own these dumps).",
                game, noun);
        } else {
            ImGui::TextColored(col(th.text_muted),
                "%s needs a playable %s before you can launch. Pick your file below "
                "(you must legally own this dump).",
                game, noun);
        }
        ImGui::PopTextWrapPos();
    }
    ImGui::Dummy(ImVec2(0, px(10)));

    if (m->has_bios) {
        const bool has_pick = m->s.bios_path[0] != 0;
        const bool offers_bundled = (plat == SETUP_PLAT_PSX);
        const char* bios_section =
            (plat == SETUP_PLAT_GBA) ? "1. GBA BIOS (required)"
            : (plat == SETUP_PLAT_PSX) ? "1. PlayStation BIOS (optional)"
                                      : "1. BIOS";
        const char* bios_help =
            (plat == SETUP_PLAT_GBA)
                ? "Browse for your gba_bios.bin dump (16 KB, SHA-1 "
                  "300c20df… — dumped from a Game Boy Advance). Setup packages "
                  "do not ship a redistributable GBA BIOS."
            : (plat == SETUP_PLAT_PSX)
                ? "Default: bundled OpenBIOS. Setup auto-selects SCPH1001.BIN "
                  "if it finds a validated dump beside the install; otherwise "
                  "browse for your own (exactly 512 KB)."
                : "Browse for a BIOS image required by this console.";
        const char* empty_bios_label =
            offers_bundled ? "OpenBIOS" : "(none selected)";
        const char* bios_picker =
            (plat == SETUP_PLAT_GBA) ? "Select GBA BIOS (gba_bios.bin)"
            : (plat == SETUP_PLAT_PSX) ? "Select PlayStation BIOS (SCPH1001.BIN)"
                                      : "Select BIOS file";

        ImGui::TextUnformatted(bios_section);
        ImGui::PushTextWrapPos(wrap_x);
        ImGui::TextColored(col(th.text_muted), "%s", bios_help);
        ImGui::PopTextWrapPos();
        const char* bp = has_pick ? m->s.bios_path : empty_bios_label;
        char belided[220];
        elide_left(bp, px(300), belided, sizeof(belided));
        ImGui::AlignTextToFramePadding();
        ImGui::TextColored(col(m->setup_bios_ok ? th.good : th.warn), "%s",
                           m->setup_bios_ok ? "OK" : "Needed");
        ImGui::SameLine();
        ImGui::TextColored(col(has_pick ? th.text : th.text_muted), "%s", belided);
        ImGui::SameLine();
        ImGui::PushStyleVar(ImGuiStyleVar_FramePadding, ImVec2(px(12), px(6)));
        if (ImGui::Button("Browse BIOS##setup", ImVec2(px(120), px(32)))) {
            request_bios_picker(m, bios_picker, true);
        }
        if (offers_bundled) {
            ImGui::SameLine();
            /* Always visible; greyed out when OpenBIOS is already selected. */
            if (!has_pick) ImGui::BeginDisabled();
            if (ImGui::Button("Use OpenBIOS##setup", ImVec2(px(128), px(32))))
                launcher_model_request_bios_path(m, "");
            if (!has_pick) ImGui::EndDisabled();
            if (ImGui::IsItemHovered(ImGuiHoveredFlags_AllowWhenDisabled))
                ImGui::SetTooltip(has_pick
                                      ? "Switch to bundled OpenBIOS (no rebuild)."
                                      : "OpenBIOS is already selected.");
        }
        ImGui::PopStyleVar();
        if (m->setup_bios_detail[0]) {
            ImGui::PushTextWrapPos(wrap_x);
            ImGui::TextColored(col(m->setup_bios_warn ? th.warn : th.text_muted),
                               "%s", m->setup_bios_detail);
            ImGui::PopTextWrapPos();
        }
        ImGui::Dummy(ImVec2(0, px(12)));
    }

    ImGui::Text("%s. %s image", m->has_bios ? "2" : "1", noun);
    ImGui::PushTextWrapPos(wrap_x);
    if (plat == SETUP_PLAT_PSX) {
        /* Keep the note as one wrapped TextColored block — SameLine +
         * TextLinkOpenURL after a wrapped line leaves a huge empty gap in
         * BeginPopupModal (Windows first-run wizard regression). */
        ImGui::TextColored(col(th.text_muted),
            "NOTE: psxrecomp games require a .cue + .bin dump of the disc. "
            "Note the number of tracks required by this project; multitrack "
            "discs are often Redump-formatted dumps. You can generate your own "
            "from the original disc with redumper "
            "(https://github.com/superg/redumper). You cannot convert a "
            "single-track .bin or .iso to multitrack.");
        ImGui::PopTextWrapPos();
        setup_url_link("Open redumper", "https://github.com/superg/redumper");
        ImGui::PushTextWrapPos(wrap_x);
    } else {
        const char* media_help =
            (plat == SETUP_PLAT_GBA)
                ? "Select your verified Game Boy Advance ROM (.gba)."
            : (plat == SETUP_PLAT_SNES)
                ? "Select your Super Nintendo ROM (.sfc / .smc)."
                : "Select your game ROM file.";
        ImGui::TextColored(col(th.text_muted), "%s", media_help);
    }
    ImGui::PopTextWrapPos();
    {
        const char* rp = m->rom_present ? m->rom_full : "(none selected)";
        char relided[220];
        elide_left(rp, px(360), relided, sizeof(relided));
        const bool rom_ok = m->rom_present && strcmp(m->rom_size, "--") != 0 &&
                            !(m->profile && m->profile->verify.mode == 1 &&
                              (m->verify.verdict == 0 || m->verify.verdict == 3));
        ImGui::AlignTextToFramePadding();
        ImGui::TextColored(col(rom_ok ? th.good : th.warn), "%s",
                           rom_ok ? "OK" : "Needed");
        ImGui::SameLine();
        ImGui::TextColored(col(th.text), "%s", relided);
        ImGui::SameLine();
        char browse_lbl[48];
        std::snprintf(browse_lbl, sizeof(browse_lbl), "Browse %s##setup", noun);
        ImGui::PushStyleVar(ImGuiStyleVar_FramePadding, ImVec2(px(12), px(6)));
        if (ImGui::Button(browse_lbl, ImVec2(px(128), px(32)))) {
            const SystemProfile* prof = (const SystemProfile*)m->profile;
            char title[96];
            if (plat == SETUP_PLAT_PSX)
                std::snprintf(title, sizeof(title),
                              "Select %s (.cue)", noun);
            else
                std::snprintf(title, sizeof(title), "Select %s", noun);
            if (prof && prof->rom_filter.pattern_count > 0)
                request_rom_picker(m, title, prof->rom_filter.patterns,
                                   prof->rom_filter.pattern_count,
                                   prof->rom_filter.desc, true);
            else
                request_rom_picker(m, title, NULL, 0, NULL, true);
        }
        ImGui::PopStyleVar();
        if (m->profile && m->profile->verify.mode == 1)
            draw_verdict_block(m, th, ImGui::GetContentRegionAvail().x);
        if (plat == SETUP_PLAT_PSX && m->rom_present && m->rom_full[0]) {
            const char* ext = strrchr(m->rom_full, '.');
            if (ext && (lps_streq_ci(ext, ".bin") || lps_streq_ci(ext, ".img") ||
                        lps_streq_ci(ext, ".car"))) {
                ImGui::PushTextWrapPos(wrap_x);
                ImGui::TextColored(col(th.warn),
                    "You picked a track image (%s). Prefer the matching .cue "
                    "in the same folder so multitrack discs are handled "
                    "correctly.",
                    ext);
                ImGui::PopTextWrapPos();
            }
        }
    }

    /* Full first-run only: Generate & rebuild. Media-confirm (cleared disc/
     * BIOS with sources already present) skips this — regenerate stays in
     * Settings → SYSTEM when the host exposes it. */
    if (!media_confirm &&
        (m->prepare_disc_cb || m->prepare_with_progress_cb)) {
        ImGui::Dummy(ImVec2(0, px(12)));
        char section_buf[128];
        const char* section;
        if (m->prepare_section_title && m->prepare_section_title[0]) {
            std::snprintf(section_buf, sizeof(section_buf), "%s. %s",
                          m->has_bios ? "3" : "2", m->prepare_section_title);
            section = section_buf;
        } else if (plat == SETUP_PLAT_PSX) {
            section = m->has_bios ? "3. Generate from disc"
                                  : "2. Generate from disc";
        } else {
            section = m->has_bios ? "3. Convert raw dump (optional)"
                                  : "2. Convert raw dump (optional)";
        }
        ImGui::TextUnformatted(section);
        ImGui::PushTextWrapPos(wrap_x);
        const char* prep_note =
            (m->prepare_disc_note && m->prepare_disc_note[0])
                ? m->prepare_disc_note
                : (plat == SETUP_PLAT_PSX
                       ? "Uses the selected .cue + track .bin files with the "
                         "local SDK, then "
                         "verifies digests against the game identity. Always "
                         "point Generate at the .cue when both files exist."
                       : "If your disc image is a raw dump that this game "
                         "cannot boot directly, convert it here. Output is "
                         "written next to the game.");
        ImGui::TextColored(col(th.text_muted), "%s", prep_note);
        ImGui::PopTextWrapPos();
        const char* prep_lbl = (m->prepare_disc_label && m->prepare_disc_label[0])
                                   ? m->prepare_disc_label
                                   : ((m->rebuild_after_prepare &&
                                       m->rebuild_with_progress_cb)
                                          ? "Generate & rebuild…"
                                          : (plat == SETUP_PLAT_PSX
                                                 ? "Prepare disc…"
                                                 : "Convert raw dump…"));
        const bool use_selected = m->prepare_use_selected_rom;
        const bool can_prep_selected = use_selected && m->rom_present &&
                                       m->rom_full[0] &&
                                       strcmp(m->rom_size, "--") != 0;
        if (use_selected && !can_prep_selected) ImGui::BeginDisabled();
        if (ImGui::Button(prep_lbl, ImVec2(px(240), px(32)))) {
            if (use_selected) {
                if (can_prep_selected)
                    launcher_model_start_prepare_disc(m, m->rom_full);
            } else {
                char buf[512];
                static const char* kPsxCueOnly[] = { "*.cue" };
                static const char* kDumpPatterns[] = {
                    "*.cue", "*.iso", "*.bin", "*.img", "*.car", "*.chd", "*.*" };
                const char* const* pats =
                    (plat == SETUP_PLAT_PSX) ? kPsxCueOnly : kDumpPatterns;
                const int npat = (plat == SETUP_PLAT_PSX) ? 1 : 7;
                if (launcher_pick_file(
                        plat == SETUP_PLAT_PSX
                            ? "Select disc (.cue)"
                            : "Select raw disc dump to convert",
                        pats, npat,
                        plat == SETUP_PLAT_PSX ? "PlayStation disc (.cue)"
                                               : "Disc dump",
                        buf, sizeof(buf)))
                    launcher_model_start_prepare_disc(m, buf);
            }
        }
        if (use_selected && !can_prep_selected) {
            ImGui::EndDisabled();
            if (ImGui::IsItemHovered(ImGuiHoveredFlags_AllowWhenDisabled))
                ImGui::SetTooltip("Select a verified %s first", noun);
        }
        if (m->setup_preparing) {
            ImGui::CloseCurrentPopup();
            ImGui::EndPopup();
            draw_setup_progress_modal(m, th);
            return;
        }
    }

    if (m->setup_status[0]) {
        ImGui::Dummy(ImVec2(0, px(8)));
        ImGui::PushTextWrapPos(wrap_x);
        ImGui::TextColored(col(th.good), "%s", m->setup_status);
        ImGui::PopTextWrapPos();
    }
    if (m->setup_error[0]) {
        ImGui::Dummy(ImVec2(0, px(6)));
        ImGui::PushTextWrapPos(wrap_x);
        ImGui::TextColored(col(th.warn), "%s", m->setup_error);
        ImGui::PopTextWrapPos();
    }

    ImGui::Dummy(ImVec2(0, px(14)));
    if (m->setup_needs_toolchain) {
        if (ImGui::Button("Back", ImVec2(px(100), px(34)))) {
            m->setup_page = 0;
            /* Re-offer the update UI if a newer pack is still available. */
            m->setup_tc_update_skipped = false;
            m->setup_error[0] = '\0';
            m->setup_status[0] = '\0';
        }
        ImGui::SameLine();
    }
    if (!m->prepare_required_before_continue) {
        const bool ready = launcher_model_can_finish_setup(m);
        const char* continue_lbl =
            media_confirm
                ? (m->has_bios ? "Confirm BIOS and disc" : "Confirm disc")
                : "Continue to launcher";
        if (!ready) ImGui::BeginDisabled();
        if (ImGui::Button(continue_lbl, ImVec2(px(220), px(34)))) {
            launcher_model_finish_setup(m);
            ImGui::CloseCurrentPopup();
        }
        if (!ready) {
            ImGui::EndDisabled();
            if (ImGui::IsItemHovered(ImGuiHoveredFlags_AllowWhenDisabled)) {
                if (!m->rom_present || !m->rom_full[0])
                    ImGui::SetTooltip("Select a %s first", noun);
                else if (m->setup_preparing)
                    ImGui::SetTooltip("Wait for the current job to finish");
                else if (m->has_bios && !m->setup_bios_ok)
                    ImGui::SetTooltip("BIOS check required");
                else if (m->profile && m->profile->verify.mode == 1 &&
                         !m->verify.netplay_ok)
                    ImGui::SetTooltip("Disc mount / track layout not accepted");
            }
        }
        ImGui::SameLine();
    } else if (launcher_model_can_finish_setup(m) &&
               m->action != LNG_ACTION_RELAUNCH) {
        launcher_model_finish_setup(m);
        ImGui::CloseCurrentPopup();
    }
    if (ImGui::Button("Quit", ImVec2(px(100), px(34))))
        m->action = LNG_ACTION_QUIT;

    if (m->setup_wizard_open && !ImGui::IsPopupOpen("First-run setup"))
        ImGui::OpenPopup("First-run setup");
    ImGui::EndPopup();
}


static const char* generate_disabled_reason(const LauncherModel* m) {
    if (!m) return "Generate is unavailable.";
    const bool has_prep =
        m->prepare_with_progress_cb != nullptr || m->prepare_disc_cb != nullptr;
    if (!has_prep) {
        return "Generate is unavailable (project/SDK not found).\n"
               "Launch from RetComM, or run the game from its source tree "
               "(src/current).";
    }
    if (!m->rom_present || !m->rom_full[0])
        return "Select a disc image first";
    return "Generate is unavailable.";
}

void draw_bios_confirm_modal(LauncherModel* m, const LauncherTheme& th) {
    if (m->bios_confirm_open) ImGui::OpenPopup("Switch BIOS?");
    ImVec2 center = ImGui::GetMainViewport()->GetCenter();
    ImGui::SetNextWindowPos(center, ImGuiCond_Appearing, ImVec2(0.5f, 0.5f));
    if (!ImGui::BeginPopupModal("Switch BIOS?", nullptr,
                                ImGuiWindowFlags_AlwaysAutoResize))
        return;
    ImGui::PushTextWrapPos(ImGui::GetCursorPosX() + px(420));
    ImGui::TextWrapped(
        "This retail BIOS is not compiled into the current build yet. "
        "Generate & rebuild will emit its BIOS C and rebuild the game binary "
        "with your current disc and toolchain. OpenBIOS switches never need "
        "this — use Use OpenBIOS instead.");
    if (m->bios_pending_path[0]) {
        ImGui::Dummy(ImVec2(0, px(8)));
        ImGui::TextColored(col(th.text_muted), "Selected:");
        ImGui::TextWrapped("%s", m->bios_pending_path);
    } else {
        ImGui::Dummy(ImVec2(0, px(8)));
        ImGui::TextColored(col(th.text_muted), "Selected: OpenBIOS");
    }
    if (m->setup_bios_detail[0]) {
        ImGui::Dummy(ImVec2(0, px(6)));
        ImGui::TextColored(col(th.warn), "%s", m->setup_bios_detail);
    }
    ImGui::PopTextWrapPos();
    ImGui::Dummy(ImVec2(0, px(12)));
    const bool can_gen = m->rom_present && m->rom_full[0] &&
                         (m->prepare_with_progress_cb || m->prepare_disc_cb);
    if (!can_gen) ImGui::BeginDisabled();
    if (ImGui::Button("Generate & rebuild…", ImVec2(px(200), px(32))))
        launcher_model_bios_confirm_accept(m);
    if (!can_gen) {
        ImGui::EndDisabled();
        if (ImGui::IsItemHovered(ImGuiHoveredFlags_AllowWhenDisabled))
            ImGui::SetTooltip("%s", generate_disabled_reason(m));
    }
    ImGui::SameLine();
    if (ImGui::Button("Use OpenBIOS", ImVec2(px(130), px(32)))) {
        launcher_model_bios_confirm_cancel(m);
        launcher_model_request_bios_path(m, "");
    }
    ImGui::SameLine();
    if (ImGui::Button("Cancel", ImVec2(px(100), px(32))))
        launcher_model_bios_confirm_cancel(m);
    if (!m->bios_confirm_open) ImGui::CloseCurrentPopup();
    ImGui::EndPopup();
}

void draw_bios_play_modal(LauncherModel* m, const LauncherTheme& th) {
    if (m->bios_play_modal_open) ImGui::OpenPopup("BIOS not ready to Play");
    ImVec2 center = ImGui::GetMainViewport()->GetCenter();
    ImGui::SetNextWindowPos(center, ImGuiCond_Appearing, ImVec2(0.5f, 0.5f));
    if (!ImGui::BeginPopupModal("BIOS not ready to Play", nullptr,
                                ImGuiWindowFlags_AlwaysAutoResize))
        return;
    ImGui::PushTextWrapPos(ImGui::GetCursorPosX() + px(440));
    ImGui::TextWrapped(
        "The selected retail BIOS is not compiled into this build. Generate & "
        "rebuild with it (same disc and toolchain), switch to OpenBIOS to Play "
        "without rebuilding, or cancel and keep the current selection.");
    if (m->s.bios_path[0]) {
        ImGui::Dummy(ImVec2(0, px(8)));
        ImGui::TextColored(col(th.text_muted), "Current selection:");
        ImGui::TextWrapped("%s", m->s.bios_path);
    } else {
        ImGui::Dummy(ImVec2(0, px(8)));
        ImGui::TextColored(col(th.text_muted), "Current selection: OpenBIOS");
    }
    if (m->setup_bios_detail[0]) {
        ImGui::Dummy(ImVec2(0, px(6)));
        ImGui::TextColored(col(th.warn), "%s", m->setup_bios_detail);
    }
    ImGui::PopTextWrapPos();
    ImGui::Dummy(ImVec2(0, px(12)));
    const bool can_gen = m->rom_present && m->rom_full[0] &&
                         (m->prepare_with_progress_cb || m->prepare_disc_cb);
    if (!can_gen) ImGui::BeginDisabled();
    if (ImGui::Button("Generate & rebuild…", ImVec2(px(200), px(32))))
        launcher_model_bios_play_generate(m);
    if (!can_gen) {
        ImGui::EndDisabled();
        if (ImGui::IsItemHovered(ImGuiHoveredFlags_AllowWhenDisabled))
            ImGui::SetTooltip("%s", generate_disabled_reason(m));
    }
    ImGui::SameLine();
    if (ImGui::Button("Use OpenBIOS", ImVec2(px(130), px(32))))
        launcher_model_bios_play_use_openbios(m);
    ImGui::SameLine();
    if (ImGui::Button("Cancel", ImVec2(px(100), px(32))))
        launcher_model_bios_play_cancel(m);
    if (!m->bios_play_modal_open) ImGui::CloseCurrentPopup();
    ImGui::EndPopup();
}

void draw_pgo_confirm_modal(LauncherModel* m, const LauncherTheme& th) {
    if (m->pgo_confirm_open) ImGui::OpenPopup("Optimize FMV Playback?");
    ImVec2 center = ImGui::GetMainViewport()->GetCenter();
    ImGui::SetNextWindowPos(center, ImGuiCond_Appearing, ImVec2(0.5f, 0.5f));
    if (!ImGui::BeginPopupModal("Optimize FMV Playback?", nullptr,
                                ImGuiWindowFlags_AlwaysAutoResize))
        return;
    ImGui::PushTextWrapPos(ImGui::GetCursorPosX() + px(460));
    ImGui::TextWrapped(
        "This will rebuild an instrumented binary, run the intro FMV in PGO "
        "training mode (video window open — do not close or interact with it), "
        "then rebuild the game with those profiles. Existing generated C is "
        "reused; the setup wizard is not run.");
    ImGui::Dummy(ImVec2(0, px(8)));
    ImGui::TextColored(col(th.warn),
                       "Expect several minutes. Keep this launcher open until "
                       "training finishes, then the optimized binary relaunches.");
    ImGui::Dummy(ImVec2(0, px(6)));
    ImGui::TextColored(col(th.text_muted),
                       "Each peer may run this independently for rollback "
                       "netplay. Digests must still match.");
    ImGui::PopTextWrapPos();
    ImGui::Dummy(ImVec2(0, px(12)));
    if (ImGui::Button("Start training", ImVec2(px(160), px(32))))
        launcher_model_pgo_confirm_accept(m);
    ImGui::SameLine();
    if (ImGui::Button("Cancel", ImVec2(px(100), px(32))))
        launcher_model_pgo_confirm_cancel(m);
    if (!m->pgo_confirm_open) ImGui::CloseCurrentPopup();
    ImGui::EndPopup();
}

void draw_fmv_timing_confirm_modal(LauncherModel* m, const LauncherTheme& th) {
    if (m->fmv_timing_confirm_open)
        ImGui::OpenPopup("Apply FMV Timing Opt?");
    ImVec2 center = ImGui::GetMainViewport()->GetCenter();
    ImGui::SetNextWindowPos(center, ImGuiCond_Appearing, ImVec2(0.5f, 0.5f));
    if (!ImGui::BeginPopupModal("Apply FMV Timing Opt?", nullptr,
                                ImGuiWindowFlags_AlwaysAutoResize))
        return;
    ImGui::PushTextWrapPos(ImGui::GetCursorPosX() + px(460));
    ImGui::TextWrapped(
        "This regenerates game C from game.toml (including "
        "load_charge_batch for VLC leaves), then rebuilds. It does not "
        "disable load-delay and does not run PGO training.");
    ImGui::Dummy(ImVec2(0, px(8)));
    ImGui::TextColored(col(th.warn),
                       "Expect a few minutes for generate + rebuild. The "
                       "launcher will relaunch the new binary when done.");
    ImGui::Dummy(ImVec2(0, px(6)));
    ImGui::TextColored(col(th.text_muted),
                       "Both peers need the same load_charge_batch setting "
                       "for matching rollback digests.");
    ImGui::PopTextWrapPos();
    ImGui::Dummy(ImVec2(0, px(12)));
    if (ImGui::Button("Generate & rebuild", ImVec2(px(180), px(32))))
        launcher_model_fmv_timing_confirm_accept(m);
    ImGui::SameLine();
    if (ImGui::Button("Cancel", ImVec2(px(100), px(32))))
        launcher_model_fmv_timing_confirm_cancel(m);
    if (!m->fmv_timing_confirm_open) ImGui::CloseCurrentPopup();
    ImGui::EndPopup();
}

void draw_skip_modal(LauncherModel* m) {
    if (m->skip_modal_open) ImGui::OpenPopup("Skip the launcher on boot?");
    ImVec2 center = ImGui::GetMainViewport()->GetCenter();
    ImGui::SetNextWindowPos(center, ImGuiCond_Appearing, ImVec2(0.5f, 0.5f));
    if (ImGui::BeginPopupModal("Skip the launcher on boot?", nullptr,
                               ImGuiWindowFlags_AlwaysAutoResize)) {
        ImGui::TextWrapped("The launcher will no longer appear - the game boots straight in. "
                           "Run with \"--launcher\" or set \"SkipLauncher = 0\" in config.ini "
                           "to bring it back.");
        ImGui::Spacing();
        if (ImGui::Button("Cancel", ImVec2(px(120), 0))) {
            launcher_model_skip_cancel(m); ImGui::CloseCurrentPopup();
        }
        ImGui::SameLine();
        if (ImGui::Button("Skip on Boot", ImVec2(px(140), 0))) {
            launcher_model_skip_confirm(m); ImGui::CloseCurrentPopup();
        }
        ImGui::EndPopup();
    }
}

void draw_restore_defaults_modal(LauncherModel* m) {
    if (m->defaults_modal_open) ImGui::OpenPopup("Restore default settings?");
    ImVec2 center = ImGui::GetMainViewport()->GetCenter();
    ImGui::SetNextWindowPos(center, ImGuiCond_Appearing, ImVec2(0.5f, 0.5f));
    if (ImGui::BeginPopupModal("Restore default settings?", nullptr,
                               ImGuiWindowFlags_AlwaysAutoResize)) {
        ImGui::TextWrapped(
            "This resets display, audio, controller, and launcher choices. "
            "Your selected ROM, SRAM, and save states are not changed.");
        ImGui::Spacing();
        if (ImGui::Button("Cancel", ImVec2(px(120), 0))) {
            launcher_model_cancel_restore_defaults(m);
            ImGui::CloseCurrentPopup();
        }
        ImGui::SameLine();
        if (ImGui::Button("Restore Defaults", ImVec2(px(150), 0))) {
            launcher_model_restore_defaults(m);
            ImGui::CloseCurrentPopup();
        }
        ImGui::EndPopup();
    }
}

void draw_ui(LauncherModel* m, const LauncherTheme& th, int logical_w, int logical_h) {
    ImGuiViewport* vp = ImGui::GetMainViewport();
    ImGui::SetNextWindowPos(vp->Pos);
    ImGui::SetNextWindowSize(vp->Size);
    // CRT ground + scanlines behind everything.
    draw_crt_background(vp->Pos, vp->Size);

    ImGui::PushStyleColor(ImGuiCol_WindowBg, ImVec4(0, 0, 0, 0));   // let CRT show
    ImGui::Begin("##launcher", nullptr,
                 ImGuiWindowFlags_NoTitleBar | ImGuiWindowFlags_NoResize |
                 ImGuiWindowFlags_NoMove | ImGuiWindowFlags_NoCollapse |
                 ImGuiWindowFlags_NoBringToFrontOnFocus);
    ImGui::PopStyleColor();

    // ---- Marquee header: brand · GAME TITLE · subtitle .......... [nav] ----
    ImVec2 hp = ImGui::GetCursorScreenPos();
    // Vertically center the brand mark against the two-line title block (game
    // title at 1.55x + platform at 1.0x). Computed from the mark's fitted height
    // so a short wide mark (e.g. the NES "Nintendo" pill, ~4:1) sits centered
    // between the two lines rather than hugging the first.
    float hdr_top = ImGui::GetCursorPosY();
    // Header brand mark. Drawn only when the profile ships one: a profile can
    // opt out (empty brand, e.g. N64 which leads with its wordmark), in which
    // case g_brand never loads and the title block starts flush-left with no
    // reserved gap. When present, the shared default is a 44x33 square mark; a
    // console that ships its OWN (typically wide) wordmark (SystemProfile.brand
    // — the NES pill, the Genesis logo) draws it larger, sized to a target
    // HEIGHT with proportional width so the logo reads clearly.
    if (g_brand.id && g_brand.w > 0) {
        const SystemProfile* hprof = (const SystemProfile*)m->profile;
        const bool own_brand = hprof && hprof->brand && hprof->brand[0];
        float brand_w = 44.0f, brand_h = 33.0f;
        if (own_brand && g_brand.h > 0) {
            brand_h = 32.0f;
            brand_w = brand_h * (float)g_brand.w / (float)g_brand.h;   // preserve aspect
            if (brand_w > 130.0f) brand_w = 130.0f;                    // sane upper bound
        }
        // Vertically center against the two-line title block (game title at
        // 1.55x + platform at 1.0x), from the fitted height.
        float line_h  = ImGui::GetTextLineHeight();
        float block_h = line_h * 1.55f + ImGui::GetStyle().ItemSpacing.y + line_h;
        float fit_h = px(brand_h);
        if (g_brand.h > 0) {
            float s = (px(brand_w) / g_brand.w < px(brand_h) / g_brand.h)
                        ? px(brand_w) / (float)g_brand.w : px(brand_h) / (float)g_brand.h;
            fit_h = g_brand.h * s;
        }
        ImGui::SetCursorPosY(hdr_top + (block_h - fit_h) * 0.5f);
        image_fit(g_brand, brand_w, brand_h); ImGui::SameLine(0, px(12));
        ImGui::SetCursorPosY(hdr_top);
    }
    ImGui::BeginGroup();
        ImGui::SetWindowFontScale(1.55f);
        ImGui::TextUnformatted(m->game_name ? m->game_name : "(null)");
        ImGui::SetWindowFontScale(1.0f);
        // Platform lockup: the wordmark image when a host supplied one
        // (SystemProfile.wordmark_image), else the plain platform text.
        if (g_wordmark.id && g_wordmark.w > 0) {
            ImGui::Dummy(ImVec2(0, px(2)));
            image_fit(g_wordmark, 240, 20);
        } else if (m->platform && m->platform[0]) {
            ImGui::PushStyleColor(ImGuiCol_Text, col(th.text_muted));
            ImGui::TextUnformatted(m->platform);
            ImGui::PopStyleColor();
        }
    ImGui::EndGroup();
    {   // right-aligned top-level navigation
        const float gap = px(6.0f);
        const float resume_x = ImGui::GetCursorPosX();
        const float resume_y = ImGui::GetCursorPosY();
        const float right = ImGui::GetWindowContentRegionMax().x;
        const float y = hdr_top + px(6.0f);
        if (m->view == LNG_VIEW_DASHBOARD) {
            const int count = 1 + (m->mods ? 1 : 0) +
                              (m->has_assist_tools ? 1 : 0) +
                              ((m->credits_text && m->credits_text[0]) ? 1 : 0);
            const float w = px(110.0f);
            const float total = w * count + gap * (count - 1);
            ImGui::SetCursorPos(ImVec2(right - total, y));
            if (ImGui::Button("Settings", ImVec2(w, px(34))))
                launcher_model_set_view(m, LNG_VIEW_SETTINGS);
            if (m->mods) {
                ImGui::SameLine(0, gap);
                if (ImGui::Button("Mods", ImVec2(w, px(34))))
                    launcher_model_set_view(m, LNG_VIEW_MODS);
            }
            if (m->has_assist_tools) {
                ImGui::SameLine(0, gap);
                if (ImGui::Button("Assist Tools", ImVec2(w, px(34))))
                    launcher_model_set_view(m, LNG_VIEW_ASSIST_TOOLS);
            }
            if (m->credits_text && m->credits_text[0]) {
                ImGui::SameLine(0, gap);
                if (ImGui::Button("Credits", ImVec2(w, px(34))))
                    launcher_model_set_view(m, LNG_VIEW_CREDITS);
            }
        } else {
            const float w = px(110.0f);
            const float name_w = px(170.0f);
            if (m->view == LNG_VIEW_NETPLAY && m->netplay_supported) {
                ImGui::SetCursorPos(ImVec2(right - w - name_w - gap, y));
                const char* player_label = m->s.netplay_player_name[0]
                    ? m->s.netplay_player_name : "Set player name";
                if (ImGui::Button(player_label, ImVec2(name_w, px(34)))) {
                    std::snprintf(m->netplay_name_edit,
                                  sizeof(m->netplay_name_edit), "%s",
                                  m->s.netplay_player_name);
                    m->netplay_name_modal_open = true;
                }
            }
            ImGui::SetCursorPos(ImVec2(right - w, y));
            if (ImGui::Button("< Back", ImVec2(w, px(34))))
                launcher_model_set_view(m, LNG_VIEW_DASHBOARD);
        }
        // Absolute placement prevents three dashboard buttons from mutating
        // the title group's line state and wrapping Settings into the body.
        ImGui::SetCursorPos(ImVec2(resume_x, resume_y));
    }
    // marquee underline: neon gradient rule under the header
    ImGui::Dummy(ImVec2(0, px(8.0f)));
    {
        ImVec2 u = ImGui::GetCursorScreenPos();
        float fw = ImGui::GetContentRegionAvail().x;
        ImDrawList* dl = ImGui::GetWindowDrawList();
        dl->AddRectFilledMultiColor(u, ImVec2(u.x + fw, u.y + px(2.0f)),
            imcol(th.accent2, 0.9f), imcol(th.accent2, 0.15f),
            imcol(th.accent2, 0.15f), imcol(th.accent2, 0.9f));
        glow_rect(dl, u, ImVec2(u.x + fw*0.5f, u.y + px(2.0f)), 0, th.accent2, 0.5f, 3);
    }
    ImGui::Dummy(ImVec2(0, px(12.0f)));
    (void)hp;

    // Body: fixed-height child that scrolls when content overflows, so nothing
    // is ever clipped out of reach. The footer below stays fixed (in the fold).
    const float footer_h = px(92.0f);   // divider + clearance + CTA + its glow
    float body_h = ImGui::GetContentRegionAvail().y - footer_h;
    if (body_h < px(80.0f)) body_h = px(80.0f);
    begin_container("body", ImVec2(0, body_h));
    switch (m->view) {
        case LNG_VIEW_DASHBOARD:  draw_dashboard(m, th, logical_w); break;
        case LNG_VIEW_SETTINGS:   draw_settings(m, th);             break;
        case LNG_VIEW_CONTROLLER: draw_controller(m, th);           break;
        case LNG_VIEW_NETPLAY:    draw_netplay(m, th);              break;
        case LNG_VIEW_MODS:       draw_mods(m, th);                 break;
        case LNG_VIEW_ASSIST_TOOLS: draw_assist_tools(m, th);        break;
        case LNG_VIEW_CREDITS:      draw_credits(m, th);             break;
    }
    end_container();

    draw_footer(m, th, footer_h);
    draw_setup_wizard_modal(m, th);
    draw_bios_confirm_modal(m, th);
    draw_bios_play_modal(m, th);
    draw_pgo_confirm_modal(m, th);
    draw_fmv_timing_confirm_modal(m, th);
    draw_standalone_builtin_rom_picker(m, th);
    draw_skip_modal(m);
    draw_netplay_player_modal(m);
    draw_netplay_network_modal(m, th);
    draw_netplay_host_modal(m, th);
    draw_netplay_password_modal(m, th);
    draw_netplay_direct_modal(m, th);
    draw_netplay_room_modal(m, th);
    draw_restore_defaults_modal(m);
    // Transfer Pak config modal (N64): opened by any tile, dashboard or
    // Controller page. Drawn at root so it isn't clipped by a card child.
    if (m->tpak_slots > 0) draw_tpak_modal(m, th);
    ImGui::End();
    (void)logical_h;
}

bool is_modifier_scancode(SDL_Scancode sc) {
    return sc == SDL_SCANCODE_LCTRL || sc == SDL_SCANCODE_RCTRL ||
           sc == SDL_SCANCODE_LALT  || sc == SDL_SCANCODE_RALT  ||
           sc == SDL_SCANCODE_LSHIFT|| sc == SDL_SCANCODE_RSHIFT ||
           sc == SDL_SCANCODE_LGUI  || sc == SDL_SCANCODE_RGUI;
}

// Keyboard capture for the rebind editors. Player buttons persist a SCANCODE to
// keybinds.ini; system hotkeys persist a KEYCODE+mods to config.ini [KeyMap].
#if !defined(LNG_SDL3)
// SDL2 only: is this raw joystick button/axis already part of the pad's
// SDL_GameController mapping? Raw capture is reserved for inputs the mapping
// can't express (PSR issue #15: 8BitDo 64 C-buttons) — prefer the clean gamepad
// event otherwise. Ported from PSR input_bindings.cpp raw_input_is_mapped().
static bool raw_input_is_mapped(SDL_JoystickID which, bool is_axis, int raw_index) {
    SDL_GameController* gc = SDL_GameControllerFromInstanceID(which);
    if (!gc) return false;
    auto hit = [&](SDL_GameControllerButtonBind b) {
        if (!is_axis && b.bindType == SDL_CONTROLLER_BINDTYPE_BUTTON) return b.value.button == raw_index;
        if ( is_axis && b.bindType == SDL_CONTROLLER_BINDTYPE_AXIS)   return b.value.axis   == raw_index;
        return false;
    };
    for (int i = 0; i < SDL_CONTROLLER_BUTTON_MAX; ++i)
        if (hit(SDL_GameControllerGetBindForButton(gc, (SDL_GameControllerButton)i))) return true;
    for (int i = 0; i < SDL_CONTROLLER_AXIS_MAX; ++i)
        if (hit(SDL_GameControllerGetBindForAxis(gc, (SDL_GameControllerAxis)i))) return true;
    return false;
}
#endif

bool try_capture(LauncherModel* m, const SDL_Event& ev) {
    if (!m->capturing && !m->hk_capturing &&
        !m->camera_capturing)
        return false;

    // ESC cancels any capture — keyboard, pad, or hotkey.
    if (ev.type == SDL_EVENT_KEY_DOWN && LNG_EVKEY(ev) == SDLK_ESCAPE) {
        launcher_model_cancel_capture(m);
        launcher_model_cancel_hk_capture(m);
        launcher_model_cancel_camera_capture(m);
        return true;
    }

    if (m->camera_capturing) {
        if (ev.type != SDL_EVENT_KEY_DOWN) return true;
        launcher_binds_set_camera(
            m, m->capture_camera, (int)LNG_EVSCAN(ev));
        launcher_model_cancel_camera_capture(m);
        return true;
    }

    // ---- GAMEPAD bind capture (capture_pad: Genesis + PSX Gamepad Bindings)
    // Persist a button/axis through the console's native bridge. Swallow
    // everything while listening; a controller button press or a decisive
    // axis push (past a dead threshold) commits. PSX only accepts events from
    // the player's selected Input source device.
    if (m->capturing && m->capture_pad) {
        if (m->settings_bindings) {
            if (ev.type == SDL_EVENT_GAMEPAD_BUTTON_DOWN) {
                launcher_model_set_captured_pad(
                    m, RECOMP_LAUNCHER_PAD_BUTTON((int)LNG_EVGBTN(ev)));
                launcher_model_cancel_capture(m);
                return true;
            }
            if (ev.type == SDL_EVENT_GAMEPAD_AXIS_MOTION) {
                const int val = (int)LNG_EVGAXISVAL(ev);
                if (val >= 20000 || val <= -20000) {
                    launcher_model_set_captured_pad(
                        m, RECOMP_LAUNCHER_PAD_AXIS(
                               (int)LNG_EVGAXIS(ev), val > 0));
                    launcher_model_cancel_capture(m);
                }
                return true;
            }
            return true;
        }
        const SystemProfile* cap_prof = (const SystemProfile*)m->profile;
        const bool psx_cap = cap_prof && cap_prof->id && !strcmp(cap_prof->id, "psx");
        const uint32_t want_id = m->player_pad_id[m->cfg_player];
        auto from_selected = [&](uint32_t which) -> bool {
            if (!psx_cap) return true;                 // Genesis: any pad
            if (!want_id) return false;
            return which == want_id;
        };
        auto try_clear_release_wait = [&](uint32_t which) {
            if (!m->map_all_wait_release) return;
            if (!from_selected(which)) return;
            // Require the whole pad at rest — clearing on a single idle axis
            // let a held stick re-commit on every subsequent AXIS_MOTION.
            if (launcher_input_gamepad_at_rest(which))
                m->map_all_wait_release = false;
        };
        auto commit_pad = [&](int kind, int code, int axis_dir) {
            launcher_binds_set_pad_button(m, m->cfg_player + 1, m->capture_btn,
                                          kind, code, axis_dir);
            if (m->map_all_active)
                launcher_model_map_all_advance(m);
            else
                launcher_model_cancel_capture(m);
        };
        if (ev.type == SDL_EVENT_GAMEPAD_BUTTON_DOWN) {
            if (m->map_all_wait_release) {
                try_clear_release_wait((uint32_t)LNG_EVGBTNWHICH(ev));
                return true;  // never bind while waiting for release
            }
            if (from_selected((uint32_t)LNG_EVGBTNWHICH(ev)))
                commit_pad(LNG_PADBIND_BUTTON, (int)LNG_EVGBTN(ev), 0);
            return true;
        }
        if (ev.type == SDL_EVENT_GAMEPAD_BUTTON_UP) {
            try_clear_release_wait((uint32_t)LNG_EVGBTNWHICH(ev));
            return true;
        }
        if (ev.type == SDL_EVENT_GAMEPAD_AXIS_MOTION) {
            if (from_selected((uint32_t)LNG_EVGAXISWHICH(ev))) {
                if (m->map_all_wait_release) {
                    try_clear_release_wait((uint32_t)LNG_EVGAXISWHICH(ev));
                    return true;
                }
                const int val = (int)LNG_EVGAXISVAL(ev);
                if (val < 20000 && val > -20000) return true; // rest/jitter
                const int axis = (int)LNG_EVGAXIS(ev);
                // PSX: every pad slot is a digital bit. Stick axes belong on
                // L-Stick/R-Stick direction rows (indices 16..23); ignore them
                // on face/shoulder slots so a twitchy stick cannot steal
                // L1/Cross/etc. Trigger axes (L2/R2) are always OK — the
                // runtime thresholds them to digital. Buttons still win when
                // SDL emits GAMEPAD_BUTTON_DOWN for the same physical control.
                if (psx_cap) {
                    const int slot = m->capture_btn;
                    const bool stick_dir_slot = (slot >= 16 && slot < 24);
#if defined(LNG_SDL3)
                    const bool stick_axis =
                        axis == (int)SDL_GAMEPAD_AXIS_LEFTX ||
                        axis == (int)SDL_GAMEPAD_AXIS_LEFTY ||
                        axis == (int)SDL_GAMEPAD_AXIS_RIGHTX ||
                        axis == (int)SDL_GAMEPAD_AXIS_RIGHTY;
#else
                    const bool stick_axis =
                        axis == (int)SDL_CONTROLLER_AXIS_LEFTX ||
                        axis == (int)SDL_CONTROLLER_AXIS_LEFTY ||
                        axis == (int)SDL_CONTROLLER_AXIS_RIGHTX ||
                        axis == (int)SDL_CONTROLLER_AXIS_RIGHTY;
#endif
                    if (!stick_dir_slot && stick_axis) return true;
                }
                commit_pad(LNG_PADBIND_AXIS, axis, val < 0 ? -1 : +1);
            }
            return true;
        }
        return true;   // swallow all other input while capturing a pad bind
    }

    // N64 pad capture: when the player being configured has a gamepad source,
    // the input.cfg store captures pad fields, not keys. Listen for pad
    // buttons / decisive axis throws / (SDL2) raw joystick fields; swallow the
    // keyboard entirely so a stray key can't land in a controller bind.
    if (m->capturing && launcher_binds_wants_pad_capture(m, m->cfg_player + 1)) {
        const int pl = m->cfg_player + 1, b = m->capture_btn, slot = m->capture_slot;
        constexpr int kScanThreshold = 20000;   // decisive throw; ignores resting drift
        if (ev.type == SDL_EVENT_GAMEPAD_BUTTON_DOWN) {
            launcher_binds_set_field(m, pl, b, slot, RUI_N64_FIELD_PAD_BUTTON, (int)LNG_EVGBTN(ev));
            launcher_model_cancel_capture(m);
        } else if (ev.type == SDL_EVENT_GAMEPAD_AXIS_MOTION) {
            const int v = (int)LNG_EVGAXISVAL(ev);
            if (v > kScanThreshold) {
                launcher_binds_set_field(m, pl, b, slot, RUI_N64_FIELD_PAD_AXIS_P, (int)LNG_EVGAXIS(ev));
                launcher_model_cancel_capture(m);
            } else if (v < -kScanThreshold) {
                launcher_binds_set_field(m, pl, b, slot, RUI_N64_FIELD_PAD_AXIS_N, (int)LNG_EVGAXIS(ev));
                launcher_model_cancel_capture(m);
            }
        }
#if !defined(LNG_SDL3)
        else if (ev.type == SDL_EVENT_JOYSTICK_BUTTON_DOWN) {
            if (!raw_input_is_mapped(LNG_EVJBTNWHICH(ev), false, (int)LNG_EVJBTN(ev))) {
                launcher_binds_set_field(m, pl, b, slot, RUI_N64_FIELD_JOY_BUTTON, (int)LNG_EVJBTN(ev));
                launcher_model_cancel_capture(m);
            }
        } else if (ev.type == SDL_EVENT_JOYSTICK_AXIS_MOTION) {
            const int v = (int)LNG_EVJAXISVAL(ev);
            if ((v > kScanThreshold || v < -kScanThreshold) &&
                !raw_input_is_mapped(LNG_EVJAXISWHICH(ev), true, (int)LNG_EVJAXIS(ev))) {
                launcher_binds_set_field(m, pl, b, slot,
                    v > 0 ? RUI_N64_FIELD_JOY_AXIS_P : RUI_N64_FIELD_JOY_AXIS_N, (int)LNG_EVJAXIS(ev));
                launcher_model_cancel_capture(m);
            }
        }
#endif
        return true;   // swallow all other input (keyboard included) while pad-capturing
    }

    /* Mouse buttons are bindable inputs on stores that keep alternates
     * (PSX): bind-a-mouse-button is the whole point of the alt slot. ImGui
     * opens capture on release, so the next down event is deliberate. */
    if (m->capturing && !m->capture_pad) {
        const SystemProfile* mprof = (const SystemProfile*)m->profile;
        const bool alt_store = mprof && mprof->controller.binds_per_input >= 2;
        if (ev.type == SDL_EVENT_MOUSE_BUTTON_UP) return true;   /* swallow */
        if (ev.type == SDL_EVENT_MOUSE_BUTTON_DOWN) {
            if (!alt_store || !m->capture_mouse_armed) return true;
            int btn = (int)ev.button.button;      /* SDL: 1 L, 2 M, 3 R, 4/5 side */
            if (btn >= 1 && btn <= 5) {
                launcher_binds_set_button_slot(m, m->cfg_player + 1, m->capture_btn,
                                               m->capture_slot, 512 + btn);
                launcher_model_cancel_capture(m);
            }
            return true;
        }
    }
    if (ev.type != SDL_EVENT_KEY_DOWN) return true;   // swallow non-key input while capturing
    if (m->capturing) {
        // N64's input.cfg keeps two alternate binds per input, so a keyboard
        // capture there must honour capture_slot via the slot-aware field API.
        // Single-bind stores (SNES/PSX/GBA) use the legacy scancode setter
        // (capture_slot is always 0 for them).
        const SystemProfile* prof = (const SystemProfile*)m->profile;
        if (m->settings_bindings)
            launcher_model_set_captured_key(m, (int)LNG_EVSCAN(ev));
        else if (prof && prof->controller.binds_per_input >= 2 && prof->id && !strcmp(prof->id, "psx"))
            launcher_binds_set_button_slot(m, m->cfg_player + 1, m->capture_btn,
                                           m->capture_slot, (int)LNG_EVSCAN(ev));
        else if (prof && prof->controller.binds_per_input >= 2)
            launcher_binds_set_field(m, m->cfg_player + 1, m->capture_btn, m->capture_slot,
                                     RUI_N64_FIELD_KEY, (int)LNG_EVSCAN(ev));
        else
            launcher_binds_set_button(m, m->cfg_player + 1, m->capture_btn, (int)LNG_EVSCAN(ev));
        launcher_model_cancel_capture(m);
        return true;
    }
    // hotkey capture: wait past a bare modifier press for the real key
    if (is_modifier_scancode((SDL_Scancode)LNG_EVSCAN(ev))) return true;
    launcher_binds_set_hotkey(m, m->capture_hk, (int)LNG_EVKEY(ev), (int)LNG_EVMOD(ev));
    launcher_model_cancel_hk_capture(m);
    return true;
}

bool is_absolute_path(const std::string& path) {
    if (path.empty()) return false;
    if (path[0] == '/' || path[0] == '\\') return true;
    if (path.size() >= 3 && path[1] == ':' &&
        ((path[0] >= 'A' && path[0] <= 'Z') || (path[0] >= 'a' && path[0] <= 'z')) &&
        (path[2] == '/' || path[2] == '\\')) return true;
    return false;
}

std::string normalized_path(const char* path) {
    std::string out = path ? path : "";
    for (char& ch : out)
        if (ch == '\\') ch = '/';
    return out;
}

std::string asset(const char* rel) {
    std::string path = normalized_path(rel);
    if (is_absolute_path(path)) return path;

#if defined(__ANDROID__)
    const char* base = SDL_AndroidGetInternalStoragePath();
#else
    const char* base = SDL_GetBasePath();
#endif
    std::string out = normalized_path(base ? base : "");
    if (!out.empty() && !path.empty() && out.back() != '/')
        out.push_back('/');
    return out + path;
}

} // namespace

// ---- launcher_panels.h contract implementation -------------------------------
// The panel registry is defined above (kPanelRegistry, anonymous namespace) —
// only this backend's draw functions can populate it (they call ImGui::*), so
// this is the sole implementation, matching today's single-backend reality.
extern "C" const LauncherPanel* launcher_panels_all(void) {
    return kPanelRegistry;   // {id=NULL}-sentinel-terminated
}

extern "C" const LauncherPanel* launcher_panel_find(const char* id) {
    if (!id) return nullptr;
    for (int i = 0; kPanelRegistry[i].id; ++i)
        if (strcmp(kPanelRegistry[i].id, id) == 0) return &kPanelRegistry[i];
    return nullptr;
}

extern "C" bool launcher_panel_available(const LauncherPanel* p, const LauncherModel* m) {
    if (!p) return false;
    return p->available ? (p->available(m) != 0) : true;
}

extern "C" LngAction launcher_backend_run(LauncherPlatform* p,
                                          LauncherModel* m,
                                          const LauncherTheme* th) {
    launcher_boot_timing_mark("rui:backend_run:begin");
    IMGUI_CHECKVERSION();
    ImGui::CreateContext();
    ImGuiIO& io = ImGui::GetIO();
    io.ConfigFlags |= ImGuiConfigFlags_NavEnableKeyboard;
    io.ConfigFlags |= ImGuiConfigFlags_NavEnableGamepad;
#if defined(__ANDROID__)
    io.ConfigFlags |= ImGuiConfigFlags_IsTouchScreen;
#endif
    io.IniFilename = nullptr;
    // Test hook: force the focus ring always-on so scripted screenshots can
    // verify nav rendering without a physical pad. Off => normal auto behaviour
    // (ring appears on pad/keyboard, hides on mouse).
#if defined(IMGUI_VERSION_NUM) && IMGUI_VERSION_NUM >= 19140
    // ConfigNavCursorVisibleAlways is 1.91.4+; a pre-1.91.4 host (rt64 1.90.x)
    // simply keeps the default auto-visibility for the test hook.
    if (const char* nv = SDL_getenv("LNG_NAV_ALWAYS"); nv && nv[0] == '1')
        io.ConfigNavCursorVisibleAlways = true;
#endif

    // Force `th` to be materialized before the store. Under the host -Os build,
    // GCC 15.2 otherwise miscompiled `g_th = th` (the value never reached the
    // global — read back as NULL). This barrier + the `volatile` on g_th make
    // the store reliably observable. Do not remove without re-verifying on the
    // gb-recompiled (-Os + ANGLE) build.
#if defined(_MSC_VER)
    _ReadWriteBarrier();
#else
    std::atomic_signal_fence(std::memory_order_seq_cst);
#endif
    g_th = th;
    LNG_ImplSDL_InitForOpenGL(p->window, p->gl);
#ifdef LNG_GLES2
    ImGui_ImplOpenGL3_Init("#version 100");   // GLES 2 GLSL (host ANGLE backend)
#else
    ImGui_ImplOpenGL3_Init("#version 330");
#endif
    launcher_boot_timing_mark("rui:imgui_gl_ready");

    // Box art: per-game path from the ABI when given (multi-variant repos
    // stage one file per variant in a shared build dir), else the default.
    g_boxart = launcher_texture_load(
        asset(m->boxart_path && m->boxart_path[0] ? m->boxart_path
                                                  : "assets/img/boxart.tga").c_str());
    // Controller art comes from the active SystemProfile's ControllerSpec —
    // never hardcoded console filenames in this common backend. Conventions:
    // a 32-bit TGA carries real alpha -> the plain alpha-respecting loader;
    // a 24-bit TGA has a flat backdrop baked in -> keyed out (top-left pixel)
    // so the art sits transparently on the panel. `image_analog`/
    // `image_digital` (the optional PSX-style mode-swap pair) are 32-bit.
    {
        const SystemProfile* prof = (const SystemProfile*)m->profile;
        const char* pad_img = (prof && prof->controller.image)
                                ? prof->controller.image : "pad.tga";
        std::string pad_path = asset((std::string("assets/img/") + pad_img).c_str());
        // TGA header byte 16 = bits per pixel: pick the loader by depth.
        int bpp = 0;
        if (FILE* f = fopen(pad_path.c_str(), "rb")) {
            unsigned char hdr[18];
            if (fread(hdr, 1, sizeof(hdr), f) == sizeof(hdr)) bpp = hdr[16];
            fclose(f);
        }
        g_pad = (bpp == 32)
            ? launcher_texture_load(pad_path.c_str())
            : launcher_texture_load_colorkey(pad_path.c_str(), 24);
        if (prof && prof->controller.image_analog)
            g_pad_analog = launcher_texture_load(
                asset((std::string("assets/img/") + prof->controller.image_analog).c_str()).c_str());
        if (prof && prof->controller.image_digital)
            g_pad_digital = launcher_texture_load(
                asset((std::string("assets/img/") + prof->controller.image_digital).c_str()).c_str());
    }
    // Header brand mark: the active SystemProfile's own (N64 -> the four-color
    // logo, NES/Genesis their wordmark), falling back to the shared recomp-ui
    // mark for consoles that don't set one. Keeps the top-left mark matched to
    // the system on screen.
    {
        const SystemProfile* bprof = (const SystemProfile*)m->profile;
        // NULL brand => the shared dots; a non-NULL EMPTY string => the profile
        // opts out of a corner emblem entirely (N64 leads with its wordmark).
        // Only load when there's an actual filename.
        const char* brand_file = bprof && bprof->brand
                                   ? bprof->brand : "brand_mark.tga";
        if (brand_file && brand_file[0])
            g_brand = launcher_texture_load(
                asset((std::string("assets/img/") + brand_file).c_str()).c_str());
        // Optional platform wordmark: loads only if the profile names one AND
        // the file is present (recomp-ui ships none — a console wordmark may be
        // a third-party trademark). Missing file => header falls back to text.
        if (bprof && bprof->wordmark_image && bprof->wordmark_image[0])
            g_wordmark = launcher_texture_load(
                asset((std::string("assets/img/") + bprof->wordmark_image).c_str()).c_str());
    }
    // Transfer Pak cartridge art (only a tpak game needs it): real GB cart PNGs
    // keyed by cart_kind, empty shell at index 0 (see g_cart / draw_tpak_cart).
    if (m->tpak_slots > 0) {
        static const char* const kCartFiles[5] = {
            "cart_empty.tga", "cart_red.tga", "cart_blue.tga",
            "cart_yellow.tga", "cart_green.tga",
        };
        for (int i = 0; i < 5; ++i)
            g_cart[i] = launcher_texture_load(
                asset((std::string("assets/img/") + kCartFiles[i]).c_str()).c_str());
    }
    g_verdict_ok    = launcher_texture_load(asset("assets/img/verdict_ok.tga").c_str());
    g_verdict_warn  = launcher_texture_load(asset("assets/img/verdict_warn.tga").c_str());
    g_verdict_bad   = launcher_texture_load(asset("assets/img/verdict_bad.tga").c_str());
    g_verdict_none  = launcher_texture_load(asset("assets/img/verdict_none.tga").c_str());
    // memcard.tga is already 32-bit with real alpha (no colorkey backdrop),
    // same as pad_analog.tga/pad_digital.tga above.
    g_memcard = launcher_texture_load(asset("assets/img/memcard.tga").c_str());
    launcher_boot_timing_mark("rui:textures_loaded");

    std::string font_path = asset("assets/fonts/LatoLatin-Regular.ttf");
    // Optional Japanese subset, merged over the Latin base when present (PMS-J).
    // Games that don't ship it stay Latin-only (fopen in apply_scale fails
    // silently), so this path is inert for every other console.
    std::string jp_font_path = asset("assets/fonts/NotoSansJP-Subset.ttf");
    std::string symbols_font_path =
        asset("assets/fonts/NotoSansSymbols2-Regular.ttf");
    std::string emoji_font_path =
        asset("assets/fonts/OpenMoji-black-glyf.ttf");
    float applied_scale = 0.0f;
    launcher_debug_init();

    long smoke_frames = 0, frame = 0;
    if (const char* sf = SDL_getenv("LNG_SMOKE_FRAMES")) smoke_frames = SDL_atoi(sf);

    // Test hook: LNG_FORCE_SCALE simulates a HiDPI display (see the platform
    // layer, which enlarges the window and reports a logical/pixel split). When
    // active, feed that split to ImGui so it renders at pixel density over a
    // logical-sized layout — validating the DPI-independent layout on any OS.
    // Unset => stock ImGui behavior (the SDL/GL backend's own framebuffer scale).
    const char* force_scale_env = SDL_getenv("LNG_FORCE_SCALE");
    const bool force_dpi = force_scale_env && force_scale_env[0] && SDL_atof(force_scale_env) > 1.0;
    bool first_present_marked = false;

    while (m->action == LNG_ACTION_NONE && !p->should_quit) {
        if (smoke_frames > 0 && ++frame > smoke_frames) { m->action = LNG_ACTION_QUIT; break; }

        SDL_Event ev;
        if (SDL_WaitEventTimeout(&ev, 16)) do {
            if (ev.type == SDL_EVENT_QUIT) p->should_quit = true;
            if (ev.type == SDL_EVENT_WINDOW_CLOSE_REQUESTED) p->should_quit = true;
            if (try_capture(m, ev)) continue;
            LNG_ImplSDL_ProcessEvent(&ev);
        } while (SDL_PollEvent(&ev));

        launcher_platform_refresh_metrics(p);
        if (applied_scale != p->display_scale) {
            apply_scale(*th, p->display_scale, font_path.c_str(),
                        jp_font_path.c_str(), symbols_font_path.c_str(),
                        emoji_font_path.c_str());
            applied_scale = p->display_scale;
            if (!first_present_marked)
                launcher_boot_timing_mark("rui:fonts_built");
        }

        // Re-poll connected gamepads every frame so hot-plugged pads (e.g. a
        // DualSense powered on after launch) appear without a relaunch.
        g_pad_count = launcher_input_poll(
            g_pads, LNG_MAX_PADS, m->has_gyro_controls ? 1 : 0);

        // PSX: keep Input source labels on concrete pad names (live SDL name
        // or saved [gamepads] registry), never the generic "Gamepad" placeholder.
        launcher_binds_sync_psx_pad_sources(m, g_pads, g_pad_count);

        // Pad capture release-gate: clear once the selected pad is fully at
        // rest (covers the case where SDL stops sending AXIS_MOTION at rest).
        if (m->capturing && m->capture_pad && m->map_all_wait_release) {
            const uint32_t id = m->player_pad_id[m->cfg_player];
            if (id && launcher_input_gamepad_at_rest(id))
                m->map_all_wait_release = false;
        }

        ImGui_ImplOpenGL3_NewFrame();
        /* Suspend ImGui's GAMEPAD navigation while a bind capture is open.
         *
         * The SDL backend POLLS gamepad state in NewFrame (see
         * ImGui_ImplSDL3_UpdateGamepads) rather than reading the SDL event
         * queue, so swallowing pad events in try_capture cannot stop the pad
         * from driving the menu: press a button to bind it and the focus
         * jumps instead. Clearing the flag for the frame is the only thing
         * that actually suppresses it. Keyboard nav stays on so Esc, arrows
         * and Enter still work while listening. */
        {
            ImGuiIO& nav_io = ImGui::GetIO();
            if (m->capturing || m->hk_capturing || m->camera_capturing)
                nav_io.ConfigFlags &= ~ImGuiConfigFlags_NavEnableGamepad;
            else
                nav_io.ConfigFlags |= ImGuiConfigFlags_NavEnableGamepad;
        }
        LNG_ImplSDL_NewFrame();
        if (force_dpi) {   // Windows has no native point/pixel split — inject it
            ImGuiIO& io = ImGui::GetIO();
            io.DisplaySize = ImVec2((float)p->logical_w, (float)p->logical_h);
            io.DisplayFramebufferScale = ImVec2(p->display_scale, p->display_scale);
        }
        ImGui::NewFrame();
        draw_ui(m, *th, p->logical_w, p->logical_h);
        ImGui::Render();

        glViewport(0, 0, p->pixel_w, p->pixel_h);
        const LngColor bg = th->background;
        glClearColor(bg.r, bg.g, bg.b, bg.a);
        glClear(GL_COLOR_BUFFER_BIT);
        ImGui_ImplOpenGL3_RenderDrawData(ImGui::GetDrawData());
        launcher_debug_step(p, m);   // script/screenshot: after draw, before swap
        launcher_platform_present(p);
        if (!first_present_marked) {
            launcher_boot_timing_mark("rui:first_swap");
            first_present_marked = true;
        }
    }

    launcher_input_shutdown();
    launcher_texture_free(&g_boxart);
    launcher_texture_free(&g_pad);
    launcher_texture_free(&g_pad_analog);
    launcher_texture_free(&g_pad_digital);
    launcher_texture_free(&g_brand);
    launcher_texture_free(&g_verdict_ok);
    launcher_texture_free(&g_verdict_warn);
    launcher_texture_free(&g_verdict_bad);
    launcher_texture_free(&g_verdict_none);
    launcher_texture_free(&g_memcard);
    launcher_texture_free(&g_wordmark);
    for (int i = 0; i < 5; ++i) launcher_texture_free(&g_cart[i]);
    ImGui_ImplOpenGL3_Shutdown();
    LNG_ImplSDL_Shutdown();
    ImGui::DestroyContext();

    if (p->should_quit && m->action == LNG_ACTION_NONE) m->action = LNG_ACTION_QUIT;
    // Persist selected gamepads (defaults if never remapped) so PLAY remembers
    // the pad in input.ini / settings even without an explicit Save click.
    if (m->action == LNG_ACTION_LAUNCH || m->action == LNG_ACTION_RELAUNCH)
        launcher_binds_prepare_psx_launch(m, g_pads, g_pad_count);
    return m->action;
}
