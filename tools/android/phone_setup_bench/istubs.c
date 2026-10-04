/* psx_interpreter.c needs these device hooks; the benchmark has no devices. */
#include <stdint.h>
uint32_t i_stat, i_mask; void sio_tick(uint32_t c){(void)c;} void gpu_vblank_tick(void){} void timers_tick(uint32_t c){(void)c;} void cdrom_tick(void){}
void psx_irq_raise(uint32_t b,uint32_t d){(void)b;(void)d;} void psx_irq_refresh_cause_ip2(void){} void gte_precision_store_word(uint32_t a,uint8_t r){(void)a;(void)r;}
