/* Shared by net_test and host policy tests. Times are monotonic seconds. */
#ifndef HAKIOS_NET_RECOVERY_POLICY_H
#define HAKIOS_NET_RECOVERY_POLICY_H
#include <stdbool.h>
#include <stdint.h>

static bool net_ipv4_usable(uint32_t host)
{
    return (host >> 24) != 0 && (host >> 24) != 127 &&
        (host >> 16) != 0xa9fe && (host >> 24) < 224;
}

struct net_recovery_state { double bad_since, last_attempt; bool bad, attempted; };

static bool net_recovery_due(struct net_recovery_state *s, double now,
    bool known, bool joined, bool up, bool dhcp, bool ipv4, bool router, bool ipv6)
{
    if (!known || !joined || !up || !dhcp || ipv4 || router || ipv6) {
        s->bad = false;
        return false;
    }
    if (!s->bad) { s->bad = true; s->bad_since = now; }
    if (now - s->bad_since < 60 || (s->attempted && now - s->last_attempt < 120))
        return false;
    /* Rate-limit failed notifications as well as successful ones. */
    s->attempted = true;
    s->last_attempt = now;
    return true;
}
#endif
