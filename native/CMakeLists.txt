if(NOT PSX_SDL3)
    message(FATAL_ERROR "The native PC port currently requires PSX_SDL_BACKEND=SDL3")
endif()

add_library(tekken3-native-core STATIC
    src/camera.cpp
    src/game.cpp
)
target_include_directories(tekken3-native-core PUBLIC
    "${CMAKE_CURRENT_SOURCE_DIR}/include"
)
target_compile_features(tekken3-native-core PUBLIC cxx_std_17)

# This is the only shared seam with the recompilation framework: read-only disc
# container code. It has no CPU, BIOS, GTE, GPU, scheduler, or generated-game
# dependency.
add_library(tekken3-native-disc STATIC
    src/disc.cpp
    "${PSXRECOMP_ROOT}/runtime/src/cue_sheet.cpp"
    "${PSXRECOMP_ROOT}/runtime/src/disc_path.cpp"
    "${PSXRECOMP_ROOT}/runtime/src/iso_reader.cpp"
)
target_include_directories(tekken3-native-disc PUBLIC
    "${CMAKE_CURRENT_SOURCE_DIR}/include"
    "${PSXRECOMP_ROOT}/runtime/include"
)
target_compile_features(tekken3-native-disc PUBLIC cxx_std_17)
target_link_libraries(tekken3-native-disc PRIVATE chdr-static)

# Architecture guard: the native product must never grow a dependency on the
# translated guest, PS1 machine, or compatibility scheduler by accident.
set(_tekken3_native_forbidden_sources
    "generated/"
    "openbios"
    "memory.c"
    "gpu.c"
    "gte.cpp"
    "cdrom.c"
    "stub_interpreter.c"
    "tekken3_widescreen_mod.c"
)
foreach(_source IN LISTS _tekken3_native_forbidden_sources)
    if("${CMAKE_CURRENT_LIST_FILE}" MATCHES "${_source}")
        message(FATAL_ERROR "Forbidden compatibility source leaked into native PC port: ${_source}")
    endif()
endforeach()

add_executable(tekken3-pc-port
    src/main.cpp
    src/renderer_gl.cpp
    "${CMAKE_SOURCE_DIR}/recomp-ui/src/third_party/gl_core_3_1.c"
)
set_target_properties(tekken3-pc-port PROPERTIES
    OUTPUT_NAME "Tekken_3_PC_Port"
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}"
)
target_compile_features(tekken3-pc-port PRIVATE cxx_std_17)
target_compile_definitions(tekken3-pc-port PRIVATE SDL_MAIN_HANDLED)
target_include_directories(tekken3-pc-port PRIVATE
    "${CMAKE_CURRENT_SOURCE_DIR}/include"
    "${CMAKE_SOURCE_DIR}/recomp-ui/src/third_party"
    ${PSX_SDL_INCLUDE_DIRS}
)
target_link_libraries(tekken3-pc-port PRIVATE
    tekken3-native-core
    tekken3-native-disc
    ${PSX_SDL_LIBRARIES}
)

if(MINGW)
    target_link_options(tekken3-pc-port PRIVATE -Wl,--stack,67108864)
    if(PSX_STATIC_RUNTIME)
        target_link_options(tekken3-pc-port PRIVATE
            -static -static-libgcc -static-libstdc++)
        target_link_libraries(tekken3-pc-port PRIVATE winpthread)
    endif()
endif()
if(WIN32)
    target_link_libraries(tekken3-pc-port PRIVATE opengl32)
endif()

include(CTest)
if(BUILD_TESTING)
    add_executable(tekken3-native-core-test tests/native_core_test.cpp)
    target_link_libraries(tekken3-native-core-test PRIVATE tekken3-native-core)
    set_target_properties(tekken3-native-core-test PROPERTIES
        RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}"
    )
    add_test(NAME tekken3-native-core COMMAND tekken3-native-core-test)
endif()
