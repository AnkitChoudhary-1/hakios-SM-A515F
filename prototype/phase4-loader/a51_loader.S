/* SPDX-License-Identifier: MIT */
#define __ASSEMBLY__ 1
#include "xnu_trampoline.h"

    .section .text.entry, "ax", %progbits
    .align 3
    .global _a51_loader_image_start
_a51_loader_image_start:
    // ARM64 Linux Image header (64 bytes)
    b       a51_loader_start            // code0: branch to entry
    .word   0                           // code1: 0 (or NOP)
    .quad   0x00080000                  // text_offset: 512 KB (0x80080000 on Exynos 9611)
    .quad   36334080                    // image_size: exact A51 kernel slot extent (36,334,080 bytes)
    .quad   2                           // flags: little-endian, 4K pages (bit 1 = 1)
    .quad   0                           // res2
    .quad   0                           // res3
    .quad   0                           // res4
    .ascii  "ARM\x64"                   // magic
    .word   0                           // pe_offset
    .space  4, 0                        // pad to exactly 64 bytes

    .global a51_loader_start
a51_loader_start:
    // Samsung S-Boot hands off execution with:
    // x0 = DTB pointer (Linux FDT from S-Boot)
    // EL1, SCTLR_EL1 = MMU off, D-Cache off
    mov     x28, x0                     // preserve incoming x0 (FDT)
    mov     x29, lr                     // preserve incoming lr

    // Enforce all interrupts masked immediately (DAIF = 0x3c0)
    msr     daifset, #0xf

    // Disable alignment fault check in SCTLR_EL1 (bit 1)
    mrs     x6, SCTLR_EL1
    bic     x6, x6, #2
    msr     SCTLR_EL1, x6
    isb

    // Set up a temporary stack in safe DRAM (0x84800000, above kernel and ramdisk)
    ldr     x9, =0x84800000
    mov     sp, x9

    adrp x6, phase4_vectors
    add x6, x6, :lo12:phase4_vectors
    msr vbar_el1, x6
    isb
    bl phase4_arm_watchdog

#ifndef PHASE4_LOADER_QEMU
    // Mirror early banner to UART0 (0x13820000) and ramoops console (0xF9D90000)
    ldr     x1, =0x13820000
    ldr     x2, =0xF9D90000
    ldr     w4, =0x43474244             // "DBGC"
    str     w4, [x2, #0]
    str     wzr, [x2, #4]               // start = 0
    add     x2, x2, #12                 // data buffer offset
    adr     x3, .Lmsg_loader_start
.Lprint_start:
    ldrb    w4, [x3], #1
    cbz     w4, .Lprint_start_done
    mov     w6, #2000
1:  ldr     w5, [x1, #0x18]
    tbz     w5, #9, 2f
    subs    w6, w6, #1
    b.ne    1b
    b       .Lprint_start_done
2:  str     w4, [x1, #0x20]
    strb    w4, [x2], #1
    b       .Lprint_start
.Lprint_start_done:
    ldr     x2, =0xF9D90000
    mov     w4, #64
    str     w4, [x2, #8]                // size

#endif

    // Record incoming silicon state into xnu_boot_record
    adrp    x10, xnu_boot_record
    add     x10, x10, :lo12:xnu_boot_record

    mrs     x3, CurrentEL
    lsr     x3, x3, #2
    str     x3, [x10, #XBR_O_ENTRY_EL]

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

    bl phase4_publish_record

    // Iterate over Table of Contents (TOC) to unpack chunks
    adrp    x20, _payload_toc
    add     x20, x20, :lo12:_payload_toc
    adrp    x19, _payload_base
    add     x19, x19, :lo12:_payload_base


    /* Validate every TOC source and destination before performing any copy. */
    mov x26, x20
    adrp x27, _payload_toc_end
    add x27, x27, :lo12:_payload_toc_end
    adrp x18, _payload_end
    add x18, x18, :lo12:_payload_end
    sub x18, x18, x19
.Lphase4_validate_toc:
    add x6, x26, #32
    cmp x6, x27
    b.hi .Lphase4_bad_toc
    ldp x21, x22, [x26]
    ldp x23, x24, [x26, #16]
    add x26, x26, #32
    cmn x21, #1
    b.eq .Lphase4_toc_sentinel
    cmp x21, x18
    b.hi .Lphase4_bad_toc
    sub x6, x18, x21
    cmp x23, x6
    b.hi .Lphase4_bad_toc
    adds x6, x23, x24
    b.cs .Lphase4_bad_toc
    cbz x6, .Lphase4_bad_toc
    ldr x7, =0x83000000
    cmp x22, x7
    b.lo .Lphase4_bad_toc
    adds x7, x22, x6
    b.cs .Lphase4_bad_toc
    ldr x8, =0x847f0000
    cmp x7, x8
    b.hi .Lphase4_bad_toc
    /* Reject pairwise destination overlap, including zero-fill extents. */
    mov x9, x20
1:  sub x8, x26, #32
    cmp x9, x8
    b.hs .Lphase4_validate_toc
    ldp x6, x8, [x9, #8]
    ldr x11, [x9, #24]
    add x8, x8, x11
    add x8, x8, x6
    cmp x7, x6
    b.ls 2f
    cmp x8, x22
    b.hi .Lphase4_bad_toc
2:  add x9, x9, #32
    b 1b
.Lphase4_toc_sentinel:
    cmp x26, x27
    b.ne .Lphase4_bad_toc
    orr x6, x22, x23
    orr x6, x6, x24
    cbnz x6, .Lphase4_bad_toc
    adrp x10, xnu_boot_record
    add x10, x10, :lo12:xnu_boot_record
    b .Ltoc_loop
.Lphase4_bad_toc:
    mov x0, #0
    mov x1, #0
    mov x2, #4
    mov x3, #0x101
    b xnu_loader_return_stub

.Ltoc_loop:
    ldr     x21, [x20], #8              // src_offset
    cmn     x21, #1                     // check for sentinel 0xFFFFFFFFFFFFFFFF (-1)
    b.eq    .Ltoc_done

    ldr     x22, [x20], #8              // dest_pa
    ldr     x23, [x20], #8              // copy_bytes
    ldr     x24, [x20], #8              // zero_bytes

    add     x25, x19, x21               // src_pa = payload_base + src_offset

    // Copy copy_bytes from src_pa (x25) to dest_pa (x22)
    cbz     x23, .Lzero_chunk
.Lcopy_loop:
    cmp     x23, #8
    b.lo    .Lcopy_tail
    ldr     x0, [x25], #8
    str     x0, [x22], #8
    sub     x23, x23, #8
    b       .Lcopy_loop

.Lcopy_tail:
    cbz     x23, .Lzero_chunk
.Lcopy_byte_loop:
    ldrb    w0, [x25], #1
    strb    w0, [x22], #1
    subs    x23, x23, #1
    b.ne    .Lcopy_byte_loop

.Lzero_chunk:
    cbz     x24, .Lclean_chunk
.Lzero_loop:
    cmp     x24, #8
    b.lo    .Lzero_tail
    str     xzr, [x22], #8
    sub     x24, x24, #8
    b       .Lzero_loop

.Lzero_tail:
    cbz     x24, .Lclean_chunk
.Lzero_byte_loop:
    strb    wzr, [x22], #1
    subs    x24, x24, #1
    b.ne    .Lzero_byte_loop

.Lclean_chunk:
    b       .Ltoc_loop

.Ltoc_done:
    mov x4, #XNU_BOOT_STATUS_PAYLOAD_LOADED
    str x4, [x10, #XBR_O_STATUS]
    bl phase4_publish_record
    adrp x6, xnu_trampoline_config
    add x6, x6, :lo12:xnu_trampoline_config
    ldr x7, [x6, #48]
    cbz x7, 1f
    /* Dedicated watchdog-expiry candidate, never enters XNU. */
    mov x7, #8
    str x7, [x10, #XBR_O_STATUS]
    mov x7, #2
    str x7, [x10, #184]
    bl phase4_publish_record
2:  wfe
    b 2b
1:

#ifndef PHASE4_LOADER_QEMU
    // Mirror jump message to UART0 and ramoops console
    ldr     x1, =0x13820000
    ldr     x2, =0xF9D90040             // continue in console buffer
    adr     x3, .Lmsg_loader_jump
.Lprint_jump:
    ldrb    w4, [x3], #1
    cbz     w4, .Lprint_jump_done
    mov     w6, #2000
1:  ldr     w5, [x1, #0x18]
    tbz     w5, #9, 2f
    subs    w6, w6, #1
    b.ne    1b
    b       .Lprint_jump_done
2:  str     w4, [x1, #0x20]
    strb    w4, [x2], #1
    b       .Lprint_jump
.Lprint_jump_done:

#endif

    // Memory barriers and Cache Maintenance
    dsb     sy
    ic      iallu
    dsb     sy
    isb

    // Read trampoline config and jump to xnu_trampoline_entry
    bl      xnu_trampoline_entry

    mov x0, #0
    mov x1, #0
    mov x2, #4
    mov x3, #0x102
    b xnu_loader_return_stub

    .section .rodata
    .align 3
.Lmsg_loader_start:
    .asciz "\n[HAKIOS] S-Boot handoff at 0x80080000, unpacking TOC...\n"
.Lmsg_loader_jump:
    .asciz "[HAKIOS] Payload unpacked. Jumping to XNU start_first_cpu...\n"

#define XNU_CONFIG_EXTERNAL 1
#include "xnu_trampoline.S"
#include "recovery.S"
#include "return.S"
