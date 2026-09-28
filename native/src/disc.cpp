#include "tekken3_native/disc.hpp"

#include "disc_path.h"
#include "iso_reader.h"

#include <algorithm>
#include <cctype>
#include <cstddef>
#include <exception>
#include <iomanip>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

namespace tekken3::native {
namespace {

constexpr std::uintmax_t kExpectedExeSize = 1'185'792;
constexpr std::uint32_t kExpectedLoadAddress = 0x80010000u;
constexpr std::uint32_t kExpectedEntryPc = 0x80079C70u;
constexpr std::uint32_t kExpectedTextSize = 0x00121000u;
constexpr std::size_t kPsxExeHeaderSize = 2048;

std::string trim_ascii(std::string value) {
    const auto is_space = [](unsigned char c) { return std::isspace(c) != 0; };
    value.erase(value.begin(),
                std::find_if(value.begin(), value.end(),
                             [&](char c) { return !is_space(static_cast<unsigned char>(c)); }));
    value.erase(std::find_if(value.rbegin(), value.rend(),
                             [&](char c) { return !is_space(static_cast<unsigned char>(c)); })
                    .base(),
                value.end());
    return value;
}

std::string uppercase_ascii(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c) {
        return static_cast<char>(std::toupper(c));
    });
    return value;
}

std::string parse_boot_path(const std::string& cnf) {
    std::istringstream input(cnf);
    std::string line;
    while (std::getline(input, line)) {
        if (!line.empty() && line.back() == '\r') {
            line.pop_back();
        }
        const std::size_t equals = line.find('=');
        if (equals == std::string::npos ||
            uppercase_ascii(trim_ascii(line.substr(0, equals))) != "BOOT") {
            continue;
        }

        std::string value = trim_ascii(line.substr(equals + 1));
        const std::string upper_value = uppercase_ascii(value);
        std::size_t colon = std::string::npos;
        if (upper_value.compare(0, 6, "CDROM:") == 0) {
            colon = 5;
        } else if (upper_value.compare(0, 7, "CDROM0:") == 0) {
            colon = 6;
        }
        if (colon == std::string::npos) {
            return {};
        }

        std::size_t begin = colon + 1;
        while (begin < value.size() &&
               (value[begin] == '\\' || value[begin] == '/')) {
            ++begin;
        }
        std::size_t end = begin;
        while (end < value.size()) {
            const unsigned char c = static_cast<unsigned char>(value[end]);
            if (value[end] == ';' || value[end] == '\0' || std::isspace(c)) {
                break;
            }
            ++end;
        }
        return value.substr(begin, end - begin);
    }
    return {};
}

std::string normalize_disc_path(std::string path) {
    for (char& c : path) {
        if (c == '\\') {
            c = '/';
        }
    }
    while (!path.empty() && path.front() == '/') {
        path.erase(path.begin());
    }
    return uppercase_ascii(path);
}

bool has_expected_boot_suffix(const std::string& boot_path) {
    static const std::string expected = "TEKKEN3/SLUS_004.02";
    const std::string normalized = normalize_disc_path(boot_path);
    if (normalized.size() < expected.size() ||
        normalized.compare(normalized.size() - expected.size(), expected.size(), expected) != 0) {
        return false;
    }
    return normalized.size() == expected.size() ||
           normalized[normalized.size() - expected.size() - 1] == '/';
}

std::string iso_reader_path(std::string boot_path) {
    for (char& c : boot_path) {
        if (c == '\\') {
            c = '/';
        }
    }
    while (!boot_path.empty() && boot_path.front() == '/') {
        boot_path.erase(boot_path.begin());
    }
    return boot_path;
}

std::uint32_t read_le32(const std::vector<std::uint8_t>& bytes,
                        std::size_t offset) {
    return static_cast<std::uint32_t>(bytes[offset]) |
           (static_cast<std::uint32_t>(bytes[offset + 1]) << 8) |
           (static_cast<std::uint32_t>(bytes[offset + 2]) << 16) |
           (static_cast<std::uint32_t>(bytes[offset + 3]) << 24);
}

std::string hex32(std::uint32_t value) {
    std::ostringstream out;
    out << "0x" << std::uppercase << std::hex << std::setw(8)
        << std::setfill('0') << value;
    return out.str();
}

DiscReport failure(DiscReport report, std::string detail) {
    report.ok = false;
    report.detail = std::move(detail);
    return report;
}

}  // namespace

DiscReport inspect_disc(const std::filesystem::path& path) {
    DiscReport report;

    try {
        const PSXRecompV4::DiscPathResolution resolved =
            PSXRecompV4::resolve_disc_path(path);
        report.mount_path = resolved.mount;

        PS1::ISOReader disc;
        if (!disc.Open(resolved.mount.string())) {
            std::string detail = "Could not mount the selected disc image";
            if (!resolved.note.empty()) {
                detail += ": " + resolved.note;
            } else {
                detail += ".";
            }
            return failure(report, std::move(detail));
        }

        report.volume_id = disc.GetVolumeID();
        report.track_count = disc.TrackCount();
        report.tracks.reserve(report.track_count > 0
                                  ? static_cast<std::size_t>(report.track_count)
                                  : 0u);
        for (int number = 1; number <= report.track_count; ++number) {
            report.tracks.push_back({number,
                                     disc.TrackIsAudio(number),
                                     disc.TrackStartLBA(number),
                                     disc.TrackPregapLBA(number)});
        }

        if (report.track_count != 3) {
            return failure(report,
                           "Unsupported disc layout: expected 3 tracks, found " +
                               std::to_string(report.track_count) + ". Select the complete CUE dump.");
        }
        if (!disc.TrackIsAudio(2)) {
            return failure(report,
                           "Unsupported disc layout: track 2 must be a CD audio track.");
        }

        const std::size_t cnf_size = disc.GetFileSize("SYSTEM.CNF");
        if (cnf_size == 0) {
            return failure(report,
                           "SYSTEM.CNF was not found on the mounted disc.");
        }
        std::vector<std::uint8_t> cnf(cnf_size);
        if (disc.ReadFile("SYSTEM.CNF", cnf.data(), cnf.size()) != cnf.size()) {
            return failure(report,
                           "SYSTEM.CNF could not be read completely.");
        }

        report.boot_path = parse_boot_path(
            std::string(reinterpret_cast<const char*>(cnf.data()), cnf.size()));
        if (report.boot_path.empty()) {
            return failure(report,
                           "SYSTEM.CNF does not contain a supported BOOT path.");
        }
        if (!has_expected_boot_suffix(report.boot_path)) {
            return failure(report,
                           "Unsupported disc BOOT path: expected TEKKEN3\\SLUS_004.02, found " +
                               report.boot_path + ".");
        }

        const std::string executable_path = iso_reader_path(report.boot_path);
        report.boot_executable_size = disc.GetFileSize(executable_path);
        if (report.boot_executable_size != kExpectedExeSize) {
            return failure(report,
                           "Unsupported boot executable size: expected 1,185,792 bytes, found " +
                               std::to_string(report.boot_executable_size) + ".");
        }

        std::vector<std::uint8_t> header(kPsxExeHeaderSize);
        if (disc.ReadFile(executable_path, header.data(), header.size()) != header.size()) {
            return failure(report,
                           "The boot executable header could not be read completely.");
        }
        static const std::string magic = "PS-X EXE";
        if (!std::equal(magic.begin(), magic.end(), header.begin())) {
            return failure(report,
                           "The BOOT file is not a PS-X EXE.");
        }

        report.entry_pc = read_le32(header, 0x10);
        report.load_address = read_le32(header, 0x18);
        report.text_size = read_le32(header, 0x1c);
        if (report.load_address != kExpectedLoadAddress) {
            return failure(report,
                           "Unsupported PS-X EXE load address: expected 0x80010000, found " +
                               hex32(report.load_address) + ".");
        }
        if (report.entry_pc != kExpectedEntryPc) {
            return failure(report,
                           "Unsupported PS-X EXE entry PC: expected 0x80079C70, found " +
                               hex32(report.entry_pc) + ".");
        }
        if (report.text_size != kExpectedTextSize) {
            return failure(report,
                           "Unsupported PS-X EXE text size: expected 0x00121000, found " +
                               hex32(report.text_size) + ".");
        }

        report.ok = true;
        report.detail = "Supported Tekken 3 disc verified.";
        if (!resolved.note.empty()) {
            report.detail += " " + resolved.note;
        }
        return report;
    } catch (const std::exception& error) {
        return failure(report,
                       std::string("Disc inspection failed: ") + error.what());
    }
}

}  // namespace tekken3::native
