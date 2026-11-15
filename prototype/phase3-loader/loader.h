/* SPDX-License-Identifier: MIT */
#ifndef HAKIOS_PHASE3_LOADER_H
#define HAKIOS_PHASE3_LOADER_H
#ifndef __ASSEMBLER__
#include <stdint.h>
#include <stddef.h>
#define CONFIG_MAGIC UINT64_C(0x33444c534f494b48)
#define FAULT_MAGIC UINT64_C(0x33544c464f494b48)
#define IMAGE_BASE UINT64_C(0x80080000)
#define IMAGE_BYTES UINT64_C(36334080)
#define MAX_TOC 64
#define MAX_KERNEL_LOG (1536u * 1024u)
#define CONSOLE_PA UINT64_C(0xf9d90000)
#define CONSOLE_BYTES (512u * 1024u)
#define DIAG_RESET 1
#define DIAG_WATCHDOG 2
#define DIAG_FAULT 3

struct loader_config {
    uint64_t magic, version, count, payload_bytes;
    uint64_t arena_base, arena_limit, entry, bootargs;
    uint64_t stub_slot, slide, checkpoint, diagnostic;
    uint64_t kernel_base, kernel_limit, log_pa, log_capacity;
    uint64_t log_len_pa, watchdog_count, nonce_hi, nonce_lo;
};
struct toc_entry { uint64_t source, destination, copy, zero, crc, reserved; };
/* Return registers x0..x8, LR, incoming SCTLR, then entry-state registers. */
struct loader_context {
    uint64_t args[9], lr, return_sctlr;
    uint64_t fdt, entry_el, entry_daif, entry_sctlr, cntfrq, midr, mpidr;
    uint64_t stage, error, wdt_before, wdt_after;
};
extern const struct loader_config payload_config;
extern const struct toc_entry payload_toc[];
extern const unsigned char payload_toc_end[];
extern const unsigned char payload_base[], payload_end[];
extern struct loader_context loader_context;
extern uint64_t loader_fault_frame[40];
extern unsigned char loader_stack_top[];
extern void loader_return_stub(void);
extern void loader_vectors(void);
extern void loader_branch(uint64_t entry, uint64_t bootargs) __attribute__((noreturn));
void loader_main(void) __attribute__((noreturn));
void loader_return_main(void) __attribute__((noreturn));
void loader_fault_main(void) __attribute__((noreturn));
#endif
#endif
