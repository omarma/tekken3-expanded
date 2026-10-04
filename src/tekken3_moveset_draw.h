/* The CPU's draw among a fighter's movesets (tekken3_native_moves.c): every
 * choice has the same chance, whatever how many there are (the game's own
 * moves plus one per imported source: 1 in 2, 1 in 3, 1 in 4...). Kept in a
 * header of its own so that tools/tests/test_moveset_draw.py can count it. */
#ifndef TEKKEN3_MOVESET_DRAW_H
#define TEKKEN3_MOVESET_DRAW_H
#include <stdint.h>

/* A seed (the clock, a counter) is mixed before use (splitmix64), else the
 * first draws of a game follow its low bits: a poor seed gave 62 / 38 over 69
 * draws of two choices. */
static inline void tekken3_moveset_seed(uint64_t *state,uint64_t seed) {
    uint64_t z=seed+0x9e3779b97f4a7c15ull;
    z=(z^(z>>30))*0xbf58476d1ce4e5b9ull;z=(z^(z>>27))*0x94d049bb133111ebull;z^=z>>31;
    *state=z?z:0x9e3779b97f4a7c15ull;
}
/* xorshift64*, never seeded with 0. */
static inline uint32_t tekken3_moveset_rng(uint64_t *state) {
    uint64_t x=*state?*state:0x9e3779b97f4a7c15ull;
    x^=x>>12;x^=x<<25;x^=x>>27;*state=x;
    return (uint32_t)((x*0x2545f4914f6cdd1dull)>>32);
}
/* One of n choices, 0 .. n-1, with the same chance each: a 32-bit draw
 * modulo n, rejecting the few top values that would favour the first ones. */
static inline unsigned tekken3_moveset_draw(unsigned n,uint64_t *state) {
    if(n<2)return 0;
    uint64_t limit=0x100000000ull-0x100000000ull%n;
    uint32_t r;
    do r=tekken3_moveset_rng(state);while(r>=limit);
    return (unsigned)(r%n);
}
#endif
