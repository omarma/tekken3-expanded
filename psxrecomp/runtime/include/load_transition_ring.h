#ifndef PSXRECOMP_LOAD_TRANSITION_RING_H
#define PSXRECOMP_LOAD_TRANSITION_RING_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Host-side load/pacing edge telemetry. An entry is appended whenever the
 * physical CD read state, bridged logical-load predicate, or turbo state
 * changes. This is deliberately observational: it does not alter pacing. */
typedef struct {
    uint32_t frame;
    uint32_t host_ms;
    uint16_t load_run;
    uint8_t  read_active;
    uint8_t  load_active;
    uint8_t  turbo_active;
} LoadTransitionEntry;

uint64_t load_transition_total(void);
int      load_transition_get(uint64_t seq, LoadTransitionEntry *out);

#ifdef __cplusplus
}
#endif

#endif /* PSXRECOMP_LOAD_TRANSITION_RING_H */
