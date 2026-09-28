# Guard against build targets whose output files collide on a case-insensitive
# filesystem (Windows and macOS — two of the three platforms we document).
#
# WHY THIS EXISTS
# ---------------
# Until 2026-07-27 recompiler/CMakeLists.txt defined BOTH `psxrecomp` (the
# user-facing CLI, from src/main_cli.cpp) and `PSXRecomp` (a legacy duplicate of
# psxrecomp-game). CMake treats those as two distinct targets and links both
# happily, but on Windows they write to the SAME path on disk. Whichever linked
# last silently overwrote the other. The CLI lost, so the binary shipped as
# `psxrecomp.exe` in the released CLI package was actually the game recompiler,
# whose arguments match nothing in the README. Nothing failed, nothing warned,
# and it never reproduced on Linux — so it shipped for a long time.
#
# A rename alone would not prevent recurrence. This check does.
#
# Compares OUTPUT_NAME (falling back to the target name, which is what CMake
# uses when OUTPUT_NAME is unset) rather than the target name itself, because
# the on-disk filename is what actually collides — two differently-named targets
# can still be given the same OUTPUT_NAME.
#
# Usage: call at the END of a CMakeLists.txt, after all targets are declared.
#   include(${CMAKE_CURRENT_SOURCE_DIR}/../runtime/check_target_name_collisions.cmake)
#   psxrecomp_check_output_name_collisions()

function(psxrecomp_check_output_name_collisions)
    get_property(_targets
        DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
        PROPERTY BUILDSYSTEM_TARGETS)

    set(_seen_lower "")
    set(_seen_target "")
    set(_seen_output "")

    foreach(_t IN LISTS _targets)
        get_target_property(_type ${_t} TYPE)
        # Only real artifacts land on disk under a name we control.
        if(NOT _type STREQUAL "EXECUTABLE"
           AND NOT _type STREQUAL "SHARED_LIBRARY"
           AND NOT _type STREQUAL "STATIC_LIBRARY"
           AND NOT _type STREQUAL "MODULE_LIBRARY")
            continue()
        endif()

        get_target_property(_out ${_t} OUTPUT_NAME)
        if(NOT _out)
            set(_out "${_t}")
        endif()

        string(TOLOWER "${_out}" _lower)
        list(FIND _seen_lower "${_lower}" _idx)
        if(NOT _idx EQUAL -1)
            list(GET _seen_target ${_idx} _other_target)
            list(GET _seen_output ${_idx} _other_output)
            message(FATAL_ERROR
                "Case-insensitive output-name collision in ${CMAKE_CURRENT_SOURCE_DIR}:\n"
                "    target '${_other_target}' produces '${_other_output}'\n"
                "    target '${_t}' produces '${_out}'\n"
                "These differ only by case, so on Windows and macOS they write the "
                "SAME file and the last one linked silently wins. Rename one target "
                "(or give it a distinct OUTPUT_NAME). Do not suppress this check: it "
                "exists because exactly this bug shipped the wrong binary in the "
                "released Windows CLI package.")
        endif()

        list(APPEND _seen_lower  "${_lower}")
        list(APPEND _seen_target "${_t}")
        list(APPEND _seen_output "${_out}")
    endforeach()
endfunction()
