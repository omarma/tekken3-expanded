#if !defined(PSX_HAS_RECOMP_NET)
/* Empty TU when recomp-net is not linked. */
#else

#include "netplay_input_hist.h"

#include <string.h>

static int8_t u8_to_i8_stick(uint8_t v)
{
    int d = (int)v - 0x80;
    if (d > 127) d = 127;
    if (d < -128) d = -128;
    return (int8_t)d;
}

static uint8_t i8_to_u8_stick(int8_t v)
{
    return (uint8_t)((int)v + 0x80);
}

void netplay_ih_reset(NetplayInputHist *h, int slot_count)
{
    if (!h) return;
    memset(h, 0, sizeof(*h));
    if (slot_count < 1) slot_count = 1;
    if (slot_count > NETPLAY_INPUT_HIST_MAX_SLOTS)
        slot_count = NETPLAY_INPUT_HIST_MAX_SLOTS;
    h->slot_count = slot_count;
}

void netplay_ih_pad_to_frame(const PsxNetPad *pad, uint32_t tick, uint8_t predicted,
                             RNetRbFrame *out)
{
    PsxNetPad n;
    if (!out) return;
    memset(out, 0, sizeof(*out));
    out->tick = tick;
    out->is_predicted = predicted ? 1u : 0u;
    out->is_valid = 1u;
    out->analog = 0u; /* MotK default digital; tip/capture may override */
    if (!pad) {
        out->buttons = 0xFFFFu;
        return;
    }
    n = *pad;
    psx_netplay_normalize_pad(&n);
    out->buttons = n.buttons;
    out->stick_x = u8_to_i8_stick(n.lx);
    out->stick_y = u8_to_i8_stick(n.ly);
    out->analog = n.analog ? 1u : 0u;
}

void netplay_ih_frame_to_pad(const RNetRbFrame *frame, PsxNetPad *pad)
{
    if (!pad) return;
    memset(pad, 0, sizeof(*pad));
    pad->buttons = 0xFFFFu;
    pad->lx = pad->ly = pad->rx = pad->ry = 0x80u;
    pad->analog = 0; /* digital until a valid frame says DualShock */
    pad->connected = 1;
    if (!frame || !frame->is_valid) return;
    pad->buttons = frame->buttons;
    pad->lx = i8_to_u8_stick(frame->stick_x);
    pad->ly = i8_to_u8_stick(frame->stick_y);
    pad->analog = frame->analog ? 1u : 0u;
    psx_netplay_normalize_pad(pad);
}

void netplay_ih_frame_to_contract(const RNetRbFrame *frame, RNetInputContractFrame *out)
{
    if (!out) return;
    memset(out, 0, sizeof(*out));
    if (!frame) return;
    out->tick = frame->tick;
    out->buttons = frame->buttons;
    out->stick_x = frame->stick_x;
    out->stick_y = frame->stick_y;
    out->is_predicted = frame->is_predicted ? 1u : 0u;
}

int netplay_ih_put(NetplayInputHist *h, int slot, const RNetRbFrame *frame)
{
    RNetRbFrame *dst;
    if (!h || !frame || !frame->is_valid) return 0;
    if (slot < 0 || slot >= h->slot_count) return 0;
    dst = &h->rows[slot][frame->tick % NETPLAY_INPUT_HIST_DEPTH];
    *dst = *frame;
    dst->is_valid = 1u;
    return 1;
}

int netplay_ih_get(const NetplayInputHist *h, int slot, uint32_t tick, RNetRbFrame *out)
{
    const RNetRbFrame *src;
    if (!h || !out) return 0;
    if (slot < 0 || slot >= h->slot_count) return 0;
    src = &h->rows[slot][tick % NETPLAY_INPUT_HIST_DEPTH];
    if (!src->is_valid || src->tick != tick) return 0;
    *out = *src;
    return 1;
}

int netplay_ih_invent_hold_last(NetplayInputHist *h, int slot, uint32_t tick,
                                RNetRbFrame *out)
{
    RNetRbFrame invented;
    RNetRbFrame prev;
    uint32_t look;

    if (!h || slot < 0 || slot >= h->slot_count) return 0;

    memset(&invented, 0, sizeof(invented));
    invented.tick = tick;
    invented.buttons = 0xFFFFu;
    invented.analog = 0u;
    invented.is_predicted = 1u;
    invented.is_valid = 1u;

    for (look = 1; look < NETPLAY_INPUT_HIST_DEPTH; look++) {
        if (tick < look) break;
        if (netplay_ih_get(h, slot, tick - look, &prev)) {
            invented.buttons = prev.buttons;
            invented.stick_x = prev.stick_x;
            invented.stick_y = prev.stick_y;
            invented.analog = prev.analog ? 1u : 0u;
            break;
        }
    }

    if (!netplay_ih_put(h, slot, &invented)) return 0;
    h->invent_count++;
    if (out) *out = invented;
    return 1;
}

int netplay_ih_invent_idle(NetplayInputHist *h, int slot, uint32_t tick,
                           RNetRbFrame *out)
{
    RNetRbFrame invented;

    if (!h || slot < 0 || slot >= h->slot_count) return 0;

    memset(&invented, 0, sizeof(invented));
    invented.tick = tick;
    invented.buttons = 0xFFFFu;
    invented.analog = 0u;
    invented.is_predicted = 1u;
    invented.is_valid = 1u;
    /* stick_x/y = 0 → neutral 0x80 via frame_to_pad */

    if (!netplay_ih_put(h, slot, &invented)) return 0;
    h->invent_count++;
    if (out) *out = invented;
    return 1;
}

int netplay_ih_promote(NetplayInputHist *h, int slot, const RNetRbFrame *wire)
{
    RNetRbFrame auth;
    if (!h || !wire || !wire->is_valid) return 0;
    auth = *wire;
    auth.is_predicted = 0u;
    auth.is_valid = 1u;
    if (!netplay_ih_put(h, slot, &auth)) return 0;
    h->promote_count++;
    return 1;
}

#endif /* PSX_HAS_RECOMP_NET */
