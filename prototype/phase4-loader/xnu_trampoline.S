/* SPDX-License-Identifier: MIT */
#define __ASSEMBLY__ 1
#include "xnu_trampoline.h"

    .section .data.record, "aw", %progbits
    .align 6
    .global xnu_boot_record
xnu_boot_record:
    .quad   HKE_XNU_RECORD_MAGIC        // magic
    .quad   HKE_XNU_RECORD_VERSION      // version
    .quad   HKE_XNU_RECORD_BYTES        // bytes (256)
    .quad   XNU_BOOT_STATUS_UNOBSERVED  // status
    .quad   0                           // reason
    .quad   0                           // code
    .quad   0                           // log_pa
    .quad   0                           // log_len
    .quad   0                           // entry_el
    .quad   0                           // entry_daif
    .quad   0                           // entry_sctlr
    .quad   0                           // entry_cntfrq
    .quad   0                           // entry_midr
    .quad   0                           // xnu_entry_pc
    .quad   0                           // xnu_boot_args_pa
    .quad   0                           // checkpoint_requested
    .quad   0                           // return_pc
    .space  (15 * 8), 0                 // reserved to 256 bytes

#ifndef XNU_CONFIG_EXTERNAL
    .section .data.config, "aw", %progbits
    .align 3
    .global xnu_trampoline_config
xnu_trampoline_config:
    .quad   0                           // offset 0:  target_entry_pc
    .quad   0                           // offset 8:  boot_args_pa
    .quad   0                           // offset 16: loader_stub_slot_pa
    .quad   1                           // offset 24: checkpoint (default 1)
    .quad   0                           // offset 32: slide (physBase - virtBase)
    .quad   0                           // offset 40: continue_pc (0 = return via RET)
#endif

    .section .text.trampoline, "ax", %progbits
    .align 3
    .global xnu_trampoline_entry
xnu_trampoline_entry:
    // Preserve caller link register
    mov     x17, lr

    // Record incoming silicon state into xnu_boot_record
    adrp    x10, xnu_boot_record
    add     x10, x10, :lo12:xnu_boot_record

    mrs     x4, CurrentEL
    lsr     x4, x4, #2
    str     x4, [x10, #XBR_O_ENTRY_EL]

    mrs     x5, DAIF
    str     x5, [x10, #XBR_O_ENTRY_DAIF]

    mrs     x6, SCTLR_EL1
    str     x6, [x10, #XBR_O_ENTRY_SCTLR]

    mrs     x7, CNTFRQ_EL0
    str     x7, [x10, #XBR_O_ENTRY_CNTFRQ]

    mrs     x8, MIDR_EL1
    str     x8, [x10, #XBR_O_ENTRY_MIDR]

    mov     x4, #XNU_BOOT_STATUS_TRAMPOLINE_INIT
    str     x4, [x10, #XBR_O_STATUS]

    // Read trampoline configuration
    adrp    x11, xnu_trampoline_config
    add     x11, x11, :lo12:xnu_trampoline_config

    ldr     x12, [x11, #0]              // target_entry_pc
    ldr     x13, [x11, #8]              // boot_args_pa
    ldr     x14, [x11, #16]             // loader_stub_slot_pa
    ldr     x15, [x11, #24]             // checkpoint
    ldr     x16, [x11, #32]             // slide

    str     x12, [x10, #XBR_O_XNU_ENTRY_PC]
    str     x13, [x10, #XBR_O_XNU_BOOT_ARGS_PA]
    str     x15, [x10, #XBR_O_CHECKPOINT_REQ]

    bl phase4_publish_record

    // Check if loader_stub_slot_pa is provided
    cbz     x14, .Lskip_stub_patch

    // Verify magic 'XNULDRST'
    ldr     x4, [x14]
    ldr     x5, =0x545352444C554E58      // "XNULDRST"
    cmp     x4, x5
    b.ne    .Lbad_slot_magic

    // Install return stub physical address, checkpoint, and slide
    adrp    x6, xnu_loader_return_stub
    add     x6, x6, :lo12:xnu_loader_return_stub
    str     x6, [x14, #8]               // stub PA
    str     x15, [x14, #16]             // checkpoint
    str     x16, [x14, #24]             // slide

    // Clean D-cache over stub slot so RAM is up to date
    dc      cvac, x14
    dsb     sy
    isb

.Lskip_stub_patch:
    // Update status to JUMPED_TO_XNU
    mov     x4, #XNU_BOOT_STATUS_JUMPED_TO_XNU
    str     x4, [x10, #XBR_O_STATUS]

    bl phase4_publish_record

    // Clean D-cache over record
    dc      cvac, x10
    dsb     sy

    // Ensure instruction cache is invalidated
    ic      iallu
    dsb     sy
    isb

    // Prepare XNU entry register contract:
    // x0 = Physical address of struct boot_args
    // DAIF = 0x3c0 (all interrupts masked)
    msr     daifset, #0xf
    mov     x0, x13

    // Jump to XNU entry point (start_first_cpu)
    br      x12

.Lbad_slot_magic:
    mov     x4, #XNU_BOOT_STATUS_INVALID_STATE
    str     x4, [x10, #XBR_O_STATUS]
    bl phase4_publish_record
    mov     lr, x17
    ret

