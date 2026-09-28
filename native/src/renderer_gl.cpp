#include "tekken3_native/renderer.hpp"

#include "gl_core_3_1.h"

#define STBIW_WINDOWS_UTF8
#define STB_IMAGE_WRITE_STATIC
#define STB_IMAGE_WRITE_IMPLEMENTATION
#include "stb_image_write.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <limits>
#include <sstream>
#include <string>
#include <system_error>
#include <utility>
#include <vector>

namespace tekken3::native {
namespace {

struct Vertex {
    float position[3];
    float normal[3];
};

constexpr std::array<Vertex, 24> kCubeVertices{{
    // +Z
    {{-0.5f, -0.5f,  0.5f}, { 0.0f,  0.0f,  1.0f}},
    {{ 0.5f, -0.5f,  0.5f}, { 0.0f,  0.0f,  1.0f}},
    {{ 0.5f,  0.5f,  0.5f}, { 0.0f,  0.0f,  1.0f}},
    {{-0.5f,  0.5f,  0.5f}, { 0.0f,  0.0f,  1.0f}},
    // -Z
    {{ 0.5f, -0.5f, -0.5f}, { 0.0f,  0.0f, -1.0f}},
    {{-0.5f, -0.5f, -0.5f}, { 0.0f,  0.0f, -1.0f}},
    {{-0.5f,  0.5f, -0.5f}, { 0.0f,  0.0f, -1.0f}},
    {{ 0.5f,  0.5f, -0.5f}, { 0.0f,  0.0f, -1.0f}},
    // +X
    {{ 0.5f, -0.5f,  0.5f}, { 1.0f,  0.0f,  0.0f}},
    {{ 0.5f, -0.5f, -0.5f}, { 1.0f,  0.0f,  0.0f}},
    {{ 0.5f,  0.5f, -0.5f}, { 1.0f,  0.0f,  0.0f}},
    {{ 0.5f,  0.5f,  0.5f}, { 1.0f,  0.0f,  0.0f}},
    // -X
    {{-0.5f, -0.5f, -0.5f}, {-1.0f,  0.0f,  0.0f}},
    {{-0.5f, -0.5f,  0.5f}, {-1.0f,  0.0f,  0.0f}},
    {{-0.5f,  0.5f,  0.5f}, {-1.0f,  0.0f,  0.0f}},
    {{-0.5f,  0.5f, -0.5f}, {-1.0f,  0.0f,  0.0f}},
    // +Y
    {{-0.5f,  0.5f,  0.5f}, { 0.0f,  1.0f,  0.0f}},
    {{ 0.5f,  0.5f,  0.5f}, { 0.0f,  1.0f,  0.0f}},
    {{ 0.5f,  0.5f, -0.5f}, { 0.0f,  1.0f,  0.0f}},
    {{-0.5f,  0.5f, -0.5f}, { 0.0f,  1.0f,  0.0f}},
    // -Y
    {{-0.5f, -0.5f, -0.5f}, { 0.0f, -1.0f,  0.0f}},
    {{ 0.5f, -0.5f, -0.5f}, { 0.0f, -1.0f,  0.0f}},
    {{ 0.5f, -0.5f,  0.5f}, { 0.0f, -1.0f,  0.0f}},
    {{-0.5f, -0.5f,  0.5f}, { 0.0f, -1.0f,  0.0f}},
}};

constexpr std::array<std::uint16_t, 36> kCubeIndices{{
     0,  1,  2,  2,  3,  0,
     4,  5,  6,  6,  7,  4,
     8,  9, 10, 10, 11,  8,
    12, 13, 14, 14, 15, 12,
    16, 17, 18, 18, 19, 16,
    20, 21, 22, 22, 23, 20,
}};

constexpr const char* kVertexShader = R"GLSL(
#version 140
in vec3 a_position;
in vec3 a_normal;

uniform mat4 u_mvp;
uniform mat4 u_model;

out vec3 v_world_position;
out vec3 v_normal;

void main() {
    vec4 world_position = u_model * vec4(a_position, 1.0);
    v_world_position = world_position.xyz;
    v_normal = normalize(mat3(u_model) * a_normal);
    gl_Position = u_mvp * vec4(a_position, 1.0);
}
)GLSL";

constexpr const char* kFragmentShader = R"GLSL(
#version 140
in vec3 v_world_position;
in vec3 v_normal;

uniform vec4 u_color;
uniform int u_lit;

out vec4 fragment_color;

void main() {
    vec3 color = u_color.rgb;
    if (u_lit != 0) {
        vec3 light_direction = normalize(vec3(-0.35, 0.82, 0.46));
        float diffuse = max(dot(normalize(v_normal), light_direction), 0.0);
        float light = 0.34 + diffuse * 0.66;
        float floor_glow = clamp(1.0 - abs(v_world_position.y) * 0.12, 0.0, 1.0);
        color = color * light + color * floor_glow * 0.055;
        float distance_fog = clamp((-v_world_position.z - 8.0) / 42.0, 0.0, 0.30);
        color = mix(color, vec3(0.035, 0.055, 0.095), distance_fog);
    }
    fragment_color = vec4(color, u_color.a);
}
)GLSL";

Mat4 rotation_z(float radians) {
    Mat4 result = Mat4::identity();
    const float cosine = std::cos(radians);
    const float sine = std::sin(radians);
    result.v[0] = cosine;
    result.v[1] = sine;
    result.v[4] = -sine;
    result.v[5] = cosine;
    return result;
}

Mat4 box_model(Vec3 center, Vec3 size, float yaw = 0.0f, float roll = 0.0f) {
    return translation(center) * rotation_y(yaw) * rotation_z(roll) * scale(size);
}

std::string shader_log(GLuint shader) {
    GLint length = 0;
    glGetShaderiv(shader, GL_INFO_LOG_LENGTH, &length);
    if (length <= 1) {
        return {};
    }
    std::vector<GLchar> buffer(static_cast<std::size_t>(length), '\0');
    GLsizei written = 0;
    glGetShaderInfoLog(shader, length, &written, buffer.data());
    return std::string(buffer.data(), static_cast<std::size_t>(std::max<GLsizei>(written, 0)));
}

std::string program_log(GLuint program) {
    GLint length = 0;
    glGetProgramiv(program, GL_INFO_LOG_LENGTH, &length);
    if (length <= 1) {
        return {};
    }
    std::vector<GLchar> buffer(static_cast<std::size_t>(length), '\0');
    GLsizei written = 0;
    glGetProgramInfoLog(program, length, &written, buffer.data());
    return std::string(buffer.data(), static_cast<std::size_t>(std::max<GLsizei>(written, 0)));
}

GLuint compile_shader(GLenum type, const char* source, std::string& failure) {
    const GLuint shader = glCreateShader(type);
    if (shader == 0) {
        failure = "OpenGL failed to create a shader object";
        return 0;
    }
    glShaderSource(shader, 1, &source, nullptr);
    glCompileShader(shader);
    GLint compiled = GL_FALSE;
    glGetShaderiv(shader, GL_COMPILE_STATUS, &compiled);
    if (compiled == GL_TRUE) {
        return shader;
    }
    failure = shader_log(shader);
    if (failure.empty()) {
        failure = "OpenGL shader compilation failed without an information log";
    }
    glDeleteShader(shader);
    return 0;
}

std::string gl_error_message(const char* operation, GLenum code) {
    std::ostringstream stream;
    stream << operation << " failed with OpenGL error 0x" << std::hex
           << static_cast<unsigned int>(code);
    return stream.str();
}

float attack_extension(const FighterState& fighter) {
    if (fighter.attack == AttackKind::none || fighter.attack_duration <= 0.0f) {
        return 0.0f;
    }
    const float phase = std::clamp(fighter.attack_age / fighter.attack_duration, 0.0f, 1.0f);
    return std::sin(phase * kPi);
}

}  // namespace

void RendererGL::set_error(std::string message) {
    error_ = std::move(message);
}

bool RendererGL::initialize() {
    if (initialized_) {
        return true;
    }
    error_.clear();

    if (ogl_LoadFunctions() == ogl_LOAD_FAILED) {
        set_error("Unable to load OpenGL functions; initialize() requires a current OpenGL context");
        return false;
    }
    if (!ogl_IsVersionGEQ(3, 1)) {
        std::ostringstream stream;
        stream << "OpenGL 3.1 or newer is required (context reports "
               << ogl_GetMajorVersion() << '.' << ogl_GetMinorVersion() << ')';
        set_error(stream.str());
        return false;
    }

    if (!glCreateShader || !glShaderSource || !glCompileShader ||
        !glCreateProgram || !glLinkProgram || !glGenVertexArrays ||
        !glGenBuffers || !glBufferData || !glVertexAttribPointer ||
        !glUniformMatrix4fv || !glDrawElements || !glReadPixels) {
        set_error("The OpenGL 3.1 loader did not provide all renderer entry points");
        return false;
    }

    std::string failure;
    const GLuint vertex_shader = compile_shader(GL_VERTEX_SHADER, kVertexShader, failure);
    if (vertex_shader == 0) {
        set_error("Vertex shader: " + failure);
        return false;
    }
    const GLuint fragment_shader = compile_shader(GL_FRAGMENT_SHADER, kFragmentShader, failure);
    if (fragment_shader == 0) {
        glDeleteShader(vertex_shader);
        set_error("Fragment shader: " + failure);
        return false;
    }

    program_ = glCreateProgram();
    if (program_ == 0) {
        glDeleteShader(fragment_shader);
        glDeleteShader(vertex_shader);
        set_error("OpenGL failed to create the renderer program");
        return false;
    }
    glAttachShader(program_, vertex_shader);
    glAttachShader(program_, fragment_shader);
    glLinkProgram(program_);
    glDeleteShader(fragment_shader);
    glDeleteShader(vertex_shader);

    GLint linked = GL_FALSE;
    glGetProgramiv(program_, GL_LINK_STATUS, &linked);
    if (linked != GL_TRUE) {
        failure = program_log(program_);
        glDeleteProgram(program_);
        program_ = 0;
        set_error("Shader link: " + (failure.empty() ? std::string("unknown failure") : failure));
        return false;
    }

    position_attribute_ = glGetAttribLocation(program_, "a_position");
    normal_attribute_ = glGetAttribLocation(program_, "a_normal");
    mvp_uniform_ = glGetUniformLocation(program_, "u_mvp");
    model_uniform_ = glGetUniformLocation(program_, "u_model");
    color_uniform_ = glGetUniformLocation(program_, "u_color");
    lit_uniform_ = glGetUniformLocation(program_, "u_lit");
    if (position_attribute_ < 0 || normal_attribute_ < 0 || mvp_uniform_ < 0 ||
        model_uniform_ < 0 || color_uniform_ < 0 || lit_uniform_ < 0) {
        glDeleteProgram(program_);
        program_ = 0;
        set_error("The renderer shader is missing a required attribute or uniform");
        return false;
    }

    glGenVertexArrays(1, &vertex_array_);
    glBindVertexArray(vertex_array_);
    glGenBuffers(1, &vertex_buffer_);
    glBindBuffer(GL_ARRAY_BUFFER, vertex_buffer_);
    glBufferData(GL_ARRAY_BUFFER, static_cast<GLsizeiptr>(sizeof(kCubeVertices)),
                 kCubeVertices.data(), GL_STATIC_DRAW);
    glGenBuffers(1, &index_buffer_);
    glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, index_buffer_);
    glBufferData(GL_ELEMENT_ARRAY_BUFFER, static_cast<GLsizeiptr>(sizeof(kCubeIndices)),
                 kCubeIndices.data(), GL_STATIC_DRAW);

    glEnableVertexAttribArray(static_cast<GLuint>(position_attribute_));
    glVertexAttribPointer(static_cast<GLuint>(position_attribute_), 3, GL_FLOAT,
                          GL_FALSE, static_cast<GLsizei>(sizeof(Vertex)),
                          reinterpret_cast<const void*>(offsetof(Vertex, position)));
    glEnableVertexAttribArray(static_cast<GLuint>(normal_attribute_));
    glVertexAttribPointer(static_cast<GLuint>(normal_attribute_), 3, GL_FLOAT,
                          GL_FALSE, static_cast<GLsizei>(sizeof(Vertex)),
                          reinterpret_cast<const void*>(offsetof(Vertex, normal)));
    glBindVertexArray(0);

    index_count_ = static_cast<int>(kCubeIndices.size());
    if (vertex_array_ == 0 || vertex_buffer_ == 0 || index_buffer_ == 0) {
        shutdown();
        set_error("OpenGL failed to allocate the cube mesh");
        return false;
    }

    const GLenum gl_error = glGetError();
    if (gl_error != GL_NO_ERROR) {
        shutdown();
        set_error(gl_error_message("Renderer initialization", gl_error));
        return false;
    }

    initialized_ = true;
    return true;
}

void RendererGL::shutdown() {
    if (vertex_array_ != 0 && glDeleteVertexArrays) {
        glDeleteVertexArrays(1, &vertex_array_);
    }
    if (vertex_buffer_ != 0 && glDeleteBuffers) {
        glDeleteBuffers(1, &vertex_buffer_);
    }
    if (index_buffer_ != 0 && glDeleteBuffers) {
        glDeleteBuffers(1, &index_buffer_);
    }
    if (program_ != 0 && glDeleteProgram) {
        glDeleteProgram(program_);
    }

    program_ = 0;
    vertex_array_ = 0;
    vertex_buffer_ = 0;
    index_buffer_ = 0;
    index_count_ = 0;
    position_attribute_ = -1;
    normal_attribute_ = -1;
    mvp_uniform_ = -1;
    model_uniform_ = -1;
    color_uniform_ = -1;
    lit_uniform_ = -1;
    initialized_ = false;
}

void RendererGL::draw_box(const Mat4& view_projection, const Mat4& model,
                          float red, float green, float blue, float alpha,
                          bool lit) {
    const Mat4 mvp = view_projection * model;
    glUniformMatrix4fv(mvp_uniform_, 1, GL_FALSE, mvp.v);
    glUniformMatrix4fv(model_uniform_, 1, GL_FALSE, model.v);
    glUniform4f(color_uniform_, red, green, blue, alpha);
    glUniform1i(lit_uniform_, lit ? 1 : 0);
    glDrawElements(GL_TRIANGLES, index_count_, GL_UNSIGNED_SHORT, nullptr);
}

void RendererGL::draw_stage(const CameraFrame& camera) {
    const Mat4 view_projection = camera.projection * camera.view;

    // The far wall and clear color are deliberately wider than the playable
    // space. A 16:9 projection reveals authored world on both sides; no 4:3
    // framebuffer is stretched or sampled to produce the backdrop.
    draw_box(view_projection, box_model({0.0f, 5.0f, -12.5f}, {72.0f, 13.0f, 0.8f}),
             0.025f, 0.034f, 0.072f, 1.0f, false);
    draw_box(view_projection, box_model({0.0f, 1.2f, -11.8f}, {56.0f, 2.1f, 0.6f}),
             0.075f, 0.095f, 0.145f, 1.0f, true);

    draw_box(view_projection, box_model({0.0f, -0.34f, 1.0f}, {48.0f, 0.68f, 30.0f}),
             0.045f, 0.095f, 0.100f, 1.0f, true);
    draw_box(view_projection, box_model({0.0f, -0.02f, -5.7f}, {48.0f, 0.08f, 0.22f}),
             0.12f, 0.34f, 0.34f, 1.0f, false);
    draw_box(view_projection, box_model({0.0f, -0.02f, 5.7f}, {48.0f, 0.08f, 0.22f}),
             0.08f, 0.22f, 0.23f, 1.0f, false);

    // Industrial bridge, towers, supports, and luminous ventilation bands.
    draw_box(view_projection, box_model({0.0f, 3.25f, -9.4f}, {39.0f, 0.48f, 1.5f}),
             0.14f, 0.17f, 0.25f, 1.0f, true);
    draw_box(view_projection, box_model({0.0f, 1.8f, -10.25f}, {17.5f, 3.0f, 1.05f}),
             0.08f, 0.09f, 0.14f, 1.0f, true);
    for (int band = 0; band < 4; ++band) {
        draw_box(view_projection,
                 box_model({0.0f, 1.05f + static_cast<float>(band) * 0.48f, -9.65f},
                           {9.7f, 0.17f, 0.12f}),
                 0.12f, 0.45f, 0.52f, 1.0f, false);
    }

    for (int side : {-1, 1}) {
        const float x = static_cast<float>(side) * 16.0f;
        draw_box(view_projection, box_model({x, 3.25f, -10.4f}, {5.8f, 7.0f, 2.8f}),
                 0.075f, 0.085f, 0.135f, 1.0f, true);
        draw_box(view_projection, box_model({x, 6.7f, -10.4f}, {6.7f, 0.35f, 3.3f}),
                 0.16f, 0.18f, 0.28f, 1.0f, true);
        draw_box(view_projection, box_model({x, 4.7f, -8.9f}, {3.1f, 1.2f, 0.14f}),
                 0.62f, 0.53f, 0.28f, 1.0f, false);
    }

    for (int support = -5; support <= 5; ++support) {
        const float x = static_cast<float>(support) * 3.2f;
        draw_box(view_projection, box_model({x, 1.55f, -9.25f}, {0.20f, 3.1f, 0.22f}),
                 0.19f, 0.21f, 0.29f, 1.0f, true);
    }

    for (int lamp = -3; lamp <= 3; ++lamp) {
        const float x = static_cast<float>(lamp) * 5.1f;
        draw_box(view_projection, box_model({x, 4.15f, -8.7f}, {0.10f, 1.65f, 0.10f}),
                 0.25f, 0.25f, 0.30f, 1.0f, true);
        draw_box(view_projection, box_model({x, 5.0f, -8.7f}, {0.78f, 0.19f, 0.24f}),
                 0.90f, 0.76f, 0.36f, 1.0f, false);
    }

    // Floor grid extends beyond the widest camera framing at either stage edge.
    for (int line = -12; line <= 12; ++line) {
        const float x = static_cast<float>(line) * 1.8f;
        draw_box(view_projection, box_model({x, 0.012f, 1.0f}, {0.025f, 0.025f, 28.0f}),
                 0.075f, 0.19f, 0.19f, 1.0f, false);
    }
    for (int line = -14; line <= 16; ++line) {
        const float z = static_cast<float>(line) * 0.88f;
        draw_box(view_projection, box_model({0.0f, 0.013f, z}, {44.0f, 0.026f, 0.025f}),
                 0.075f, 0.18f, 0.18f, 1.0f, false);
    }
}

void RendererGL::draw_fighter(const CameraFrame& camera,
                              const FighterState& fighter,
                              int fighter_index) {
    const Mat4 view_projection = camera.projection * camera.view;
    const float facing = fighter.facing < 0 ? -1.0f : 1.0f;
    const float extension = attack_extension(fighter);
    const float x = fighter.x;
    const float base_y = fighter.y;

    std::array<float, 3> primary = fighter_index == 0
        ? std::array<float, 3>{{0.08f, 0.24f, 0.68f}}
        : std::array<float, 3>{{0.48f, 0.07f, 0.16f}};
    const std::array<float, 3> accent = fighter_index == 0
        ? std::array<float, 3>{{0.92f, 0.72f, 0.12f}}
        : std::array<float, 3>{{0.72f, 0.52f, 0.64f}};
    if (fighter.hit_flash > 0.0f) {
        primary = {{1.0f, 0.86f, 0.72f}};
    }

    draw_box(view_projection, box_model({x, base_y + 1.47f, 0.0f}, {0.78f, 1.20f, 0.52f}),
             primary[0], primary[1], primary[2], 1.0f, true);
    draw_box(view_projection, box_model({x, base_y + 0.82f, 0.0f}, {0.86f, 0.34f, 0.58f}),
             accent[0], accent[1], accent[2], 1.0f, true);
    draw_box(view_projection, box_model({x, base_y + 2.30f, 0.0f}, {0.58f, 0.58f, 0.58f}),
             0.78f, 0.57f, 0.43f, 1.0f, true);
    draw_box(view_projection, box_model({x, base_y + 2.55f, 0.0f}, {0.63f, 0.16f, 0.63f}),
             0.10f, 0.075f, 0.08f, 1.0f, true);

    for (int side : {-1, 1}) {
        const float leg_x = x + static_cast<float>(side) * 0.23f;
        const float step = extension * 0.12f * static_cast<float>(side);
        draw_box(view_projection,
                 box_model({leg_x + step, base_y + 0.36f, 0.0f}, {0.27f, 0.72f, 0.31f},
                           0.0f, -step * 0.9f),
                 0.08f, 0.075f, 0.10f, 1.0f, true);
        draw_box(view_projection,
                 box_model({leg_x + step + facing * 0.08f, base_y + 0.08f, 0.08f},
                           {0.36f, 0.17f, 0.65f}),
                 accent[0] * 0.55f, accent[1] * 0.55f, accent[2] * 0.55f,
                 1.0f, true);
    }

    const float attack_reach = extension *
        (fighter.attack == AttackKind::heavy ? 0.92f : 0.62f);
    const float lead_center = x + facing * (0.53f + attack_reach * 0.5f);
    const float lead_width = 0.54f + attack_reach;
    draw_box(view_projection,
             box_model({lead_center, base_y + 1.72f + extension * 0.16f, 0.02f},
                       {lead_width, 0.24f, 0.28f}, 0.0f,
                       facing * (0.16f - extension * 0.12f)),
             primary[0], primary[1], primary[2], 1.0f, true);
    draw_box(view_projection,
             box_model({x - facing * 0.48f, base_y + 1.57f, -0.02f},
                       {0.55f, 0.23f, 0.27f}, 0.0f, -facing * 0.30f),
             primary[0], primary[1], primary[2], 1.0f, true);
    draw_box(view_projection,
             box_model({x + facing * (0.80f + attack_reach),
                        base_y + 1.72f + extension * 0.16f, 0.02f},
                       {0.28f, 0.30f, 0.32f}),
             accent[0], accent[1], accent[2], 1.0f, true);
}

void RendererGL::draw_hud_rect(const Mat4& projection, float x, float y,
                               float width, float height,
                               float red, float green, float blue, float alpha) {
    const Mat4 model = box_model({x + width * 0.5f, y + height * 0.5f, 0.0f},
                                 {width, height, 0.02f});
    draw_box(projection, model, red, green, blue, alpha, false);
}

void RendererGL::draw_digit(const Mat4& projection, int digit, float x, float y,
                            float width, float height, float thickness,
                            float red, float green, float blue) {
    static constexpr std::array<unsigned char, 10> masks{{
        0x3f, 0x06, 0x5b, 0x4f, 0x66,
        0x6d, 0x7d, 0x07, 0x7f, 0x6f,
    }};
    digit = std::clamp(digit, 0, 9);
    const unsigned char mask = masks[static_cast<std::size_t>(digit)];
    const float horizontal_width = width - thickness * 2.0f;
    const float vertical_height = height * 0.5f - thickness * 1.5f;

    if (mask & 0x01) draw_hud_rect(projection, x + thickness, y + height - thickness,
                                   horizontal_width, thickness, red, green, blue);
    if (mask & 0x02) draw_hud_rect(projection, x + width - thickness, y + height * 0.5f,
                                   thickness, vertical_height, red, green, blue);
    if (mask & 0x04) draw_hud_rect(projection, x + width - thickness, y + thickness,
                                   thickness, vertical_height, red, green, blue);
    if (mask & 0x08) draw_hud_rect(projection, x + thickness, y,
                                   horizontal_width, thickness, red, green, blue);
    if (mask & 0x10) draw_hud_rect(projection, x, y + thickness,
                                   thickness, vertical_height, red, green, blue);
    if (mask & 0x20) draw_hud_rect(projection, x, y + height * 0.5f,
                                   thickness, vertical_height, red, green, blue);
    if (mask & 0x40) draw_hud_rect(projection, x + thickness, y + height * 0.5f - thickness * 0.5f,
                                   horizontal_width, thickness, red, green, blue);
}

void RendererGL::draw_hud(const MatchState& match,
                          int pixel_width, int pixel_height) {
    const float width = static_cast<float>(pixel_width);
    const float height = static_cast<float>(pixel_height);
    const Mat4 hud_projection = orthographic(0.0f, width, 0.0f, height, -1.0f, 1.0f);
    const float margin = std::max(18.0f, width * 0.026f);
    const float bar_width = std::min(width * 0.35f, 460.0f);
    const float bar_height = std::max(16.0f, height * 0.027f);
    const float bar_y = height - std::max(40.0f, height * 0.064f);
    const float frame = std::max(3.0f, bar_height * 0.18f);

    const float player_health = std::clamp(match.fighters[0].health / 100.0f, 0.0f, 1.0f);
    const float opponent_health = std::clamp(match.fighters[1].health / 100.0f, 0.0f, 1.0f);

    draw_hud_rect(hud_projection, margin - frame, bar_y - frame,
                  bar_width + frame * 2.0f, bar_height + frame * 2.0f,
                  0.70f, 0.62f, 0.33f, 1.0f);
    draw_hud_rect(hud_projection, margin, bar_y, bar_width, bar_height,
                  0.045f, 0.045f, 0.055f, 1.0f);
    draw_hud_rect(hud_projection, margin, bar_y, bar_width * player_health, bar_height,
                  player_health < 0.25f ? 0.82f : 0.08f,
                  player_health < 0.25f ? 0.12f : 0.78f,
                  0.20f, 1.0f);

    const float right_x = width - margin - bar_width;
    draw_hud_rect(hud_projection, right_x - frame, bar_y - frame,
                  bar_width + frame * 2.0f, bar_height + frame * 2.0f,
                  0.70f, 0.62f, 0.33f, 1.0f);
    draw_hud_rect(hud_projection, right_x, bar_y, bar_width, bar_height,
                  0.045f, 0.045f, 0.055f, 1.0f);
    draw_hud_rect(hud_projection, right_x + bar_width * (1.0f - opponent_health), bar_y,
                  bar_width * opponent_health, bar_height,
                  opponent_health < 0.25f ? 0.82f : 0.08f,
                  opponent_health < 0.25f ? 0.12f : 0.78f,
                  0.20f, 1.0f);

    const int seconds = std::clamp(static_cast<int>(std::ceil(match.round_time)), 0, 99);
    const float digit_height = std::max(34.0f, height * 0.064f);
    const float digit_width = digit_height * 0.52f;
    const float digit_gap = digit_width * 0.18f;
    const float timer_x = width * 0.5f - digit_width - digit_gap * 0.5f;
    const float timer_y = height - digit_height - std::max(11.0f, height * 0.015f);
    const float segment = std::max(3.0f, digit_width * 0.16f);
    draw_digit(hud_projection, seconds / 10, timer_x, timer_y,
               digit_width, digit_height, segment, 0.08f, 0.92f, 0.68f);
    draw_digit(hud_projection, seconds % 10, timer_x + digit_width + digit_gap, timer_y,
               digit_width, digit_height, segment, 0.08f, 0.92f, 0.68f);

    const float pip_size = std::max(5.0f, height * 0.010f);
    const unsigned pips = std::min(match.round_number, 5u);
    for (unsigned pip = 0; pip < pips; ++pip) {
        draw_hud_rect(hud_projection,
                      width * 0.5f - (static_cast<float>(pips) * 0.5f - static_cast<float>(pip))
                          * (pip_size + 3.0f),
                      timer_y - pip_size - 6.0f, pip_size, pip_size,
                      0.82f, 0.63f, 0.18f, 1.0f);
    }

    if (match.round_over) {
        const float panel_width = std::min(width * 0.34f, 400.0f);
        const float panel_height = std::max(18.0f, height * 0.035f);
        draw_hud_rect(hud_projection, width * 0.5f - panel_width * 0.5f,
                      height * 0.55f, panel_width, panel_height,
                      0.76f, 0.10f, 0.08f, 1.0f);
        draw_hud_rect(hud_projection, width * 0.5f - panel_width * 0.32f,
                      height * 0.55f + panel_height * 0.32f,
                      panel_width * 0.64f, panel_height * 0.36f,
                      0.98f, 0.78f, 0.25f, 1.0f);
    }
}

bool RendererGL::render(const MatchState& match,
                        int pixel_width, int pixel_height) {
    if (!initialized_) {
        set_error("render() called before initialize()");
        return false;
    }
    if (pixel_width <= 0 || pixel_height <= 0) {
        set_error("render() requires a positive drawable size");
        return false;
    }
    error_.clear();

    while (glGetError() != GL_NO_ERROR) {
        // Discard stale context errors so the result below belongs to this frame.
    }

    glViewport(0, 0, pixel_width, pixel_height);
    glClearColor(0.012f, 0.018f, 0.040f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    glEnable(GL_DEPTH_TEST);
    glDepthFunc(GL_LEQUAL);
    glDepthMask(GL_TRUE);
    glEnable(GL_CULL_FACE);
    glCullFace(GL_BACK);
    glFrontFace(GL_CCW);
    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);

    glUseProgram(program_);
    glBindVertexArray(vertex_array_);

    const CameraFrame camera = match.camera.frame(pixel_width, pixel_height);
    draw_stage(camera);
    draw_fighter(camera, match.fighters[0], 0);
    draw_fighter(camera, match.fighters[1], 1);

    glDisable(GL_DEPTH_TEST);
    glDepthMask(GL_FALSE);
    draw_hud(match, pixel_width, pixel_height);
    glDepthMask(GL_TRUE);
    glEnable(GL_DEPTH_TEST);

    glBindVertexArray(0);
    glUseProgram(0);

    const GLenum gl_error = glGetError();
    if (gl_error != GL_NO_ERROR) {
        set_error(gl_error_message("Frame rendering", gl_error));
        return false;
    }
    return true;
}

bool RendererGL::capture_png(const char* path,
                             int pixel_width, int pixel_height) {
    return capture_png(std::string(path ? path : ""), pixel_width, pixel_height);
}

bool RendererGL::capture_png(const std::filesystem::path& path,
                             int pixel_width, int pixel_height) {
    return capture_png(path.u8string(), pixel_width, pixel_height);
}

bool RendererGL::capture_png(const std::string& path,
                             int pixel_width, int pixel_height) {
    if (!initialized_) {
        set_error("capture_png() called before initialize()");
        return false;
    }
    if (path.empty()) {
        set_error("capture_png() requires a non-empty output path");
        return false;
    }
    if (pixel_width <= 0 || pixel_height <= 0) {
        set_error("capture_png() requires a positive drawable size");
        return false;
    }
    error_.clear();

    const std::size_t row_bytes = static_cast<std::size_t>(pixel_width) * 3u;
    const std::size_t byte_count = row_bytes * static_cast<std::size_t>(pixel_height);
    if (row_bytes / 3u != static_cast<std::size_t>(pixel_width) ||
        row_bytes > static_cast<std::size_t>(std::numeric_limits<int>::max()) ||
        (pixel_height > 0 && byte_count / static_cast<std::size_t>(pixel_height) != row_bytes)) {
        set_error("Screenshot dimensions overflow the capture buffer");
        return false;
    }

    std::vector<unsigned char> pixels(byte_count);
    while (glGetError() != GL_NO_ERROR) {
    }
    glPixelStorei(GL_PACK_ALIGNMENT, 1);
    glReadPixels(0, 0, pixel_width, pixel_height, GL_RGB, GL_UNSIGNED_BYTE,
                 pixels.data());
    const GLenum read_error = glGetError();
    if (read_error != GL_NO_ERROR) {
        set_error(gl_error_message("Framebuffer capture", read_error));
        return false;
    }

    std::vector<unsigned char> row(row_bytes);
    for (int y = 0; y < pixel_height / 2; ++y) {
        unsigned char* top = pixels.data() + static_cast<std::size_t>(y) * row_bytes;
        unsigned char* bottom = pixels.data() +
            static_cast<std::size_t>(pixel_height - 1 - y) * row_bytes;
        std::copy(top, top + row_bytes, row.begin());
        std::copy(bottom, bottom + row_bytes, top);
        std::copy(row.begin(), row.end(), bottom);
    }

    const std::filesystem::path output = std::filesystem::u8path(path);
    if (output.has_parent_path()) {
        std::error_code directory_error;
        std::filesystem::create_directories(output.parent_path(), directory_error);
        if (directory_error) {
            set_error("Unable to create screenshot directory: " + directory_error.message());
            return false;
        }
    }

    if (stbi_write_png(path.c_str(), pixel_width, pixel_height, 3,
                       pixels.data(), static_cast<int>(row_bytes)) == 0) {
        set_error("stb_image_write could not write PNG: " + path);
        return false;
    }
    return true;
}

}  // namespace tekken3::native
