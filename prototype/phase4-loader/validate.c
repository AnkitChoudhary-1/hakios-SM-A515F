/* SPDX-License-Identifier: MIT */
/* This module never writes a payload destination or touches a peripheral.
 * The exact implementation is exercised with native ASan/UBSan as well as
 * by the complete AArch64 loader under QEMU. */
#include "validate.h"

uint32_t phase4_crc32(const unsigned char *p, uint64_t n)
{
    uint32_t crc = ~0u;
    for (uint64_t i = 0; i < n; i++) {
        crc ^= p[i];
        for (unsigned j = 0; j < 8; j++)
            crc = (crc >> 1) ^ (0xedb88320u & (0u - (crc & 1)));
    }
    return ~crc;
}
int phase4_span(uint64_t a, uint64_t n, uint64_t lo, uint64_t hi)
{ return hi >= lo && a >= lo && a <= hi && n <= hi - a; }
int phase4_overlap(uint64_t a, uint64_t n, uint64_t b, uint64_t m)
{
    /* Subtraction avoids end-address wraparound, including malformed input. */
    return n && m && (a <= b ? b - a < n : a - b < m);
}
static const unsigned char *backing(const struct loader_config *c,
                                    const struct toc_entry *toc,
                                    const unsigned char *p, uint64_t a, uint64_t n)
{
    for (uint64_t i = 0; i < c->count; i++) {
        const struct toc_entry *t = &toc[i];
        if (phase4_span(a, n, t->destination, t->destination + t->copy))
            return p + t->source + (a - t->destination);
    }
    return 0;
}
static int covered(const struct loader_config *c, const struct toc_entry *toc,
                   uint64_t a, uint64_t n)
{
    for (uint64_t i = 0; i < c->count; i++) {
        const struct toc_entry *t = &toc[i];
        if (phase4_span(a, n, t->destination, t->destination + t->copy + t->zero)) return 1;
    }
    return 0;
}
int phase4_validate(const struct loader_config *c, const struct toc_entry *toc,
                    uint64_t toc_bytes, const unsigned char *p,
                    uint64_t pbytes, uint64_t runtime, uint64_t paddr)
{
    if (!c || !toc || !p || c->magic != CONFIG_MAGIC || c->version != 1 ||
        !c->count || c->count > MAX_TOC || c->count * sizeof(*toc) != toc_bytes ||
        !pbytes || pbytes > IMAGE_BYTES || c->payload_bytes != pbytes ||
        (runtime != IMAGE_BASE && runtime != LEGACY_IMAGE_BASE && runtime != MEASURED_IMAGE_BASE) ||
        !phase4_span(paddr, pbytes, runtime, runtime + IMAGE_BYTES) ||
        c->diagnostic > DIAG_COPY || c->checkpoint > 40 ||
        c->watchdog_count < 100 || c->watchdog_count > 65535 ||
        c->slide != SLIDE_BITS || !(c->nonce_hi | c->nonce_lo)) return VALID_CONFIG;
    if (c->arena_base != ARENA_BASE || c->arena_limit != ARENA_LIMIT ||
        c->kernel_base < ARENA_BASE || c->kernel_limit > ARENA_LIMIT ||
        c->kernel_base >= c->kernel_limit ||
        phase4_overlap(ARENA_BASE, ARENA_LIMIT - ARENA_BASE, runtime, IMAGE_BYTES) ||
        (c->entry & 3) || !phase4_span(c->entry, 4, c->kernel_base, c->kernel_limit) ||
        (c->bootargs & 7) || !phase4_span(c->bootargs, 736, ARENA_BASE, ARENA_LIMIT) ||
        (c->stub_slot & 7) || !phase4_span(c->stub_slot, 32, c->kernel_base, c->kernel_limit) ||
        c->log_capacity != MAX_KERNEL_LOG ||
        !phase4_span(c->log_pa, c->log_capacity, c->kernel_base, c->kernel_limit) ||
        (c->log_len_pa & 3) || !phase4_span(c->log_len_pa, 4, c->kernel_base, c->kernel_limit)) return VALID_LAYOUT;
    for (uint64_t i = 0; i < c->count; i++) {
        const struct toc_entry *t = &toc[i];
        if (t->reserved || t->crc > UINT32_MAX ||
            !phase4_span(t->source, t->copy, 0, pbytes) ||
            t->zero > UINT64_MAX - t->copy || !(t->copy | t->zero) ||
            !phase4_span(t->destination, t->copy + t->zero, ARENA_BASE, ARENA_LIMIT)) return VALID_TOC;
        for (uint64_t j = 0; j < i; j++)
            if (phase4_overlap(t->destination, t->copy + t->zero,
                               toc[j].destination, toc[j].copy + toc[j].zero)) return VALID_TOC;
        if (phase4_crc32(p + t->source, t->copy) != (uint32_t)t->crc) return VALID_CRC;
    }
    const unsigned char *slot = backing(c, toc, p, c->stub_slot, 32);
    if (!backing(c, toc, p, c->entry, 4) || !backing(c, toc, p, c->bootargs, 736) || !slot ||
        !covered(c, toc, c->log_pa, c->log_capacity) || !covered(c, toc, c->log_len_pa, 4)) return VALID_BACKING;
    static const unsigned char magic[8] = {'X','N','U','L','D','R','S','T'};
    for (unsigned i = 0; i < sizeof(magic); i++) if (slot[i] != magic[i]) return VALID_SLOT;
    return VALID_OK;
}
