include_guard(GLOBAL)

include(FetchContent)

# libchdr is the small, BSD-licensed decompressor used by MAME-compatible CHD
# images. Pin the exact source archive (and its digest) so generated games do
# not silently change their disc decoder between builds.
set(INSTALL_STATIC_LIBS OFF CACHE BOOL "Do not install libchdr dependencies" FORCE)
set(WITH_SYSTEM_ZLIB OFF CACHE BOOL "Use libchdr's pinned miniz" FORCE)
set(WITH_SYSTEM_ZSTD OFF CACHE BOOL "Use libchdr's pinned zstd" FORCE)
set(CHDR_WANT_RAW_DATA_SECTOR ON CACHE BOOL
    "Reconstruct complete 2352-byte CD sectors" FORCE)
set(CHDR_WANT_SUBCODE ON CACHE BOOL
    "Decode CHD CD subchannel payloads" FORCE)
set(CHDR_VERIFY_BLOCK_CRC ON CACHE BOOL
    "Verify decoded CHD blocks" FORCE)

set(_psx_libchdr_timestamp_args "")
if(CMAKE_VERSION VERSION_GREATER_EQUAL 3.24)
    list(APPEND _psx_libchdr_timestamp_args
        DOWNLOAD_EXTRACT_TIMESTAMP TRUE)
endif()

FetchContent_Declare(psx_libchdr
    URL
        "https://github.com/rtissera/libchdr/archive/6cde5348eb118da3baf94f75a69577a005a484fd.tar.gz"
    URL_HASH
        "SHA256=a222b1f1c842f988c2aad51e5f56ba94a423ed87ccab71f1abdb757caa7444f5"
    ${_psx_libchdr_timestamp_args})
FetchContent_MakeAvailable(psx_libchdr)
