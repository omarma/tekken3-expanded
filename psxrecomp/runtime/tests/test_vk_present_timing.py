#!/usr/bin/env python3
from pathlib import Path

source = (Path(__file__).parents[1] / "src" / "gpu_vk_renderer.c").read_text()
for field in ("present_qpc", "wait_us", "acquire_us", "present_us"):
    assert field in source
for call in (
    "s_perf_cur.wait_us += perf_elapsed_us(wait_start)",
    "s_perf_cur.acquire_us += perf_elapsed_us(acquire_start)",
    "s_perf_cur.present_us += perf_elapsed_us(present_start)",
):
    assert call in source
assert '\\"acquire_us\\":%u' in source
print("Vulkan present-timing telemetry test passed")
