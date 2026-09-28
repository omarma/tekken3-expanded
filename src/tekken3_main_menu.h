#pragma once
#ifdef __cplusplus
extern "C" {
#endif
int tekken3_main_menu_quit_requested(void);
/* Every VBlank: puts back the native indices after the menu's last frame. */
void tekken3_main_menu_vblank(void);
/* Nonzero while a mode's choice sound, or the sound of leaving a mode,
 * plays: loads keep their normal pace. */
int tekken3_main_menu_hold_turbo(void);
/* Called before the native menu prologue in every execution backend.
 * Nonzero means Quit was consumed; caller returns to the guest link register. */
int tekken3_main_menu_enter(void);
#ifdef __cplusplus
}
#endif
