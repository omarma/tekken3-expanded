#pragma once

#include <string>

namespace PSXRecompCLI {

// SYSTEM.CNF uses backslashes for disc-internal paths. Canonicalize them
// before passing the path to host filesystem utilities.
std::string normalize_boot_path(const std::string& boot);

std::string boot_filename(const std::string& boot);
std::string serial_from_boot(const std::string& boot);

} // namespace PSXRecompCLI
