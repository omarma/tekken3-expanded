#include "tekken3_native/game.hpp"

#include <cmath>
#include <iostream>

namespace {

int failures = 0;

void check(bool condition, const char* label) {
    if (!condition) {
        std::cerr << "FAIL: " << label << '\n';
        ++failures;
    }
}

}  // namespace

int main() {
    using namespace tekken3::native;

    CameraRig camera;
    const CameraFrame four_three = camera.frame(640, 480);
    const CameraFrame widescreen = camera.frame(1280, 720);
    check(std::abs(four_three.projection.v[5] - widescreen.projection.v[5]) < 0.0001f,
          "vertical field of view is invariant");
    check(widescreen.horizontal_fov > four_three.horizontal_fov,
          "16:9 reveals more horizontal world than 4:3");
    check(widescreen.projection.v[0] < four_three.projection.v[0],
          "projection expands horizontally at wide aspect ratios");

    NativeGame game(false);
    InputFrame move{};
    move.move_axis = 1.0f;
    for (int i = 0; i < 43; ++i) {
        game.step(1.0f / 60.0f, move);
    }
    const float moved_x = game.state().fighters[0].x;
    check(moved_x > -0.1f, "native player movement advances simulation");

    InputFrame attack{};
    attack.heavy_attack = true;
    for (int i = 0; i < 35; ++i) {
        game.step(1.0f / 60.0f, attack);
    }
    check(game.state().fighters[1].health < 100.0f,
          "native hit detection applies attack damage");
    check(game.state().round_time < 60.0f, "fixed-step match timer advances");

    if (failures != 0) {
        return 1;
    }
    std::cout << "native core: all checks passed\n";
    return 0;
}
