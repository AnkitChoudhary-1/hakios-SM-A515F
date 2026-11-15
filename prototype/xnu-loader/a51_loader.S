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

    // Initialize persistent RAM bank 0xFB000000 (GNSS 8MB reserved RAM, never wiped)
    ldr     x11, =0xFB000000
    ldr     x12, =0x32454c5241494b48    // HKE_XNU_RECORD_MAGIC ("HKIARLE2")
    str     x12, [x11, #XBR_O_MAGIC]
    mov     x12, #1                     // version
    str     x12, [x11, #XBR_O_VERSION]
    mov     x12, #256                   // bytes
    str     x12, [x11, #XBR_O_BYTES]
    str     x4, [x11, #XBR_O_STATUS]
    str     x3, [x11, #XBR_O_ENTRY_EL]
    str     x5, [x11, #XBR_O_ENTRY_DAIF]
    str     x6, [x11, #XBR_O_ENTRY_SCTLR]
    str     x7, [x11, #XBR_O_ENTRY_CNTFRQ]
    str     x8, [x11, #XBR_O_ENTRY_MIDR]

    // Also mirror to 0xF9000040 (DSS header safe offset), 0xF9000100, and 0x8F000000
    ldr     x11, =0xF9000040
    ldr     x12, =0x32454c5241494b48
    str     x12, [x11, #XBR_O_MAGIC]
    mov     x12, #1
    str     x12, [x11, #XBR_O_VERSION]
    mov     x12, #256
    str     x12, [x11, #XBR_O_BYTES]
    str     x4, [x11, #XBR_O_STATUS]
    str     x3, [x11, #XBR_O_ENTRY_EL]
    str     x5, [x11, #XBR_O_ENTRY_DAIF]
    str     x6, [x11, #XBR_O_ENTRY_SCTLR]
    str     x7, [x11, #XBR_O_ENTRY_CNTFRQ]
    str     x8, [x11, #XBR_O_ENTRY_MIDR]

    ldr     x11, =0x8F000000
    ldr     x12, =0x32454c5241494b48
    str     x12, [x11, #XBR_O_MAGIC]
    mov     x12, #1
    str     x12, [x11, #XBR_O_VERSION]
    mov     x12, #256
    str     x12, [x11, #XBR_O_BYTES]
    str     x4, [x11, #XBR_O_STATUS]
    str     x3, [x11, #XBR_O_ENTRY_EL]
    str     x5, [x11, #XBR_O_ENTRY_DAIF]
    str     x6, [x11, #XBR_O_ENTRY_SCTLR]
    str     x7, [x11, #XBR_O_ENTRY_CNTFRQ]
    str     x8, [x11, #XBR_O_ENTRY_MIDR]

    ldr     x11, =0xF9000100
    ldr     x12, =0x32454c5241494b48
    str     x12, [x11, #XBR_O_MAGIC]
    mov     x12, #1
    str     x12, [x11, #XBR_O_VERSION]
    mov     x12, #256
    str     x12, [x11, #XBR_O_BYTES]
    str     x4, [x11, #XBR_O_STATUS]
    str     x3, [x11, #XBR_O_ENTRY_EL]
    str     x5, [x11, #XBR_O_ENTRY_DAIF]
    str     x6, [x11, #XBR_O_ENTRY_SCTLR]
    str     x7, [x11, #XBR_O_ENTRY_CNTFRQ]
    str     x8, [x11, #XBR_O_ENTRY_MIDR]

    // Iterate over Table of Contents (TOC) to unpack chunks
    adrp    x20, _payload_toc
    add     x20, x20, :lo12:_payload_toc
    adrp    x19, _payload_base
    add     x19, x19, :lo12:_payload_base

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
    // Update status to PAYLOAD_LOADED
    mov     x4, #XNU_BOOT_STATUS_PAYLOAD_LOADED
    str     x4, [x10, #XBR_O_STATUS]
    ldr     x11, =0xFB000000
    str     x4, [x11, #XBR_O_STATUS]
    ldr     x11, =0xF9000040
    str     x4, [x11, #XBR_O_STATUS]
    ldr     x11, =0xF9000100
    str     x4, [x11, #XBR_O_STATUS]
    ldr     x11, =0x8F000000
    str     x4, [x11, #XBR_O_STATUS]

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

    // Memory barriers and Cache Maintenance
    dsb     sy
    ic      iallu
    dsb     sy
    isb

    // Read trampoline config and jump to xnu_trampoline_entry
    bl      xnu_trampoline_entry

    // If xnu_trampoline_entry returns:
    // Clean caches and halt safely
    adrp    x10, xnu_boot_record
    add     x10, x10, :lo12:xnu_boot_record
    dc      cvac, x10
    ldr     x11, =0xF9000100
    dc      cvac, x11
    dsb     sy

.Lloader_halt:
    b       .Lstub_halt

    .section .rodata
    .align 3
.Lmsg_loader_start:
    .asciz "\n[HAKIOS] S-Boot handoff at 0x80080000, unpacking TOC...\n"
.Lmsg_loader_jump:
    .asciz "[HAKIOS] Payload unpacked. Jumping to XNU start_first_cpu...\n"

#define XNU_CONFIG_EXTERNAL 1
#include "xnu_trampoline.S"
