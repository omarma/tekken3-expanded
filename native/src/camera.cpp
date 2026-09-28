#include "tekken3_native/camera.hpp"

#include <algorithm>
#include <cmath>

namespace tekken3::native {

void CameraRig::reset(float center_x) {
    center_x_ = center_x;
    fighter_span_ = 5.0f;
}

void CameraRig::update(float player_one_x, float player_two_x, float dt) {
    const float desired_center = (player_one_x + player_two_x) * 0.5f;
    const float desired_span = std::max(std::abs(player_two_x - player_one_x), 4.5f);
    const float smoothing = 1.0f - std::exp(-std::max(dt, 0.0f) * 7.5f);
    center_x_ += (desired_center - center_x_) * smoothing;
    fighter_span_ += (desired_span - fighter_span_) * smoothing;
}

CameraFrame CameraRig::frame(int pixel_width, int pixel_height) const {
    CameraFrame result{};
    result.aspect = static_cast<float>(std::max(pixel_width, 1)) /
                    static_cast<float>(std::max(pixel_height, 1));
    result.horizontal_fov = 2.0f * std::atan(
        std::tan(result.vertical_fov * 0.5f) * result.aspect);

    // The vertical field of view is invariant. Widescreen therefore reveals
    // more world horizontally instead of stretching or cropping a 4:3 image.
    const float fit_distance = (fighter_span_ + 3.0f) /
        (2.0f * std::tan(result.horizontal_fov * 0.5f));
    const float distance = std::max(10.5f, fit_distance);
    result.target = {center_x_, 1.75f, 0.0f};
    result.eye = {center_x_, 4.4f, distance};
    result.view = look_at(result.eye, result.target, {0.0f, 1.0f, 0.0f});
    result.projection = perspective(result.vertical_fov, result.aspect, 0.1f, 120.0f);
    return result;
}

}  // namespace tekken3::native
