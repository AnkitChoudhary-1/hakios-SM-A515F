#ifndef HAKIOS_PROBE_H
#define HAKIOS_PROBE_H
#include <stddef.h>
#include <stdint.h>

#define HP_VERSION 1u
#define HP_FRAME_SIZE 256u
#define HP_FRAME_COUNT 7u
#define HP_MAX_ARENA (1024u * 1024u)
#define HP_MAX_FUEL (1024u * 1024u)
#define HP_ENTRY_FLAGS_ALL 0x3fffu

enum hp_mode { HP_HOST_SIMULATION = 1, HP_QEMU_VIRT = 2 };
enum hp_status {
    HP_OK = 0, HP_BAD_ARGUMENT = 1, HP_UNSUPPORTED = 2,
    HP_BAD_ENTRY = 3, HP_BAD_RANGE = 4, HP_OVERLAP = 5,
    HP_BAD_CAPACITY = 6, HP_BAD_CALLBACK = 7, HP_PAYLOAD_FAILED = 8,
    HP_BUDGET_EXHAUSTED = 9, HP_RETURN_FAILED = 10
};
enum hp_stage {
    HP_ENTRY = 1, HP_VALIDATED = 2, HP_PREPARED = 3,
    HP_PAYLOAD_ENTER = 4, HP_PAYLOAD_EXIT = 5,
    HP_RETURN_REQUEST = 6, HP_RETURN_RESULT = 7
};
enum hp_region { HP_INPUT, HP_PAYLOAD, HP_BSS, HP_STACK, HP_LOG, HP_REGIONS };
struct hp_span { uint64_t offset, size; };
/* Field order is also the stage-frame wire order. Flags mark valid fields. */
struct hp_entry {
    uint64_t x[4], pc, sp, current_el, cntfrq, sctlr, daif;
    uint64_t tcr, ttbr0, ttbr1, vbar;
};
struct hp_plan {
    uint32_t version, mode, entry_flags;
    struct hp_entry entry;
    uint8_t build_sha256[32], input_sha256[32], fdt_sha256[32];
    struct hp_span region[HP_REGIONS];
    uint64_t fuel;
};
struct hp_payload_view {
    const uint8_t *bytes;
    size_t size;
    uint8_t *bss;
    size_t bss_size;
    /* A cooperative budget. This cannot preempt a non-returning callback. */
    uint64_t fuel;
};
struct hp_result {
    uint32_t status, frames, payload_called, return_called;
    int32_t payload_status, return_status;
    uint64_t fuel_remaining;
};
typedef int32_t (*hp_payload_fn)(struct hp_payload_view *, void *);
typedef int32_t (*hp_return_fn)(uint32_t outcome, void *);
/* Trusted callbacks must leave plan, arena layout and frame bytes unchanged. */
struct hp_callbacks { hp_payload_fn payload; hp_return_fn return_to_caller; void *context; };

uint32_t hp_validate(const struct hp_plan *, size_t arena_size);
struct hp_result hp_run(uint8_t *arena, size_t arena_size,
                        const struct hp_plan *, const struct hp_callbacks *);
uint32_t hp_crc32(const uint8_t *, size_t);
int hp_frame_valid(const uint8_t *frame, size_t size, uint32_t sequence);
#endif
