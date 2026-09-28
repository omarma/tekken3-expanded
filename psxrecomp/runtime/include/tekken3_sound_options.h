#ifndef TEKKEN3_SOUND_OPTIONS_H
#define TEKKEN3_SOUND_OPTIONS_H
#ifdef __cplusplus
extern "C" {
#endif
/* Host preferences; intentionally independent of memory cards/savestates. */
void tekken3_sound_options_configure(const char *game_id, const char *save_path);
void tekken3_sound_options_tick(void);
#ifdef __cplusplus
}
#endif
#endif
