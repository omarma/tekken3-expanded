#include "consoles/psx/psx_binds.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum {
    TEST_CROSS = 6,
    TEST_MOUSE1 = 513
};

static void require(int condition, const char *message)
{
    if (condition) return;
    fprintf(stderr, "FAIL: %s\n", message);
    exit(1);
}

static int file_contains(const char *path, const char *needle)
{
    FILE *file = fopen(path, "rb");
    char text[8192];
    size_t size;
    if (!file) return 0;
    size = fread(text, 1, sizeof(text) - 1, file);
    fclose(file);
    text[size] = '\0';
    return strstr(text, needle) != NULL;
}

int main(int argc, char **argv)
{
    const char *path;
    int primary;
    if (argc != 2) {
        fprintf(stderr, "usage: psx_binds_test <temporary-ini>\n");
        return 2;
    }
    path = argv[1];
    remove(path);

    rui_psx_binds_init(path);
    primary = rui_psx_binds_get_slot(path, 0, TEST_CROSS, 0);
    require(primary != 0, "Cross has a seeded primary binding");
    require(rui_psx_binds_get_slot(path, 0, TEST_CROSS, 1) == 0,
            "Cross alternate starts unbound");

    rui_psx_binds_set_slot(path, 0, TEST_CROSS, 1, TEST_MOUSE1);
    require(rui_psx_binds_get_slot(path, 0, TEST_CROSS, 0) == primary,
            "setting alternate preserves primary");
    require(rui_psx_binds_get_slot(path, 0, TEST_CROSS, 1) == TEST_MOUSE1,
            "mouse pseudo-scancode round-trips in memory");
    require(file_contains(path, "Mouse1"),
            "mouse alternate persists by its runtime-compatible name");

    rui_psx_binds_set_slot(path, 0, TEST_CROSS, 0, primary);
    require(rui_psx_binds_get_slot(path, 0, TEST_CROSS, 1) == TEST_MOUSE1,
            "rewriting primary does not erase alternate");
    require(file_contains(path, "Mouse1"),
            "rewriting primary preserves alternate on disk");

    rui_psx_binds_reset(path, 0);
    require(rui_psx_binds_get_slot(path, 0, TEST_CROSS, 1) == 0,
            "reset clears alternate binding");

    remove(path);
    puts("PSX dual-bind persistence tests passed");
    return 0;
}
