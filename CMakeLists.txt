cmake_minimum_required(VERSION 3.20)
project(Tekken3Recomp LANGUAGES C CXX)

# Tekken 3 Expanded.exe, the double-click way to play on Windows: the setup
# builds it and copies it beside Setup Tekken 3.cmd (launcher/setup_backend.py).
# Defined before runtime.cmake so none of the game's build settings reach it.
if(WIN32)
    add_executable(tekken3-play WIN32 launcher/bootstrap.c)
    target_link_libraries(tekken3-play PRIVATE user32)
    set_target_properties(tekken3-play PROPERTIES RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}")
    # The T3E icon (launcher/icon.rc) on both executables, when a resource
    # compiler is there; without one they keep the default icon.
    include(CheckLanguage)
    check_language(RC)
    if(CMAKE_RC_COMPILER)
        enable_language(RC)
        target_sources(tekken3-play PRIVATE launcher/icon.rc)
    endif()
endif()

set(PSXRECOMP_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/psxrecomp" CACHE PATH
    "Path to psxrecomp")

# --- Opt-in product surfaces (OFF by default in the framework) -------------
# Scaffold prompts / flags fill these. Without recomp-ui, PSX_RECOMP_UI is OFF.
# Setup-host CI requires WIZARD_CMAKE_BLOCK / ENABLE_SETUP_WIZARD (FORCE_SETUP_HOST
# alone does not open first-run / Generate & rebuild).
# recomp-ui submodule present (PSX_RECOMP_UI defaults ON).
# Full netplay UI — enable after adding recomp-ui + testing:
# if(EXISTS "${PSXRECOMP_ROOT}/lib/recomp-net/CMakeLists.txt")
#     set(PSX_NETPLAY ON CACHE BOOL "…" FORCE)
# endif()
set(PSX_SETUP_WIZARD ON CACHE BOOL
    "Advertise first-run setup wizard + Generate & rebuild in recomp-ui" FORCE)
include("${PSXRECOMP_ROOT}/runtime/runtime.cmake")

option(TEKKEN3_BUILD_RECOMP_RUNTIME
    "Build the legacy hybrid recompilation/reference executable" ON)
if(TEKKEN3_BUILD_RECOMP_RUNTIME)
psxrecomp_add_game_runtime(psx-runtime
    # ENABLE_NETPLAY_IF_PRESENT
    # NETPLAY_LOBBY_URL "ws://netplay.retcomm.net:8765"
    ENABLE_SETUP_WIZARD
    WINDOW_TITLE "Tekken 3 Expanded"
    DEFAULT_GAME_CONFIG_PATH "game.toml"
    MAX_PLAYERS 2
    # LAUNCHER_BOXART "${CMAKE_CURRENT_SOURCE_DIR}/launcher_assets/img/boxart.tga"
    GEN_MARKER "generated/SLUS_004.02_dispatch.c"
    GEN_FULL_GLOB "generated/SLUS_004.02_full_*.c"
    CODEGEN_SETUP_SOURCES "${CMAKE_CURRENT_SOURCE_DIR}/codegen_setup.c"
)

# Game-owned visual enhancements are trusted static plugins.  Package
# manifests can select them, but never load native code from an archive.
if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/generated/SLUS_004.02_dispatch.c"
   AND NOT PSXRECOMP_FORCE_SETUP_HOST)
target_sources(psx-runtime PRIVATE
    "${CMAKE_CURRENT_SOURCE_DIR}/src/tekken3_widescreen_mod.c"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/tekken3_fight_camera.c"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/tekken3_forest_hd_mod.c"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/tekken3_nina_skin_mod.c"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/tekken3_xiaoyu_skin_mod.c"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/tekken3_anna_skin_mod.c"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/tekken3_kuma_skin_mod.c"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/tekken3_unlock_characters_mod.c"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/tekken3_difficulty_mod.c"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/tekken3_main_menu.c"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/tekken3_new_skin_mods.c"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/tekken3_selector_timer_mod.c"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/tekken3_jin_ttt1_hit_mod.c"
)
# Tekken-only hooks inside the shared psxrecomp runtime (upstream guards them
# with TEKKEN3_LAUNCHER, which also brings its launcher).
target_compile_definitions(psx-runtime PRIVATE TEKKEN3_RUNTIME=1)

# Rebuild a narrow native camera variant from the current generated routine.
# Exact MIPS/operand guards keep this reproducible without editing guest RAM
# or maintaining a second hand-copied recompiler output file.
find_package(Python3 REQUIRED COMPONENTS Interpreter)
set(TEKKEN3_FIGHT_CAMERA_SOURCE "${CMAKE_CURRENT_BINARY_DIR}/tekken3_fight_camera_generated.c")
add_custom_target(tekken3_fight_camera_codegen
    COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tools/build_fight_camera.py"
        --source "${CMAKE_CURRENT_SOURCE_DIR}/generated/SLUS_004.02_full_26.c"
        --exe "${CMAKE_CURRENT_SOURCE_DIR}/disc/SLUS_004.02"
        --output "${TEKKEN3_FIGHT_CAMERA_SOURCE}"
    BYPRODUCTS "${TEKKEN3_FIGHT_CAMERA_SOURCE}"
    VERBATIM)
add_dependencies(psx-runtime tekken3_fight_camera_codegen)
target_sources(psx-runtime PRIVATE "${TEKKEN3_FIGHT_CAMERA_SOURCE}")
target_include_directories(psx-runtime PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/src")
set_source_files_properties("${TEKKEN3_FIGHT_CAMERA_SOURCE}" PROPERTIES
    INCLUDE_DIRECTORIES "${CMAKE_CURRENT_SOURCE_DIR}/generated")
# Apple's ld64 has no --wrap, and the option is a hard error there, so every
# wrapped routine below is redirected with the preprocessor instead: the
# defining TU is compiled with -D<sym>=__real_<sym> and the wrapping TU with
# -D__wrap_<sym>=<sym>. Call sites elsewhere still say <sym> and therefore
# reach the wrapper, which is what --wrap does, and a wrapper delegating to
# __real_<sym> still finds the stock routine. Every other platform keeps the
# linker option. WRAPPER names a generated wrapper that cannot be found by
# scanning src/; DEFINED_IN overrides a defining TU that is not compiled.
function(tekken3_wrap_symbol sym)
    cmake_parse_arguments(TW "" "WRAPPER;DEFINED_IN" "" ${ARGN})
    if(NOT APPLE)
        target_link_options(psx-runtime PRIVATE "-Wl,--wrap=${sym}")
        return()
    endif()
    set_property(GLOBAL APPEND PROPERTY TEKKEN3_WRAP_SYMS "${sym}")
    if(TW_WRAPPER)
        set_property(GLOBAL PROPERTY TEKKEN3_WRAP_WRAPPER_${sym} "${TW_WRAPPER}")
    endif()
    if(TW_DEFINED_IN)
        set_property(GLOBAL PROPERTY TEKKEN3_WRAP_DEF_${sym} "${TW_DEFINED_IN}")
    endif()
endfunction()

# Resolve every accumulated symbol in one pass and apply the definitions.
function(tekken3_apply_wraps)
    if(NOT APPLE)
        return()
    endif()
    get_property(_syms GLOBAL PROPERTY TEKKEN3_WRAP_SYMS)
    if(NOT _syms)
        return()
    endif()
    string(REPLACE ";" "," _symarg "${_syms}")
    execute_process(
        COMMAND "${Python3_EXECUTABLE}"
                "${CMAKE_CURRENT_SOURCE_DIR}/tools/resolve_wrap_targets.py"
                --root "${CMAKE_CURRENT_SOURCE_DIR}" --symbols "${_symarg}"
        OUTPUT_VARIABLE _out ERROR_VARIABLE _err RESULT_VARIABLE _rc
        OUTPUT_STRIP_TRAILING_WHITESPACE)
    if(NOT _rc EQUAL 0)
        message(FATAL_ERROR
            "resolve_wrap_targets.py failed (exit ${_rc}); --wrap emulation "
            "cannot be applied:\n${_err}")
    endif()
    string(REPLACE "\n" ";" _lines "${_out}")
    foreach(_line IN LISTS _lines)
        string(REPLACE "|" ";" _parts "${_line}")
        list(GET _parts 0 _sym)
        list(GET _parts 1 _def)
        set(_wrapper "")
        list(LENGTH _parts _n)
        if(_n GREATER 2)
            list(GET _parts 2 _wrapper)
        endif()
        get_property(_def_override GLOBAL PROPERTY TEKKEN3_WRAP_DEF_${_sym})
        if(_def_override)
            set(_def "${_def_override}")
        endif()
        get_property(_wrapper_override GLOBAL PROPERTY TEKKEN3_WRAP_WRAPPER_${_sym})
        if(_wrapper_override)
            set(_wrapper "${_wrapper_override}")
        endif()
        if(NOT _wrapper)
            message(FATAL_ERROR
                "no wrapper found for ${_sym}: it is defined in ${_def} but no "
                "src/*.c defines __wrap_${_sym}. Pass WRAPPER to "
                "tekken3_wrap_symbol() when a generated file wraps it.")
        endif()
        set_property(SOURCE "${_def}" APPEND PROPERTY
            COMPILE_DEFINITIONS "${_sym}=__real_${_sym}")
        set_property(SOURCE "${_wrapper}" APPEND PROPERTY
            COMPILE_DEFINITIONS "__wrap_${_sym}=${_sym}")
    endforeach()
    list(LENGTH _syms _count)
    message(STATUS "Emulated -Wl,--wrap for ${_count} symbol(s) without ld64")
endfunction()

# Apple's ld64 has no --wrap, and the option is a hard error there. The
# regenerated camera variant is a complete replacement: build_fight_camera.py
# renames the stock definition to __wrap_func_80064E10, nothing calls
# __real_func_80064E10, and every reference lives in the dispatch table. So
# reproduce --wrap with the preprocessor: move the stock definition aside in
# its own shard, and let the variant take the name the call sites use. Other
# platforms keep the linker option.
tekken3_wrap_symbol(func_80064E10 WRAPPER "${TEKKEN3_FIGHT_CAMERA_SOURCE}")
# "QUIT GAME" in the main menu: the screen dispatch arm that enters the
# menu overlay (src/tekken3_main_menu.c).
tekken3_wrap_symbol(func_80028CD4)
# Sounds that must not speed up with the load that follows them (same file).
tekken3_wrap_symbol(func_800753BC)
set_property(TARGET psx-runtime APPEND PROPERTY LINK_DEPENDS
    "${CMAKE_CURRENT_SOURCE_DIR}/mods/preloaded/packages/tekken3.enhancement.true-widescreen/1.0.0/manifest.toml")

# TTT1 characters. The code needs no game data to build; the characters come
# from the user's own ROM (tools/ttt1_import.py, tools/ttt1_stage_roster.py)
# and the mod stays idle until they are staged.
option(TEKKEN3_TTT1_CHARACTERS "Build the TTT1 characters mod" ON)
if(TEKKEN3_TTT1_CHARACTERS)
    target_sources(psx-runtime PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/src/tekken3_ttt1_mod.c")
    target_sources(psx-runtime PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/src/tekken3_ttt1_renderer.c")
    tekken3_wrap_symbol(func_80036CAC)
    tekken3_wrap_symbol(func_80035B28)
    tekken3_wrap_symbol(func_80035BC0)
    tekken3_wrap_symbol(func_80035190)
    tekken3_wrap_symbol(func_80035CE8)
    target_sources(psx-runtime PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/src/tekken3_ttt1_motion.c")
    tekken3_wrap_symbol(func_8003AD10)
    tekken3_wrap_symbol(func_80037CBC)
    tekken3_wrap_symbol(func_80034844)
    tekken3_wrap_symbol(func_8006A3BC)
    tekken3_wrap_symbol(func_8003C8F0)
    target_sources(psx-runtime PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/src/tekken3_ttt1_combat.c")
    set(TTT1_COMBAT_HOOKS "${CMAKE_CURRENT_BINARY_DIR}/tekken3_ttt1_combat_generated.c")
    set(TTT1_PUSH_HOOKS "${CMAKE_CURRENT_BINARY_DIR}/tekken3_ttt1_push_generated.c")
    add_custom_target(tekken3_ttt1_combat_codegen
        COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tools/build_ttt1_combat_hooks.py"
            --root "${CMAKE_CURRENT_SOURCE_DIR}" --output "${TTT1_COMBAT_HOOKS}"
        BYPRODUCTS "${TTT1_COMBAT_HOOKS}" "${TTT1_PUSH_HOOKS}" VERBATIM)
    add_dependencies(psx-runtime tekken3_ttt1_combat_codegen)
    target_sources(psx-runtime PRIVATE "${TTT1_COMBAT_HOOKS}" "${TTT1_PUSH_HOOKS}")
    set_source_files_properties("${CMAKE_CURRENT_SOURCE_DIR}/generated/SLUS_004.02_full_04.c" PROPERTIES HEADER_FILE_ONLY TRUE)
    set_source_files_properties("${TTT1_COMBAT_HOOKS}" "${TTT1_PUSH_HOOKS}" PROPERTIES
        INCLUDE_DIRECTORIES "${CMAKE_CURRENT_SOURCE_DIR}/generated")
    tekken3_wrap_symbol(func_8002F3AC WRAPPER "${TTT1_COMBAT_HOOKS}")
    tekken3_wrap_symbol(func_8003F098 WRAPPER "${TTT1_COMBAT_HOOKS}")
    tekken3_wrap_symbol(func_8002DE24 WRAPPER "${TTT1_COMBAT_HOOKS}")
    target_sources(psx-runtime PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/src/tekken3_ttt1_voices.c")
    tekken3_wrap_symbol(func_80040C90)
    target_sources(psx-runtime PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/src/tekken3_ttt1_sfx.c")
    tekken3_wrap_symbol(func_80040DF4)
    tekken3_wrap_symbol(func_80041CB4)
    tekken3_wrap_symbol(func_800757A8)
    tekken3_wrap_symbol(func_8008D658)
    tekken3_wrap_symbol(func_8003CB84)
    tekken3_wrap_symbol(spu_render)
    tekken3_wrap_symbol(spu_set_host_mix_volume)
    tekken3_wrap_symbol(spu_init)
    tekken3_wrap_symbol(spu_snapshot_read)
    tekken3_wrap_symbol(func_8002D178)
    tekken3_wrap_symbol(func_80038B4C)
    tekken3_wrap_symbol(func_800389C0)
    tekken3_wrap_symbol(func_8002D264)
    tekken3_wrap_symbol(func_8002E8D0)
    tekken3_wrap_symbol(func_8002E0BC)
    tekken3_wrap_symbol(func_8002CC28)
    tekken3_wrap_symbol(func_8002EE94)
    tekken3_wrap_symbol(func_8002CD7C)
    tekken3_wrap_symbol(func_80059890)
    tekken3_wrap_symbol(func_8002C580)
    tekken3_wrap_symbol(func_8002A914)
    target_sources(psx-runtime PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/src/tekken3_ttt1_selector.c")
    # Natives on their TTT1 moves, chosen on the selector's MOVESET card
    # (src/tekken3_native_moves.c), drawn in the display list 8007E0B8 hands over.
    target_sources(psx-runtime PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/src/tekken3_native_moves.c")
    tekken3_wrap_symbol(func_8007E0B8)
    tekken3_wrap_symbol(tekken3_outfits_input)
    tekken3_wrap_symbol(host_osd_outfit_image)
    tekken3_wrap_symbol(host_osd_draw_sdl)
    target_sources(psx-runtime PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/src/tekken3_ttt1_roster.c")
    # Kazuya's TTT ending in place of his Arcade ending movie (TTT Cinematics).
    target_sources(psx-runtime PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/src/tekken3_embu_scenes.c")
    tekken3_wrap_symbol(func_80063EEC)
    tekken3_wrap_symbol(func_8004FF74)
    tekken3_wrap_symbol(func_8004E000)
    tekken3_wrap_symbol(func_8002A40C)
    tekken3_wrap_symbol(func_8006D7CC)
    tekken3_wrap_symbol(func_80052938)
    tekken3_wrap_symbol(func_80052940)
    tekken3_wrap_symbol(func_8004B790)
    tekken3_wrap_symbol(func_8004B928)
    # Shard 04 is HEADER_FILE_ONLY here; TTT1_PUSH_HOOKS compiles its copy.
    tekken3_wrap_symbol(func_80031BFC DEFINED_IN "${TTT1_PUSH_HOOKS}")
    tekken3_wrap_symbol(func_8003172C DEFINED_IN "${TTT1_PUSH_HOOKS}")
    tekken3_wrap_symbol(func_80052AD0)
    tekken3_wrap_symbol(func_80052958)
    tekken3_wrap_symbol(func_80052990)
    tekken3_wrap_symbol(func_8006BF20)
    tekken3_wrap_symbol(func_8003626C)
    tekken3_wrap_symbol(func_80036294)
    tekken3_wrap_symbol(func_800362C4)
    tekken3_wrap_symbol(func_8003F044)
    tekken3_wrap_symbol(func_8002D1DC)
    tekken3_wrap_symbol(func_800293BC)
    target_sources(psx-runtime PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/src/tekken3_ttt1_records.c")
    tekken3_wrap_symbol(func_800513C0)
    tekken3_wrap_symbol(func_80051464)
    tekken3_wrap_symbol(func_8005155C)
    tekken3_wrap_symbol(func_80051660)
    tekken3_wrap_symbol(func_8004CD80)
    tekken3_wrap_symbol(func_8004BEC0)
    tekken3_wrap_symbol(func_8004C240)
    tekken3_wrap_symbol(func_8005138C)
    tekken3_wrap_symbol(func_8004CC08)
    tekken3_wrap_symbol(func_8004F3B0)
    tekken3_wrap_symbol(func_8004F0E4)
    tekken3_wrap_symbol(func_8004CE54)
endif()

tekken3_apply_wraps()

# A dynamic developer build can import the bundled Clang C++ runtime.  Stage it
# when that actually happens; production builds use PSX_STATIC_RUNTIME and need
# no non-system DLLs beside the executable.
if(WIN32 AND NOT PSX_STATIC_RUNTIME)
    get_filename_component(_tekken3_compiler_bin "${CMAKE_CXX_COMPILER}" DIRECTORY)
    foreach(_tekken3_runtime_dll IN ITEMS libc++.dll libunwind.dll)
        if(EXISTS "${_tekken3_compiler_bin}/${_tekken3_runtime_dll}")
            add_custom_command(TARGET psx-runtime POST_BUILD
                COMMAND ${CMAKE_COMMAND} -E copy_if_different
                    "${_tekken3_compiler_bin}/${_tekken3_runtime_dll}"
                    "$<TARGET_FILE_DIR:psx-runtime>/${_tekken3_runtime_dll}"
                VERBATIM
            )
        endif()
    endforeach()
elseif(WIN32)
    add_custom_command(TARGET psx-runtime POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E rm -f
            "$<TARGET_FILE_DIR:psx-runtime>/libc++.dll"
            "$<TARGET_FILE_DIR:psx-runtime>/libunwind.dll"
        VERBATIM
    )
endif()

# Stage the reviewed Tekken-specific catalog after the framework catalog.  The
# framework's own POST_BUILD step recreates mods/, so ordering this command
# here preserves both catalogs and also removes stale game packages.
add_custom_command(TARGET psx-runtime POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E rm -rf
        "$<TARGET_FILE_DIR:psx-runtime>/mods/packages/tekken3.enhancement.true-widescreen"
    COMMAND ${CMAKE_COMMAND} -E copy_directory
        "${CMAKE_CURRENT_SOURCE_DIR}/mods/preloaded/packages"
        "$<TARGET_FILE_DIR:psx-runtime>/mods/packages"
    COMMENT "Staging Tekken 3 built-in mod catalog"
    VERBATIM
)
add_custom_command(TARGET psx-runtime POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_directory
        "${CMAKE_CURRENT_SOURCE_DIR}/mods/assets/forest-hd"
        "$<TARGET_FILE_DIR:psx-runtime>/mods/forest-hd"
    COMMENT "Staging forest HD texture assets"
    VERBATIM
)
add_custom_command(TARGET psx-runtime POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_directory
        "${CMAKE_CURRENT_SOURCE_DIR}/mods/assets/nina-white-satin"
        "$<TARGET_FILE_DIR:psx-runtime>/mods/nina-white-satin"
    COMMENT "Staging Nina White Satin textures"
    VERBATIM
)
add_custom_command(TARGET psx-runtime POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_directory
        "${CMAKE_CURRENT_SOURCE_DIR}/mods/assets/xiaoyu-cherry-blossom"
        "$<TARGET_FILE_DIR:psx-runtime>/mods/xiaoyu-cherry-blossom"
    COMMENT "Staging Xiaoyu Cherry Blossom Ribbon textures"
    VERBATIM
)
add_custom_command(TARGET psx-runtime POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_directory
        "${CMAKE_CURRENT_SOURCE_DIR}/mods/assets/anna-jessica-rabbit"
        "$<TARGET_FILE_DIR:psx-runtime>/mods/anna-jessica-rabbit"
    COMMENT "Staging Anna Jessica Rabbit textures"
    VERBATIM
)
# Arcade CPU levels come from the user's own ROMs (tools/difficulty/import.py)
# and are never committed: staged only when the import has been run.
set(TEKKEN3_DIFFICULTY_LEVELS "${CMAKE_CURRENT_SOURCE_DIR}/workspace/difficulty/levels.bin")
if(EXISTS "${TEKKEN3_DIFFICULTY_LEVELS}")
    set_property(TARGET psx-runtime APPEND PROPERTY LINK_DEPENDS "${TEKKEN3_DIFFICULTY_LEVELS}")
    add_custom_command(TARGET psx-runtime POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E make_directory "$<TARGET_FILE_DIR:psx-runtime>/mods/difficulty"
        COMMAND ${CMAKE_COMMAND} -E copy_if_different "${TEKKEN3_DIFFICULTY_LEVELS}"
            "$<TARGET_FILE_DIR:psx-runtime>/mods/difficulty/levels.bin"
        COMMENT "Staging arcade CPU difficulty levels"
        VERBATIM)
endif()
file(GLOB TEKKEN3_GALLERY_ASSETS CONFIGURE_DEPENDS
    "${CMAKE_CURRENT_SOURCE_DIR}/mods/assets/outfit-menu/*")
file(GLOB TEKKEN3_KUMA_ASSETS CONFIGURE_DEPENDS
    "${CMAKE_CURRENT_SOURCE_DIR}/mods/assets/kuma-polar-bear/*")
set_property(TARGET psx-runtime APPEND PROPERTY LINK_DEPENDS ${TEKKEN3_KUMA_ASSETS}
    "${CMAKE_CURRENT_SOURCE_DIR}/mods/preloaded/packages/tekken3.skin.kuma-polar-bear/1.0.0/manifest.toml")
add_custom_command(TARGET psx-runtime POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_directory
        "${CMAKE_CURRENT_SOURCE_DIR}/mods/assets/kuma-polar-bear"
        "$<TARGET_FILE_DIR:psx-runtime>/mods/kuma-polar-bear"
    COMMENT "Staging Kuma Polar Bear textures"
    VERBATIM)
# Eddy Monochrome, Julia Blue Turquoise, Heihachi Tiger Coat (upstream v0.1.3).
foreach(_new_skin IN ITEMS eddy-monochrome julia-blue heihachi-tiger-coat)
    file(GLOB _new_skin_assets CONFIGURE_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/mods/assets/${_new_skin}/*")
    set_property(TARGET psx-runtime APPEND PROPERTY LINK_DEPENDS ${_new_skin_assets}
        "${CMAKE_CURRENT_SOURCE_DIR}/mods/preloaded/packages/tekken3.skin.${_new_skin}/1.0.0/manifest.toml")
    add_custom_command(TARGET psx-runtime POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_directory
            "${CMAKE_CURRENT_SOURCE_DIR}/mods/assets/${_new_skin}"
            "$<TARGET_FILE_DIR:psx-runtime>/mods/${_new_skin}"
        COMMENT "Staging ${_new_skin} textures"
        VERBATIM)
endforeach()
set_property(TARGET psx-runtime APPEND PROPERTY LINK_DEPENDS ${TEKKEN3_GALLERY_ASSETS})
add_custom_command(TARGET psx-runtime POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_directory
        "${CMAKE_CURRENT_SOURCE_DIR}/mods/assets/outfit-menu"
        "$<TARGET_FILE_DIR:psx-runtime>/mods/outfit-menu"
    COMMENT "Staging skin gallery artwork and catalog"
    VERBATIM
)

# The mod's package, and the TTT1 characters imported locally. The original ROM
# dumps and intermediate files stay private under workspace/.
if(TEKKEN3_TTT1_CHARACTERS)
    set(TTT1_PACKAGE "${CMAKE_CURRENT_SOURCE_DIR}/mods/local-packages/tekken3.character.ttt1/1.0.0/manifest.toml")
    set_property(TARGET psx-runtime APPEND PROPERTY LINK_DEPENDS "${TTT1_PACKAGE}")
    # TTT Cinematics: its data comes from the setup (tools/ttt_cinematics.py).
    set(TTT_CINEMATICS_PACKAGE "${CMAKE_CURRENT_SOURCE_DIR}/mods/local-packages/tekken3.cinematic.ttt-cinematics/1.0.0/manifest.toml")
    set_property(TARGET psx-runtime APPEND PROPERTY LINK_DEPENDS "${TTT_CINEMATICS_PACKAGE}")
    add_custom_command(TARGET psx-runtime POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E rm -rf "$<TARGET_FILE_DIR:psx-runtime>/mods/jun"
            "$<TARGET_FILE_DIR:psx-runtime>/mods/packages/tekken3.character.jun-probe"
        COMMAND ${CMAKE_COMMAND} -E make_directory "$<TARGET_FILE_DIR:psx-runtime>/mods/packages/tekken3.character.ttt1/1.0.0"
        COMMAND ${CMAKE_COMMAND} -E copy_if_different "${TTT1_PACKAGE}" "$<TARGET_FILE_DIR:psx-runtime>/mods/packages/tekken3.character.ttt1/1.0.0/manifest.toml"
        COMMAND ${CMAKE_COMMAND} -E make_directory "$<TARGET_FILE_DIR:psx-runtime>/mods/packages/tekken3.cinematic.ttt-cinematics/1.0.0"
        COMMAND ${CMAKE_COMMAND} -E copy_if_different "${TTT_CINEMATICS_PACKAGE}" "$<TARGET_FILE_DIR:psx-runtime>/mods/packages/tekken3.cinematic.ttt-cinematics/1.0.0/manifest.toml"
        COMMENT "Staging the TTT1 characters and TTT Cinematics packages"
        VERBATIM)
    # TTT1 guests gathered by tools/ttt1_stage_roster.py, switched at the selector.
    set(TTT1_ROSTER "${CMAKE_CURRENT_SOURCE_DIR}/workspace/ttt1-import/roster")
    if(EXISTS "${TTT1_ROSTER}/guests.txt")
        set_property(TARGET psx-runtime APPEND PROPERTY LINK_DEPENDS "${TTT1_ROSTER}/guests.txt")
        add_custom_command(TARGET psx-runtime POST_BUILD
            COMMAND ${CMAKE_COMMAND} -E copy_directory "${TTT1_ROSTER}" "$<TARGET_FILE_DIR:psx-runtime>/mods/ttt1"
            COMMENT "Staging private TTT1 guests"
            VERBATIM)
    endif()
endif()

# Jin's TTT1 strong-hit effect, converted from the user's ROM by
# tools/ttt1_jin_hit_effect.py. The mod does nothing until it is present.
set(JIN_TTT1_HIT_EFFECT "${CMAKE_CURRENT_SOURCE_DIR}/workspace/ttt1-import/jin/Jin-TTT1-hiteffect.tim")
if(EXISTS "${JIN_TTT1_HIT_EFFECT}")
    set_property(TARGET psx-runtime APPEND PROPERTY LINK_DEPENDS "${JIN_TTT1_HIT_EFFECT}")
    add_custom_command(TARGET psx-runtime POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E make_directory "$<TARGET_FILE_DIR:psx-runtime>/mods/jin-ttt1-hit-effect"
        COMMAND ${CMAKE_COMMAND} -E copy_if_different "${JIN_TTT1_HIT_EFFECT}" "$<TARGET_FILE_DIR:psx-runtime>/mods/jin-ttt1-hit-effect"
        COMMENT "Staging private Jin TTT1 strong-hit effect"
        VERBATIM)
endif()

if(WIN32 AND CMAKE_RC_COMPILER)
    target_sources(psx-runtime PRIVATE launcher/icon.rc)
endif()

# Finder draws a generic icon for a bare Unix executable, there being nowhere
# in one to keep an icon: it gets the T3E icon (packaging/icon.png) in its
# resource fork. TEKKEN3_MACOS_ICON names another PNG or .icns.
if(APPLE)
    set(TEKKEN3_MACOS_ICON "" CACHE FILEPATH
        "PNG or .icns to use as the Finder icon of the built executable")
    if(NOT TEKKEN3_MACOS_ICON)
        set(TEKKEN3_MACOS_ICON "${CMAKE_CURRENT_SOURCE_DIR}/packaging/icon.png")
    endif()
    if(TEKKEN3_MACOS_ICON)
        set_property(TARGET psx-runtime APPEND PROPERTY LINK_DEPENDS
            "${TEKKEN3_MACOS_ICON}")
        add_custom_command(TARGET psx-runtime POST_BUILD
            COMMAND "${CMAKE_CURRENT_SOURCE_DIR}/tools/macos_set_icon.sh"
                    "${TEKKEN3_MACOS_ICON}" "$<TARGET_FILE:psx-runtime>"
            COMMENT "Setting the Finder icon on the executable"
            VERBATIM)
    endif()
endif()

endif()

endif() # Full game enhancements need locally generated game code.

# The recompiled executable above remains a behavioral oracle while the game is
# migrated system-by-system.  The PC-port target below is deliberately separate:
# it does not compile generated guest code, OpenBIOS, the PS1 GPU/GTE, or the
# compatibility scheduler.
option(TEKKEN3_BUILD_PC_PORT "Build the independent native Tekken 3 PC port" OFF)
if(TEKKEN3_BUILD_PC_PORT)
    add_subdirectory(native)
endif()
