#!/usr/bin/env python3
from pathlib import Path
import re

source = (Path(__file__).parents[1] / "src" / "gpu_vk_renderer.c").read_text()
make = re.search(
    r"static int make_staging\([^;]*?\) \{.*?\n\}", source, re.DOTALL
)
release = re.search(r"static void staging_release\(.*?\n\}", source, re.DOTALL)
destroy = re.search(r"static void staging_destroy\(.*?\n\}", source, re.DOTALL)
assert make and release and destroy
assert "entry->size >= bytes" in make.group(0)
assert "entry->busy = 1" in make.group(0)
assert "p_vkMapMemory" in make.group(0)
assert "busy = 0" in release.group(0)
assert "p_vkUnmapMemory" in destroy.group(0)
assert source.count("p_vkUnmapMemory(s_dev, rmem)") == 0
assert source.count("p_vkUnmapMemory(s_dev, umem)") == 0
print("Vulkan staging-cache test passed")
