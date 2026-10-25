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

    // Redump's audio tracks: PREGAP 00:02:00, two seconds the disc has before
    // INDEX 01 and the file does not store. They take their place on the disc
    // (no data: the CD model plays them as silence) and push later tracks back.
    write_sectors(dir / "audio3.bin", 3, 0x33);
    {
        std::ofstream cue(dir / "pregap.cue");
        cue << "FILE \"data.bin\" BINARY\n"
               "  TRACK 01 MODE2/2352\n"
               "    INDEX 01 00:00:00\n"
               "FILE \"audio.bin\" BINARY\n"
               "  TRACK 02 AUDIO\n"
               "    PREGAP 00:00:02\n"
               "    INDEX 01 00:00:00\n"
               "FILE \"audio3.bin\" BINARY\n"
               "  TRACK 03 AUDIO\n"
               "    INDEX 00 00:00:00\n"
               "    INDEX 01 00:00:01\n";
    }
    PS1::ISOReader gapped;
    assert(gapped.Open((dir / "pregap.cue").string()));
    assert(gapped.TrackCount() == 3);
    assert(gapped.TrackPregapLBA(2) == 4);
    assert(gapped.TrackStartLBA(2) == 6);
    assert(gapped.TrackPregapLBA(3) == 9);
    assert(gapped.TrackStartLBA(3) == 10);
    assert(gapped.GetSectorCount() == 12);
    assert(gapped.ReadRawSector(3, raw) && raw[0] == 0x11);
    assert(!gapped.ReadRawSector(4, raw));
    assert(!gapped.ReadRawSector(5, raw));
    assert(gapped.ReadRawSector(6, raw) && raw[0] == 0x22);
    assert(gapped.ReadRawSector(9, raw) && raw[0] == 0x33);
    gapped.Close();

    // A single-file image: the PREGAP splits the file.
    {
        std::ofstream out(dir / "one.bin", std::ios::binary);
        std::vector<uint8_t> sector(2352, 0x11);
        for (int i = 0; i < 4; ++i) out.write(reinterpret_cast<const char*>(sector.data()), sector.size());
        sector.assign(2352, 0x22);
        for (int i = 0; i < 3; ++i) out.write(reinterpret_cast<const char*>(sector.data()), sector.size());
    }
    {
        std::ofstream cue(dir / "one.cue");
        cue << "FILE \"one.bin\" BINARY\n"
               "  TRACK 01 MODE2/2352\n"
               "    INDEX 01 00:00:00\n"
               "  TRACK 02 AUDIO\n"
               "    PREGAP 00:00:02\n"
               "    INDEX 01 00:00:04\n";
    }
    PS1::ISOReader single;
    assert(single.Open((dir / "one.cue").string()));
    assert(single.TrackPregapLBA(2) == 4);
    assert(single.TrackStartLBA(2) == 6);
    assert(single.GetSectorCount() == 9);
    assert(single.ReadRawSector(3, raw) && raw[0] == 0x11);
    assert(!single.ReadRawSector(5, raw));
    assert(single.ReadRawSector(6, raw) && raw[0] == 0x22);
    assert(single.ReadRawSector(8, raw) && raw[0] == 0x22);
    single.Close();
    std::filesystem::remove_all(dir);
    return 0;
}
