#include "recomp_launcher.h"
#include "consoles/psx/psx_profile.h"

#include <assert.h>
#include <string.h>

int main(void) {
    RecompLauncherCGameInfo game;
    memset(&game, 0, sizeof(game));

    launcher_profile_apply_psx(&game);

    /* PSX display enhancements are mod-owned, never generic launcher rows. */
    assert(game.widescreen_supported == 0);
    assert(game.aspect_mask == 0);
    assert(game.has_frame_interp == 0);
    assert(game.has_skip_fmv == 0);

    /* Unrelated PSX Display capabilities remain available. */
    assert(game.has_renderer == 1);
    assert(game.has_supersampling == 1);
    assert(game.has_screen_kind == 1);

    return 0;
}
