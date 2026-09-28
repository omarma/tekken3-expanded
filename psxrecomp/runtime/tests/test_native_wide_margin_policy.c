#include "native_wide_margin_policy.h"

#include <assert.h>
#include <stdint.h>
#include <stdio.h>

int main(void) {
    uint32_t fb0 = UINT32_MAX;
    uint32_t fb1 = UINT32_MAX;

    assert(psx_ws_margin_refresh_once(100u, &fb0));
    assert(!psx_ws_margin_refresh_once(100u, &fb0));
    assert(psx_ws_margin_refresh_once(100u, &fb1));
    assert(psx_ws_margin_refresh_once(101u, &fb0));
    assert(!psx_ws_margin_refresh_once(101u, &fb0));
    assert(!psx_ws_margin_refresh_once(101u, NULL));

    puts("PASS: native-wide margins refresh once per framebuffer and frame");
    return 0;
}
