// launcher_device.h - controller-source conversion at the recomp-ui C ABI.

#pragma once

#include <algorithm>
#include <cctype>
#include <string>

namespace PSXRecompV4 {

inline std::string trim_launcher_device(const std::string& device) {
    const auto first = std::find_if_not(device.begin(), device.end(),
        [](unsigned char c) { return std::isspace(c) != 0; });
    const auto last = std::find_if_not(device.rbegin(), device.rend(),
        [](unsigned char c) { return std::isspace(c) != 0; }).base();
    return first < last ? std::string(first, last) : std::string();
}

inline std::string normalize_launcher_device(const std::string& device) {
    std::string normalized = trim_launcher_device(device);
    std::transform(normalized.begin(), normalized.end(), normalized.begin(),
        [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    return normalized;
}

inline int launcher_source_from_device(const std::string& device) {
    const std::string normalized = normalize_launcher_device(device);
    if (normalized.empty() || normalized == "none") return 0;
    if (normalized == "keyboard") return 1;
    return 2;
}

inline std::string launcher_device_from_source(
    int source, const std::string& previous_device) {
    if (source <= 0) return "none";
    if (source == 1) return "keyboard";

    // recomp-ui's C ABI currently returns a source category, not the selected
    // controller GUID. Preserve an existing gamepad/GUID assignment; when the
    // user switched from None/Keyboard, persist the runtime's first-pad alias.
    if (launcher_source_from_device(previous_device) == 2) {
        return trim_launcher_device(previous_device);
    }
    return "gamepad";
}

} // namespace PSXRecompV4
