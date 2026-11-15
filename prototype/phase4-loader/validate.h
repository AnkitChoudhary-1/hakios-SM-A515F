/* SPDX-License-Identifier: MIT */
#ifndef HAKIOS_PHASE4_VALIDATE_H
#define HAKIOS_PHASE4_VALIDATE_H
#include "loader.h"
enum validation_error {
    VALID_OK = 0, VALID_CONFIG = 1, VALID_LAYOUT = 2, VALID_TOC = 3,
    VALID_CRC = 4, VALID_BACKING = 5, VALID_SLOT = 6, VALID_FDT = 7,
};
uint32_t phase4_crc32(const unsigned char *p, uint64_t n);
int phase4_span(uint64_t a, uint64_t n, uint64_t lo, uint64_t hi);
int phase4_overlap(uint64_t a, uint64_t n, uint64_t b, uint64_t m);
int phase4_validate(const struct loader_config *c, const struct toc_entry *toc,
                    uint64_t toc_bytes, const unsigned char *payload,
                    uint64_t payload_bytes, uint64_t runtime_base, uint64_t payload_pa);
#endif
