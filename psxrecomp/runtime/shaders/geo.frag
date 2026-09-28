#version 450
/* Untextured fragment: emit the interpolated vertex colour. Mask bit (alpha)
 * is carried so the stencil-mirror pass reads it; for opaque draws alpha=1. */
layout(location = 0) noperspective in vec4 v_col;
layout(location = 0) out vec4 o_col;
void main() {
    o_col = v_col;
}
