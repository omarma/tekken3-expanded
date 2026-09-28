#include "cli_boot_path.h"

#include <cstdio>
#include <string>

namespace {

int failures = 0;

void check(bool condition, const char* message) {
    if (condition) return;
    std::fprintf(stderr, "FAIL: %s\n", message);
    failures++;
}

} // namespace

int main() {
    const std::string windows_style = "EXE\\SLUS_123.45";
    const std::string posix_style = "EXE/SLUS_123.45";

    check(PSXRecompCLI::normalize_boot_path(windows_style) == posix_style,
          "normalizes SYSTEM.CNF backslashes independent of the host OS");
    check(PSXRecompCLI::boot_filename(windows_style) == "SLUS_123.45",
          "extracts a subdirectory boot filename from backslashes");
    check(PSXRecompCLI::boot_filename(posix_style) == "SLUS_123.45",
          "extracts a subdirectory boot filename from forward slashes");
    check(PSXRecompCLI::serial_from_boot(windows_style) == "SLUS-12345",
          "does not include the boot directory in the generated game ID");
    check(PSXRecompCLI::serial_from_boot(windows_style) ==
              PSXRecompCLI::serial_from_boot(posix_style),
          "generates the same game ID for Linux and Windows path forms");
    check(PSXRecompCLI::boot_filename("SCUS_944.23") == "SCUS_944.23",
          "preserves root-level boot filenames");
    check(PSXRecompCLI::serial_from_boot("SCUS_944.23") == "SCUS-94423",
          "preserves root-level game ID generation");
    check(PSXRecompCLI::serial_from_boot("") == "PSX-GAME",
          "preserves the fallback game ID for an empty boot path");

    return failures == 0 ? 0 : 1;
}
