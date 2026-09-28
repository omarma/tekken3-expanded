/* Exercise the actual two render paths, including capture/snapshot identity. */
#ifdef NDEBUG
#undef NDEBUG
#endif
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../src/spu.c"
uint64_t s_frame_count;
static int shadow_delta;
void psx_irq_raise(uint32_t a,uint32_t b) { (void)a;(void)b; }
uint64_t psx_get_cycle_count(void) { return 0; }
void audio_trace_pcm(int a,const int16_t *b,int c) { (void)a;(void)b;(void)c; }
void audio_trace_event(uint16_t a,uint32_t b,uint32_t c) { (void)a;(void)b;(void)c; }
bool spu_shadow_enabled(void) { return shadow_delta!=0; }
void spu_shadow_reset(void) {}
void spu_shadow_process(int16_t *p,int n) { for(int i=0;i<n*2;i++)p[i]=clamp16(p[i]+shadow_delta); }
static void setup(int with_voice) {
    spu_init();
    spu_write(0x1f801daa,0xff01);
    spu_write(0x1f801d80,0x3fff);spu_write(0x1f801d82,0x3fff);
    spu_write(0x1f801db0,0x7fff);spu_write(0x1f801db2,0x7fff);
    if(with_voice) {
        spu_write(0x1f801c00,0x1000);spu_write(0x1f801c02,0x1000);
        spu_write(0x1f801c04,0x1000);spu_write(0x1f801c06,0x600);
        spu_write(0x1f801c08,0);spu_write(0x1f801c0a,0);
        spu_write(0x1f801d94,1);spu_write(0x1f801d88,1);
    }
    int16_t cd[512*2];
    for(int i=0;i<512;i++) {cd[i*2]=3000;cd[i*2+1]=-2000;}
    spu_cd_audio_push(cd,512);
}
int main(void) {
    uint32_t size=spu_snapshot_bytes();
    uint8_t *initial=malloc(size),*reference=malloc(size),*actual=malloc(size);
    uint8_t *reference_ram=malloc(SPU_RAM_SIZE);assert(reference_ram);
    assert(initial && reference && actual);
    int16_t full[512*2],music[512*2],sfx[512*2],mixed[512*2];
    for(int voice=0;voice<=1;voice++) {
        setup(voice);spu_snapshot_write(initial);
        spu_set_host_mix_volume(100,100);spu_render(full,512);spu_snapshot_write(reference);memcpy(reference_ram,spu_ram,SPU_RAM_SIZE);
        setup(voice);
        spu_set_host_mix_volume(0,100);spu_render(music,512);spu_snapshot_write(actual);
        assert(!memcmp(actual,reference,size));
        assert(!memcmp(reference_ram,spu_ram,SPU_RAM_SIZE));
        setup(voice);
        spu_set_host_mix_volume(100,0);spu_render(sfx,512);spu_snapshot_write(actual);
        assert(!memcmp(actual,reference,size));
        assert(!memcmp(reference_ram,spu_ram,SPU_RAM_SIZE));
        int sfx_nonzero=0;
        for(int i=0;i<1024;i++) {
            assert(abs(full[i]-music[i]-sfx[i])<=1);
            if(sfx[i])sfx_nonzero=1;
        }
        assert(sfx_nonzero==voice && music[200]>1000);
        setup(voice);
        spu_set_host_mix_volume(50,25);spu_render(mixed,512);
        for(int i=0;i<1024;i++)assert(abs(mixed[i]-(sfx[i]/2+music[i]/4))<=2);
        setup(voice);
        spu_set_host_mix_volume(0,0);spu_render(mixed,512);
        for(int i=0;i<1024;i++)assert(mixed[i]==0);
    }
    /* Quieting the music removes it before saturation (no clipped residue). */
    spu_set_host_mix_volume(100,0);
    assert(host_mix_sample(50000,30000,32767)==19999);
    assert(host_mix_sample(-50000,-30000,32767)==-20000);
    /* HQ substitution is verified on canonical audio, then receives SFX gain. */
    setup(0);spu_snapshot_write(initial);shadow_delta=400;
    spu_set_host_mix_volume(50,0);spu_render(mixed,512);
    for(int i=0;i<1024;i++)assert(mixed[i]==200);
    shadow_delta=0;
    /* Large caller buffers are bounded; both mute and disabled-SPU paths. */
    int16_t big[4096*2];
    spu_set_host_mix_volume(0,0);setup(1);spu_render(big,4096);
    for(int i=0;i<8192;i++)assert(big[i]==0);
    spu_write(0x1f801daa,0);spu_set_host_mix_volume(50,50);spu_render(big,4096);
    for(int i=0;i<8192;i++)assert(big[i]==0);
    free(initial);free(reference);free(actual);free(reference_ram);
    puts("SPU host volumes: bus separation, gain, mute, clipping, HQ and guest-state identity passed");
    return 0;
}
