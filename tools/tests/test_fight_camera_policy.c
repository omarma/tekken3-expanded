#include "tekken3_fight_camera.h"
#include <assert.h>
#include <stdio.h>

int main(void)
{
    assert(tekken3_fight_focal_policy(500, 1, 61, 5, 0) == 376);
    for (uint32_t f = 1; f <= 32767; ++f) {
        assert(tekken3_fight_focal_policy(f, 0, 61, 5, 0) == f);
        assert(tekken3_fight_focal_policy(f, 1, 0, 5, 0) == f);
        assert(tekken3_fight_focal_policy(f, 1, 61, 6, 0) == f);
        assert(tekken3_fight_focal_policy(f, 1, 61, 7, 0) == f);
        assert(tekken3_fight_focal_policy(f, 1, 61, 5, 1) == f);
        uint32_t previous = f;
        for (int m = 1; m <= 61; ++m) {
            uint32_t wide = tekken3_fight_focal_policy(f, 1, m, 5, 0);
            assert(wide > 0 && wide <= previous);
            previous = wide;
        }
    }
    assert(tekken3_fight_focal_policy(0, 1, 61, 0, 0) == 0);
    assert(tekken3_fight_focal_policy(500, 1, 62, 0, 0) == 500);
    puts("Fight camera policy: identity, exclusions, and focal bounds passed");
}
