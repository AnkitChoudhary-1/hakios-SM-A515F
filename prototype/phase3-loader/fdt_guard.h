/* SPDX-License-Identifier: MIT */
#ifndef HAKIOS_PHASE3_FDT_GUARD_H
#define HAKIOS_PHASE3_FDT_GUARD_H
#include <stdint.h>
/* Checks the supplied bytes without modifying them. available bounds every
 * read; physical is used only for the preserved-FDT overlap check. */
int phase3_fdt_guard(const unsigned char *f, uint32_t available,
                    uint64_t physical, uint64_t dram_base,
                    uint64_t arena_base, uint64_t arena_limit);
#endif
