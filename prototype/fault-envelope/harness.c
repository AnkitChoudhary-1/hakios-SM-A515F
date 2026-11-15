// SPDX-License-Identifier: GPL-2.0
#include <stdint.h>
#include <stddef.h>
extern uint64_t hkf_record[64], fixture_registers[24];
extern uint64_t fixture_record_before[64], fixture_record_after[64];
static void put(char c)
{
    volatile uint32_t *uart = (volatile uint32_t *)(uintptr_t)0x09000000;
    for (unsigned n = 0; n < 1000000; ++n)
        if (!(uart[6] & (1u << 5))) { uart[0] = (unsigned char)c; return; }
}
static void text(const char *s) { while (*s) put(*s++); }
static void packet(const void *data, size_t size)
{
    const unsigned char *p = data;
    const char *digits = "0123456789abcdef";
    for (size_t i = 0; i < size; ++i) {
        put(digits[p[i] >> 4]); put(digits[p[i] & 15]);
    }
    put('\n');
}
void fixture_main(void)
{
    text("HKF_CONTINUED_V1\nRECORD "); packet(hkf_record, sizeof hkf_record);
    text("REGISTERS "); packet(fixture_registers, sizeof fixture_registers);
    text("BEFORE "); packet(fixture_record_before, sizeof fixture_record_before);
    text("AFTER "); packet(fixture_record_after, sizeof fixture_record_after);
    uint64_t el;
    __asm__ volatile("mrs %0, CurrentEL" : "=r"(el));
    register uint64_t call __asm__("x0") = 0x84000008;
    if (el == 8) __asm__ volatile("smc #0" : "+r"(call) : : "memory");
    else __asm__ volatile("hvc #0" : "+r"(call) : : "memory");
}
