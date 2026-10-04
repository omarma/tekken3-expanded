// A damaged ISO9660 directory must not make the reader read outside its
// buffers: a name longer than its record, and a directory size near 4 GB
// (whose sector count wrapped to an empty buffer). A cue INDEX time no disc
// has (its frame count overflowed an int) is ignored.
#include "cue_sheet.h"
#include "iso_reader.h"

#include <cassert>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <string>
#include <vector>

static void put733(uint8_t* p, uint32_t v) {
    for (int i = 0; i < 4; ++i) {
        p[i] = (uint8_t)(v >> (8 * i));
        p[7 - i] = (uint8_t)(v >> (8 * i));
    }
}

// A record of `length` bytes at `p` naming `name` (name_len may claim more).
static size_t put_record(uint8_t* p, uint8_t length, uint8_t name_len, const char* name) {
    p[0] = length;
    put733(p + 2, 21);
    put733(p + 10, 2048);
    p[32] = name_len;
    std::memcpy(p + 33, name, std::strlen(name));
    return length;
}

static std::filesystem::path write_iso(const std::filesystem::path& dir, uint32_t root_size,
                                       const std::vector<uint8_t>& root) {
    std::vector<uint8_t> image(22 * 2048, 0);
    uint8_t* pvd = &image[16 * 2048];
    pvd[0] = 1;
    std::memcpy(pvd + 1, "CD001", 5);
    pvd[156] = 34;
    put733(pvd + 156 + 2, 20);
    put733(pvd + 156 + 10, root_size);
    std::memcpy(&image[20 * 2048], root.data(), root.size());
    const auto path = dir / "disc.iso";
    std::ofstream(path, std::ios::binary).write(reinterpret_cast<const char*>(image.data()),
                                                (std::streamsize)image.size());
    return path;
}

int main() {
    const auto dir = std::filesystem::temp_directory_path() / "psxrecomp-iso-damaged-test";
    std::filesystem::remove_all(dir);
    std::filesystem::create_directories(dir);

    // A record whose name claims 200 bytes in a 34-byte record, then a good one.
    {
        std::vector<uint8_t> root(2048, 0);
        size_t at = put_record(&root[0], 34, 200, "X");
        put_record(&root[at], 40, 7, "A.BIN;1");
        PS1::ISOReader reader;
        assert(reader.Open(write_iso(dir, 2048, root).string()));
        const auto files = reader.ListFiles("");
        assert(files.size() == 1);
        assert(files[0].name == "A.BIN");
        reader.Close();
    }
    // A root directory of 0xFFFFFFFF bytes: refused, nothing listed.
    {
        std::vector<uint8_t> root(2048, 0);
        put_record(&root[0], 40, 7, "A.BIN;1");
        PS1::ISOReader reader;
        assert(reader.Open(write_iso(dir, 0xFFFFFFFFu, root).string()));
        assert(reader.ListFiles("").empty());
        PS1::ISOFileEntry entry;
        assert(!reader.FindFile("A.BIN", entry));
        reader.Close();
    }
    // INDEX times out of range: ignored, so the track has no start.
    {
        std::ofstream(dir / "disc.bin", std::ios::binary) << std::string(2352, '\0');
        std::ofstream(dir / "bad.cue") << "FILE \"disc.bin\" BINARY\n"
                                          "  TRACK 01 MODE2/2352\n"
                                          "    INDEX 01 99999999:00:00\n"
                                          "  TRACK 02 MODE2/2352\n"
                                          "    INDEX 01 00:61:00\n"
                                          "  TRACK 03 AUDIO\n"
                                          "    INDEX 01 00:02:-1\n"
                                          "  TRACK 04 AUDIO\n"
                                          "    INDEX 01 00:02:16\n";
        const PSXRecompV4::CueSheet sheet = PSXRecompV4::parse_cue_sheet(dir / "bad.cue");
        assert(sheet.tracks.size() == 1);
        assert(sheet.tracks[0].number == 4);
        assert(sheet.tracks[0].index01 == 2 * 75 + 16);
    }
    std::filesystem::remove_all(dir);
    return 0;
}
