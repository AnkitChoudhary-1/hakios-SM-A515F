/* SPDX-License-Identifier: MIT */
#ifndef HAKIOS_XNU_TRAMPOLINE_H
#define HAKIOS_XNU_TRAMPOLINE_H

#define HKE_XNU_RECORD_MAGIC 0x32454c5241494b48ULL /* "HKIARL2" */
#define HKE_XNU_RECORD_VERSION 1
#define HKE_XNU_RECORD_BYTES 256

/* Trampoline and Boot Status Codes */
#define XNU_BOOT_STATUS_UNOBSERVED      0
#define XNU_BOOT_STATUS_TRAMPOLINE_INIT 1
#define XNU_BOOT_STATUS_PAYLOAD_LOADED  2
#define XNU_BOOT_STATUS_JUMPED_TO_XNU   3
#define XNU_BOOT_STATUS_CHECKPOINT_HIT  4
#define XNU_BOOT_STATUS_EARLY_EXCEPTION 5
#define XNU_BOOT_STATUS_PANIC_OR_EXIT   6
#define XNU_BOOT_STATUS_INVALID_STATE   7

/* Offsets in struct xnu_boot_record */
#define XBR_O_MAGIC                 0
#define XBR_O_VERSION               8
#define XBR_O_BYTES                 16
#define XBR_O_STATUS                24
#define XBR_O_REASON                32
#define XBR_O_CODE                  40
#define XBR_O_LOG_PA                48
#define XBR_O_LOG_LEN               56
#define XBR_O_ENTRY_EL              64
#define XBR_O_ENTRY_DAIF            72
#define XBR_O_ENTRY_SCTLR           80
#define XBR_O_ENTRY_CNTFRQ          88
#define XBR_O_ENTRY_MIDR            96
#define XBR_O_XNU_ENTRY_PC          104
#define XBR_O_XNU_BOOT_ARGS_PA      112
#define XBR_O_CHECKPOINT_REQ        120
#define XBR_O_RETURN_PC             128

#if !defined(__ASSEMBLY__) && !defined(__ASSEMBLER__)
#include <stdint.h>

struct xnu_boot_record {
    uint64_t magic;
    uint64_t version;
    uint64_t bytes;
    uint64_t status;
    uint64_t reason;
    uint64_t code;
    uint64_t log_pa;
    uint64_t log_len;
    uint64_t entry_el;
    uint64_t entry_daif;
    uint64_t entry_sctlr;
    uint64_t entry_cntfrq;
    uint64_t entry_midr;
    uint64_t xnu_entry_pc;
    uint64_t xnu_boot_args_pa;
    uint64_t checkpoint_requested;
    uint64_t return_pc;
    uint64_t reserved[15];
};

struct Boot_Video {
    uint64_t v_baseAddr;
    uint64_t v_display;
    uint64_t v_rowBytes;
    uint64_t v_width;
    uint64_t v_height;
    uint64_t v_depth;
};

#define BOOT_LINE_LENGTH 608

struct boot_args {
    uint16_t Revision;
    uint16_t Version;
    uint64_t virtBase;
    uint64_t physBase;
    uint64_t memSize;
    uint64_t topOfKernelData;
    struct Boot_Video Video;
    uint32_t machineType;
    void *deviceTreeP;
    uint32_t deviceTreeLength;
    char CommandLine[BOOT_LINE_LENGTH];
    uint64_t bootFlags;
    uint64_t memSizeActual;
};

extern struct xnu_boot_record xnu_boot_record;
#endif

#endif /* HAKIOS_XNU_TRAMPOLINE_H */

