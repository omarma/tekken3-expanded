#ifndef PSX_NETPLAY_RB_POST_H
#define PSX_NETPLAY_RB_POST_H

/*
 * RB_POST already carries target_tick on the wire. After tip-extend the peer
 * may still deliver a POST for the prior tip while we Verify the new tip —
 * latching that digest caused false post diverge (local@T+1 vs peer@T).
 *
 * Accept only when peer tip equals the current episode tip.
 */

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

static inline int netplay_rb_peer_post_tip_ok(uint32_t peer_target, uint32_t episode_tip)
{
    return peer_target == episode_tip;
}

#ifdef __cplusplus
}
#endif

#endif /* PSX_NETPLAY_RB_POST_H */
