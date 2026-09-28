#!/usr/bin/env python3
from pathlib import Path
import re

source = (Path(__file__).parents[1] / "src" / "gpu_vk_renderer.c").read_text()
helper = re.search(
    r"static void color_self_barrier\(.*?\n\}", source, flags=re.DOTALL
)
assert helper, "color_self_barrier not found"
body = helper.group(0)
for token in (
    "VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL",
    "VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT",
    "VK_ACCESS_COLOR_ATTACHMENT_READ_BIT",
    "VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT",
):
    assert token in body, f"missing {token}"

assert source.count("color_self_barrier(cb, s_vram_img)") == 1
assert source.count("color_self_barrier(cb, s_wide_img[i])") == 3
print("Vulkan color self-barrier test passed")
