cmake_minimum_required(VERSION 3.24)

if(NOT RECOMP_UI_ROOT)
    message(FATAL_ERROR "RECOMP_UI_ROOT is required")
endif()

set(RUI_ASSETS "${RECOMP_UI_ROOT}/assets")
include("${RECOMP_UI_ROOT}/cmake/recomp_ui_assets.cmake")

function(assert_console_asset_names CONSOLE EXPECTED_NAMES)
    _recomp_ui_resolve_console_assets(_assets "${CONSOLE}")
    set(_actual_names)
    foreach(_asset IN LISTS _assets)
        if(NOT EXISTS "${_asset}")
            message(FATAL_ERROR "${CONSOLE} manifest asset does not exist: ${_asset}")
        endif()
        get_filename_component(_name "${_asset}" NAME)
        list(APPEND _actual_names "${_name}")
    endforeach()

    set(_expected_names ${EXPECTED_NAMES})
    list(SORT _actual_names)
    list(SORT _expected_names)
    if(NOT "${_actual_names}" STREQUAL "${_expected_names}")
        message(FATAL_ERROR
            "${CONSOLE} asset manifest mismatch.\n"
            "  expected: ${_expected_names}\n"
            "  actual:   ${_actual_names}")
    endif()
endfunction()

assert_console_asset_names(
    psx
    "brand_psx.tga;memcard.tga;pad_analog.tga;pad_digital.tga")
assert_console_asset_names(
    n64
    "brand_n64.tga;cart_blue.tga;cart_empty.tga;cart_green.tga;cart_red.tga;cart_yellow.tga;pad_n64.tga")
assert_console_asset_names(
    nes
    "brand_nes.tga;pad_nes.tga")
assert_console_asset_names(
    snes
    "pad.tga")
assert_console_asset_names(
    nds
    "brand_nds.tga;pad_nds.tga")

_recomp_ui_resolve_console_assets(_gb_assets gb)
_recomp_ui_resolve_console_assets(_gbc_assets gbc)
if(NOT "${_gb_assets}" STREQUAL "${_gbc_assets}")
    message(FATAL_ERROR "GB and GBC must resolve to the same asset family")
endif()

_recomp_ui_resolve_console_assets(_all_assets all)
list(LENGTH _all_assets _all_count)
if(NOT _all_count EQUAL 24)
    message(FATAL_ERROR
        "The explicit all-console manifest should contain 24 assets, got ${_all_count}")
endif()

message(STATUS "recomp-ui console asset manifests are scoped and complete")
