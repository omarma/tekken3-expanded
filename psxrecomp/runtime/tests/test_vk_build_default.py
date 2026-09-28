#!/usr/bin/env python3
from pathlib import Path
import re


root = Path(__file__).parents[2]
runtime_cmake = (root / "runtime" / "runtime.cmake").read_text()
config_loader = (root / "recompiler" / "src" / "config_loader.h").read_text()

option = re.search(
    r'option\(PSX_ENABLE_VULKAN\s+"[^"]*"\s+(ON|OFF)\)', runtime_cmake
)
assert option, "PSX_ENABLE_VULKAN option not found"
assert option.group(1) == "ON", "Vulkan backend is not compiled by default"
assert "DEFAULT_VIDEO_RENDERER = VIDEO_RENDERER_OPENGL" in config_loader, (
    "enabling the Vulkan build changed the runtime renderer default away from OpenGL"
)

print("Vulkan build/default-renderer policy test passed")
