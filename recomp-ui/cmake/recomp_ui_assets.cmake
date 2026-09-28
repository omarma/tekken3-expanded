# Runtime asset manifests for recomp-ui consumers.
#
# Keep this file free of project()/enable_language() calls so the manifests can
# also be verified from a lightweight `cmake -P` test.

set(_RUI_COMMON_FONT_ASSETS
    "${RUI_ASSETS}/common/fonts/LatoLatin-Regular.ttf"
    "${RUI_ASSETS}/common/fonts/LatoLatin-Bold.ttf"
    "${RUI_ASSETS}/common/fonts/OpenMoji-black-glyf.ttf"
    "${RUI_ASSETS}/common/fonts/NotoSansSymbols2-Regular.ttf")

set(_RUI_COMMON_IMG_ASSETS
    "${RUI_ASSETS}/common/img/brand_mark.tga"
    "${RUI_ASSETS}/common/img/verdict_ok.tga"
    "${RUI_ASSETS}/common/img/verdict_warn.tga"
    "${RUI_ASSETS}/common/img/verdict_bad.tga"
    "${RUI_ASSETS}/common/img/verdict_none.tga")

set(_RUI_CONSOLE_ASSETS_snes
    "${RUI_ASSETS}/consoles/snes/img/pad.tga")

set(_RUI_CONSOLE_ASSETS_psx
    "${RUI_ASSETS}/consoles/psx/img/pad_analog.tga"
    "${RUI_ASSETS}/consoles/psx/img/pad_digital.tga"
    "${RUI_ASSETS}/consoles/psx/img/memcard.tga"
    "${RUI_ASSETS}/consoles/psx/img/brand_psx.tga")

set(_RUI_CONSOLE_ASSETS_gba
    "${RUI_ASSETS}/consoles/gba/img/pad_gba.tga")

set(_RUI_CONSOLE_ASSETS_n64
    "${RUI_ASSETS}/consoles/n64/img/pad_n64.tga"
    "${RUI_ASSETS}/consoles/n64/img/brand_n64.tga"
    "${RUI_ASSETS}/consoles/n64/img/cart_empty.tga"
    "${RUI_ASSETS}/consoles/n64/img/cart_red.tga"
    "${RUI_ASSETS}/consoles/n64/img/cart_blue.tga"
    "${RUI_ASSETS}/consoles/n64/img/cart_yellow.tga"
    "${RUI_ASSETS}/consoles/n64/img/cart_green.tga")

set(_RUI_CONSOLE_ASSETS_nes
    "${RUI_ASSETS}/consoles/nes/img/pad_nes.tga"
    "${RUI_ASSETS}/consoles/nes/img/brand_nes.tga")

set(_RUI_CONSOLE_ASSETS_genesis
    "${RUI_ASSETS}/consoles/genesis/img/pad_genesis.tga"
    "${RUI_ASSETS}/consoles/genesis/img/brand_genesis.tga"
    "${RUI_ASSETS}/consoles/genesis/img/boxart_sonic1.tga")

set(_RUI_CONSOLE_ASSETS_gb
    "${RUI_ASSETS}/consoles/gb/img/pad_gb.tga"
    "${RUI_ASSETS}/consoles/gb/img/pad_gbc.tga"
    "${RUI_ASSETS}/consoles/gb/img/brand_gb.tga"
    "${RUI_ASSETS}/consoles/gb/img/brand_gbc.tga")

# GBC uses the same runtime asset family as GB.
set(_RUI_CONSOLE_ASSETS_gbc ${_RUI_CONSOLE_ASSETS_gb})

set(_RUI_CONSOLE_ASSETS_nds
    "${RUI_ASSETS}/consoles/nds/img/pad_nds.tga"
    "${RUI_ASSETS}/consoles/nds/img/brand_nds.tga")

set(_RUI_CONSOLE_IDS snes psx gba n64 nes genesis gb nds)
set(_RUI_ACCEPTED_CONSOLE_IDS ${_RUI_CONSOLE_IDS} gbc)

function(_recomp_ui_resolve_console_assets OUT_VAR CONSOLE)
    string(TOLOWER "${CONSOLE}" _rui_console)

    if(_rui_console STREQUAL "all")
        set(_rui_assets)
        foreach(_rui_id IN LISTS _RUI_CONSOLE_IDS)
            list(APPEND _rui_assets ${_RUI_CONSOLE_ASSETS_${_rui_id}})
        endforeach()
        list(REMOVE_DUPLICATES _rui_assets)
    elseif(_rui_console IN_LIST _RUI_ACCEPTED_CONSOLE_IDS)
        set(_rui_assets ${_RUI_CONSOLE_ASSETS_${_rui_console}})
    else()
        list(JOIN _RUI_ACCEPTED_CONSOLE_IDS ", " _rui_expected)
        message(FATAL_ERROR
            "recomp-ui: unsupported CONSOLE '${CONSOLE}'. "
            "Expected one of: ${_rui_expected}, or explicit 'all'.")
    endif()

    set(${OUT_VAR} "${_rui_assets}" PARENT_SCOPE)
endfunction()

function(_recomp_ui_stage_assets TGT CONSOLE)
    if("${CONSOLE}" STREQUAL "")
        list(JOIN _RUI_ACCEPTED_CONSOLE_IDS ", " _rui_expected)
        message(FATAL_ERROR
            "recomp-ui: ${TGT} must select its runtime assets with "
            "CONSOLE <${_rui_expected}>. Use CONSOLE all only when one target "
            "intentionally supports multiple console families.")
    endif()

    _recomp_ui_resolve_console_assets(_rui_console_assets "${CONSOLE}")
    _recomp_ui_resolve_console_assets(_rui_all_console_assets all)

    # A reused output directory may contain assets copied by an older build.
    # Remove only files owned by recomp-ui's console manifests before staging
    # the selected family; per-game box art and other host assets are untouched.
    set(_rui_stale_console_assets)
    foreach(_rui_asset IN LISTS _rui_all_console_assets)
        get_filename_component(_rui_name "${_rui_asset}" NAME)
        list(APPEND _rui_stale_console_assets
            "$<TARGET_FILE_DIR:${TGT}>/assets/img/${_rui_name}")
    endforeach()
    list(REMOVE_DUPLICATES _rui_stale_console_assets)

    add_custom_command(TARGET ${TGT} POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E make_directory
                "$<TARGET_FILE_DIR:${TGT}>/assets/fonts"
        COMMAND ${CMAKE_COMMAND} -E make_directory
                "$<TARGET_FILE_DIR:${TGT}>/assets/img"
        COMMAND ${CMAKE_COMMAND} -E rm -f ${_rui_stale_console_assets}
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
                ${_RUI_COMMON_FONT_ASSETS}
                "$<TARGET_FILE_DIR:${TGT}>/assets/fonts/"
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
                ${_RUI_COMMON_IMG_ASSETS}
                ${_rui_console_assets}
                "$<TARGET_FILE_DIR:${TGT}>/assets/img/"
        VERBATIM)

    string(TOLOWER "${CONSOLE}" _rui_console)
    message(STATUS "recomp-ui: staging ${_rui_console} runtime assets for ${TGT}")
endfunction()
