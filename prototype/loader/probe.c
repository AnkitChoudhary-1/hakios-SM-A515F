#include "probe.h"

static void zero(uint8_t *p, size_t n) { while (n--) *p++ = 0; }
static void copy(uint8_t *to, const uint8_t *from, size_t n) { while (n--) *to++ = *from++; }
static void put32(uint8_t *p, uint32_t v) {
    for (unsigned i = 0; i < 4; i++) { p[i] = (uint8_t)v; v >>= 8; }
}
static void put64(uint8_t *p, uint64_t v) {
    for (unsigned i = 0; i < 8; i++) { p[i] = (uint8_t)v; v >>= 8; }
}
static uint32_t get32(const uint8_t *p) {
    uint32_t v = 0;
    for (unsigned i = 0; i < 4; i++) v |= (uint32_t)p[i] << (8u * i);
    return v;
}
uint32_t hp_crc32(const uint8_t *p, size_t n) {
    uint32_t c = UINT32_MAX;
    while (n--) {
        c ^= *p++;
        for (unsigned j = 0; j < 8; j++) c = (c >> 1) ^ (0xedb88320u & (0u - (c & 1u)));
    }
    return ~c;
}
static const uint8_t magic[8] = { 'H','A','K','I','P','R','B','1' };
int hp_frame_valid(const uint8_t *p, size_t n, uint32_t seq) {
    if (!p || n != HP_FRAME_SIZE || seq >= HP_FRAME_COUNT) return 0;
    for (unsigned i = 0; i < 8; i++) if (p[i] != magic[i]) return 0;
    return get32(p + 8) == HP_VERSION && get32(p + 12) == seq &&
        get32(p + 16) == seq + 1 && get32(p + 252) == hp_crc32(p, 252);
}
uint32_t hp_validate(const struct hp_plan *p, size_t n) {
    if (!p || !n || n > HP_MAX_ARENA) return HP_BAD_ARGUMENT;
    if (p->version != HP_VERSION ||
        (p->mode != HP_HOST_SIMULATION && p->mode != HP_QEMU_VIRT)) return HP_UNSUPPORTED;
    if (!p->entry_flags || (p->entry_flags & ~HP_ENTRY_FLAGS_ALL) ||
        ((p->entry_flags & (1u << 6)) && (p->entry.current_el < 1 || p->entry.current_el > 3)) ||
        ((p->entry_flags & (1u << 7)) && !p->entry.cntfrq)) return HP_BAD_ENTRY;
    if (!p->fuel || p->fuel > HP_MAX_FUEL) return HP_BAD_CAPACITY;
    for (unsigned i = 0; i < HP_REGIONS; i++) {
        const struct hp_span *s = &p->region[i];
        /* Subtraction avoids overflow and rejects before pointer arithmetic. */
        if (!s->size || s->offset > n || s->size > n - s->offset ||
            (s->offset & 15u) || (s->size & 15u)) return HP_BAD_RANGE;
        for (unsigned j = 0; j < i; j++) {
            const struct hp_span *t = &p->region[j];
            if (s->offset < t->offset + t->size && t->offset < s->offset + s->size)
                return HP_OVERLAP;
        }
    }
    if (p->region[HP_INPUT].size > p->region[HP_PAYLOAD].size ||
        p->region[HP_LOG].size < HP_FRAME_COUNT * HP_FRAME_SIZE) return HP_BAD_CAPACITY;
    return HP_OK;
}
static void frame(uint8_t *arena, const struct hp_plan *p, struct hp_result *r,
                  uint32_t stage, uint32_t status) {
    uint8_t *f = arena + (size_t)p->region[HP_LOG].offset + (size_t)r->frames * HP_FRAME_SIZE;
    zero(f, HP_FRAME_SIZE);
    copy(f, magic, sizeof magic);
    put32(f + 8, HP_VERSION); put32(f + 12, r->frames);
    put32(f + 16, stage); put32(f + 20, status);
    put32(f + 24, p->mode); put32(f + 28, p->entry_flags);
    copy(f + 32, p->build_sha256, 32); copy(f + 64, p->input_sha256, 32);
    copy(f + 96, p->fdt_sha256, 32);
    for (unsigned i = 0; i < 4; i++) put64(f + 128 + i * 8, p->entry.x[i]);
    put64(f + 160, p->entry.pc); put64(f + 168, p->entry.sp);
    put64(f + 176, p->entry.current_el); put64(f + 184, p->entry.cntfrq);
    put64(f + 192, p->entry.sctlr); put64(f + 200, p->entry.daif);
    put64(f + 208, p->entry.tcr); put64(f + 216, p->entry.ttbr0);
    put64(f + 224, p->entry.ttbr1); put64(f + 232, p->entry.vbar);
    put64(f + 240, r->fuel_remaining);
    put32(f + 248, stage == HP_RETURN_RESULT ? (uint32_t)r->return_status :
          stage >= HP_PAYLOAD_EXIT ? (uint32_t)r->payload_status : 0u);
    put32(f + 252, hp_crc32(f, 252));
    r->frames++;
}
struct hp_result hp_run(uint8_t *arena, size_t n, const struct hp_plan *p,
                        const struct hp_callbacks *cb) {
    struct hp_result r = {0};
    r.status = hp_validate(p, n);
    if (r.status != HP_OK) return r;
    if (!arena) { r.status = HP_BAD_ARGUMENT; return r; }
    if (!cb || !cb->payload || !cb->return_to_caller) { r.status = HP_BAD_CALLBACK; return r; }
    r.fuel_remaining = p->fuel;
    /* Entry was already captured by the trusted adapter, before this function. */
    frame(arena, p, &r, HP_ENTRY, HP_OK);
    frame(arena, p, &r, HP_VALIDATED, HP_OK);
    copy(arena + (size_t)p->region[HP_PAYLOAD].offset,
         arena + (size_t)p->region[HP_INPUT].offset, (size_t)p->region[HP_INPUT].size);
    zero(arena + (size_t)p->region[HP_PAYLOAD].offset + (size_t)p->region[HP_INPUT].size,
         (size_t)(p->region[HP_PAYLOAD].size - p->region[HP_INPUT].size));
    zero(arena + (size_t)p->region[HP_BSS].offset, (size_t)p->region[HP_BSS].size);
    zero(arena + (size_t)p->region[HP_STACK].offset, (size_t)p->region[HP_STACK].size);
    frame(arena, p, &r, HP_PREPARED, HP_OK);
    struct hp_payload_view view = {
        arena + (size_t)p->region[HP_PAYLOAD].offset, (size_t)p->region[HP_INPUT].size,
        arena + (size_t)p->region[HP_BSS].offset, (size_t)p->region[HP_BSS].size, p->fuel
    };
    frame(arena, p, &r, HP_PAYLOAD_ENTER, HP_OK);
    r.payload_called = 1;
    r.payload_status = cb->payload(&view, cb->context);
    r.fuel_remaining = view.fuel;
    if (view.fuel > p->fuel || !view.fuel) r.status = HP_BUDGET_EXHAUSTED;
    else if (r.payload_status) r.status = HP_PAYLOAD_FAILED;
    frame(arena, p, &r, HP_PAYLOAD_EXIT, r.status);
    frame(arena, p, &r, HP_RETURN_REQUEST, r.status);
    r.return_called = 1;
    r.return_status = cb->return_to_caller(r.status, cb->context);
    if (r.return_status) r.status = HP_RETURN_FAILED;
    frame(arena, p, &r, HP_RETURN_RESULT, r.status);
    return r;
}
