#!/usr/bin/env python3
from pathlib import Path
import re

source = (Path(__file__).parents[1] / "src" / "gpu_vk_renderer.c").read_text()

begin = re.search(r"static VkCommandBuffer begin_oneshot\(.*?\n\}", source, re.DOTALL)
end = re.search(r"static void end_oneshot\(.*?\n\}", source, re.DOTALL)
flush = re.search(r"static void flush_work\(.*?\n\}", source, re.DOTALL)
sync = re.search(
    r"static void vk_gpu_sync_internal\(void\) \{.*?\n\}", source, re.DOTALL
)
assert begin and end and flush and sync
assert "if (s_work_cb) return s_work_cb" in begin.group(0)
assert "p_vkQueueSubmit" not in end.group(0)
assert "p_vkQueueSubmit" in flush.group(0)
assert "s_work_cb = VK_NULL_HANDLE" in flush.group(0)
assert "flush_work();" in sync.group(0)
print("Vulkan command-buffer batching test passed")
