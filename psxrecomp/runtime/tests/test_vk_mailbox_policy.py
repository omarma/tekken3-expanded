#!/usr/bin/env python3
from pathlib import Path
import re

source = (Path(__file__).parents[1] / "src" / "gpu_vk_renderer.c").read_text()
choose = re.search(r"static VkPresentModeKHR choose_present_mode\(.*?\n\}", source, re.DOTALL)
assert choose
body = choose.group(0)
assert "s_present_mode_req == 0" in body
assert "VK_PRESENT_MODE_IMMEDIATE_KHR" in body
assert "VK_PRESENT_MODE_MAILBOX_KHR" in body
assert "return VK_PRESENT_MODE_FIFO_KHR" in body
assert "s_present_mode_req < 0" not in body
print("Vulkan MAILBOX present-policy test passed")
