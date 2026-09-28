#include "mod_plugins.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static PSXModVBlankCallback callback;
static unsigned char progress[16];
static int started, reads, writes;

int psx_mod_register_vblank_plugin(const char *id, PSXModVBlankCallback fn) {
    assert(strcmp(id, "tekken3.unlock-all-characters") == 0);
    callback = fn;
    return 1;
}
int psx_mod_game_started(void) { return started; }
uint32_t psx_mod_read_word(uint32_t address) {
    assert(address == 0x80097EF0u);
    reads++;
    return (uint32_t)progress[0] | ((uint32_t)progress[1] << 8) |
        ((uint32_t)progress[2] << 16) | ((uint32_t)progress[3] << 24);
}
void psx_mod_write_word(uint32_t address, uint32_t value) {
    assert(address == 0x80097EF0u);
    writes++;
    for (unsigned i = 0; i < 4; i++) progress[i] = (unsigned char)(value >> (8*i));
}
uint8_t psx_mod_read_byte(uint32_t address) {
    assert(address == 0x80097EF6u);
    reads++;
    return progress[6];
}
void psx_mod_write_byte(uint32_t address, uint8_t value) {
    assert(address == 0x80097EF6u);
    writes++;
    progress[6] = value;
}

int main(void) {
    assert(callback);
    memset(progress, 0xA0, sizeof(progress));
    progress[6] = 0;
    callback();
    assert(reads == 0 && writes == 0); /* BIOS is untouched. */
    started = 1;
    callback();
    assert(psx_mod_read_word(0x80097EF0u) == 0xA0BFFFFFu);
    assert(progress[6] == 5 && writes == 2);
    for (int i = 4; i < 16; i++)
        if (i != 6) assert(progress[i] == 0xA0);
    callback();
    assert(writes == 2); /* No writes once the roster is unlocked. */
    progress[6] = 7;
    callback();
    assert(progress[6] == 7 && writes == 2); /* Never reduce progress. */
    memset(progress, 0, sizeof(progress)); /* Loading an older save. */
    callback();
    assert(psx_mod_read_word(0x80097EF0u) == 0x001FFFFFu);
    assert(progress[6] == 5 && writes == 4);
    puts("PASS: default character unlock, boot guard, old saves and neighboring flags");
    return 0;
}
