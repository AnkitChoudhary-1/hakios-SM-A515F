/* SPDX-License-Identifier: GPL-2.0 */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "capture_contract.h"
static unsigned char record[HK4_RECORD_BYTES], header[HK4_LOG_HEADER_BYTES];
static unsigned int checks;
static void put(unsigned char *p, unsigned long long n)
{
    unsigned int i;
    for (i = 0; i < 8; ++i)
        p[i] = n >> (8 * i);
}
static void check(int ok) { ++checks; assert(ok); }
static void reset(void)
{
    memset(record, 0, sizeof(record));
    memset(header, 0, sizeof(header));
    put(record, HK4_RECORD_MAGIC); put(record + 8, 1);
    put(record + 16, HK4_RECORD_BYTES); put(record + 24, 6);
    put(record + 48, 0x83000000); put(record + 56, 65536);
    put(record + 136, 0x1122334455667788ULL); put(record + 144, 0x8877665544332211ULL);
    put(header, HK4_LOG_MAGIC); put(header + 8, 65536);
    put(header + 16, 65536); put(header + 24, 6);
}
static int valid(unsigned long long cap)
{
    return hk4_committed_log(record, header, cap, 0x1122334455667788ULL, 0x8877665544332211ULL);
}
int main(void)
{
    unsigned int i;
    reset(); check(valid(65536)); check(!valid(400));
    put(header + 8, 400); check(valid(400));
    put(header + 8, 401); check(!valid(400));
    reset(); put(header, 0); check(!valid(65536));
    reset(); put(record + 48, 0x847effff); check(!valid(65536));
    reset(); put(record + 48, ~0ULL - 1024); check(!valid(65536));
    reset(); put(record + 48, 0x82ffffff); check(!valid(65536));
    reset(); put(header + 16, ~0ULL); check(!valid(65536));
    reset(); put(header + 8, 65537); check(!valid(65536));
    reset(); put(record + 56, 65535); put(header + 16, 65535); check(!valid(65536));
    reset(); put(header + 24, 5); check(!valid(65536));
    reset(); put(record + 24, 8); put(header + 24, 8); check(!valid(65536));
    reset(); check(!hk4_current_record(record, 0, 0));
    reset(); check(!hk4_current_record(record, 1, 2));
    for (i = 0; i < 256; ++i) {
        reset(); record[136 + i % 16] ^= 1U << (i % 8);
        check(!valid(65536));
    }
    reset(); put(record + 48, 0x847f0000); put(record + 56, 0);
    put(header + 8, 0); put(header + 16, 0); check(valid(65536));
    reset(); put(record + 48, 0x847e0000); check(valid(65536));
    printf("HAKIOS_P4_CAPTURE_CONTRACT checks=%u pass=1\n", checks);
    return 0;
}
