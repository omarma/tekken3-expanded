#include "../src/gpu_vk_upload.h"

#include <assert.h>
#include <stdio.h>

int main(void)
{
    assert(vk_upload_aligned_texels(0) == 0);
    assert(vk_upload_aligned_texels(1) == 2);
    assert(vk_upload_aligned_texels(2) == 2);
    assert(vk_upload_aligned_texels(3) == 4);
    assert((vk_upload_aligned_texels(1023u * 511u) * 2u) % 4u == 0);
    puts("Vulkan upload alignment tests passed");
    return 0;
}
