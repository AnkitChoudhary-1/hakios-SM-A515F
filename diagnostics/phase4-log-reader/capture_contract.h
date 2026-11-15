/* SPDX-License-Identifier: GPL-2.0 */
#ifndef HAKIOS_PHASE4_CAPTURE_CONTRACT_H
#define HAKIOS_PHASE4_CAPTURE_CONTRACT_H

#define HK4_RECORD_BYTES 256U
#define HK4_LOG_HEADER_BYTES 32U
#define HK4_MAX_LOG 65536U
#define HK4_RECORD_MAGIC 0x32454c5241494b48ULL
#define HK4_LOG_MAGIC 0x3150474c344b4848ULL

/* Decode without unaligned loads or dependence on host byte order. */
static inline unsigned long long hk4_u64(const unsigned char *p)
{
    unsigned long long value = 0;
    unsigned int i;
    for (i = 0; i < 8; ++i)
        value |= (unsigned long long)p[i] << (8 * i);
    return value;
}

static inline int hk4_current_record(const unsigned char *record,
                                     unsigned long long nonce_hi,
                                     unsigned long long nonce_lo)
{
    return (nonce_hi || nonce_lo) &&
        hk4_u64(record) == HK4_RECORD_MAGIC &&
        hk4_u64(record + 8) == 1 &&
        hk4_u64(record + 16) == HK4_RECORD_BYTES &&
        hk4_u64(record + 24) <= 8 &&
        hk4_u64(record + 136) == nonce_hi &&
        hk4_u64(record + 144) == nonce_lo;
}

/* The saved source address is checked only as metadata and never followed. */
static inline int hk4_committed_log(const unsigned char *record,
                                    const unsigned char *header,
                                    unsigned long long capacity,
                                    unsigned long long nonce_hi,
                                    unsigned long long nonce_lo)
{
    unsigned long long copied = hk4_u64(header + 8);
    unsigned long long declared = hk4_u64(header + 16);
    unsigned long long status = hk4_u64(record + 24);
    unsigned long long source = hk4_u64(record + 48);
    if (!hk4_current_record(record, nonce_hi, nonce_lo) ||
        capacity > HK4_MAX_LOG || hk4_u64(header) != HK4_LOG_MAGIC ||
        status < 4 || status > 7 || hk4_u64(header + 24) != status ||
        declared != hk4_u64(record + 56) || copied > declared ||
        copied > capacity)
        return 0;
    if (copied && (source < 0x83000000ULL || source >= 0x847f0000ULL ||
                   declared > 0x847f0000ULL - source))
        return 0;
    return 1;
}
#endif
