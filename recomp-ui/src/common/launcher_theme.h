// launcher_theme.h — shared design tokens for the launcher.
//
// One source of truth for color / spacing / radius / type, expressed in LOGICAL
// units. Each backend multiplies the pixel-affecting values by the platform
// display_scale so the look is identical at 100%, 125%, 150%, 175% and across
// backends. Keeping tokens here (not baked into a backend) is what lets a
// future toolkit swap reuse the same visual language.

#ifndef LAUNCHER_NG_THEME_H
#define LAUNCHER_NG_THEME_H

#ifdef __cplusplus
extern "C" {
#endif

typedef struct { float r, g, b, a; } LngColor;

typedef struct {
    LngColor background;      // ink — the CRT ground
    LngColor background2;     // slightly lifted ground for the vignette center
    LngColor panel;
    LngColor panel_hovered;
    LngColor control;         // button/input fill — MUST contrast with panel
    LngColor control_hovered;
    LngColor border;          // panel + control outline
    LngColor accent;          // the one bold place: brand + primary CTA
    LngColor accent_dim;      // gradient partner / pressed
    LngColor accent_text;
    LngColor accent2;         // SECONDARY accent for section headings/eyebrows.
                              // Defaults to `accent` (one-accent look); a theme
                              // sets it apart for a dual-accent identity (N64:
                              // red primary + logo-blue headings).
    LngColor text;
    LngColor text_muted;
    LngColor good;        // verified / connected (phosphor mint)
    LngColor warn;        // unverified / caution (amber)
    LngColor focus_ring;  // gamepad/keyboard focus outline (cyan, sparingly)
    LngColor scanline;    // CRT scanline overlay (very low alpha)

    // logical dimensions (unscaled)
    float spacing_xs, spacing_sm, spacing_md, spacing_lg;
    float radius_sm, radius_lg;
    float row_height;
    float font_body, font_title, font_small;
    float focus_ring_width;
    int   scanlines;      // 1 = draw the CRT scanline overlay, 0 = flat (e.g. PSX)
} LauncherTheme;

static inline LngColor lng_rgba(float r, float g, float b, float a) {
    LngColor c; c.r = r; c.g = g; c.b = b; c.a = a; return c;
}

// "CRT Console Boot Screen" theme. A cinematic dark retro-console look: a
// violet-biased near-black ground (chosen, not a default grey), ONE bold neon
// accent (electric violet) reserved for brand + primary action, phosphor-mint
// and amber for state only, cyan for focus. Boldness spent in one place; the
// rest kept quiet.
static inline LauncherTheme launcher_theme_default(void) {
    LauncherTheme t;
    t.background      = lng_rgba(0.039f, 0.051f, 0.086f, 1.0f); // #0A0D16 ink
    t.background2     = lng_rgba(0.071f, 0.090f, 0.145f, 1.0f); // #121725 vignette center
    t.panel           = lng_rgba(0.078f, 0.102f, 0.157f, 1.0f); // #141A28 card
    t.panel_hovered   = lng_rgba(0.125f, 0.165f, 0.243f, 1.0f); // #202A3E
    t.control         = lng_rgba(0.106f, 0.137f, 0.208f, 1.0f); // #1B2335 button
    t.control_hovered = lng_rgba(0.145f, 0.188f, 0.278f, 1.0f); // #253047
    t.border          = lng_rgba(0.169f, 0.208f, 0.314f, 1.0f); // #2B3550 hairline
    t.accent          = lng_rgba(0.604f, 0.361f, 1.000f, 1.0f); // #9A5CFF electric violet
    t.accent_dim      = lng_rgba(0.431f, 0.247f, 0.812f, 1.0f); // #6E3FCF gradient/pressed
    t.accent_text     = lng_rgba(1.0f, 1.0f, 1.0f, 1.0f);
    t.accent2         = t.accent;                                // single-accent by default
    t.text            = lng_rgba(0.925f, 0.933f, 0.965f, 1.0f); // #ECEEF6
    t.text_muted      = lng_rgba(0.529f, 0.565f, 0.659f, 1.0f); // #8790A8
    t.good            = lng_rgba(0.275f, 0.890f, 0.608f, 1.0f); // #46E39B phosphor mint
    t.warn            = lng_rgba(0.961f, 0.698f, 0.235f, 1.0f); // #F5B23C amber
    t.focus_ring      = lng_rgba(0.220f, 0.882f, 0.902f, 1.0f); // #38E1E6 cyan
    t.scanline        = lng_rgba(0.0f, 0.0f, 0.0f, 0.18f);      // CRT scanline

    t.spacing_xs = 4.0f;  t.spacing_sm = 8.0f;
    t.spacing_md = 16.0f; t.spacing_lg = 24.0f;
    t.radius_sm  = 6.0f;  t.radius_lg  = 14.0f;
    t.row_height = 44.0f;                      // large rows: Steam Deck friendly
    t.font_body  = 18.0f; t.font_title = 34.0f; t.font_small = 13.0f;
    t.focus_ring_width = 2.5f;
    t.scanlines  = 1;                          // CRT look: scanlines ON
    return t;
}

// "PlayStation" theme. A cooler, flatter take for PSX titles: deep blue-black
// ground, ONE clean PlayStation-blue accent for brand + primary action, and NO
// CRT scanlines (the disc era, not the cartridge/CRT-arcade era). Same layout
// and design language as the default; only the palette + scanline flag differ.
static inline LauncherTheme launcher_theme_psx(void) {
    LauncherTheme t = launcher_theme_default();   // inherit spacing/type/dims
    t.background      = lng_rgba(0.039f, 0.047f, 0.078f, 1.0f); // #0A0C14 blue-black
    t.background2     = lng_rgba(0.063f, 0.078f, 0.122f, 1.0f); // #10141F lifted center
    t.panel           = lng_rgba(0.071f, 0.094f, 0.149f, 1.0f); // #121826 card
    t.panel_hovered   = lng_rgba(0.110f, 0.153f, 0.251f, 1.0f); // #1C2740
    t.control         = lng_rgba(0.086f, 0.114f, 0.180f, 1.0f); // #161D2E button
    t.control_hovered = lng_rgba(0.129f, 0.176f, 0.271f, 1.0f); // #212D45
    t.border          = lng_rgba(0.157f, 0.196f, 0.282f, 1.0f); // #283248 hairline
    t.accent          = lng_rgba(0.180f, 0.490f, 1.000f, 1.0f); // #2E7DFF PlayStation blue
    t.accent_dim      = lng_rgba(0.102f, 0.353f, 0.839f, 1.0f); // #1A5AD6 pressed/gradient
    t.accent_text     = lng_rgba(1.0f, 1.0f, 1.0f, 1.0f);
    t.accent2         = t.accent;                                // single-accent (blue)
    t.text            = lng_rgba(0.910f, 0.925f, 0.961f, 1.0f); // #E8ECF5
    t.text_muted      = lng_rgba(0.494f, 0.541f, 0.639f, 1.0f); // #7E8AA3
    /* good/warn keep their semantic colors; focus stays cyan (reads clearly on blue). */
    t.scanlines       = 0;                       // flat, no CRT scanlines
    return t;
}

// "Game Boy Advance" theme. The handheld LCD era: a deep indigo ground (the
// AGB-001 shell), ONE saturated indigo-violet accent for brand + primary
// action, and NO CRT scanlines (a backlit LCD never had them). Same layout and
// design language as the default; only the palette + scanline flag differ.
static inline LauncherTheme launcher_theme_gba(void) {
    LauncherTheme t = launcher_theme_default();   // inherit spacing/type/dims
    t.background      = lng_rgba(0.047f, 0.043f, 0.090f, 1.0f); // #0C0B17 indigo-black
    t.background2     = lng_rgba(0.082f, 0.075f, 0.145f, 1.0f); // #151325 lifted center
    t.panel           = lng_rgba(0.094f, 0.086f, 0.165f, 1.0f); // #18162A card
    t.panel_hovered   = lng_rgba(0.145f, 0.133f, 0.247f, 1.0f); // #25223F
    t.control         = lng_rgba(0.118f, 0.110f, 0.200f, 1.0f); // #1E1C33 button
    t.control_hovered = lng_rgba(0.161f, 0.149f, 0.271f, 1.0f); // #292645
    t.border          = lng_rgba(0.204f, 0.188f, 0.325f, 1.0f); // #343053 hairline
    t.accent          = lng_rgba(0.463f, 0.427f, 0.945f, 1.0f); // #766DF1 GBA indigo
    t.accent_dim      = lng_rgba(0.325f, 0.290f, 0.741f, 1.0f); // #534ABD pressed/gradient
    t.accent_text     = lng_rgba(1.0f, 1.0f, 1.0f, 1.0f);
    t.accent2         = t.accent;                                // single-accent (indigo)
    t.text            = lng_rgba(0.922f, 0.918f, 0.957f, 1.0f); // #EBEAF4
    t.text_muted      = lng_rgba(0.525f, 0.510f, 0.647f, 1.0f); // #8682A5
    /* good/warn keep their semantic colors; focus stays cyan (reads on indigo). */
    t.scanlines       = 0;                       // LCD, not CRT: flat
    return t;
}

// "Nintendo DS" theme. The dual-LCD handheld uses neutral graphite/silver
// chrome with a cool cyan interaction accent and a soft cobalt secondary.
// It is flat and scanline-free: the screens are LCD panels, not a CRT.
static inline LauncherTheme launcher_theme_nds(void) {
    LauncherTheme t = launcher_theme_default();
    t.background      = lng_rgba(0.035f, 0.043f, 0.055f, 1.0f); // #090B0E
    t.background2     = lng_rgba(0.059f, 0.071f, 0.086f, 1.0f); // #0F1216
    t.panel           = lng_rgba(0.075f, 0.086f, 0.102f, 1.0f); // #13161A
    t.panel_hovered   = lng_rgba(0.114f, 0.133f, 0.157f, 1.0f); // #1D2228
    t.control         = lng_rgba(0.094f, 0.110f, 0.129f, 1.0f); // #181C21
    t.control_hovered = lng_rgba(0.133f, 0.165f, 0.192f, 1.0f); // #222A31
    t.border          = lng_rgba(0.204f, 0.235f, 0.267f, 1.0f); // #343C44
    t.accent          = lng_rgba(0.078f, 0.788f, 0.886f, 1.0f); // #14C9E2
    t.accent_dim      = lng_rgba(0.047f, 0.553f, 0.667f, 1.0f); // #0C8DAA
    t.accent_text     = lng_rgba(0.020f, 0.043f, 0.055f, 1.0f);
    t.accent2         = lng_rgba(0.329f, 0.573f, 0.929f, 1.0f); // #5492ED
    t.text            = lng_rgba(0.925f, 0.941f, 0.957f, 1.0f);
    t.text_muted      = lng_rgba(0.557f, 0.596f, 0.639f, 1.0f);
    t.scanlines       = 0;
    return t;
}

// "Nintendo 64" theme. The 64-bit cartridge era, but a decade past the CRT
// arcade look of the default: a neutral graphite ground (the charcoal N64
// console plastic, deliberately NOT the blue/violet of the others), ONE
// confident Nintendo red for brand + primary action, and NO scanlines (this
// unit renders through RT64, a modern HLE GPU — a flat, clean panel, not a
// faux-CRT). State colors (mint / amber / cyan) are unchanged. Same layout and
// design language as the default; only the palette + scanline flag differ.
static inline LauncherTheme launcher_theme_n64(void) {
    LauncherTheme t = launcher_theme_default();   // inherit spacing/type/dims
    t.background      = lng_rgba(0.075f, 0.078f, 0.086f, 1.0f); // #131417 graphite ink
    t.background2     = lng_rgba(0.106f, 0.110f, 0.122f, 1.0f); // #1B1C1F lifted center
    t.panel           = lng_rgba(0.098f, 0.102f, 0.114f, 1.0f); // #191A1D card
    t.panel_hovered   = lng_rgba(0.145f, 0.153f, 0.169f, 1.0f); // #25272B
    t.control         = lng_rgba(0.125f, 0.129f, 0.145f, 1.0f); // #202125 button
    t.control_hovered = lng_rgba(0.176f, 0.184f, 0.204f, 1.0f); // #2D2F34
    t.border          = lng_rgba(0.204f, 0.212f, 0.235f, 1.0f); // #34363C hairline
    t.accent          = lng_rgba(0.878f, 0.227f, 0.184f, 1.0f); // #E03A2F logo red (primary/CTA)
    t.accent_dim      = lng_rgba(0.686f, 0.145f, 0.114f, 1.0f); // #AF251D pressed/gradient
    t.accent_text     = lng_rgba(1.0f, 1.0f, 1.0f, 1.0f);
    t.accent2         = lng_rgba(0.204f, 0.451f, 0.878f, 1.0f); // #3473E0 logo blue (headings)
    t.text            = lng_rgba(0.929f, 0.933f, 0.945f, 1.0f); // #EDEEF1 near-white
    t.text_muted      = lng_rgba(0.541f, 0.557f, 0.596f, 1.0f); // #8A8E98 neutral grey
    /* good/warn keep their semantic colors; focus stays cyan (reads on graphite). */
    t.scanlines       = 0;                       // RT64 HLE GPU, not a CRT: flat
    return t;
}

// "Nintendo Entertainment System" theme. The cartridge/CRT era: a neutral
// graphite ground (the front-loader's grey, not a color-biased ink) with ONE
// bold Nintendo red accent for brand + primary action — the color of the
// console's stripe and the controller's A/B buttons. CRT scanlines ON (the
// living-room-TV era). Same layout and design language as the default; only the
// palette differs (neutral greys instead of the default's violet-blue bias).
static inline LauncherTheme launcher_theme_nes(void) {
    LauncherTheme t = launcher_theme_default();   // inherit spacing/type/dims
    t.background      = lng_rgba(0.051f, 0.055f, 0.063f, 1.0f); // #0D0E10 graphite ink
    t.background2     = lng_rgba(0.086f, 0.094f, 0.106f, 1.0f); // #16181B lifted center
    t.panel           = lng_rgba(0.098f, 0.106f, 0.118f, 1.0f); // #191B1E card
    t.panel_hovered   = lng_rgba(0.149f, 0.161f, 0.180f, 1.0f); // #26292E
    t.control         = lng_rgba(0.125f, 0.137f, 0.153f, 1.0f); // #202327 button
    t.control_hovered = lng_rgba(0.173f, 0.188f, 0.212f, 1.0f); // #2C3036
    t.border          = lng_rgba(0.200f, 0.216f, 0.239f, 1.0f); // #33373D hairline
    t.accent          = lng_rgba(0.898f, 0.196f, 0.153f, 1.0f); // #E53227 NES red
    t.accent_dim      = lng_rgba(0.659f, 0.118f, 0.090f, 1.0f); // #A81E17 pressed/gradient
    t.accent_text     = lng_rgba(1.0f, 1.0f, 1.0f, 1.0f);
    t.accent2         = t.accent;                                // single-accent (red) — else headings inherit default violet
    t.text            = lng_rgba(0.925f, 0.925f, 0.933f, 1.0f); // #ECECEE
    t.text_muted      = lng_rgba(0.541f, 0.557f, 0.588f, 1.0f); // #8A8E96
    /* good/warn keep their semantic colors; focus stays cyan (reads on graphite). */
    t.scanlines       = 1;                        // cartridge/CRT era: scanlines ON
    return t;
}

// "Sega Genesis" theme. The 16-bit cartridge/CRT-arcade era: a cool blue-black
// ground and ONE bold Sega azure accent for brand + primary action, distinctly
// more cyan than the PSX royal blue so the two never read alike. CRT scanlines
// stay ON (this is the tube/cartridge era, same rationale as the default).
static inline LauncherTheme launcher_theme_genesis(void) {
    LauncherTheme t = launcher_theme_default();   // inherit spacing/type/dims
    t.background      = lng_rgba(0.035f, 0.047f, 0.075f, 1.0f); // #090C13 blue-black ink
    t.background2     = lng_rgba(0.059f, 0.082f, 0.129f, 1.0f); // #0F1521 lifted center
    t.panel           = lng_rgba(0.067f, 0.094f, 0.149f, 1.0f); // #111826 card
    t.panel_hovered   = lng_rgba(0.106f, 0.153f, 0.235f, 1.0f); // #1B273C
    t.control         = lng_rgba(0.082f, 0.114f, 0.176f, 1.0f); // #151D2D button
    t.control_hovered = lng_rgba(0.122f, 0.173f, 0.263f, 1.0f); // #1F2C43
    t.border          = lng_rgba(0.149f, 0.204f, 0.298f, 1.0f); // #26344C hairline
    t.accent          = lng_rgba(0.090f, 0.635f, 0.902f, 1.0f); // #17A2E6 Sega azure
    t.accent_dim      = lng_rgba(0.055f, 0.451f, 0.702f, 1.0f); // #0E73B3 pressed/gradient
    t.accent_text     = lng_rgba(1.0f, 1.0f, 1.0f, 1.0f);
    t.accent2         = t.accent;                                // single-accent (azure) — else headings inherit default violet
    t.text            = lng_rgba(0.914f, 0.929f, 0.961f, 1.0f); // #E9EDF5
    t.text_muted      = lng_rgba(0.498f, 0.545f, 0.643f, 1.0f); // #7F8BA4
    /* good/warn keep their semantic colors; focus stays cyan (reads on blue). */
    t.scanlines       = 1;                       // CRT/cartridge era: scanlines ON
    return t;
}

// "Game Boy" (DMG) theme. The original 1989 handheld's reflective pea-green
// LCD: an olive-tinted dark ground and the classic Game Boy screen green as the
// one accent (the #9bbc0f/#306230 dot-matrix palette). Backlit-launcher chrome,
// so NO CRT scanlines — the DMG panel was a passive reflective LCD, not a tube.
static inline LauncherTheme launcher_theme_gb(void) {
    LauncherTheme t = launcher_theme_default();   // inherit spacing/type/dims
    t.background      = lng_rgba(0.043f, 0.055f, 0.031f, 1.0f); // #0B0E08 olive-black
    t.background2     = lng_rgba(0.071f, 0.090f, 0.051f, 1.0f); // #12170D lifted center
    t.panel           = lng_rgba(0.082f, 0.102f, 0.059f, 1.0f); // #151A0F card
    t.panel_hovered   = lng_rgba(0.122f, 0.153f, 0.086f, 1.0f); // #1F2716
    t.control         = lng_rgba(0.098f, 0.125f, 0.071f, 1.0f); // #192012 button
    t.control_hovered = lng_rgba(0.141f, 0.176f, 0.098f, 1.0f); // #242D19
    t.border          = lng_rgba(0.180f, 0.220f, 0.125f, 1.0f); // #2E3820 hairline
    t.accent          = lng_rgba(0.545f, 0.675f, 0.059f, 1.0f); // #8BAC0F GB screen green
    t.accent_dim      = lng_rgba(0.376f, 0.510f, 0.098f, 1.0f); // #608219 pressed/gradient
    t.accent_text     = lng_rgba(0.043f, 0.055f, 0.031f, 1.0f); // dark ink on the bright green
    t.text            = lng_rgba(0.914f, 0.929f, 0.878f, 1.0f); // #E9EDE0 warm off-white
    t.text_muted      = lng_rgba(0.545f, 0.573f, 0.475f, 1.0f); // #8B9279
    /* good/warn keep their semantic colors; focus stays cyan (reads on olive). */
    t.scanlines       = 0;                       // reflective LCD, not CRT: flat
    return t;
}

// "Game Boy Color" theme. The 1998 color handheld (the translucent "Berry" /
// "Grape" shells + the rainbow wordmark): a cool near-black ground and a vivid
// berry-magenta accent, distinct from every other console's blue/green/indigo.
// Still a backlit-style launcher over a reflective color LCD — scanlines OFF.
static inline LauncherTheme launcher_theme_gbc(void) {
    LauncherTheme t = launcher_theme_default();   // inherit spacing/type/dims
    t.background      = lng_rgba(0.055f, 0.039f, 0.063f, 1.0f); // #0E0A10 aubergine-black
    t.background2     = lng_rgba(0.090f, 0.063f, 0.102f, 1.0f); // #17101A lifted center
    t.panel           = lng_rgba(0.102f, 0.071f, 0.114f, 1.0f); // #1A121D card
    t.panel_hovered   = lng_rgba(0.157f, 0.106f, 0.176f, 1.0f); // #281B2D
    t.control         = lng_rgba(0.129f, 0.090f, 0.145f, 1.0f); // #211725 button
    t.control_hovered = lng_rgba(0.180f, 0.125f, 0.204f, 1.0f); // #2E2034
    t.border          = lng_rgba(0.235f, 0.161f, 0.263f, 1.0f); // #3C2943 hairline
    t.accent          = lng_rgba(0.859f, 0.239f, 0.616f, 1.0f); // #DB3D9D GBC berry magenta
    t.accent_dim      = lng_rgba(0.643f, 0.157f, 0.451f, 1.0f); // #A42873 pressed/gradient
    t.accent_text     = lng_rgba(1.0f, 1.0f, 1.0f, 1.0f);
    t.text            = lng_rgba(0.937f, 0.918f, 0.945f, 1.0f); // #EFEAF1
    t.text_muted      = lng_rgba(0.596f, 0.541f, 0.620f, 1.0f); // #988A9E
    /* good/warn keep their semantic colors; focus stays cyan (reads on aubergine). */
    t.scanlines       = 0;                       // color LCD, not CRT: flat
    return t;
}

// Pick a built-in theme by name ("psx" -> PlayStation, "gba" -> Game Boy
// Advance, "gbc" -> Game Boy Color, "gb" -> Game Boy (DMG), "n64" -> Nintendo
// 64, "nes" -> Nintendo Entertainment System, "genesis" -> Sega Genesis;
// anything else -> default CRT). Note the "gb*" order: match "gba" and "gbc"
// (3rd char) BEFORE the bare "gb" fallback.
static inline LauncherTheme launcher_theme_by_name(const char* name) {
    if (name && (name[0] == 'p' || name[0] == 'P') &&
        (name[1] == 's' || name[1] == 'S'))
        return launcher_theme_psx();
    if (name && (name[0] == 'g' || name[0] == 'G') &&
        (name[1] == 'b' || name[1] == 'B') &&
        (name[2] == 'a' || name[2] == 'A'))
        return launcher_theme_gba();
    if (name && (name[0] == 'n' || name[0] == 'N') &&
        (name[1] == 'd' || name[1] == 'D') &&
        (name[2] == 's' || name[2] == 'S'))
        return launcher_theme_nds();
    if (name && (name[0] == 'n' || name[0] == 'N') && name[1] == '6' && name[2] == '4')
        return launcher_theme_n64();
    if (name && (name[0] == 'n' || name[0] == 'N') &&
        (name[1] == 'e' || name[1] == 'E') &&
        (name[2] == 's' || name[2] == 'S'))
        return launcher_theme_nes();
    if (name && (name[0] == 'g' || name[0] == 'G') &&
        (name[1] == 'b' || name[1] == 'B') &&
        (name[2] == 'c' || name[2] == 'C'))
        return launcher_theme_gbc();
    if (name && (name[0] == 'g' || name[0] == 'G') &&
        (name[1] == 'b' || name[1] == 'B'))
        return launcher_theme_gb();
    if (name && (name[0] == 'g' || name[0] == 'G') &&
        (name[1] == 'e' || name[1] == 'E'))
        return launcher_theme_genesis();
    return launcher_theme_default();
}

#ifdef __cplusplus
}
#endif

#endif // LAUNCHER_NG_THEME_H
