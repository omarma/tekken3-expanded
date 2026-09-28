#ifndef LAUNCHER_UDP_PORT_H
#define LAUNCHER_UDP_PORT_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Universal UDP port policy used by recomp-ui before create()/join():
 *   Host create LAN/Direct IP — exact UI port required; fail when busy
 *   Host create online        — ignore UI port; prefer 7777, then +1..+span-1
 *   Guest join (any path)     — prefer 7778, then +1..+span-1 → "0.0.0.0:<port>"
 *
 * Self-contained (no recomp-net link). Exclusive bind probes omit SO_REUSEADDR
 * so a second bind on the same port is detected. */

/* 1 = free on INADDR_ANY, 0 = busy / invalid. */
int launcher_udp_port_available(int port);

/* Returns a free port, or -1. span <= 0 selects 32 (MotK contract). */
int launcher_udp_find_free_port(int preferred, int span);

/* Fill guest_bind with "0.0.0.0:<free>" (prefer 7778, span 32). Returns 0. */
int launcher_udp_prepare_guest_bind(char *out, size_t cap);

/* Parse "host:port"; returns 7777 when missing/invalid. */
int launcher_endpoint_port(const char *endpoint);

/* Rewrite port in place (capacity includes NUL). Returns 0 on success. */
int launcher_endpoint_set_port(char *endpoint, size_t cap, int port);

#ifdef __cplusplus
}
#endif

#endif /* LAUNCHER_UDP_PORT_H */
