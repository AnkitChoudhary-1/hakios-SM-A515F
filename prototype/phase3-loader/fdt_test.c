/* SPDX-License-Identifier: MIT */
/* Host-only ASan/UBSan runner. Each input has an exact-sized allocation. */
#include "fdt_guard.h"
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>

int main(int argc, char **argv)
{
    if (argc < 3 || (argc - 1) % 2) return 2;
    unsigned checks = 0;
    for (int arg = 1; arg < argc; arg += 2) {
        FILE *file = fopen(argv[arg], "rb");
        if (!file || fseek(file, 0, SEEK_END)) return 2;
        long n = ftell(file);
        if (n < 0 || n > 2 * 1024 * 1024 || fseek(file, 0, SEEK_SET)) return 2;
        unsigned char *raw = malloc(n ? (size_t)n : 1);
        if (!raw || fread(raw, 1, (size_t)n, file) != (size_t)n) return 2;
        fclose(file);
        int expected = atoi(argv[arg + 1]);
        int actual = phase3_fdt_guard(raw, (uint32_t)n, UINT64_C(0x8a100000),
                                     UINT64_C(0x80000000), UINT64_C(0x83430000), UINT64_C(0x87000000));
        if (actual != expected) {
            fprintf(stderr, "FAIL %s expected=%d actual=%d\n", argv[arg], expected, actual);
            free(raw);
            return 1;
        }
        checks++;
        /* Every header prefix and a spread of interior truncations must reject. */
        if (expected) {
            for (uint32_t len = 0; len < (uint32_t)n; len += len < 48 ? 1 : 733) {
                unsigned char *short_raw = malloc(len ? len : 1);
                if (!short_raw) return 2;
                memcpy(short_raw, raw, len);
                if (phase3_fdt_guard(short_raw, len, UINT64_C(0x8a100000),
                                    UINT64_C(0x80000000), UINT64_C(0x83430000), UINT64_C(0x87000000))) {
                    fprintf(stderr, "FAIL accepted truncated FDT length=%u\n", len);
                    return 1;
                }
                free(short_raw);
                checks++;
            }
        }
        free(raw);
    }
    printf("FDT_SANITIZER_PASS checks=%u\n", checks);
    return 0;
}
