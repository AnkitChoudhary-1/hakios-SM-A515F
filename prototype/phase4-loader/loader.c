/* SPDX-License-Identifier: MIT */
/* Single-core, freestanding Phase 4 loader. No allocator, filesystem, UART
 * polling, GNSS writes or overlapping debug-snapshot mirrors. */
#include "loader.h"
#include "fdt_guard.h"
#include "validate.h"
#define crc32 phase4_crc32
#define span phase4_span

static volatile unsigned char *const console = (void *)(uintptr_t)(CONSOLE_PA + 12);
static volatile unsigned char *const pmsg = (void *)(uintptr_t)(0xf9e90000 + 12);
static uint32_t used;
static int publishing;
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
    text("HAKIOS_P4_ENVELOPE_V1 nonce="); nonce();
    text(" stage="); number(loader_context.stage, 10, 0);
    text(" error="); number(loader_context.error, 10, 0);
    text(" reason="); number(reason, 10, 0); field(" code=0x", code);
    field("entry_el=0x", loader_context.entry_el); field("midr=0x", loader_context.midr);
    field("mpidr=0x", loader_context.mpidr); field("cntfrq=0x", loader_context.cntfrq);
    field("entry_sctlr=0x", loader_context.entry_sctlr); field("return_sctlr=0x", loader_context.return_sctlr);
    field("entry_daif=0x", loader_context.entry_daif);
    field("runtime_base=0x", loader_context.runtime_base);
    field("fdt=0x", loader_context.fdt);
    field("wdt_before=0x", loader_context.wdt_before); field("wdt_after=0x", loader_context.wdt_after);
    field("validated=0x", loader_context.validated);
    field("copy_entries=0x", loader_context.copy_entries);
    field("copied_bytes=0x", loader_context.copied_bytes);
    field("zeroed_bytes=0x", loader_context.zeroed_bytes);
    uint64_t copied = 0;
    int valid = loader_context.validated && requested <= MAX_KERNEL_LOG && requested <= payload_config.log_capacity &&
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
    text("HAKIOS_P4_LOG_BEGIN\n");
    for (uint64_t i = 0; i < copied; i++) put(((const unsigned char *)(uintptr_t)log_pa)[i]);
    text("\nHAKIOS_P4_LOG_END nonce="); nonce(); text(" crc32="); number(crc, 16, 8); put('\n');
    uint32_t envelope_crc = crc32((const unsigned char *)console, used);
    text("HAKIOS_P4_ENVELOPE_CRC32="); number(envelope_crc, 16, 8); put('\n');
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

void loader_main(void)
{
    loader_context.stage = 1;
    envelope(0, 0, 5, 0);
    int error = phase4_validate(&payload_config, payload_toc,
        (uint64_t)(payload_toc_end - (const unsigned char *)payload_toc),
        payload_base, (uint64_t)(payload_end - payload_base),
        (uint64_t)(uintptr_t)_start, (uint64_t)(uintptr_t)payload_base);
    if (error) fail((uint64_t)error);
#ifndef LOADER_QEMU
    if (payload_config.diagnostic == DIAG_COPY) fail(VALID_CONFIG);
#endif
    if (!span(loader_context.fdt, 40, 0x80000000, 0x100000000) ||
        !phase4_fdt_guard((const void *)(uintptr_t)loader_context.fdt, 2 * 1024 * 1024,
                         loader_context.fdt, 0x80000000, ARENA_BASE,
                         INITIAL_MEMORY_LIMIT, loader_context.runtime_base)) fail(VALID_FDT);
    loader_context.validated = 1;
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
    /* Every CRC, bound and source-backed entry/BootArgs/return-slot check
     * completed above, before the first destination write. */
    for (uint64_t i = 0; i < payload_config.count; i++) {
        const struct toc_entry *e = &payload_toc[i];
        unsigned char *dst = (void *)(uintptr_t)e->destination;
        for (uint64_t j = 0; j < e->copy; j++) dst[j] = payload_base[e->source + j];
        for (uint64_t j = 0; j < e->zero; j++) dst[e->copy + j] = 0;
        loader_context.copy_entries++;
        loader_context.copied_bytes += e->copy;
        loader_context.zeroed_bytes += e->zero;
    }
    volatile uint64_t *slot = (void *)(uintptr_t)payload_config.stub_slot;
    slot[1] = (uint64_t)(uintptr_t)loader_return_stub;
    slot[2] = payload_config.checkpoint;
    slot[3] = payload_config.slide;
    barrier();
    loader_context.stage = 4;
    envelope(0, 0, 5, 0);
#ifdef LOADER_QEMU
    if (payload_config.diagnostic == DIAG_COPY) {
        envelope(0, 0, 7, DIAG_COPY);
        finish();
    }
#endif
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
