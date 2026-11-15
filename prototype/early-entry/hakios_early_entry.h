/* SPDX-License-Identifier: GPL-2.0 */
#ifndef HAKIOS_EARLY_ENTRY_H
#define HAKIOS_EARLY_ENTRY_H

#define HKE_MAGIC 0x31454c5241494b48
#define HKE_VERSION 1
#define HKE_BYTES 256
#define HKE_UNOBSERVED 0
#define HKE_EXECUTED 1
#define HKE_INVALID_DAIF 2
#define HKE_REASON_NONE 0
#define HKE_REASON_DAIF 1
#define HKE_PAYLOAD_MARKER 0x3143455845494b48

#define HKE_O_MAGIC 0
#define HKE_O_VERSION 8
#define HKE_O_BYTES 16
#define HKE_O_STATUS 24
#define HKE_O_REASON 32
#define HKE_O_X0 40
#define HKE_O_EL 72
#define HKE_O_ENTRY_PC 80
#define HKE_O_PAYLOAD_PC 88
#define HKE_O_CONTINUE_PC 96
#define HKE_O_SP 104
#define HKE_O_DAIF 112
#define HKE_O_CNTFRQ 120
#define HKE_O_MIDR 128
#define HKE_O_SCTLR 136
#define HKE_O_CTR 144
#define HKE_O_LINE_BYTES 152
#define HKE_O_VALUE 160
#define HKE_O_MARKER 168
#define HKE_O_LR 176
#define HKE_O_NZCV 184

#if !defined(__ASSEMBLY__) && !defined(__ASSEMBLER__)
#ifdef HKE_HOST_TEST
#include <stdint.h>
typedef uint64_t hke_u64;
#else
#include <linux/types.h>
typedef u64 hke_u64;
#endif
struct hakios_early_record {
	hke_u64 magic, version, bytes, status, reason;
	hke_u64 entry_x[4];
	hke_u64 current_el, entry_pc, payload_pc, continuation_pc, entry_sp;
	hke_u64 daif, cntfrq, midr, sctlr, ctr, cache_line_bytes;
	hke_u64 payload_value, payload_marker, entry_lr, nzcv;
	hke_u64 reserved[8];
};
extern struct hakios_early_record hakios_early_record;
#ifndef HKE_HOST_TEST
void hakios_early_report(void);
#endif
#endif
#endif
