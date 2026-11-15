// SPDX-License-Identifier: GPL-2.0
#define HKE_HOST_TEST 1
#include "hakios_early_entry.h"
#include <stddef.h>

extern uint64_t harness_registers[19];
extern void stext(void), hakios_early_tiny_payload(void), hakios_early_entry_continue(void);
_Static_assert(sizeof(struct hakios_early_record) == HKE_BYTES, "record extent");
_Static_assert(offsetof(struct hakios_early_record, current_el) == HKE_O_EL, "EL offset");
_Static_assert(offsetof(struct hakios_early_record, nzcv) == HKE_O_NZCV, "NZCV offset");
static unsigned checks, failures;
static void check(int ok) { ++checks; if (!ok) ++failures; }
static void uart_char(char c)
{
	volatile uint32_t *uart = (volatile uint32_t *)(uintptr_t)0x09000000;
	for (unsigned tries = 0; tries < 1000000; ++tries) {
		if (!(uart[6] & (1u << 5))) { uart[0] = (unsigned char)c; return; }
	}
}
static void uart(const char *s) { while (*s) uart_char(*s++); }
static void hex(const void *data, size_t n)
{
	const uint8_t *p = data;
	const char *digits = "0123456789abcdef";
	for (size_t i = 0; i < n; ++i) {
		uart_char(digits[p[i] >> 4]); uart_char(digits[p[i] & 15]);
	}
}
static void decimal(unsigned n)
{
	char buf[12]; unsigned used = 0;
	do { buf[used++] = (char)('0' + n % 10); n /= 10; } while (n);
	while (used) uart_char(buf[--used]);
}
void harness_main(void)
{
	uint64_t current_el;
	asm volatile("mrs %0, CurrentEL" : "=r"(current_el));
	const uint64_t expected[19] = {0x1010, 0x2020, 0x3030, 0x4040,
		0x1818, 0x1919, 0x2020, 0x2121, 0x2222, 0x2323, 0x2424,
		0x2525, 0x2626, 0x2727, 0x2828, 0x2929, 0x3030, 0, 0xa0000000};
	const struct hakios_early_record *r = &hakios_early_record;
	for (unsigned i = 0; i < 19; ++i) check(harness_registers[i] == expected[i]);
	check(r->magic == HKE_MAGIC && r->version == HKE_VERSION && r->bytes == HKE_BYTES);
#if HKE_CASE == 2 || HKE_CASE == 3
	check(r->status == HKE_UNOBSERVED);
	const uint64_t *words = (const uint64_t *)r;
	for (unsigned i = 3; i < 32; ++i) check(words[i] == 0);
#else
	for (unsigned i = 0; i < 4; ++i) check(r->entry_x[i] == expected[i]);
	check(r->current_el == current_el);
	check(r->entry_pc == (uintptr_t)stext);
	check(r->payload_pc == (uintptr_t)hakios_early_tiny_payload);
	check(r->continuation_pc == (uintptr_t)hakios_early_entry_continue);
	check(r->entry_sp == 0 && r->entry_lr == 0x3030 && r->nzcv == 0xa0000000);
	check(!(r->sctlr & 5));
	check(r->cache_line_bytes == (4ULL << ((r->ctr >> 16) & 15)));
	for (unsigned i = 0; i < 8; ++i) check(r->reserved[i] == 0);
#if HKE_CASE == 1
	check(r->status == HKE_INVALID_DAIF && r->reason == HKE_REASON_DAIF);
	check((r->daif & 0x3c0) == 0x340);
	check(r->payload_marker == 0 && r->payload_value == 0);
#else
	check(r->status == HKE_EXECUTED && r->reason == HKE_REASON_NONE);
	check((r->daif & 0x3c0) == 0x3c0);
	check(r->payload_marker == HKE_PAYLOAD_MARKER);
	uint64_t value = expected[0] ^ expected[1] ^ expected[2] ^ expected[3] ^ r->cntfrq ^ r->midr;
	value = (value >> 7) | (value << 57);
	check(r->payload_value == value);
#endif
#endif
	uart("HKE_TEST_V1 case="); decimal(HKE_CASE);
	uart(" el="); decimal((unsigned)(current_el >> 2));
	uart(" checks="); decimal(checks);
	uart(failures ? " result=FAIL\n" : " result=PASS\n");
	uart("RECORD "); hex(r, HKE_BYTES); uart("\n");
	uart("REGISTERS "); hex(harness_registers, sizeof harness_registers); uart("\n");
	/* QEMU PSCI shutdown only, unrelated to Samsung reset/Android return. */
	register uint64_t call asm("x0") = 0x84000008;
	if (current_el == 8)
		asm volatile("smc #0" : "+r"(call) : : "memory");
	else
		asm volatile("hvc #0" : "+r"(call) : : "memory");
}
