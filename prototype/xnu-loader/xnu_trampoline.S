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

#ifdef XNU_CONFIG_EXTERNAL
    ldr     x9, =0xFB000000
    str     x12, [x9, #XBR_O_XNU_ENTRY_PC]
    str     x13, [x9, #XBR_O_XNU_BOOT_ARGS_PA]
    str     x15, [x9, #XBR_O_CHECKPOINT_REQ]
    ldr     x9, =0xF9000040
    str     x12, [x9, #XBR_O_XNU_ENTRY_PC]
    str     x13, [x9, #XBR_O_XNU_BOOT_ARGS_PA]
    str     x15, [x9, #XBR_O_CHECKPOINT_REQ]
    ldr     x9, =0xF9000100
    str     x12, [x9, #XBR_O_XNU_ENTRY_PC]
    str     x13, [x9, #XBR_O_XNU_BOOT_ARGS_PA]
    str     x15, [x9, #XBR_O_CHECKPOINT_REQ]
#endif

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

#ifdef XNU_CONFIG_EXTERNAL
    ldr     x9, =0xFB000000
    str     x4, [x9, #XBR_O_STATUS]
    dc      cvac, x9
    ldr     x9, =0xF9000040
    str     x4, [x9, #XBR_O_STATUS]
    dc      cvac, x9
    ldr     x9, =0xF9000100
    str     x4, [x9, #XBR_O_STATUS]
    dc      cvac, x9
    dsb     sy
#endif

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
#ifdef XNU_CONFIG_EXTERNAL
    ldr     x9, =0xFB000000
    str     x4, [x9, #XBR_O_STATUS]
    dc      cvac, x9
    ldr     x9, =0xF9000040
    str     x4, [x9, #XBR_O_STATUS]
    dc      cvac, x9
    ldr     x9, =0xF9000100
    str     x4, [x9, #XBR_O_STATUS]
    dc      cvac, x9
    dsb     sy
#endif
    mov     lr, x17
    ret

/*
 * Return stub called by XNU upon checkpoint hit or early exception
 * Contract from XNU (LOADER_CHECKPOINT / loader_return / early exception):
 *   x0 = log PA
 *   x1 = log len
 *   x2 = reason (0 = normal, 1 = exception, 2 = checkpoint)
 *   x3 = code / checkpoint number / ESR
 *   MMU is OFF, DAIF is masked
 */
    .align 3
    .global xnu_loader_return_stub
xnu_loader_return_stub:
#ifdef XNU_CONFIG_EXTERNAL
    // 1. Mask interrupts and ensure MMU & D-cache are OFF so physical memory is directly accessible
    msr     daifset, #0xf
    mrs     x9, sctlr_el1
    bic     x9, x9, #1                  // Clear M (bit 0, MMU off)
    bic     x9, x9, #4                  // Clear C (bit 2, D-cache off)
    msr     sctlr_el1, x9
    isb
#endif

    adrp    x10, xnu_boot_record
    add     x10, x10, :lo12:xnu_boot_record

    // Record return values
    str     x0, [x10, #XBR_O_LOG_PA]
    str     x1, [x10, #XBR_O_LOG_LEN]
    str     x2, [x10, #XBR_O_REASON]
    str     x3, [x10, #XBR_O_CODE]

    // Determine status based on reason
    cmp     x2, #2                      // Checkpoint?
    b.eq    .Lreason_checkpoint
    cmp     x2, #1                      // Early exception?
    b.eq    .Lreason_exception
    mov     x4, #XNU_BOOT_STATUS_PANIC_OR_EXIT
    b       .Lsave_status

.Lreason_checkpoint:
    mov     x4, #XNU_BOOT_STATUS_CHECKPOINT_HIT
    b       .Lsave_status

.Lreason_exception:
    mov     x4, #XNU_BOOT_STATUS_EARLY_EXCEPTION

.Lsave_status:
    str     x4, [x10, #XBR_O_STATUS]

    // Record return address (LR)
    str     lr, [x10, #XBR_O_RETURN_PC]

    // Flush record to RAM so it survives any subsequent reset or inspection
    dc      cvac, x10
    dsb     sy

#ifdef XNU_CONFIG_EXTERNAL
    // 2. Mirror full 256-byte xnu_boot_record to 0xFB000000, 0xF9000040, and 0xF9000100
    // Bank 1: 0xFB000000 (GNSS 8MB reserved DRAM, never wiped)
    ldr     x11, =0xFB000000
    mov     x12, x10
    mov     x13, #32
.Lcopy_rec_to_fb000000:
    ldr     x14, [x12], #8
    str     x14, [x11], #8
    subs    x13, x13, #1
    b.ne    .Lcopy_rec_to_fb000000

    // Bank 2: 0xF9000040 (DSS safe offset)
    ldr     x11, =0xF9000040
    mov     x12, x10
    mov     x13, #32
.Lcopy_rec_to_f9000040:
    ldr     x14, [x12], #8
    str     x14, [x11], #8
    subs    x13, x13, #1
    b.ne    .Lcopy_rec_to_f9000040

    // Bank 3: 0xF9000100 (DSS legacy offset)
    ldr     x11, =0xF9000100
    mov     x12, x10
    mov     x13, #32
.Lcopy_rec_to_f9000100:
    ldr     x14, [x12], #8
    str     x14, [x11], #8
    subs    x13, x13, #1
    b.ne    .Lcopy_rec_to_f9000100

    // Bank 4: 0x8F000000 (Safe Normal DRAM, unaffected by Samsung DSS/TZ)
    ldr     x11, =0x8F000000
    mov     x12, x10
    mov     x13, #32
.Lcopy_rec_to_8f000000:
    ldr     x14, [x12], #8
    str     x14, [x11], #8
    subs    x13, x13, #1
    b.ne    .Lcopy_rec_to_8f000000

    // 3. If log pointer x0 and length x1 are valid, write to safe DSS DRAM, GNSS, ramoops, and UART0
    cbz     x0, .Lskip_stub_log
    cbz     x1, .Lskip_stub_log

    // Bank 1: Safe DSS persistent RAM at 0xF9000140 (DSS_KEEP_HEADER_SZ = 768 bytes)
    ldr     x11, =0xF9000140
    ldr     x18, =0x48414B494F534C47    // "HAKIOSLG"
    str     x18, [x11, #0]
    str     x1,  [x11, #8]              // size = log len
    str     x0,  [x11, #16]             // log_pa
    str     x4,  [x11, #24]             // status

    // Copy log text to 0xF9000160 (cap at 400 bytes to stay inside 768-byte preserved window)
    add     x12, x11, #32               // 0xF9000160
    mov     x16, x0
    mov     x17, x1
    mov     x18, #400
    cmp     x17, x18
    csel    x17, x17, x18, ls           // min(log_len, 400)
    mov     x21, x17
.Lcopy_log_f9:
    cbz     x17, .Ldone_log_f9
    ldrb    w19, [x16], #1
    strb    w19, [x12], #1
    subs    x17, x17, #1
    b.ne    .Lcopy_log_f9
.Ldone_log_f9:
    strb    wzr, [x12]                  // null terminate

    // Flush cache lines over 0xF9000140..0xF90002F0
    ldr     x11, =0xF9000140
    add     x18, x21, #40
.Lflush_f9_log:
    dc      cvac, x11
    add     x11, x11, #64
    subs    x18, x18, #64
    b.gt    .Lflush_f9_log
    dsb     sy

    // Bank 2: Persistent GNSS log header at 0xFB0001E0 and data at 0xFB000200
    ldr     x11, =0xFB0001E0
    ldr     x18, =0x48414B494F534C47    // "HAKIOSLG"
    str     x18, [x11, #0]
    str     x1,  [x11, #8]              // size = log len
    str     x0,  [x11, #16]             // log_pa
    str     x4,  [x11, #24]             // status

    ldr     x18, =0xFB000200            // GNSS log buffer start
    mov     x16, x0
    mov     x17, x1
.Lcopy_gnss_log:
    cbz     x17, .Ldone_gnss_log
    ldrb    w19, [x16], #1
    strb    w19, [x18], #1
    subs    x17, x17, #1
    b.ne    .Lcopy_gnss_log
.Ldone_gnss_log:
    strb    wzr, [x18]

    // Clean caches across GNSS buffer
    ldr     x18, =0xFB0001E0
    add     x19, x1, #40
.Lclean_gnss_log:
    dc      cvac, x18
    add     x18, x18, #64
    subs    x19, x19, #64
    b.gt    .Lclean_gnss_log
    dsb     sy

    // Bank 3: Persistent ramoops console at 0xF9D90000
    ldr     x15, =0xF9D90000
    ldr     w18, =0x43474244            // "DBGC"
    str     w18, [x15, #0]              // sig
    str     wzr, [x15, #4]              // start = 0
    str     w1,  [x15, #8]              // size = log len
    add     x15, x15, #12               // data start at 0xF9D9000C
    mov     x16, x0
    mov     x17, x1
.Lcopy_ramoops_log:
    cbz     x17, .Ldone_ramoops_log
    ldrb    w19, [x16], #1
    strb    w19, [x15], #1
    subs    x17, x17, #1
    b.ne    .Lcopy_ramoops_log
.Ldone_ramoops_log:
    ldr     x15, =0xF9D90000
    dc      cvac, x15
    dsb     sy

    // Bank 4: Persistent DRAM log at 0x8F000140 (header) and 0x8F000160 (text)
    ldr     x11, =0x8F000140
    ldr     x18, =0x48414B494F534C47    // "HAKIOSLG"
    str     x18, [x11, #0]
    str     x1,  [x11, #8]              // size = log len
    str     x0,  [x11, #16]             // log_pa
    str     x4,  [x11, #24]             // status

    add     x12, x11, #32               // 0x8F000160
    mov     x16, x0
    mov     x17, x1                     // full log_len
    ldr     x18, =8192                  // support up to 8KB in safe 0x8F000160 window
    cmp     x17, x18
    csel    x17, x17, x18, ls           // min(log_len, 8192)
.Lcopy_log_8f:
    cbz     x17, .Ldone_log_8f
    ldrb    w19, [x16], #1
    strb    w19, [x12], #1
    subs    x17, x17, #1
    b.ne    .Lcopy_log_8f
.Ldone_log_8f:
    strb    wzr, [x12]

    // Flush cache lines over 0x8F000000..0x8F002200
    ldr     x11, =0x8F000000
    ldr     x18, =8448
.Lflush_8f_log:
    dc      cvac, x11
    add     x11, x11, #64
    subs    x18, x18, #64
    b.gt    .Lflush_8f_log
    dsb     sy

    // Bank 5: Print to UART0 with bounded timeout (never spin forever)
    ldr     x14, =0x13820000            // UART0
    mov     x16, x0
    mov     x17, x1
.Luart_log_loop:
    cbz     x17, .Lskip_stub_log
    ldrb    w19, [x16], #1
    mov     w21, #2000                  // timeout counter
1:  ldr     w20, [x14, #0x18]
    tbz     w20, #9, 2f
    subs    w21, w21, #1
    b.ne    1b
    b       .Lskip_stub_log             // UART unresponsive, skip
2:  str     w19, [x14, #0x20]
    subs    x17, x17, #1
    b.ne    .Luart_log_loop

.Lskip_stub_log:
    // Flush caches over persistent banks
    ldr     x11, =0xFB000000
    dc      cvac, x11
    add     x12, x11, #64
    dc      cvac, x12
    add     x12, x11, #128
    dc      cvac, x12
    add     x12, x11, #192
    dc      cvac, x12

    ldr     x11, =0xF9000040
    dc      cvac, x11
    add     x12, x11, #64
    dc      cvac, x12
    add     x12, x11, #128
    dc      cvac, x12
    add     x12, x11, #192
    dc      cvac, x12

    ldr     x11, =0xF9000100
    dc      cvac, x11
    ldr     x15, =0xF9D90000
    dc      cvac, x15
    dsb     sy
#endif

    // Check if a continuation address is configured
    adrp    x11, xnu_trampoline_config
    add     x11, x11, :lo12:xnu_trampoline_config
    ldr     x12, [x11, #40]             // continue_pc
    cbz     x12, .Lreturn_or_hang

    br      x12

.Lreturn_or_hang:
#ifdef XNU_CONFIG_EXTERNAL
    // Print completion banner to UART0
    ldr     x14, =0x13820000
    adr     x3, .Lmsg_stub_done
.Lprint_stub_done:
    ldrb    w4, [x3], #1
    cbz     w4, .Lstub_halt
    mov     w21, #2000
1:  ldr     w5, [x14, #0x18]
    tbz     w5, #9, 2f
    subs    w21, w21, #1
    b.ne    1b
    b       .Lstub_halt
2:  str     w4, [x14, #0x20]
    b       .Lprint_stub_done

.Lstub_halt:
    // Memory barrier before triggering reset
    dsb     sy
    isb

    // DFD debug-reset suppression: ensure reset is not intercepted
    ldr     x11, =0x11860500
    ldr     w12, [x11]
    tbz     w12, #0, 1f
    mov     w12, #0xf1
    str     w12, [x11]
1:
    // Set S-Boot recovery reason magic (0x12345674 boots into TWRP recovery partition)
    ldr     x11, =0x11860808
    ldr     w12, [x11]
    mov     w13, #0x00ff0000
    bic     w12, w12, w13
    mov     w13, #0x004e0000
    orr     w12, w12, w13
    str     w12, [x11]

    ldr     x11, =0x1186080c
    ldr     w12, =0x12345674
    str     w12, [x11]

    ldr     x11, =0x11860810
    mov     w12, #0xff
    str     w12, [x11]

    // Exynos PMU SWRESET: write 1 to 0x11860400
    ldr     x11, =0x11860400
    mov     w12, #1
    str     w12, [x11]
    dsb     sy
    isb

2:
    wfe
    b       2b

.Lmsg_stub_done:
    .asciz "\n[HAKIOS] XNU execution complete. Persistent memory saved at 0xF9000100 & ramoops. Halting CPU.\n"
#else
    ret
#endif

