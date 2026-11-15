#include "probe.h"
#include <stdio.h>
#include <string.h>

static unsigned checks, failures;
#define CHECK(expr) do { checks++; if (!(expr)) { failures++; \
    fprintf(stderr, "FAIL line=%d expression=%s\n", __LINE__, #expr); } } while (0)

#define ARENA_SIZE 4096u
static uint8_t arena[ARENA_SIZE], before[ARENA_SIZE];
struct callback_state {
    unsigned payload_calls, return_calls;
    int32_t payload_code, return_code;
    unsigned fuel_action;
    uint32_t outcome;
};

static int all_byte(const uint8_t *p, size_t n, uint8_t value) {
    while (n--) if (*p++ != value) return 0;
    return 1;
}
static uint32_t read32(const uint8_t *p) {
    uint32_t v = 0;
    for (unsigned i = 0; i < 4; i++) v |= (uint32_t)p[i] << (8u * i);
    return v;
}
static uint64_t read64(const uint8_t *p) {
    uint64_t v = 0;
    for (unsigned i = 0; i < 8; i++) v |= (uint64_t)p[i] << (8u * i);
    return v;
}
static void write32(uint8_t *p, uint32_t v) {
    for (unsigned i = 0; i < 4; i++) { p[i] = (uint8_t)v; v >>= 8; }
}

static struct hp_plan plan(void) {
    struct hp_plan p = {0};
    p.version = HP_VERSION;
    p.mode = HP_HOST_SIMULATION;
    p.entry_flags = HP_ENTRY_FLAGS_ALL;
    for (unsigned i = 0; i < 4; i++) p.entry.x[i] = UINT64_C(0x1122334455667700) + i;
    p.entry.pc = UINT64_C(0x1122334455667788);
    p.entry.sp = UINT64_C(0x8877665544332211);
    p.entry.current_el = 2;
    p.entry.cntfrq = 1000000;
    p.entry.sctlr = UINT64_C(0x99aabbccddeeff00);
    p.entry.daif = UINT64_C(0x0123456789abcdef);
    p.entry.tcr = UINT64_C(0xfedcba9876543210);
    p.entry.ttbr0 = UINT64_C(0x1234567887654321);
    p.entry.ttbr1 = UINT64_C(0xabcdef0012345678);
    p.entry.vbar = UINT64_C(0x8765432100fedcba);
    for (unsigned i = 0; i < 32; i++) {
        p.build_sha256[i] = (uint8_t)i;
        p.input_sha256[i] = (uint8_t)(32u + i);
        p.fdt_sha256[i] = (uint8_t)(64u + i);
    }
    p.region[HP_INPUT] = (struct hp_span){0x100, 64};
    p.region[HP_PAYLOAD] = (struct hp_span){0x200, 96};
    p.region[HP_BSS] = (struct hp_span){0x300, 64};
    p.region[HP_STACK] = (struct hp_span){0x400, 64};
    p.region[HP_LOG] = (struct hp_span){0x600, HP_FRAME_SIZE * HP_FRAME_COUNT + 16u};
    p.fuel = 100;
    return p;
}
static void initialize(const struct hp_plan *p) {
    memset(arena, 0xa5, sizeof arena);
    for (size_t i = 0; i < (size_t)p->region[HP_INPUT].size; i++)
        arena[(size_t)p->region[HP_INPUT].offset + i] = (uint8_t)(i ^ 0x59u);
    memcpy(before, arena, sizeof arena);
}
static int32_t payload(struct hp_payload_view *v, void *opaque) {
    struct callback_state *s = opaque;
    s->payload_calls++;
    CHECK(v->bytes == arena + 0x200);
    CHECK(v->size == 64);
    CHECK(v->bss == arena + 0x300);
    CHECK(v->bss_size == 64);
    CHECK(memcmp(v->bytes, arena + 0x100, v->size) == 0);
    CHECK(all_byte(v->bss, v->bss_size, 0));
    CHECK(all_byte(arena + 0x400, 64, 0));
    CHECK(v->fuel == 100);
    if (s->fuel_action == 0) v->fuel--;
    else if (s->fuel_action == 1) v->fuel = 0;
    else if (s->fuel_action == 2) v->fuel++;
    return s->payload_code;
}
static int32_t return_to_caller(uint32_t outcome, void *opaque) {
    struct callback_state *s = opaque;
    s->return_calls++;
    s->outcome = outcome;
    CHECK(s->payload_calls == 1);
    return s->return_code;
}
static struct hp_callbacks callbacks(struct callback_state *s) {
    struct hp_callbacks c = {payload, return_to_caller, s};
    return c;
}

/* Every rejected plan must be rejected before writes and both callbacks. */
static void reject(const struct hp_plan *p, size_t size, uint32_t expected) {
    struct callback_state s = {0};
    struct hp_callbacks c = callbacks(&s);
    memset(arena, 0xa5, sizeof arena);
    memcpy(before, arena, sizeof arena);
    CHECK(hp_validate(p, size) == expected);
    struct hp_result r = hp_run(arena, size, p, &c);
    CHECK(r.status == expected);
    CHECK(r.frames == 0);
    CHECK(r.payload_called == 0 && r.return_called == 0);
    CHECK(s.payload_calls == 0 && s.return_calls == 0);
    CHECK(r.payload_status == 0 && r.return_status == 0 && r.fuel_remaining == 0);
    CHECK(memcmp(arena, before, sizeof arena) == 0);
}
static void invalid_plans(void) {
    struct hp_plan p = plan();
    reject(NULL, ARENA_SIZE, HP_BAD_ARGUMENT);
    reject(&p, 0, HP_BAD_ARGUMENT);
    reject(&p, (size_t)HP_MAX_ARENA + 1u, HP_BAD_ARGUMENT);
    p.version++; reject(&p, ARENA_SIZE, HP_UNSUPPORTED);
    p = plan(); p.mode = 0; reject(&p, ARENA_SIZE, HP_UNSUPPORTED);
    p = plan(); p.mode = 3; reject(&p, ARENA_SIZE, HP_UNSUPPORTED);
    p = plan(); p.entry_flags = 0; reject(&p, ARENA_SIZE, HP_BAD_ENTRY);
    p = plan(); p.entry_flags |= 1u << 14; reject(&p, ARENA_SIZE, HP_BAD_ENTRY);
    p = plan(); p.entry.current_el = 0; reject(&p, ARENA_SIZE, HP_BAD_ENTRY);
    p = plan(); p.entry.current_el = 4; reject(&p, ARENA_SIZE, HP_BAD_ENTRY);
    p = plan(); p.entry.cntfrq = 0; reject(&p, ARENA_SIZE, HP_BAD_ENTRY);
    p = plan(); p.fuel = 0; reject(&p, ARENA_SIZE, HP_BAD_CAPACITY);
    p = plan(); p.fuel = (uint64_t)HP_MAX_FUEL + 1u; reject(&p, ARENA_SIZE, HP_BAD_CAPACITY);
    for (unsigned i = 0; i < HP_REGIONS; i++) {
        p = plan(); p.region[i].size = 0; reject(&p, ARENA_SIZE, HP_BAD_RANGE);
        p = plan(); p.region[i].offset = UINT64_MAX; reject(&p, ARENA_SIZE, HP_BAD_RANGE);
        p = plan(); p.region[i].size = UINT64_MAX; reject(&p, ARENA_SIZE, HP_BAD_RANGE);
        p = plan(); p.region[i].offset = ARENA_SIZE; reject(&p, ARENA_SIZE, HP_BAD_RANGE);
        p = plan(); p.region[i].offset = ARENA_SIZE + 16u; reject(&p, ARENA_SIZE, HP_BAD_RANGE);
        p = plan(); p.region[i].offset++; reject(&p, ARENA_SIZE, HP_BAD_RANGE);
        p = plan(); p.region[i].size++; reject(&p, ARENA_SIZE, HP_BAD_RANGE);
        p = plan(); p.region[i].offset = ARENA_SIZE - 16u;
        p.region[i].size = 32; reject(&p, ARENA_SIZE, HP_BAD_RANGE);
    }
    /* Make the higher-index span begin at the first span, covering every pair. */
    for (unsigned i = 0; i < HP_REGIONS; i++) for (unsigned j = i + 1; j < HP_REGIONS; j++) {
        p = plan(); p.region[j].offset = p.region[i].offset;
        reject(&p, ARENA_SIZE, HP_OVERLAP);
    }
    p = plan(); p.region[HP_PAYLOAD].size = 48; reject(&p, ARENA_SIZE, HP_BAD_CAPACITY);
    p = plan(); p.region[HP_LOG].size = HP_FRAME_SIZE * HP_FRAME_COUNT - 16u;
    reject(&p, ARENA_SIZE, HP_BAD_CAPACITY);

    p = plan();
    p.region[HP_PAYLOAD].offset = p.region[HP_INPUT].offset + p.region[HP_INPUT].size;
    CHECK(hp_validate(&p, ARENA_SIZE) == HP_OK);
    p = plan(); p.region[HP_LOG].size = HP_FRAME_SIZE * HP_FRAME_COUNT;
    CHECK(hp_validate(&p, (size_t)(p.region[HP_LOG].offset + p.region[HP_LOG].size)) == HP_OK);
    p = plan(); p.fuel = HP_MAX_FUEL; CHECK(hp_validate(&p, HP_MAX_ARENA) == HP_OK);
    p = plan(); p.mode = HP_QEMU_VIRT; CHECK(hp_validate(&p, ARENA_SIZE) == HP_OK);
    p = plan(); p.entry_flags = 1; p.entry.current_el = 0; p.entry.cntfrq = 0;
    CHECK(hp_validate(&p, ARENA_SIZE) == HP_OK);
    p = plan(); p.entry.current_el = 1; CHECK(hp_validate(&p, ARENA_SIZE) == HP_OK);
    p.entry.current_el = 3; CHECK(hp_validate(&p, ARENA_SIZE) == HP_OK);
}
static void invalid_callbacks(void) {
    struct hp_plan p = plan();
    struct callback_state s = {0};
    struct hp_callbacks c = callbacks(&s);
    initialize(&p);
    struct hp_result r = hp_run(NULL, ARENA_SIZE, &p, &c);
    CHECK(r.status == HP_BAD_ARGUMENT && r.frames == 0);
    CHECK(s.payload_calls == 0 && s.return_calls == 0);
    r = hp_run(arena, ARENA_SIZE, &p, NULL);
    CHECK(r.status == HP_BAD_CALLBACK && r.frames == 0);
    CHECK(memcmp(arena, before, sizeof arena) == 0);
    c.payload = NULL;
    r = hp_run(arena, ARENA_SIZE, &p, &c);
    CHECK(r.status == HP_BAD_CALLBACK && r.frames == 0);
    CHECK(memcmp(arena, before, sizeof arena) == 0);
    c = callbacks(&s); c.return_to_caller = NULL;
    r = hp_run(arena, ARENA_SIZE, &p, &c);
    CHECK(r.status == HP_BAD_CALLBACK && r.frames == 0);
    CHECK(memcmp(arena, before, sizeof arena) == 0);
    CHECK(s.payload_calls == 0 && s.return_calls == 0);
}

static void frame_fields(const struct hp_plan *p, const struct hp_result *r,
                         uint32_t payload_outcome) {
    const uint64_t expected[] = {
        p->entry.x[0], p->entry.x[1], p->entry.x[2], p->entry.x[3],
        p->entry.pc, p->entry.sp, p->entry.current_el, p->entry.cntfrq,
        p->entry.sctlr, p->entry.daif, p->entry.tcr,
        p->entry.ttbr0, p->entry.ttbr1, p->entry.vbar
    };
    CHECK(r->frames == HP_FRAME_COUNT);
    for (unsigned i = 0; i < HP_FRAME_COUNT; i++) {
        const uint8_t *f = arena + (size_t)p->region[HP_LOG].offset + i * HP_FRAME_SIZE;
        CHECK(hp_frame_valid(f, HP_FRAME_SIZE, i));
        CHECK(memcmp(f, "HAKIPRB1", 8) == 0);
        CHECK(read32(f + 8) == HP_VERSION);
        CHECK(read32(f + 12) == i && read32(f + 16) == i + 1u);
        CHECK(read32(f + 20) == (i < 4 ? HP_OK : i < 6 ? payload_outcome : r->status));
        CHECK(read32(f + 24) == p->mode && read32(f + 28) == p->entry_flags);
        CHECK(memcmp(f + 32, p->build_sha256, 32) == 0);
        CHECK(memcmp(f + 64, p->input_sha256, 32) == 0);
        CHECK(memcmp(f + 96, p->fdt_sha256, 32) == 0);
        for (unsigned j = 0; j < 14; j++) CHECK(read64(f + 128 + j * 8u) == expected[j]);
        CHECK(read64(f + 240) == (i < 4 ? p->fuel : r->fuel_remaining));
        CHECK(read32(f + 248) == (i == 6 ? (uint32_t)r->return_status :
                                   i >= 4 ? (uint32_t)r->payload_status : 0u));
        CHECK(read32(f + 252) == hp_crc32(f, 252));
    }
}
static void memory_footprint(const struct hp_plan *p) {
    CHECK(memcmp(arena + 0x100, before + 0x100, 64) == 0);
    CHECK(memcmp(arena + 0x200, before + 0x100, 64) == 0);
    CHECK(all_byte(arena + 0x240, 32, 0));
    CHECK(all_byte(arena + 0x300, 64, 0));
    CHECK(all_byte(arena + 0x400, 64, 0));
    int untouched = 1;
    for (size_t i = 0; i < sizeof arena; i++) {
        int modified = 0;
        for (unsigned j = HP_PAYLOAD; j < HP_LOG; j++)
            if (i >= p->region[j].offset && i < p->region[j].offset + p->region[j].size)
                modified = 1;
        if (i >= p->region[HP_LOG].offset &&
            i < p->region[HP_LOG].offset + HP_FRAME_SIZE * HP_FRAME_COUNT) modified = 1;
        if (!modified && arena[i] != before[i]) untouched = 0;
    }
    CHECK(untouched);
    CHECK(all_byte(arena + (size_t)p->region[HP_LOG].offset + HP_FRAME_SIZE * HP_FRAME_COUNT, 16, 0xa5));
}
static void run_outcome(int32_t payload_code, unsigned fuel_action, int32_t return_code,
                        uint32_t payload_outcome, uint32_t final_outcome) {
    struct hp_plan p = plan(), saved = p;
    struct callback_state s = {0};
    s.payload_code = payload_code; s.fuel_action = fuel_action; s.return_code = return_code;
    struct hp_callbacks c = callbacks(&s), saved_c = c;
    initialize(&p);
    struct hp_result r = hp_run(arena, sizeof arena, &p, &c);
    CHECK(r.status == final_outcome);
    CHECK(r.payload_called == 1 && r.return_called == 1);
    CHECK(s.payload_calls == 1 && s.return_calls == 1);
    CHECK(s.outcome == payload_outcome);
    CHECK(r.payload_status == payload_code && r.return_status == return_code);
    CHECK(r.fuel_remaining == (fuel_action == 0 ? 99u : fuel_action == 1 ? 0u :
                                  fuel_action == 2 ? 101u : 100u));
    CHECK(memcmp(&p, &saved, sizeof p) == 0);
    CHECK(memcmp(&c, &saved_c, sizeof c) == 0);
    frame_fields(&p, &r, payload_outcome);
    memory_footprint(&p);
}
static void frame_guards(void) {
    uint8_t frame_copy[HP_FRAME_SIZE];
    const uint8_t *original = arena + 0x600;
    CHECK(hp_crc32((const uint8_t *)"123456789", 9) == UINT32_C(0xcbf43926));
    CHECK(hp_crc32(NULL, 0) == 0);
    CHECK(!hp_frame_valid(NULL, HP_FRAME_SIZE, 0));
    CHECK(!hp_frame_valid(original, 0, 0));
    CHECK(!hp_frame_valid(original, HP_FRAME_SIZE - 1u, 0));
    CHECK(!hp_frame_valid(original, HP_FRAME_SIZE + 1u, 0));
    CHECK(!hp_frame_valid(original, HP_FRAME_SIZE, HP_FRAME_COUNT));
    CHECK(!hp_frame_valid(original, HP_FRAME_SIZE, 1));
    /* Every byte is checksum-covered, including identity and entry snapshots. */
    for (unsigned i = 0; i < HP_FRAME_SIZE; i++) {
        memcpy(frame_copy, original, sizeof frame_copy); frame_copy[i] ^= 1u;
        CHECK(!hp_frame_valid(frame_copy, sizeof frame_copy, 0));
    }
    for (unsigned i = 0; i < 8; i++) {
        memcpy(frame_copy, original, sizeof frame_copy); frame_copy[i] ^= 1u;
        write32(frame_copy + 252, hp_crc32(frame_copy, 252));
        CHECK(!hp_frame_valid(frame_copy, sizeof frame_copy, 0));
    }
    const unsigned fields[] = {8, 12, 16};
    for (unsigned i = 0; i < 3; i++) {
        memcpy(frame_copy, original, sizeof frame_copy);
        write32(frame_copy + fields[i], 99);
        write32(frame_copy + 252, hp_crc32(frame_copy, 252));
        CHECK(!hp_frame_valid(frame_copy, sizeof frame_copy, 0));
    }
}

int main(void) {
    invalid_plans();
    invalid_callbacks();
    run_outcome(0, 0, 0, HP_OK, HP_OK);
    run_outcome(-7, 0, 0, HP_PAYLOAD_FAILED, HP_PAYLOAD_FAILED);
    run_outcome(0, 1, 0, HP_BUDGET_EXHAUSTED, HP_BUDGET_EXHAUSTED);
    run_outcome(0, 2, 0, HP_BUDGET_EXHAUSTED, HP_BUDGET_EXHAUSTED);
    run_outcome(-7, 1, 0, HP_BUDGET_EXHAUSTED, HP_BUDGET_EXHAUSTED);
    run_outcome(0, 3, 0, HP_OK, HP_OK);
    run_outcome(0, 0, -9, HP_OK, HP_RETURN_FAILED);
    run_outcome(-7, 0, -9, HP_PAYLOAD_FAILED, HP_RETURN_FAILED);
    run_outcome(0, 1, -9, HP_BUDGET_EXHAUSTED, HP_RETURN_FAILED);
    frame_guards();
    if (failures) { fprintf(stderr, "HOST_PROBE_FAIL checks=%u failures=%u\n", checks, failures); return 1; }
    printf("HOST_PROBE_PASS checks=%u\n", checks);
    return 0;
}
