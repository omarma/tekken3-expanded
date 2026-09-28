#version 450
/* Quad blit fragment: sample an RGBA8 source (alpha = bit15), split by STP for
 * the stencil-mirror write, OR set-mask into the output alpha. Exact integer
 * source fetch (no normalized-uv edge precision). u_src_div maps fragcoord to
 * src texel (S for native-res sources, 1 for hr-res); u_src_off is added after
 * the divide in src texel units. Ported from the GL backend's BLIT_FS. */
layout(set = 0, binding = 0) uniform sampler2D u_src;
layout(push_constant) uniform PC {
    float u_shift;
    int   u_stp_pass;   /* 0=all, 1=bit15=0 only, 2=bit15=1 only */
    int   u_maskset;
    int   u_src_div;
    ivec2 u_src_off;
    ivec4 u_rect;       /* unused in frag; keeps the block layout in sync */
} pc;
layout(location = 0) out vec4 frag;
void main() {
    ivec2 p = ivec2(gl_FragCoord.xy);
    vec4 c = texelFetch(u_src, p / pc.u_src_div + pc.u_src_off, 0);
    bool stp = c.a >= 0.5;
    if (pc.u_stp_pass == 1 && stp) discard;
    if (pc.u_stp_pass == 2 && !stp) discard;
    frag = vec4(c.rgb, (stp || pc.u_maskset != 0) ? 1.0 : 0.0);
}
