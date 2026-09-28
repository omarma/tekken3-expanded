#include "cli_boot_path.h"

#include <cctype>
#include <filesystem>

namespace PSXRecompCLI {

std::string normalize_boot_path(const std::string& boot) {
    std::string normalized;
    normalized.reserve(boot.size());
    for (char c : boot) normalized += (c == '\\') ? '/' : c;
    return normalized;
}

std::string boot_filename(const std::string& boot) {
    return std::filesystem::path(normalize_boot_path(boot)).filename().string();
}

std::string serial_from_boot(const std::string& boot) {
    std::string base = boot_filename(boot);
    std::string clean;
    for (char c : base) {
        if (std::isalnum(static_cast<unsigned char>(c))) {
            clean += static_cast<char>(std::toupper(static_cast<unsigned char>(c)));
        }
    }
    size_t split = 0;
    while (split < clean.size() &&
           std::isalpha(static_cast<unsigned char>(clean[split]))) {
        split++;
    }
    if (split && split < clean.size()) clean.insert(split, "-");
    return clean.empty() ? "PSX-GAME" : clean;
}

} // namespace PSXRecompCLI
