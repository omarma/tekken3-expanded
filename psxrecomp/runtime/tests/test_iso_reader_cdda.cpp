#include "iso_reader.h"

#include <cassert>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <string>
#include <vector>

static void write_sectors(const std::filesystem::path& path, int count, uint8_t marker) {
    std::ofstream out(path, std::ios::binary);
    std::vector<uint8_t> sector(2352, marker);
    for (int i = 0; i < count; ++i) out.write(reinterpret_cast<const char*>(sector.data()), sector.size());
}

int main() {
    const auto dir = std::filesystem::temp_directory_path() / "psxrecomp-cdda-reader-test";
    std::filesystem::remove_all(dir);
    std::filesystem::create_directories(dir);
    write_sectors(dir / "data.bin", 4, 0x11);
    write_sectors(dir / "audio.bin", 3, 0x22);

    {
        std::ofstream cue(dir / "disc.cue");
        cue << "FILE \"data.bin\" BINARY\n"
               "  TRACK 01 MODE2/2352\n"
               "    INDEX 01 00:00:00\n"
               "FILE \"audio.bin\" BINARY\n"
               "  TRACK 02 AUDIO\n"
               "    INDEX 00 00:00:00\n"
               "    INDEX 01 00:00:01\n";
    }

    PS1::ISOReader reader;
    assert(reader.Open((dir / "disc.cue").string()));
    assert(reader.TrackCount() == 2);
    assert(reader.TrackStartLBA(1) == 0);
    assert(reader.TrackPregapLBA(1) == 0);
    assert(!reader.TrackIsAudio(1));
    assert(reader.TrackPregapLBA(2) == 4);
    assert(reader.TrackStartLBA(2) == 5);
    assert(reader.TrackIsAudio(2));
    assert(reader.GetSectorCount() == 7);

    uint8_t raw[2352] = {};
    assert(reader.ReadRawSector(4, raw));
    assert(raw[0] == 0x22);
    reader.Close();
    std::filesystem::remove_all(dir);
    return 0;
}
