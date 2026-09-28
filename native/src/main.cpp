#include "tekken3_native/disc.hpp"
#include "tekken3_native/game.hpp"
#include "tekken3_native/renderer.hpp"

#include <SDL3/SDL.h>
#include <SDL3/SDL_main.h>

#include <algorithm>
#include <chrono>
#include <filesystem>
#include <iostream>
#include <string>

namespace fs = std::filesystem;
using tekken3::native::DiscReport;
using tekken3::native::InputFrame;
using tekken3::native::NativeGame;
using tekken3::native::Renderer;

namespace {

struct Options {
    fs::path disc;
    fs::path capture;
    int frames = 150;
    int width = 1280;
    int height = 720;
    bool self_test = false;
    bool no_disc = false;
    bool help = false;
};

bool parse_integer(const char* text, int& output) {
    try {
        const int value = std::stoi(text);
        if (value <= 0) return false;
        output = value;
        return true;
    } catch (...) {
        return false;
    }
}

bool parse_options(int argc, char** argv, Options& options) {
    for (int i = 1; i < argc; ++i) {
        const std::string argument = argv[i];
        auto next = [&](const char* name) -> const char* {
            if (i + 1 >= argc) {
                std::cerr << name << " requires a value\n";
                return nullptr;
            }
            return argv[++i];
        };
        if (argument == "--disc") {
            const char* value = next("--disc");
            if (!value) return false;
            options.disc = fs::u8path(value);
        } else if (argument == "--capture") {
            const char* value = next("--capture");
            if (!value) return false;
            options.capture = fs::u8path(value);
        } else if (argument == "--frames") {
            const char* value = next("--frames");
            if (!value || !parse_integer(value, options.frames)) return false;
        } else if (argument == "--width") {
            const char* value = next("--width");
            if (!value || !parse_integer(value, options.width)) return false;
        } else if (argument == "--height") {
            const char* value = next("--height");
            if (!value || !parse_integer(value, options.height)) return false;
        } else if (argument == "--self-test") {
            options.self_test = true;
        } else if (argument == "--no-disc") {
            options.no_disc = true;
        } else if (argument == "--help" || argument == "-h") {
            options.help = true;
        } else {
            std::cerr << "Unknown option: " << argument << '\n';
            return false;
        }
    }
    return true;
}

void print_help() {
    std::cout
        << "Tekken 3 PC Port - native vertical slice\n\n"
        << "  --disc <cue/bin/chd>  legally owned Tekken 3 USA disc\n"
        << "  --capture <png>       render a deterministic frame and exit\n"
        << "  --frames <count>      simulation frames before capture\n"
        << "  --width/--height      output dimensions (default 1280x720)\n"
        << "  --self-test           verify native simulation and disc boundary\n"
        << "  --no-disc             developer-only procedural slice\n\n"
        << "Controls: A/D move, W or Space jump, J/K attack, R reset, "
           "F11 fullscreen, Esc quit.\n";
}

fs::path default_disc_path() {
    const fs::path candidate = fs::current_path() / "disc" / "Tekken 3 (USA).cue";
    return fs::exists(candidate) ? candidate : fs::path{};
}

int run_self_test() {
    NativeGame game(false);
    InputFrame input{};
    input.move_axis = 1.0f;
    for (int frame = 0; frame < 60; ++frame) {
        game.step(1.0f / 60.0f, input);
    }
    const auto widescreen = game.state().camera.frame(1920, 1080);
    const auto classic = game.state().camera.frame(640, 480);
    if (game.state().fighters[0].x <= -2.0f ||
        widescreen.horizontal_fov <= classic.horizontal_fov) {
        std::cerr << "Native simulation/camera self-test failed\n";
        return 1;
    }
    std::cout << "Native simulation and true-aspect camera: OK\n";
    return 0;
}

}  // namespace

int main(int argc, char** argv) {
    Options options{};
    if (!parse_options(argc, argv, options)) {
        print_help();
        return 2;
    }
    if (options.help) {
        print_help();
        return 0;
    }

    if (options.disc.empty() && !options.no_disc) options.disc = default_disc_path();
    if (!options.no_disc) {
        if (options.disc.empty()) {
            std::cerr << "No disc supplied. Use --disc with a legally owned "
                         "Tekken 3 (USA) CUE/BIN/CHD.\n";
            return 3;
        }
        const DiscReport report = tekken3::native::inspect_disc(options.disc);
        if (!report.ok) {
            std::cerr << "Disc rejected: " << report.detail << '\n';
            return 3;
        }
        std::cout << "Disc verified: " << report.volume_id << " ("
                  << report.track_count << " tracks)\n";
    }

    if (options.self_test) return run_self_test();

    SDL_SetMainReady();
    if (!SDL_Init(SDL_INIT_VIDEO | SDL_INIT_GAMEPAD)) {
        std::cerr << "SDL initialization failed: " << SDL_GetError() << '\n';
        return 4;
    }

    SDL_GL_SetAttribute(SDL_GL_CONTEXT_MAJOR_VERSION, 3);
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_MINOR_VERSION, 3);
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_PROFILE_MASK, SDL_GL_CONTEXT_PROFILE_CORE);
    SDL_GL_SetAttribute(SDL_GL_DOUBLEBUFFER, 1);
    SDL_GL_SetAttribute(SDL_GL_DEPTH_SIZE, 24);
    SDL_GL_SetAttribute(SDL_GL_STENCIL_SIZE, 8);

    SDL_WindowFlags flags = SDL_WINDOW_OPENGL | SDL_WINDOW_RESIZABLE |
                            SDL_WINDOW_HIGH_PIXEL_DENSITY;
    if (!options.capture.empty()) flags |= SDL_WINDOW_HIDDEN;
    SDL_Window* window = SDL_CreateWindow("Tekken 3 PC Port - Native Slice",
                                           options.width, options.height, flags);
    if (!window) {
        std::cerr << "Window creation failed: " << SDL_GetError() << '\n';
        SDL_Quit();
        return 4;
    }
    SDL_SetWindowMinimumSize(window, 640, 360);

    SDL_GLContext context = SDL_GL_CreateContext(window);
    if (!context || !SDL_GL_MakeCurrent(window, context)) {
        std::cerr << "OpenGL context creation failed: " << SDL_GetError() << '\n';
        if (context) SDL_GL_DestroyContext(context);
        SDL_DestroyWindow(window);
        SDL_Quit();
        return 4;
    }
    SDL_GL_SetSwapInterval(options.capture.empty() ? 1 : 0);

    Renderer renderer;
    if (!renderer.initialize()) {
        std::cerr << "Renderer initialization failed: " << renderer.error() << '\n';
        SDL_GL_DestroyContext(context);
        SDL_DestroyWindow(window);
        SDL_Quit();
        return 5;
    }

    NativeGame game(true);
    constexpr float fixed_step = 1.0f / 60.0f;
    bool running = true;
    bool fullscreen = false;
    int rendered_frames = 0;
    float accumulator = 0.0f;
    auto previous_time = std::chrono::steady_clock::now();

    while (running) {
        SDL_Event event{};
        while (SDL_PollEvent(&event)) {
            if (event.type == SDL_EVENT_QUIT) {
                running = false;
            } else if (event.type == SDL_EVENT_KEY_DOWN && !event.key.repeat) {
                if (event.key.key == SDLK_ESCAPE) {
                    running = false;
                } else if (event.key.key == SDLK_F11) {
                    fullscreen = !fullscreen;
                    SDL_SetWindowFullscreen(window, fullscreen);
                } else if (event.key.key == SDLK_R) {
                    InputFrame restart{};
                    restart.restart = true;
                    game.step(fixed_step, restart);
                }
            }
        }

        InputFrame input{};
        if (options.capture.empty()) {
            const bool* keys = SDL_GetKeyboardState(nullptr);
            input.move_axis = (keys[SDL_SCANCODE_D] ? 1.0f : 0.0f) -
                              (keys[SDL_SCANCODE_A] ? 1.0f : 0.0f);
            input.jump = keys[SDL_SCANCODE_W] || keys[SDL_SCANCODE_SPACE];
            input.light_attack = keys[SDL_SCANCODE_J];
            input.heavy_attack = keys[SDL_SCANCODE_K];

            const auto now = std::chrono::steady_clock::now();
            accumulator += std::min(
                std::chrono::duration<float>(now - previous_time).count(), 0.2f);
            previous_time = now;
            while (accumulator >= fixed_step) {
                game.step(fixed_step, input);
                accumulator -= fixed_step;
            }
        } else {
            input.move_axis = rendered_frames < 38 ? 1.0f : 0.0f;
            input.light_attack = rendered_frames >= 62 && rendered_frames < 82;
            game.step(fixed_step, input);
        }

        int pixel_width = 0;
        int pixel_height = 0;
        SDL_GetWindowSizeInPixels(window, &pixel_width, &pixel_height);
        renderer.render(game.state(), pixel_width, pixel_height);

        ++rendered_frames;
        if (!options.capture.empty() && rendered_frames >= options.frames) {
            const fs::path parent = options.capture.parent_path();
            if (!parent.empty()) fs::create_directories(parent);
            if (!renderer.capture_png(options.capture.u8string(), pixel_width, pixel_height)) {
                std::cerr << "Capture failed: " << renderer.error() << '\n';
                running = false;
                rendered_frames = -1;
            } else {
                std::cout << "Captured native frame: " << options.capture.u8string() << '\n';
                running = false;
            }
        } else {
            SDL_GL_SwapWindow(window);
        }
    }

    renderer.shutdown();
    SDL_GL_DestroyContext(context);
    SDL_DestroyWindow(window);
    SDL_Quit();
    return rendered_frames < 0 ? 6 : 0;
}
