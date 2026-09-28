#pragma once
#include <string.h>

/* Player 2's own keyboard defaults: every player used to start with player
 * 1's map, so one key drove both. Looked up by name so the order of the
 * runtime's button table does not matter. From upstream v0.1.3, which puts
 * the buttons on the numeric keypad; a Mac laptop has none, so there they
 * sit on F G V B (the mirror of player 1's A S Z X) and the number row. */
static SDL_Scancode tekken3_keyboard_default(int player, const char *name,
                                            SDL_Scancode original) {
    if (player != 1) return original; /* zero-based */
    static const struct { const char *name; SDL_Scancode key; } keys[] = {
        {"up", SDL_SCANCODE_I}, {"down", SDL_SCANCODE_K},
        {"left", SDL_SCANCODE_J}, {"right", SDL_SCANCODE_L},
        {"l1", SDL_SCANCODE_U}, {"r1", SDL_SCANCODE_O},
#ifdef __APPLE__
        {"triangle", SDL_SCANCODE_F}, {"circle", SDL_SCANCODE_G},
        {"square", SDL_SCANCODE_V}, {"cross", SDL_SCANCODE_B},
        {"l2", SDL_SCANCODE_7}, {"r2", SDL_SCANCODE_9},
        {"l3", SDL_SCANCODE_0}, {"r3", SDL_SCANCODE_MINUS},
        {"start", SDL_SCANCODE_P}, {"select", SDL_SCANCODE_BACKSPACE},
#else
        {"cross", SDL_SCANCODE_KP_1}, {"circle", SDL_SCANCODE_KP_2},
        {"square", SDL_SCANCODE_KP_4}, {"triangle", SDL_SCANCODE_KP_5},
        {"l2", SDL_SCANCODE_KP_7}, {"r2", SDL_SCANCODE_KP_9},
        {"l3", SDL_SCANCODE_KP_0}, {"r3", SDL_SCANCODE_KP_PERIOD},
        {"start", SDL_SCANCODE_KP_ENTER}, {"select", SDL_SCANCODE_BACKSPACE},
#endif
        {"ls_up", SDL_SCANCODE_I}, {"ls_down", SDL_SCANCODE_K},
        {"ls_left", SDL_SCANCODE_J}, {"ls_right", SDL_SCANCODE_L}
    };
    for (unsigned i = 0; i < sizeof keys / sizeof *keys; ++i)
        if (!strcmp(name, keys[i].name)) return keys[i].key;
    return SDL_SCANCODE_UNKNOWN;
}
