#include <stdint.h>

#if defined(__GNUC__)
#define EXPORT __attribute__((visibility("default")))
#else
#define EXPORT
#endif

EXPORT int overlay_abi(void) { return 0x12345678; }
EXPORT void overlay_init(const void *callbacks) { (void)callbacks; }
EXPORT void overlay_flush_cycles(void) {}
EXPORT uint32_t func_80012345(void) { return 0xC0DEF00Du; }
