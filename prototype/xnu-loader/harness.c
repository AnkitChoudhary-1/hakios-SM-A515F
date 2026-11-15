// SPDX-License-Identifier: MIT
#include "xnu_trampoline.h"
#include <stddef.h>
#include <stdint.h>

#ifndef TEST_CASE
#define TEST_CASE 0
#endif

extern uint64_t xnu_trampoline_config[6];
extern struct xnu_boot_record xnu_boot_record;
extern void harness_trampoline_continue(void);
extern void xnu_loader_return_stub(uint64_t, uint64_t, uint64_t, uint64_t);

/* Flattened Apple Device Tree blob embedded via linker */
extern uint8_t dt_blob_start[];
extern uint8_t dt_blob_end[];

/* 28 KB aligned storage for the real XNU slice when TEST_CASE >= 1 */
#if TEST_CASE >= 1
extern uint8_t xnu_slice_start[];
#endif

/* Mock loader stub slot for TEST_CASE 0 */
#if TEST_CASE == 0
static uint64_t mock_stub_slot[4] __attribute__((aligned(8))) = {
    0x545352444C554E58ULL, /* "XNULDRST" */
    0,                     /* stub PA */
    0,                     /* checkpoint */
    0                      /* slide */
};
#endif

/* Test boot_args structure */
static struct boot_args test_boot_args __attribute__((section(".data.boot_args"), aligned(64)));

static unsigned checks, failures;

static void uart_char(char c) {
    volatile uint32_t *uart = (volatile uint32_t *)(uintptr_t)0x09000000;
    for (unsigned tries = 0; tries < 1000000; ++tries) {
        if (!(uart[6] & (1u << 5))) {
            uart[0] = (unsigned char)c;
            return;
        }
    }
}

static void uart(const char *s) {
    while (*s) uart_char(*s++);
}

static void check_msg(int ok, const char *msg) {
    ++checks;
    if (!ok) {
        ++failures;
        uart("FAIL_CHECK: ");
        uart(msg);
        uart("\n");
    }
}
#define check(cond) check_msg((cond), #cond)

static void hex(const void *data, size_t n) {
    const uint8_t *p = data;
    const char *digits = "0123456789abcdef";
    for (size_t i = 0; i < n; ++i) {
        uart_char(digits[p[i] >> 4]);
        uart_char(digits[p[i] & 15]);
    }
}

static void decimal(unsigned n) {
    char buf[12];
    unsigned used = 0;
    do {
        buf[used++] = (char)('0' + n % 10);
        n /= 10;
    } while (n);
    while (used) uart_char(buf[--used]);
}

#if TEST_CASE == 0
void mock_xnu_entry(void *ba) {
    uint64_t cur_el, daif, sctlr;
    __asm__ volatile("mrs %0, CurrentEL" : "=r"(cur_el));
    __asm__ volatile("mrs %0, DAIF" : "=r"(daif));
    __asm__ volatile("mrs %0, SCTLR_EL1" : "=r"(sctlr));

    check(ba == &test_boot_args);
    check((cur_el >> 2) == 1);
    check((daif & 0x3c0) == 0x3c0);
    check(!(sctlr & 1));

    /* Verify device tree pointers and properties passed in boot_args */
    check(test_boot_args.deviceTreeP == &dt_blob_start[0]);
    check(test_boot_args.deviceTreeLength > 8192);

    const uint32_t *dt_header = (const uint32_t *)test_boot_args.deviceTreeP;
    check(dt_header[0] > 0); /* nProperties > 0 */
    check(dt_header[1] > 0); /* nChildren > 0 */

    /* Simulate XNU checkpoint 1 hit: reason = 2, code = 1 */
    xnu_loader_return_stub(0, 0, 2, 1);
}
#endif

void harness_setup(void) {
    /* Zero entire boot_args struct */
    uint8_t *ba_raw = (uint8_t *)&test_boot_args;
    for (size_t i = 0; i < sizeof(test_boot_args); ++i) {
        ba_raw[i] = 0;
    }

    /* Calculate device tree size */
    uint32_t dt_size = (uint32_t)(&dt_blob_end[0] - &dt_blob_start[0]);

    /* Populate test_boot_args matching Darwin kernel contract */
    test_boot_args.Revision = 2;
    test_boot_args.Version = 2;
    test_boot_args.virtBase = 0xFFFFFFF004000000ULL;
    test_boot_args.physBase = 0x40000000ULL;
    test_boot_args.memSize = 0x40000000ULL;
    test_boot_args.topOfKernelData = 0x45000000ULL;
    test_boot_args.deviceTreeP = (void *)(uintptr_t)&dt_blob_start[0];
    test_boot_args.deviceTreeLength = dt_size;
    test_boot_args.bootFlags = 0;
    test_boot_args.memSizeActual = 0x40000000ULL;

    const char *cmd = "-v serial=3 cpus=1 rd=md0 debug=0x144";
    for (int i = 0; cmd[i] && i < BOOT_LINE_LENGTH - 1; ++i) {
        test_boot_args.CommandLine[i] = cmd[i];
    }

#if TEST_CASE == 0
    xnu_trampoline_config[0] = (uint64_t)(uintptr_t)&mock_xnu_entry;
    xnu_trampoline_config[1] = (uint64_t)(uintptr_t)&test_boot_args;
    xnu_trampoline_config[2] = (uint64_t)(uintptr_t)&mock_stub_slot[0];
    xnu_trampoline_config[3] = 1; /* checkpoint 1 */
    xnu_trampoline_config[4] = 0; /* slide */
    xnu_trampoline_config[5] = (uint64_t)(uintptr_t)&harness_trampoline_continue;
#elif TEST_CASE == 1
    /* Real XNU entry slice, checkpoint 1 */
    xnu_trampoline_config[0] = (uint64_t)(uintptr_t)&xnu_slice_start[0x205c]; /* start_first_cpu */
    xnu_trampoline_config[1] = (uint64_t)(uintptr_t)&test_boot_args;
    xnu_trampoline_config[2] = (uint64_t)(uintptr_t)&xnu_slice_start[0x7f0];  /* loader_stub_slot */
    xnu_trampoline_config[3] = 1; /* checkpoint 1 */
    xnu_trampoline_config[4] = 0; /* slide */
    xnu_trampoline_config[5] = (uint64_t)(uintptr_t)&harness_trampoline_continue;
#elif TEST_CASE == 2
    /* Real XNU entry slice, checkpoint 2 */
    xnu_trampoline_config[0] = (uint64_t)(uintptr_t)&xnu_slice_start[0x205c]; /* start_first_cpu */
    xnu_trampoline_config[1] = (uint64_t)(uintptr_t)&test_boot_args;
    xnu_trampoline_config[2] = (uint64_t)(uintptr_t)&xnu_slice_start[0x7f0];  /* loader_stub_slot */
    xnu_trampoline_config[3] = 2; /* checkpoint 2 */
    xnu_trampoline_config[4] = 0; /* slide */
    xnu_trampoline_config[5] = (uint64_t)(uintptr_t)&harness_trampoline_continue;
#endif
}

void harness_finish(void) {
    const struct xnu_boot_record *r = &xnu_boot_record;
    uint32_t expected_checkpoint = (TEST_CASE == 2) ? 2 : 1;

    check(r->magic == HKE_XNU_RECORD_MAGIC);
    check(r->version == HKE_XNU_RECORD_VERSION);
    check(r->bytes == HKE_XNU_RECORD_BYTES);
    check(r->status == XNU_BOOT_STATUS_CHECKPOINT_HIT);
    check(r->reason == 2); /* Checkpoint reason */
    check(r->code == expected_checkpoint);
    check(r->entry_el == 1);
    check(r->xnu_boot_args_pa == (uint64_t)(uintptr_t)&test_boot_args);
    check(r->checkpoint_requested == expected_checkpoint);
    check(test_boot_args.deviceTreeP == &dt_blob_start[0]);
    check(test_boot_args.deviceTreeLength > 8192);

    uart("XNU_TEST case="); decimal(TEST_CASE);
    uart(" el="); decimal((unsigned)r->entry_el);
    uart(" checks="); decimal(checks);
    uart(failures ? " result=FAIL\n" : " result=PASS\n");
    uart("RECORD "); hex(r, HKE_XNU_RECORD_BYTES); uart("\n");
}
