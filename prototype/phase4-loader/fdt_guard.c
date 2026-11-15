/* SPDX-License-Identifier: MIT */
#include "fdt_guard.h"

static uint32_t be32(const unsigned char *p)
{ return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) | ((uint32_t)p[2] << 8) | p[3]; }
static uint64_t be64(const unsigned char *p)
{ return ((uint64_t)be32(p) << 32) | be32(p + 4); }
static int span(uint64_t a, uint64_t n, uint64_t lo, uint64_t hi)
{ return a >= lo && a <= hi && n <= hi - a; }
static int overlaps(uint64_t a, uint64_t n, uint64_t b, uint64_t m)
{ return n && m && a < b + m && b < a + n; }
static int terminated(const unsigned char *p, uint32_t max)
{
    for (uint32_t i = 0; i < max && i < 128; i++) if (!p[i]) return 1;
    return 0;
}
static int name_is(const unsigned char *p, const char *s)
{
    for (unsigned i = 0; i < 128; i++) {
        if (p[i] != (unsigned char)s[i]) return 0;
        if (!p[i]) return 1;
    }
    return 0;
}

int phase4_fdt_guard(const unsigned char *f, uint32_t available,
                    uint64_t physical, uint64_t dram_base,
                    uint64_t arena_base, uint64_t arena_limit, uint64_t image_base)
{
    if (available < 40 || arena_base < dram_base || arena_limit <= arena_base) return 0;
    uint32_t total = be32(f + 4), so = be32(f + 8), st = be32(f + 12), ro = be32(f + 16);
    uint32_t sn = be32(f + 36), strings = be32(f + 32);
    if (be32(f) != 0xd00dfeed || be32(f + 20) != 17 || be32(f + 24) > 17 ||
        total < 40 || total > available || total > 2 * 1024 * 1024 ||
        !span(physical, total, 0x80000000, 0x100000000) ||
        !span(so, sn, 40, total) || !span(st, strings, 40, total) ||
        !span(ro, 16, 40, total) || (so & 3) || (ro & 7) ||
        overlaps(so, sn, st, strings) ||
        overlaps(physical, total, arena_base, arena_limit - arena_base) ||
        overlaps(physical, total, image_base, 36334080)) return 0;
    uint32_t r = ro;
    for (unsigned i = 0; ; i++, r += 16) {
        if (i >= 128 || !span(r, 16, 0, total) ||
            overlaps(r, 16, so, sn) || overlaps(r, 16, st, strings)) return 0;
        uint64_t a = be64(f + r), n = be64(f + r + 8);
        if (!a && !n) break;
        if (n > UINT64_MAX - a || overlaps(a, n, arena_base, arena_limit - arena_base)) return 0;
    }
    struct level {
        uint32_t ac, sc, parent_ac, parent_sc;
        int reserved, memory, children;
    } levels[32];
    int depth = -1, root_seen = 0, root_closed = 0, memory_covers_budget = 0;
    uint32_t at = so, end = so + sn;
    for (unsigned tokens = 0; tokens < 32768 && at <= end && end - at >= 4; tokens++) {
        uint32_t token = be32(f + at); at += 4;
        if (token == 1) {
            if (root_closed || ++depth >= 32) return 0;
            uint32_t name_at = at;
            if (!terminated(f + at, end - at)) return 0;
            while (f[at]) at++;
            if (depth == 0 && (root_seen || at != name_at)) return 0;
            if (depth == 0) root_seen = 1;
            at = (at + 4) & ~3u;
            if (at > end) return 0;
            if (depth) levels[depth - 1].children = 1;
            levels[depth].parent_ac = depth ? levels[depth - 1].ac : 2;
            levels[depth].parent_sc = depth ? levels[depth - 1].sc : 1;
            /* #*-cells describes children and is not inherited in the FDT ABI. */
            levels[depth].ac = 2;
            levels[depth].sc = 1;
            levels[depth].children = 0;
            levels[depth].reserved = (depth && levels[depth - 1].reserved) ||
                (depth == 1 && name_is(f + name_at, "reserved-memory"));
            levels[depth].memory = depth == 1 &&
                (name_is(f + name_at, "memory") ||
                 (at - name_at >= 8 && f[name_at] == 'm' && f[name_at + 1] == 'e' &&
                  f[name_at + 2] == 'm' && f[name_at + 3] == 'o' &&
                  f[name_at + 4] == 'r' && f[name_at + 5] == 'y' && f[name_at + 6] == '@'));
        } else if (token == 2) {
            if (depth < 0) return 0;
            if (--depth == -1) root_closed = 1;
        } else if (token == 3) {
            if (depth < 0 || levels[depth].children || end - at < 8) return 0;
            uint32_t n = be32(f + at), no = be32(f + at + 4); at += 8;
            if (n > end - at || no >= strings || !terminated(f + st + no, strings - no)) return 0;
            const unsigned char *name = f + st + no;
            if (name_is(name, "#address-cells")) {
                if (n != 4 || be32(f + at) > 2) return 0;
                levels[depth].ac = be32(f + at);
            } else if (name_is(name, "#size-cells")) {
                if (n != 4 || be32(f + at) > 2) return 0;
                levels[depth].sc = be32(f + at);
            } else if (levels[depth].reserved && name_is(name, "ranges") && n) {
                /* Translating reserved addresses needs an explicit adapter. */
                return 0;
            } else if ((levels[depth].reserved || levels[depth].memory) && name_is(name, "reg")) {
                uint32_t ac = levels[depth].parent_ac, sc = levels[depth].parent_sc, width = 4 * (ac + sc);
                if (!ac || !sc || !width || !n || n % width) return 0;
                for (uint32_t j = 0; j < n; j += width) {
                    uint64_t a = ac == 2 ? be64(f + at + j) : be32(f + at + j);
                    uint64_t z = sc == 2 ? be64(f + at + j + ac * 4) : be32(f + at + j + ac * 4);
                    if (z > UINT64_MAX - a) return 0;
                    if (levels[depth].reserved && overlaps(a, z, arena_base, arena_limit - arena_base)) return 0;
                    if (levels[depth].memory && span(dram_base, arena_limit - dram_base, a, a + z)) memory_covers_budget = 1;
                }
            }
            at = (at + n + 3) & ~3u;
            if (at > end) return 0;
        } else if (token == 4) {
            continue;
        } else if (token == 9) {
            return root_seen && root_closed && depth == -1 && memory_covers_budget && at == end;
        } else return 0;
    }
    return 0;
}
