// test_disc_in_apk.cpp — the disc read in place from the APK (Android).
//
// Built for arm64 Android with the NDK and run under qemu by
// test_disc_in_apk.py, which makes a synthetic disc, puts it into an APK with
// build_apk.py (packed or plain) and writes the placeholders the app
// (GameData.java) would write. Linked like libmain.so: android_apk_file.c and
// disc_pack.c with --wrap=fopen, the runtime's own disc code (ISOReader, cue
// sheet, disc identity) and hd_png.c.
//
// Usage (from the test's data folder, as the runtime runs from the app's):
//   test_disc_in_apk <cue> <placeholder> <original> [<placeholder> <original>]...
//                    [--png <placeholder> <rgba>]... [--big <placeholder> <original> <offset>]
// Every placeholder must read back byte for byte as its original file, and
// each PNG decode to its .rgba's pixels.

#include "android_apk_file.h"
#include "crc32.h"
#include "disc_identity.h"
#include "hd_png.h"
#include "iso_reader.h"

#include <libchdr/chd.h>

#include <atomic>
#include <cerrno>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <random>
#include <string>
#include <sys/stat.h>
#include <thread>
#include <vector>

// The test disc is a .cue: CHD support is not linked in.
extern "C" {
chd_error chd_open(const char*, int, chd_file*, chd_file**) { return CHDERR_FILE_NOT_FOUND; }
void chd_close(chd_file*) {}
const chd_header* chd_get_header(chd_file*) { return nullptr; }
chd_error chd_read(chd_file*, uint32_t, void*) { return CHDERR_READ_ERROR; }
chd_error chd_get_metadata(chd_file*, uint32_t, uint32_t, void*, uint32_t, uint32_t*, uint32_t*, uint8_t*) {
    return CHDERR_METADATA_NOT_FOUND;
}
}

extern "C" FILE* __real_fopen(const char*, const char*);

static int g_failures = 0;
static int g_checks = 0;

#define CHECK(cond, ...)                                                    \
    do {                                                                    \
        ++g_checks;                                                         \
        if (!(cond)) {                                                      \
            ++g_failures;                                                   \
            std::fprintf(stderr, "FAIL %s:%d: %s: ", __FILE__, __LINE__, #cond); \
            std::fprintf(stderr, __VA_ARGS__);                              \
            std::fputc('\n', stderr);                                       \
        }                                                                   \
    } while (0)

static std::vector<uint8_t> slurp(const char* path) {
    // The original is read with the real fopen, so the reference never goes
    // through the code under test.
    std::vector<uint8_t> out;
    FILE* f = __real_fopen(path, "rb");
    if (!f) return out;
    uint8_t buf[1 << 16];
    size_t n;
    while ((n = std::fread(buf, 1, sizeof(buf), f)) > 0) out.insert(out.end(), buf, buf + n);
    std::fclose(f);
    return out;
}

static void check_stdio(const char* placeholder, const std::vector<uint8_t>& want) {
    FILE* f = std::fopen(placeholder, "rb");
    CHECK(f != nullptr, "fopen %s: %s", placeholder, std::strerror(errno));
    if (!f) return;

    // Whole file, sequentially, in odd-sized reads.
    std::vector<uint8_t> got;
    std::vector<uint8_t> buf(3001);
    size_t n;
    while ((n = std::fread(buf.data(), 1, buf.size(), f)) > 0) got.insert(got.end(), buf.data(), buf.data() + n);
    CHECK(got.size() == want.size(), "%s: read %zu bytes, want %zu", placeholder, got.size(), want.size());
    CHECK(got == want, "%s: sequential read differs", placeholder);
    CHECK(std::feof(f) && !std::ferror(f), "%s: end of file", placeholder);

    // Size through fseeko/ftello, as the launcher and libc++ do.
    CHECK(fseeko(f, 0, SEEK_END) == 0, "fseeko end");
    CHECK((uint64_t)ftello(f) == want.size(), "ftello at end = %lld", (long long)ftello(f));

    // Random reads, including ones that run past the end.
    std::mt19937_64 rng(42);
    for (int i = 0; i < 2000; ++i) {
        const uint64_t at = rng() % (want.size() + 100);
        const size_t len = 1 + (size_t)(rng() % 5000);
        CHECK(fseeko(f, (off_t)at, SEEK_SET) == 0, "fseeko %llu", (unsigned long long)at);
        std::vector<uint8_t> part(len);
        const size_t r = std::fread(part.data(), 1, len, f);
        const size_t expect = at >= want.size() ? 0 : std::min<uint64_t>(len, want.size() - at);
        CHECK(r == expect, "fread at %llu: %zu, want %zu", (unsigned long long)at, r, expect);
        if (r == expect && r && std::memcmp(part.data(), want.data() + at, r) != 0) {
            CHECK(false, "fread at %llu differs", (unsigned long long)at);
        }
        std::clearerr(f);
    }
    // Relative seeks.
    CHECK(fseeko(f, 100, SEEK_SET) == 0 && fseeko(f, 50, SEEK_CUR) == 0 && ftello(f) == 150, "SEEK_CUR");
    CHECK(fseeko(f, -10, SEEK_END) == 0 && ftello(f) == (off_t)want.size() - 10, "SEEK_END");
    CHECK(std::fclose(f) == 0, "fclose");

    // Writing is never redirected: a placeholder opened for writing is the
    // placeholder itself (nothing in the game does that, but it must not
    // pretend to write into the APK).
    FILE* w = std::fopen(placeholder, "r+b");
    CHECK(w != nullptr, "fopen r+b");
    if (w) {
        char magic[20] = {};
        CHECK(std::fread(magic, 1, 14, w) == 14 && std::memcmp(magic, "psxrecomp-apk-", 14) == 0,
              "r+b opens the placeholder itself");
        std::fclose(w);
    }
}

static void check_ifstream(const char* placeholder, const std::vector<uint8_t>& want) {
    std::ifstream f(placeholder, std::ios::binary | std::ios::ate);
    CHECK(f.is_open(), "ifstream %s", placeholder);
    if (!f.is_open()) return;
    CHECK((uint64_t)f.tellg() == want.size(), "ifstream size %lld", (long long)f.tellg());
    std::mt19937_64 rng(7);
    for (int i = 0; i < 2000; ++i) {
        const uint64_t at = rng() % want.size();
        const size_t len = 1 + (size_t)(rng() % 9000);
        f.clear();
        f.seekg((std::streamoff)at, std::ios::beg);
        std::vector<char> part(len);
        f.read(part.data(), (std::streamsize)len);
        const size_t r = (size_t)f.gcount();
        const size_t expect = std::min<uint64_t>(len, want.size() - at);
        CHECK(r == expect, "ifstream read at %llu: %zu, want %zu", (unsigned long long)at, r, expect);
        if (r == expect && std::memcmp(part.data(), want.data() + at, r) != 0) {
            CHECK(false, "ifstream read at %llu differs", (unsigned long long)at);
        }
    }
}

// Several threads, each with its own stream on the same track, as the CD-ROM
// thread and the launcher's verification may do.
static void check_threads(const char* placeholder, const std::vector<uint8_t>& want) {
    std::atomic<int> bad{0};
    std::vector<std::thread> threads;
    for (int t = 0; t < 8; ++t) {
        threads.emplace_back([&, t] {
            FILE* f = std::fopen(placeholder, "rb");
            if (!f) { bad++; return; }
            std::mt19937_64 rng(1000 + t);
            uint8_t sector[2352];
            for (int i = 0; i < 3000; ++i) {
                const uint64_t lba = rng() % (want.size() / 2352);
                if (fseeko(f, (off_t)(lba * 2352), SEEK_SET) != 0 ||
                    std::fread(sector, 1, sizeof(sector), f) != sizeof(sector) ||
                    std::memcmp(sector, want.data() + lba * 2352, sizeof(sector)) != 0) {
                    bad++;
                }
            }
            std::fclose(f);
        });
    }
    for (auto& t : threads) t.join();
    CHECK(bad == 0, "%d bad reads across threads", bad.load());
}

static void check_iso_reader(const char* cue, const char* data_placeholder,
                             const std::vector<uint8_t>& data) {
    PS1::ISOReader reader;
    CHECK(reader.Open(cue), "ISOReader::Open(%s)", cue);
    if (!reader.IsOpen()) return;
    CHECK(reader.TrackCount() == 3, "track count %d", reader.TrackCount());
    CHECK(reader.TrackIsAudio(2) && !reader.TrackIsAudio(1), "track kinds");
    CHECK(reader.GetVolumeID() == "TEKKEN3", "volume id '%s'", reader.GetVolumeID().c_str());
    const uint32_t sectors = (uint32_t)(data.size() / 2352);
    uint8_t user[2048], raw[2352];
    for (uint32_t lba = 0; lba < sectors; ++lba) {
        if (!reader.ReadSector(lba, user) || std::memcmp(user, data.data() + lba * 2352 + 24, 2048) != 0) {
            CHECK(false, "ReadSector(%u)", lba);
            break;
        }
        if (!reader.ReadRawSector(lba, raw) || std::memcmp(raw, data.data() + lba * 2352, 2352) != 0) {
            CHECK(false, "ReadRawSector(%u)", lba);
            break;
        }
    }
    ++g_checks;

    // The disc check the launcher runs (verify, rom_present): header, serial
    // and the CRC of the whole data track, read through the placeholder.
    const uint32_t crc = crc32_compute(data.data(), data.size());
    const PSXRecompV4::DiscIdentity id =
        PSXRecompV4::identify_disc(cue, "SLUS-00402", crc, true, true);
    CHECK(id.opened && id.has_header, "identify_disc opened=%d header=%d (%s)",
          id.opened, id.has_header, id.detail.c_str());
    CHECK(id.detected_serial == "SLUS-00402", "serial '%s'", id.detected_serial.c_str());
    CHECK(id.crc_computed && id.crc == crc && id.crc_matches, "crc %08x want %08x", id.crc, crc);
    CHECK(id.toc_opened && id.track_count == 3, "toc %d tracks", id.track_count);
    (void)data_placeholder;
}

// A texture's PNG, read through its placeholder and decoded as the game does
// (hd_load_image), must give exactly its .rgba's pixels.
static void check_png(const char* placeholder, const char* rgba_path) {
    const std::vector<uint8_t> rgba = slurp(rgba_path);
    CHECK(rgba.size() > 16 && std::memcmp(rgba.data(), "HDRGBA01", 8) == 0, "%s", rgba_path);
    FILE* f = std::fopen(placeholder, "rb");
    CHECK(f != nullptr, "fopen %s", placeholder);
    if (!f || rgba.size() <= 16) { if (f) std::fclose(f); return; }
    std::vector<uint8_t> png;
    uint8_t buf[1 << 16];
    size_t n;
    while ((n = std::fread(buf, 1, sizeof(buf), f)) > 0) png.insert(png.end(), buf, buf + n);
    std::fclose(f);
    uint32_t w = 0, h = 0, want_w, want_h;
    std::memcpy(&want_w, rgba.data() + 8, 4);
    std::memcpy(&want_h, rgba.data() + 12, 4);
    const auto start = std::chrono::steady_clock::now();
    unsigned char* pixels = hd_png_decode(png.data(), png.size(), &w, &h);
    const double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start).count();
    CHECK(pixels && w == want_w && h == want_h, "%s: decoded %ux%u, want %ux%u", placeholder, w, h, want_w, want_h);
    if (pixels && w == want_w && h == want_h) {
        CHECK(std::memcmp(pixels, rgba.data() + 16, (size_t)w * h * 4) == 0, "%s: pixels differ", placeholder);
    }
    std::free(pixels);
    std::printf("ok  %s: %zu bytes of PNG = %zu bytes of .rgba (%ux%u), decoded in %.0f ms\n",
                placeholder, png.size(), rgba.size(), w, h, ms);
}

int main(int argc, char** argv) {
    if (argc < 4) {
        std::fprintf(stderr, "usage: %s <cue> <placeholder> <original>... [--png <p> <rgba>]... "
                     "[--big <p> <o> <offset>]\n", argv[0]);
        return 2;
    }
    const char* cue = argv[1];
    std::vector<uint8_t> data_track;
    int i = 2;
    for (; i + 1 < argc && argv[i][0] != '-'; i += 2) {
        const std::vector<uint8_t> want = slurp(argv[i + 1]);
        CHECK(!want.empty(), "original %s", argv[i + 1]);
        struct stat st;
        CHECK(stat(argv[i], &st) == 0 && (uint64_t)st.st_size == want.size(),
              "placeholder %s has the original's size", argv[i]);
        CHECK((uint64_t)st.st_blocks * 512 < 64 * 1024,
              "placeholder %s takes %lld bytes on disk", argv[i], (long long)st.st_blocks * 512);
        const auto start = std::chrono::steady_clock::now();
        check_stdio(argv[i], want);
        const double s = std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
        check_ifstream(argv[i], want);
        check_threads(argv[i], want);
        if (data_track.empty()) data_track = want;
        std::printf("ok  %s (%zu bytes; stdio checks in %.2f s)\n", argv[i], want.size(), s);
    }
    check_iso_reader(cue, argv[2], data_track);
    std::printf("ok  ISOReader + identify_disc on %s\n", cue);

    for (; i + 2 < argc && std::strcmp(argv[i], "--png") == 0; i += 3) check_png(argv[i + 1], argv[i + 2]);

    if (i + 3 < argc && std::strcmp(argv[i], "--big") == 0) {
        // A range past 4 GB in a (sparse) container: 64-bit offsets.
        const std::vector<uint8_t> want = slurp(argv[i + 2]);
        FILE* f = std::fopen(argv[i + 1], "rb");
        CHECK(f != nullptr, "fopen big placeholder");
        if (f) {
            std::vector<uint8_t> got(want.size());
            CHECK(std::fread(got.data(), 1, got.size(), f) == got.size() && got == want,
                  "range at offset %s", argv[i + 3]);
            CHECK(fseeko(f, 0, SEEK_END) == 0 && (uint64_t)ftello(f) == want.size(), "big size");
            std::fclose(f);
        }
        std::printf("ok  range at offset %s\n", argv[i + 3]);
    }

    // A placeholder whose size is not its packed track's (or whose APK is
    // gone) fails to open instead of reading wrong bytes.
    {
        FILE* f = std::fopen("wrong-size.bin", "rb");
        CHECK(f == nullptr, "a placeholder of the wrong size must not open");
        if (f) std::fclose(f);
    }
    // A placeholder whose APK is gone fails to open instead of reading zeros.
    {
        FILE* f = std::fopen("stale.bin", "rb");
        CHECK(f == nullptr, "a placeholder naming a missing APK must not open");
        if (f) std::fclose(f);
    }
    // Ordinary files are untouched.
    {
        FILE* f = std::fopen("ordinary.txt", "rb");
        char line[64] = {};
        CHECK(f && std::fgets(line, sizeof(line), f) && std::strcmp(line, "just a file\n") == 0,
              "ordinary file");
        if (f) std::fclose(f);
        FILE* w = std::fopen("written.txt", "wb");
        CHECK(w && std::fputs("hello\n", w) >= 0, "writing a file");
        if (w) std::fclose(w);
    }

    std::printf("%d checks, %d failures\n", g_checks, g_failures);
    return g_failures ? 1 : 0;
}
