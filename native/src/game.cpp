#include "tekken3_native/game.hpp"

#include <algorithm>
#include <cmath>

namespace tekken3::native {

namespace {
constexpr float kMoveSpeed = 4.6f;
constexpr float kGravity = 19.0f;
constexpr float kJumpSpeed = 7.2f;
constexpr float kStageLimit = 11.0f;
constexpr float kMinimumSeparation = 0.72f;
}

NativeGame::NativeGame(bool enable_cpu_opponent)
    : cpu_opponent_(enable_cpu_opponent) {
    reset_round();
}

void NativeGame::reset_round() {
    const unsigned round = state_.round_number;
    state_ = MatchState{};
    state_.round_number = round;
    state_.fighters[0].x = -2.4f;
    state_.fighters[1].x = 2.4f;
    state_.fighters[0].facing = 1;
    state_.fighters[1].facing = -1;
    state_.camera.reset();
    previous_jump_ = false;
}

void NativeGame::begin_attack(FighterState& fighter, AttackKind kind) {
    if (fighter.attack != AttackKind::none || state_.round_over) {
        return;
    }
    fighter.attack = kind;
    fighter.attack_age = 0.0f;
    fighter.attack_duration = kind == AttackKind::heavy ? 0.52f : 0.34f;
    fighter.attack_connected = false;
}

void NativeGame::update_fighter(FighterState& fighter, float dt,
                                float move_axis, bool jump) {
    const float attack_slowdown = fighter.attack == AttackKind::none ? 1.0f : 0.28f;
    fighter.x += std::clamp(move_axis, -1.0f, 1.0f) * kMoveSpeed * attack_slowdown * dt;
    fighter.x = std::clamp(fighter.x, -kStageLimit, kStageLimit);

    if (jump && fighter.y <= 0.001f) {
        fighter.vertical_velocity = kJumpSpeed;
    }
    fighter.vertical_velocity -= kGravity * dt;
    fighter.y += fighter.vertical_velocity * dt;
    if (fighter.y < 0.0f) {
        fighter.y = 0.0f;
        fighter.vertical_velocity = 0.0f;
    }

    fighter.hit_flash = std::max(0.0f, fighter.hit_flash - dt);
    if (fighter.attack != AttackKind::none) {
        fighter.attack_age += dt;
        if (fighter.attack_age >= fighter.attack_duration) {
            fighter.attack = AttackKind::none;
            fighter.attack_age = 0.0f;
            fighter.attack_duration = 0.0f;
            fighter.attack_connected = false;
        }
    }
}

void NativeGame::resolve_attack(FighterState& attacker, FighterState& defender) {
    if (attacker.attack == AttackKind::none || attacker.attack_connected) {
        return;
    }
    const bool heavy = attacker.attack == AttackKind::heavy;
    const float active_start = heavy ? 0.18f : 0.09f;
    const float active_end = heavy ? 0.31f : 0.19f;
    if (attacker.attack_age < active_start || attacker.attack_age > active_end) {
        return;
    }
    const float reach = heavy ? 1.78f : 1.48f;
    const bool correct_side = (defender.x - attacker.x) * attacker.facing >= 0.0f;
    if (correct_side && std::abs(defender.x - attacker.x) <= reach && defender.y < 1.3f) {
        defender.health = std::max(0.0f, defender.health - (heavy ? 15.0f : 8.0f));
        defender.hit_flash = 0.14f;
        defender.x += static_cast<float>(attacker.facing) * (heavy ? 0.48f : 0.24f);
        attacker.attack_connected = true;
    }
}

void NativeGame::step(float dt, const InputFrame& input) {
    dt = std::clamp(dt, 0.0f, 1.0f / 20.0f);
    if (input.restart) {
        reset_round();
        return;
    }

    if (state_.round_over) {
        state_.end_delay += dt;
        if (state_.end_delay >= 2.2f) {
            ++state_.round_number;
            reset_round();
        }
        state_.camera.update(state_.fighters[0].x, state_.fighters[1].x, dt);
        return;
    }

    FighterState& player = state_.fighters[0];
    FighterState& opponent = state_.fighters[1];
    const float distance = opponent.x - player.x;
    const float cpu_move = cpu_opponent_ && std::abs(distance) > 2.2f
        ? (distance > 0.0f ? -0.58f : 0.58f) : 0.0f;

    const bool jump_edge = input.jump && !previous_jump_;
    previous_jump_ = input.jump;
    update_fighter(player, dt, input.move_axis, jump_edge);
    update_fighter(opponent, dt, cpu_move, false);

    if (input.heavy_attack) {
        begin_attack(player, AttackKind::heavy);
    } else if (input.light_attack) {
        begin_attack(player, AttackKind::light);
    }
    if (cpu_opponent_ && std::abs(distance) < 1.55f && opponent.attack == AttackKind::none) {
        begin_attack(opponent, AttackKind::light);
    }

    // Keep the fighters ordered on the classic one-dimensional combat line.
    if (player.x > opponent.x - kMinimumSeparation) {
        const float midpoint = (player.x + opponent.x) * 0.5f;
        player.x = midpoint - kMinimumSeparation * 0.5f;
        opponent.x = midpoint + kMinimumSeparation * 0.5f;
    }
    player.facing = player.x <= opponent.x ? 1 : -1;
    opponent.facing = -player.facing;

    resolve_attack(player, opponent);
    resolve_attack(opponent, player);

    state_.round_time = std::max(0.0f, state_.round_time - dt);
    state_.round_over = state_.round_time <= 0.0f ||
                        player.health <= 0.0f || opponent.health <= 0.0f;
    state_.camera.update(player.x, opponent.x, dt);
}

}  // namespace tekken3::native
