#include "spu_gauss.h"

#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

int main(void)
{
    int16_t previous[3] = { 1000, 2000, 3000 };
    int16_t samples[28];
    memset(samples, 0, sizeof(samples));
    samples[0] = 4000;

    /* At the start of a block all three historical taps must come from the
     * previous block. These coefficients are table entries 255, 511, 256, 0. */
    assert(spu_gaussian_interpolate(previous, samples, 0, 0) == 1994);

    /* The same four values inside a block must produce the same result. */
    samples[0] = 1000;
    samples[1] = 2000;
    samples[2] = 3000;
    samples[3] = 4000;
    assert(spu_gaussian_interpolate(previous, samples, 3, 0) == 1994);

    memset(previous, 0, sizeof(previous));
    memset(samples, 0, sizeof(samples));
    assert(spu_gaussian_interpolate(previous, samples, 0, 0x800u) == 0);

    puts("SPU Gaussian interpolation tests passed");
    return 0;
}
