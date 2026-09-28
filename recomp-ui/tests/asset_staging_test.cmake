if(NOT ASSET_DIR)
    message(FATAL_ERROR "ASSET_DIR is required")
endif()

file(GLOB _font_paths "${ASSET_DIR}/fonts/*")
file(GLOB _image_paths "${ASSET_DIR}/img/*")

set(_font_names)
foreach(_path IN LISTS _font_paths)
    get_filename_component(_name "${_path}" NAME)
    list(APPEND _font_names "${_name}")
endforeach()

set(_image_names)
foreach(_path IN LISTS _image_paths)
    get_filename_component(_name "${_path}" NAME)
    list(APPEND _image_names "${_name}")
endforeach()

set(_expected_fonts
    LatoLatin-Bold.ttf
    LatoLatin-Regular.ttf
    NotoSansSymbols2-Regular.ttf
    OpenMoji-black-glyf.ttf)
set(_expected_images
    brand_mark.tga
    brand_psx.tga
    memcard.tga
    pad_analog.tga
    pad_digital.tga
    verdict_bad.tga
    verdict_none.tga
    verdict_ok.tga
    verdict_warn.tga)

list(SORT _font_names)
list(SORT _image_names)
list(SORT _expected_fonts)
list(SORT _expected_images)

if(NOT "${_font_names}" STREQUAL "${_expected_fonts}")
    message(FATAL_ERROR
        "PSX staged font set mismatch.\n"
        "  expected: ${_expected_fonts}\n"
        "  actual:   ${_font_names}")
endif()
if(NOT "${_image_names}" STREQUAL "${_expected_images}")
    message(FATAL_ERROR
        "PSX staged image set mismatch.\n"
        "  expected: ${_expected_images}\n"
        "  actual:   ${_image_names}")
endif()

message(STATUS "PSX target staged only common and PlayStation assets")
