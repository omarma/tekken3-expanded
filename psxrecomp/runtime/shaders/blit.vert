#version 450
/* Quad blit (vertex-less): CPU->VRAM upload flushes and VRAM->VRAM copies. The
 * destination rect (native VRAM px) rides in the push constant; six gl_VertexID
 * positions form two triangles. The SxS supersample is just a larger
 * framebuffer. blit.frag does the exact integer source fetch from gl_FragCoord. */
layout(push_constant) uniform PC {
    float u_shift;
    int   u_stp_pass;
    int   u_maskset;
    int   u_src_div;
    ivec2 u_src_off;
    ivec4 u_rect;       /* x0, y0, x1, y1 (native px) */
} pc;
void main() {
    vec2 c[6] = vec2[6](vec2(0,0), vec2(1,0), vec2(0,1),
                        vec2(1,0), vec2(0,1), vec2(1,1));
    vec2 uv = c[gl_VertexIndex];
    float px = mix(float(pc.u_rect.x), float(pc.u_rect.z), uv.x);
    float py = mix(float(pc.u_rect.y), float(pc.u_rect.w), uv.y);
    gl_Position = vec4((px + pc.u_shift) / 512.0 - 1.0,
                       (py + pc.u_shift) / 256.0 - 1.0, 0.0, 1.0);
}
