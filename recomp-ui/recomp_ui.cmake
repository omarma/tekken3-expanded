# recomp_ui.cmake — reusable in-game Dear ImGui launcher integration.
#
# One call wires the whole GUI pre-boot launcher into any host target:
#
#     set(RECOMP_UI_ROOT <path-to-recomp-ui>)   # or add as a git submodule
#     include(${RECOMP_UI_ROOT}/recomp_ui.cmake)
#     recomp_target_launcher_ui(<host_target> CONSOLE <console-id>
#                                              [BOXART <path-to-boxart.tga>]
#                                              [BOXART_NAME <dest-basename.tga>]
#                                              [PAD <pad.tga>] [BRAND <brand.tga>])
#
# This is the console-agnostic extraction of the SNES-recomp "launcher_ng"
# Dear ImGui launcher: same UI, same behavior, generic C ABI
# (recomp_launcher_run_window(), declared in src/recomp_launcher.h). Any
# recomp ecosystem (SNES, NES, N64, PSX, ...) can consume this repo as a git
# submodule and get byte-identical launcher behavior with zero UI code of
# its own.
#
# Unlike the in-tree snesrecomp launcher_ng, this module BUNDLES crc32,
# sha256, and keybinds — recomp-ui is fully self-contained and does not
# assume the host already compiles those helpers.
#
# It uses the VENDORED ImGui at src/third_party/imgui — no network /
# FetchContent, so every consumer builds offline and reproducibly.
#
# The host's own main() should call recomp_launcher_run_window() from
# recomp_launcher.h, typically behind a compile-time gate on RECOMP_LAUNCHER
# (defined PRIVATE on the target by this module, so the host can also
# #ifdef RECOMP_LAUNCHER around its call site to match).

# Root of this recomp-ui checkout. A consumer can override RECOMP_UI_ROOT
# before including this file (e.g. when vendoring recomp-ui somewhere
# non-standard); otherwise it defaults to this file's own directory, which is
# correct for the normal "add as a git submodule, include() it" usage.
set(RECOMP_UI_ROOT "${CMAKE_CURRENT_LIST_DIR}" CACHE PATH
    "Root directory of the recomp-ui launcher repo")

option(RECOMP_UI_ENABLE_MODS
    "Enable the schema-driven Mods launcher view (still requires a host provider)"
    OFF)

if(DEFINED SNESRECOMP_SDL_BACKEND)
    if(SNESRECOMP_SDL_BACKEND STREQUAL "SDL3")
        set(RECOMP_UI_SDL3 ON CACHE BOOL
            "Build recomp-ui against SDL3 instead of the SDL2 fallback" FORCE)
    else()
        set(RECOMP_UI_SDL3 OFF CACHE BOOL
            "Build recomp-ui against SDL3 instead of the SDL2 fallback" FORCE)
    endif()
else()
    option(RECOMP_UI_SDL3
        "Build recomp-ui against SDL3 instead of the SDL2 fallback"
        OFF)
endif()

set(RUI_SRC    ${RECOMP_UI_ROOT}/src)
set(RUI_IMGUI  ${RUI_SRC}/third_party/imgui)
set(RUI_ASSETS ${RECOMP_UI_ROOT}/assets)
include("${RECOMP_UI_ROOT}/cmake/recomp_ui_assets.cmake")

# The ImGui backend is C++; the host project() is often C-only. enable_language
# must run at directory scope (not inside the function, which executes during
# generation), so it lives here — safe/idempotent if CXX is already enabled.
enable_language(CXX)

function(recomp_target_launcher_ui TGT)
    # BOXART_NAME: destination basename for BOXART under assets/img/ (default
    # "boxart.tga"). Needed when several targets stage into ONE exe dir (Sonic
    # 3 & Knuckles builds three modes side by side) and each needs its own
    # box art file — pairs with GameInfo.boxart_path the runtime reads.
    # HOST_IMGUI: the host target already compiles Dear ImGui (imgui.cpp +
    # imgui_impl_sdl2 or imgui_impl_sdl3 plus opengl3) — reuse that ONE copy
    # instead of linking a second, which would be a duplicate-symbol / ODR
    # clash. IMGUI_DIR is the
    # host's ImGui source dir (must contain imgui.h + backends/imgui_impl_*.h)
    # that recomp-ui's own backend glue (launcher_imgui.cpp) compiles against.
    # Used by gb-recompiled, whose runtime already vendors + uses ImGui for its
    # in-game menu. Omit both to keep the default self-contained vendored ImGui.
    cmake_parse_arguments(
        RUI
        "HOST_IMGUI"
        "CONSOLE;BOXART;BOXART_NAME;PAD;BRAND;IMGUI_DIR"
        ""
        ${ARGN})

    set_target_properties(${TGT} PROPERTIES CXX_STANDARD 17 CXX_STANDARD_REQUIRED ON)

    # ImGui provider. Normally recomp-ui compiles its OWN vendored Dear ImGui
    # (fully self-contained — the SNES/PSX/GBA standalone consumers). But an
    # rt64-based N64 host already links Dear ImGui (rt64's debug inspector), and
    # two ImGui copies in one binary collide at link (duplicate symbols). Such a
    # host sets RECOMP_UI_HOST_IMGUI=ON and points RECOMP_UI_HOST_IMGUI_INCLUDE
    # at its ImGui + backends headers; recomp-ui then compiles ONLY launcher
    # code against those headers and links the host's ImGui core/backends. The
    # launcher UI is version-guarded (see launcher_imgui.cpp) so it builds
    # against the host's ImGui even when older than the vendored one.
    set(_rui_use_host_imgui FALSE)
    set(_rui_host_imgui_include "")
    if(RECOMP_UI_HOST_IMGUI)
        set(_rui_use_host_imgui TRUE)
        set(_rui_host_imgui_include "${RECOMP_UI_HOST_IMGUI_INCLUDE}")
    elseif(RUI_HOST_IMGUI)
        if(NOT RUI_IMGUI_DIR)
            message(FATAL_ERROR "recomp_target_launcher_ui(HOST_IMGUI ...) requires IMGUI_DIR <host imgui source dir>")
        endif()
        set(_rui_use_host_imgui TRUE)
        set(_rui_host_imgui_include "${RUI_IMGUI_DIR}")
    endif()

    if(RECOMP_UI_SDL3)
        set(_rui_platform_source
            ${RUI_SRC}/common/launcher_platform_sdl3.c)
        set(_rui_imgui_platform_backend
            ${RUI_IMGUI}/backends/imgui_impl_sdl3.cpp)
    else()
        set(_rui_platform_source
            ${RUI_SRC}/common/launcher_platform_sdl2.c)
        set(_rui_imgui_platform_backend
            ${RUI_IMGUI}/backends/imgui_impl_sdl2.cpp)
    endif()

    if(_rui_use_host_imgui)
        message(STATUS "recomp-ui: using HOST Dear ImGui (${_rui_host_imgui_include})")
        set(_rui_imgui_sources)   # host compiles imgui core + backends
    else()
        set(_rui_imgui_sources
            ${RUI_IMGUI}/imgui.cpp
            ${RUI_IMGUI}/imgui_draw.cpp
            ${RUI_IMGUI}/imgui_tables.cpp
            ${RUI_IMGUI}/imgui_widgets.cpp
            ${_rui_imgui_platform_backend}
            ${RUI_IMGUI}/backends/imgui_impl_opengl3.cpp)
    endif()

    target_sources(${TGT} PRIVATE
        # console-agnostic launcher core (C) — src/common/
        ${RUI_SRC}/common/launcher_model.c
        ${_rui_platform_source}
        ${RUI_SRC}/common/launcher_gl.c
        ${RUI_SRC}/common/launcher_input.c
        ${RUI_SRC}/common/launcher_files.c
        ${RUI_SRC}/common/launcher_debug.c
        ${RUI_SRC}/common/launcher_binds.c
        ${RUI_SRC}/common/launcher_udp_port.c  # host-lobby UDP port probe / auto-pick
        ${RUI_SRC}/common/recomp_runtime_ui.c # renderer-agnostic in-game overlay
        ${RUI_SRC}/common/recomp_runtime_settings.c # shared cross-ecosystem setting catalog
        ${RUI_SRC}/common/launcher_boot_timing.c  # PSX_LAUNCHER_BOOT_TIMING / LNG_BOOT_TIMING
        ${RUI_SRC}/common/launcher_ng_capi.c   # implements recomp_launcher_run_window()
        ${RUI_SRC}/third_party/tinyfiledialogs.c
        # console-specific helpers (src/consoles/<id>/) — always compiled, only
        # reached when the active SystemProfile opts into the capability
        ${RUI_SRC}/consoles/psx/memcard_format.c   # PS1 blank memory-card image writer
        ${RUI_SRC}/consoles/psx/psx_binds.c        # PSX-native keybind persistence bridge
        ${RUI_SRC}/consoles/psx/psx_pad_binds.c    # PSX gamepad input.ini per-GUID bridge
        ${RUI_SRC}/consoles/n64/n64_binds.c        # N64-native input.cfg bridge (kb+pad tables)
        ${RUI_SRC}/consoles/nes/nes_binds.c        # NES-native keybind persistence bridge
        ${RUI_SRC}/consoles/genesis/genesis_binds.c # Genesis-native settings.ini key.*/pad.* bridge
        ${RUI_SRC}/consoles/gb/gb_binds.c          # Game Boy-native keybinds.ini [controls] bridge
        # bundled engine helpers (recomp-ui is self-contained; the host does
        # not need to already compile these)
        ${RUI_SRC}/common/crc32.c
        ${RUI_SRC}/common/sha256.c
        ${RUI_SRC}/common/sha1.c        # cartridge ROM identity (GBA/SNES gate on SHA-1)
        ${RUI_SRC}/common/keybinds.c
        ${RUI_SRC}/common/ips_patch.c   # MSU-1 IPS auto-patching (launcher_model.c)
        # Dear ImGui backend (the shipping UI) + vendored ImGui core/backends
        # (the latter omitted when a host provides its own — see above)
        ${RUI_SRC}/common/backends/imgui/launcher_imgui.cpp
        ${RUI_SRC}/common/backends/imgui/runtime_ui_imgui.cpp
        ${_rui_imgui_sources}
    )

    target_include_directories(${TGT} PRIVATE
        ${RUI_SRC}                   # recomp_launcher.h / launcher_profile.h / launcher_system.h
                                     # + "third_party/..." + "consoles/<id>/..." includes
        ${RUI_SRC}/common            # launcher core headers (bare-name includes)
    )
    if(_rui_use_host_imgui)
        target_include_directories(${TGT} PRIVATE ${_rui_host_imgui_include})
    else()
        target_include_directories(${TGT} PRIVATE ${RUI_IMGUI} ${RUI_IMGUI}/backends)
    endif()

    target_compile_definitions(${TGT} PRIVATE
        RECOMP_LAUNCHER           # un-gate the GUI launcher block in the host's main()
        RECOMP_UI_ENABLE_MODS=$<BOOL:${RECOMP_UI_ENABLE_MODS}>
        SDL_MAIN_HANDLED)         # our real main() is the entry point (no SDL_main redirect)
    if(ANDROID)
        target_compile_definitions(${TGT} PRIVATE
            LNG_GLES2=1
            IMGUI_IMPL_OPENGL_ES2=1)
    endif()
    if(RECOMP_UI_SDL3)
        target_compile_definitions(${TGT} PRIVATE LNG_SDL3=1)
        message(STATUS "recomp-ui: SDL3 platform backend")
    else()
        message(STATUS "recomp-ui: SDL2 compatibility platform backend")
    endif()

    # OpenGL: the ImGui GL3 backend + launcher_gl.c need the system GL library.
    # Link it here so a host gets it from this ONE call (self-contained) rather
    # than having to remember to link OpenGL itself — mirrors the standalone
    # CMakeLists.txt. SDL is still the host's to provide (its provenance varies:
    # vendored, find_package, etc.); GL is a uniform system lib, so it lives here.
    if(ANDROID)
        find_library(RUI_GLES2_LIBRARY GLESv2 REQUIRED)
        find_library(RUI_EGL_LIBRARY EGL REQUIRED)
        find_library(RUI_LOG_LIBRARY log REQUIRED)
        target_link_libraries(${TGT} PRIVATE
            ${RUI_GLES2_LIBRARY} ${RUI_EGL_LIBRARY} ${RUI_LOG_LIBRARY})
    elseif(WIN32)
        # ws2_32: launcher_udp_port.c exclusive UDP bind probes for host lobby.
        target_link_libraries(${TGT} PRIVATE opengl32 ws2_32)
    else()
        find_package(OpenGL REQUIRED)
        target_link_libraries(${TGT} PRIVATE OpenGL::GL ${CMAKE_DL_LIBS})
    endif()

    if(NOT MSVC)
        # the vendored ImGui + tinyfiledialogs compile clean; nothing extra needed.
    endif()

    # ---- stage runtime assets next to the exe -----------------------------------
    # Common chrome is always staged. CONSOLE selects exactly one validated
    # assets/consoles/<id>/ manifest, so a PSX game cannot silently ship N64
    # cartridges or NES/SNES controller art. The RUNTIME layout
    # next to the exe stays flat (assets/fonts + assets/img) — the launcher's
    # load paths are unchanged. The standalone preview opts into all explicitly.
    if(NOT ANDROID)
        _recomp_ui_stage_assets(${TGT} "${RUI_CONSOLE}")
    endif()
    # Per-console controller image: overrides the default pad.tga (e.g. a
    # PlayStation DualShock for PSX). 24-bit TGA, top-left pixel = colorkey.
    if(RUI_PAD AND EXISTS ${RUI_PAD})
        add_custom_command(TARGET ${TGT} POST_BUILD
            COMMAND ${CMAKE_COMMAND} -E copy_if_different
                    ${RUI_PAD} $<TARGET_FILE_DIR:${TGT}>/assets/img/pad.tga
            VERBATIM)
    endif()
    if(RUI_BOXART AND EXISTS ${RUI_BOXART})
        set(RUI_BOXART_DEST "boxart.tga")
        if(RUI_BOXART_NAME)
            set(RUI_BOXART_DEST "${RUI_BOXART_NAME}")
        endif()
        add_custom_command(TARGET ${TGT} POST_BUILD
            COMMAND ${CMAKE_COMMAND} -E copy_if_different
                    ${RUI_BOXART} $<TARGET_FILE_DIR:${TGT}>/assets/img/${RUI_BOXART_DEST}
            VERBATIM)
    endif()
    # Per-console brand mark (top-left, next to the game title): overrides the
    # default brand_mark.tga (e.g. the PlayStation shapes for PSX). 32-bit TGA.
    if(RUI_BRAND AND EXISTS ${RUI_BRAND})
        add_custom_command(TARGET ${TGT} POST_BUILD
            COMMAND ${CMAKE_COMMAND} -E copy_if_different
                    ${RUI_BRAND} $<TARGET_FILE_DIR:${TGT}>/assets/img/brand_mark.tga
            VERBATIM)
    endif()
endfunction()

# recomp_target_runtime_ui_sdlrenderer2(<host_target>)
#
# Adds the official Dear ImGui SDL_Renderer2 renderer backend to exactly one
# host target. ImGui core and the SDL2 platform backend remain owned by
# recomp_target_launcher_ui() (or by a HOST_IMGUI provider), so SDL_Renderer
# runtime families can opt in without creating a second ImGui copy or duplicate
# backend symbols.
function(recomp_target_runtime_ui_sdlrenderer2 TGT)
    if(NOT TARGET ${TGT})
        message(FATAL_ERROR
            "recomp_target_runtime_ui_sdlrenderer2(${TGT}): target does not exist")
    endif()

    get_target_property(_rui_sdlrenderer2_added ${TGT}
        RECOMP_UI_SDLRENDERER2_ADDED)
    if(_rui_sdlrenderer2_added)
        return()
    endif()

    target_sources(${TGT} PRIVATE
        ${RUI_IMGUI}/backends/imgui_impl_sdlrenderer2.cpp)
    target_include_directories(${TGT} PRIVATE
        ${RUI_IMGUI}
        ${RUI_IMGUI}/backends)
    set_property(TARGET ${TGT} PROPERTY RECOMP_UI_SDLRENDERER2_ADDED TRUE)
endfunction()

# recomp_stage_launcher_assets(<exe_target> CONSOLE <console-id>
#                              [BOXART <path>] [BOXART_NAME <name>])
#
# Staging-ONLY helper (no source compilation) for hosts that compile the
# recomp-ui launcher into a SHARED runtime library (e.g. gb-recompiled's gbrt)
# and therefore can't use recomp_target_launcher_ui() — its POST_BUILD asset
# copy has to attach to the final EXE target, not the static lib. Call this on
# the game exe from the generated project's CMake. Stages the shared chrome,
# the selected console family, and optional per-game box art next to the exe
# (the flat assets/fonts + assets/img layout the launcher loads).
function(recomp_stage_launcher_assets TGT)
    cmake_parse_arguments(RSA "" "CONSOLE;BOXART;BOXART_NAME" "" ${ARGN})
    _recomp_ui_stage_assets(${TGT} "${RSA_CONSOLE}")
    # Per-game box art (24/32-bit TGA). The seam points GameInfo.boxart_path at
    # "assets/img/boxart.tga" (or BOXART_NAME) next to the exe.
    if(RSA_BOXART AND EXISTS ${RSA_BOXART})
        set(RSA_DEST "boxart.tga")
        if(RSA_BOXART_NAME)
            set(RSA_DEST "${RSA_BOXART_NAME}")
        endif()
        add_custom_command(TARGET ${TGT} POST_BUILD
            COMMAND ${CMAKE_COMMAND} -E copy_if_different
                    ${RSA_BOXART} $<TARGET_FILE_DIR:${TGT}>/assets/img/${RSA_DEST}
            VERBATIM)
    endif()
endfunction()
