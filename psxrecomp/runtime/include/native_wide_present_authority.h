#ifndef PSX_NATIVE_WIDE_PRESENT_AUTHORITY_H
#define PSX_NATIVE_WIDE_PRESENT_AUTHORITY_H

#ifdef __cplusplus
extern "C" {
#endif

/* A full native-wide mirror is allowed to own the centre only while a real
 * wide frame is being presented.  Sustained GTE-quiet 2D screens may contain
 * CPU uploads / VRAM copies that are authoritative only in canonical VRAM, so
 * they deliberately fall back to the centre splice. */
static inline int psx_ws_wide_mirror_authority_allowed(int full_mirror_opt_in,
                                                        int wide_present,
                                                        int quiet_2d) {
    return full_mirror_opt_in && wide_present && !quiet_2d;
}

/* Fast GL mirroring normally skips centre-only primitives and therefore needs
 * the canonical splice. It may skip the splice only when a separate exact
 * scene path proves it mirrored a complete sidecar. Complete mirroring may
 * skip it when the frame is authoritative. Software passes fast_center_mode=0
 * because it never performs GL's centre-only draw skip. */
static inline int psx_ws_wide_center_splice_required(int fast_center_mode,
                                                      int mirror_authoritative,
                                                      int sidecar_complete) {
    /* Fast mode normally omitted centre-only primitives, so generic fast
     * frames must retain the canonical splice. A separately proven complete
     * sidecar is the only bounded exception. Authority remains mandatory. */
    return (fast_center_mode && !sidecar_complete) || !mirror_authoritative;
}

/* Canonical dirty tracking cannot observe a primitive that changes only a
 * reveal margin. Until wide surfaces have their own dirty generations, an
 * authoritative full mirror must always reach the swap path. */
static inline int psx_ws_wide_duplicate_present_may_skip(
    int mirror_authoritative) {
    return !mirror_authoritative;
}

#ifdef __cplusplus
}
#endif

#endif /* PSX_NATIVE_WIDE_PRESENT_AUTHORITY_H */
