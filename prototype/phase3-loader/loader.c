/* SPDX-License-Identifier: MIT */
/* Single-core, freestanding Phase 3 loader. No allocator, filesystem, UART
 * polling, GNSS writes or overlapping debug-snapshot mirrors. */
#include "loader.h"
#include "fdt_guard.h"

static volatile unsigned char *const console = (void *)(uintptr_t)(CONSOLE_PA + 12);
static volatile unsigned char *const pmsg = (void *)(uintptr_t)(0xf9e90000 + 12);
static uint32_t used;
static int publishing;
static uint32_t crc32(const unsigned char *p, uint64_t n)
{
    uint32_t crc = ~0u;
    for (uint64_t i = 0; i < n; i++) {
        crc ^= p[i];
        for (unsigned j = 0; j < 8; j++) crc = (crc >> 1) ^ (0xedb88320u & (0u - (crc & 1)));
    }
    return ~crc;
}
static int span(uint64_t a, uint64_t n, uint64_t lo, uint64_t hi)
{ return a >= lo && a <= hi && n <= hi - a; }
static int overlaps(uint64_t a, uint64_t n, uint64_t b, uint64_t m)
{ return n && m && a < b + m && b < a + n; }
static void barrier(void) { __asm__ volatile("dsb sy" ::: "memory"); }
#ifndef LOADER_QEMU
static uint64_t ticks(void) { uint64_t n; __asm__ volatile("mrs %0, CNTPCT_EL0" : "=r"(n)); return n; }
static uint32_t read32(uint64_t a) { return *(volatile uint32_t *)(uintptr_t)a; }
#endif
static void write32(uint64_t a, uint32_t n) { *(volatile uint32_t *)(uintptr_t)a = n; barrier(); }

static void put(char c) { if (used < CONSOLE_BYTES - 12) console[used++] = (unsigned char)c; }
static void text(const char *s) { for (unsigned i = 0; i < 1024 && s[i]; i++) put(s[i]); }
static void number(uint64_t n, unsigned base, unsigned width)
{
    char out[32]; unsigned i = 0;
    do { out[i++] = "0123456789abcdef"[n % base]; n /= base; } while (n && i < sizeof(out));
    while (i < width && i < sizeof(out)) out[i++] = '0';
    while (i) put(out[--i]);
}
static void field(const char *s, uint64_t n) { text(s); number(n, 16, 16); put(' '); }
static void nonce(void) { number(payload_config.nonce_hi, 16, 16); number(payload_config.nonce_lo, 16, 16); }
static void commit(void)
{
    /* Data first; complete header last. On warm recovery boot ramoops saves
     * the prior console before clearing it. This contract still needs silicon
     * persistence evidence; a source-backed address alone is insufficient. */
    barrier();
    /* The separately measured pmsg region is retained by recovery too.
     * Mirror only the bounded completed envelope, never GNSS or other RAM. */
    write32(0xf9e90000, 0);
    for (uint32_t i = 0; i < used; i++) pmsg[i] = console[i];
    barrier();
    write32(0xf9e90004, used);
    write32(0xf9e90008, used);
    write32(0xf9e90000, 0x43474244u);
    barrier();
    /* Publish console last: observers may stop as soon as it is complete. */
    write32(CONSOLE_PA + 4, used);
    write32(CONSOLE_PA + 8, used);
    write32(CONSOLE_PA, 0x43474244u);
    barrier();
}
static void envelope(uint64_t log_pa, uint64_t requested, uint64_t reason, uint64_t code)
{
    publishing = 1;
    write32(CONSOLE_PA, 0);
    used = 0;
    text("HAKIOS_P3_ENVELOPE_V1 nonce="); nonce();
    text(" stage="); number(loader_context.stage, 10, 0);
    text(" error="); number(loader_context.error, 10, 0);
    text(" reason="); number(reason, 10, 0); field(" code=0x", code);
    field("entry_el=0x", loader_context.entry_el); field("midr=0x", loader_context.midr);
    field("mpidr=0x", loader_context.mpidr); field("cntfrq=0x", loader_context.cntfrq);
    field("entry_sctlr=0x", loader_context.entry_sctlr); field("return_sctlr=0x", loader_context.return_sctlr);
    field("fdt=0x", loader_context.fdt);
    field("wdt_before=0x", loader_context.wdt_before); field("wdt_after=0x", loader_context.wdt_after);
    uint64_t copied = 0;
    int valid = requested <= MAX_KERNEL_LOG && requested <= payload_config.log_capacity &&
        log_pa == payload_config.log_pa && span(log_pa, requested, payload_config.kernel_base, payload_config.kernel_limit);
    if (valid) copied = requested;
    if (copied > CONSOLE_BYTES - 4096) copied = CONSOLE_BYTES - 4096;
    uint32_t crc = copied ? crc32((const unsigned char *)(uintptr_t)log_pa, copied) : 0;
    text(" log_valid="); number(valid, 10, 0);
    text(" requested="); number(requested, 10, 0);
    text(" copied="); number(copied, 10, 0);
    text(" crc32="); number(crc, 16, 8); put('\n');
    if (reason == 1) {
        text("HAKIOS_XNU_EARLY_FAULT "); field("esr=0x", code);
        field("elr=0x", loader_context.args[4]); field("far=0x", loader_context.args[5]);
        field("lr=0x", loader_context.args[6]); field("sp=0x", loader_context.args[7]); put('\n');
    }
    if (loader_fault_frame[0] == FAULT_MAGIC) {
        text("HAKIOS_LOADER_FAULT "); field("esr=0x", loader_fault_frame[33]);
        field("elr=0x", loader_fault_frame[34]); field("far=0x", loader_fault_frame[35]);
        field("sp=0x", loader_fault_frame[32]); field("sctlr=0x", loader_fault_frame[36]); put('\n');
        for (unsigned i = 0; i < 31; i++) {
            text("x"); number(i, 10, 0); text("=0x"); number(loader_fault_frame[i + 1], 16, 16);
            put(i % 4 == 3 ? '\n' : ' ');
        }
        put('\n');
    }
    text("HAKIOS_P3_LOG_BEGIN\n");
    for (uint64_t i = 0; i < copied; i++) put(((const unsigned char *)(uintptr_t)log_pa)[i]);
    text("\nHAKIOS_P3_LOG_END nonce="); nonce(); text(" crc32="); number(crc, 16, 8); put('\n');
    commit();
    publishing = 0;
}

static void recovery_reason(void)
{
#ifndef LOADER_QEMU
    uint32_t n = read32(0x11860808);
    write32(0x11860808, (n & ~0x00ff0000u) | 0x004e0000u);
    write32(0x1186080c, 0x12345674u);
    write32(0x11860810, 0xffu);
#endif
}
static void watchdog(void)
{
#ifndef LOADER_QEMU
    /* Source-backed cluster 0 PMU reset masks and PERI Q-channel clock
     * request. Count down observation and actual watchdog reset are separate
     * evidence predicates. No Linux/ACPM watchdog petting is assumed. */
    write32(0x11860408, read32(0x11860408) & ~(1u << 23));
    write32(0x1186040c, read32(0x1186040c) & ~(1u << 23));
    write32(0x10033068, (read32(0x10033068) & ~7u) | 6u);
    write32(0x10050000, 0);
    write32(0x1005000c, 1);
    uint32_t count = payload_config.watchdog_count <= 65535 && payload_config.watchdog_count >= 100 ? payload_config.watchdog_count : 65535;
    write32(0x10050004, count);
    write32(0x10050008, count);
    write32(0x10050000, 0xff39u);
    loader_context.wdt_before = read32(0x10050008);
    uint64_t start = ticks();
    for (uint32_t i = 0; i < 1000000 && ticks() - start < loader_context.cntfrq / 100; i++) __asm__ volatile("yield");
    loader_context.wdt_after = read32(0x10050008);
#endif
}
static void finish(void) __attribute__((noreturn));
static void finish(void)
{
    barrier();
#ifdef LOADER_QEMU
    /* Host observes the same emitted envelope. Hardware reset MMIO is the
     * sole excluded part of this QEMU build. */
    for (;;) __asm__ volatile("wfe");
#else
    recovery_reason();
    /* DFD debug-reset suppression must not intercept the software reset. */
    uint32_t n = read32(0x11860500);
    /* exynos-reboot.c: the clear bits are commands, not state bits to mask
     * out. dfd_set_dump_gpr(0) writes DFD_EDPCSR_DUMP_EN | four CLEAR bits. */
    if (n & 1u) write32(0x11860500, 0xf1u);
    write32(0x11860400, 1);
    /* Independently armed watchdog remains active if direct PMU reset fails.
     * ACPM shutdown is unproved until this diagnostic returns on hardware. */
    for (;;) __asm__ volatile("wfe");
#endif
}
static void fail(uint64_t error) __attribute__((noreturn));
static void fail(uint64_t error)
{
    loader_context.error = error;
    envelope(0, 0, 4, error);
    finish();
}

static int validate(void)
{
    const struct loader_config *c = &payload_config;
    if (c->magic != CONFIG_MAGIC || c->version != 1 || !c->count || c->count > MAX_TOC ||
        c->payload_bytes != (uint64_t)(payload_end - payload_base) ||
        c->count * sizeof(struct toc_entry) != (uint64_t)(payload_toc_end - (const unsigned char *)payload_toc) ||
        !span((uint64_t)(uintptr_t)payload_base, c->payload_bytes, IMAGE_BASE, IMAGE_BASE + IMAGE_BYTES) ||
        c->arena_base < IMAGE_BASE + IMAGE_BYTES || c->arena_limit > 0x87000000 || c->arena_base >= c->arena_limit ||
        c->kernel_base < c->arena_base || c->kernel_limit > c->arena_limit || c->kernel_base >= c->kernel_limit ||
        !span(c->entry, 4, c->kernel_base, c->kernel_limit) ||
        !span(c->bootargs, 736, c->arena_base, c->arena_limit) ||
        !span(c->stub_slot, 32, c->kernel_base, c->kernel_limit) ||
        !span(c->log_pa, c->log_capacity, c->kernel_base, c->kernel_limit) || c->log_capacity != MAX_KERNEL_LOG ||
        !span(c->log_len_pa, 4, c->kernel_base, c->kernel_limit)) return 0;
    for (uint64_t i = 0; i < c->count; i++) {
        const struct toc_entry *e = &payload_toc[i];
        if (e->reserved || e->copy > c->payload_bytes || !span(e->source, e->copy, 0, c->payload_bytes) ||
            e->zero > UINT64_MAX - e->copy || (e->copy == 0 && e->zero == 0) ||
            !span(e->destination, e->copy + e->zero, c->arena_base, c->arena_limit) ||
            crc32(payload_base + e->source, e->copy) != e->crc) return 0;
        for (uint64_t j = 0; j < i; j++) {
            const struct toc_entry *p = &payload_toc[j];
            if (overlaps(e->destination, e->copy + e->zero, p->destination, p->copy + p->zero)) return 0;
        }
    }
    return 1;
}

void loader_main(void)
{
    loader_context.stage = 1;
    envelope(0, 0, 5, 0);
    recovery_reason();
    watchdog();
    loader_context.stage = 2;
    envelope(0, 0, 5, 0);
    if (payload_config.diagnostic == DIAG_RESET) {
        loader_context.stage = 3; envelope(0, 0, 3, DIAG_RESET); finish();
    }
    if (payload_config.diagnostic == DIAG_WATCHDOG) {
        loader_context.stage = 3; envelope(0, 0, 3, DIAG_WATCHDOG);
        for (;;) __asm__ volatile("wfe");
    }
    if (payload_config.diagnostic == DIAG_FAULT) __asm__ volatile("brk #0x353");
    /* Diagnostics touch no payload destination. Full runs still validate
     * every input before the first copy. */
    if (!validate()) fail(1);
    if (!span(loader_context.fdt, 40, 0x80000000, 0x100000000) ||
        !phase3_fdt_guard((const void *)(uintptr_t)loader_context.fdt, 2 * 1024 * 1024,
                         loader_context.fdt, 0x80000000,
                         payload_config.arena_base, payload_config.arena_limit)) fail(2);
    for (uint64_t i = 0; i < payload_config.count; i++) {
        const struct toc_entry *e = &payload_toc[i];
        unsigned char *dst = (void *)(uintptr_t)e->destination;
        for (uint64_t j = 0; j < e->copy; j++) dst[j] = payload_base[e->source + j];
        for (uint64_t j = 0; j < e->zero; j++) dst[e->copy + j] = 0;
    }
    volatile uint64_t *slot = (void *)(uintptr_t)payload_config.stub_slot;
    if (slot[0] != UINT64_C(0x545352444c554e58)) fail(3);
    slot[1] = (uint64_t)(uintptr_t)loader_return_stub;
    slot[2] = payload_config.checkpoint;
    slot[3] = payload_config.slide;
    barrier();
    loader_context.stage = 4;
    envelope(0, 0, 5, 0);
    loader_branch(payload_config.entry, payload_config.bootargs);
}
void loader_return_main(void)
{
    loader_context.stage = 5;
    envelope(loader_context.args[0], loader_context.args[1], loader_context.args[2], loader_context.args[3]);
    finish();
}
void loader_fault_main(void)
{
    if (publishing) finish(); /* A nested output fault must not recurse. */
    loader_context.error = 9;
    envelope(0, 0, 6, loader_fault_frame[33]);
    finish();
}
