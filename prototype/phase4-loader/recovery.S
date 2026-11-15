/* SPDX-License-Identifier: MIT */
/* Standalone A51 recovery. No Linux callbacks or watchdog petting. */
    .section .text.phase4_recovery, "ax", %progbits
    .align 3
    .global phase4_arm_watchdog
phase4_arm_watchdog:
    adrp x10, xnu_boot_record
    add x10, x10, :lo12:xnu_boot_record
    adrp x6, _phase4_nonce
    add x6, x6, :lo12:_phase4_nonce
    ldp x7, x8, [x6]
    stp x7, x8, [x10, #136]
#ifndef PHASE4_LOADER_QEMU
    /* samsung,exynos7-wdt: PMU DISABLE/MASK_RESET bit 23, cluster 0. */
    ldr x6, =0x11860408
    ldr w7, [x6]
    bic w7, w7, #0x00800000
    str w7, [x6]
    ldr w7, [x6, #4]
    bic w7, w7, #0x00800000
    str w7, [x6, #4]
    /* PERI WDT0 Q-channel request, inherited from the retained CAL source. */
    ldr x6, =0x10033068
    ldr w7, [x6]
    bic w7, w7, #7
    orr w7, w7, #6
    str w7, [x6]
    /* Set the recovery target before an asynchronous reset can occur. */
    ldr x6, =0x11860808
    ldr w7, [x6]
    bic w7, w7, #0x00ff0000
    mov w8, #0x004e0000
    orr w7, w7, w8
    str w7, [x6]
    ldr w7, =0x12345674
    str w7, [x6, #4]
    mov w7, #255
    str w7, [x6, #8]
    ldr x6, =0x10050000
    str wzr, [x6]
    mov w7, #1
    str w7, [x6, #12]
    /* OSCCLK is 26 MHz in the matching DTS. /256 /128 gives about
     * 41.3 seconds for normal runs, 5.2 seconds for the expiry test. */
    adrp x7, xnu_trampoline_config
    add x7, x7, :lo12:xnu_trampoline_config
    ldr x8, [x7, #48]
    mov w7, #32768
    cbz x8, 4f
    mov w7, #4096
4:
    str w7, [x6, #4]
    str w7, [x6, #8]
    mov w7, #0xff39
    str w7, [x6]
    dsb sy
    ldr w7, [x6, #8]
    str x7, [x10, #152]
    mrs x7, cntpct_el0
    mrs x8, cntfrq_el0
    mov x9, #100
    udiv x8, x8, x9
    add x8, x8, x7
    mov x9, #0x100000
1:  mrs x7, cntpct_el0
    cmp x7, x8
    b.hs 2f
    subs x9, x9, #1
    b.ne 1b
2:  ldr w7, [x6, #8]
    str x7, [x10, #160]
    ldr w8, [x6]
    str x8, [x10, #168]
    ldr x6, =0x11860404
    ldr w8, [x6]
    str x8, [x10, #176]
    ldr x8, [x10, #152]
    cmp x7, x8
    b.hs 3f
    cbz x7, 3f
    mov x7, #1
    str x7, [x10, #184]
#else
    mov x7, #1
    str x7, [x10, #184]
#endif
    ret
#ifndef PHASE4_LOADER_QEMU
3:  mov x0, #0
    mov x1, #0
    mov x2, #4
    mov x3, #0x100
    b xnu_loader_return_stub
#endif

    .global phase4_publish_record
phase4_publish_record:
    /* Each bank has exactly one non-overlapping record. */
    adrp x10, xnu_boot_record
    add x10, x10, :lo12:xnu_boot_record
#ifndef PHASE4_LOADER_QEMU
    ldr x6, =0xfb000000
    str xzr, [x6, #0x1e0]
    mov x7, x10
    mov x8, #32
1:  ldr x9, [x7], #8
    str x9, [x6], #8
    subs x8, x8, #1
    b.ne 1b
    ldr x6, =0xf9000040
    str xzr, [x6, #0x100]
    mov x7, x10
    mov x8, #32
2:  ldr x9, [x7], #8
    str x9, [x6], #8
    subs x8, x8, #1
    b.ne 2b
#endif
    ldr x6, =0x8f000000
    str xzr, [x6, #0x140]
    mov x7, x10
    mov x8, #32
3:  ldr x9, [x7], #8
    str x9, [x6], #8
    subs x8, x8, #1
    b.ne 3b
    dsb sy
    ret

    .global phase4_reset
phase4_reset:
    dsb sy
#ifndef PHASE4_LOADER_QEMU
    ldr x6, =0x11860500
    ldr w7, [x6]
    tbz w7, #0, 1f
    mov w7, #0xf1
    str w7, [x6]
1:  ldr x6, =0x11860808
    ldr w7, [x6]
    bic w7, w7, #0x00ff0000
    mov w8, #0x004e0000
    orr w7, w7, w8
    str w7, [x6]
    ldr w7, =0x12345674
    str w7, [x6, #4]
    mov w7, #255
    str w7, [x6, #8]
    ldr x6, =0x11860400
    mov w7, #1
    str w7, [x6]
    dsb sy
#endif
2:  wfe
    b 2b

    /* A fault before XNU installs its own vectors still has a return route. */
    .balign 2048
    .global phase4_vectors
phase4_vectors:
    .rept 16
    b phase4_fault
    .balign 128
    .endr
phase4_fault:
    msr daifset, #0xf
    adrp x10, xnu_boot_record
    add x10, x10, :lo12:xnu_boot_record
    mrs x6, elr_el1
    str x6, [x10, #192]
    mrs x6, far_el1
    str x6, [x10, #200]
    mov x0, #0
    mov x1, #0
    mov x2, #1
    mrs x3, esr_el1
    b xnu_loader_return_stub
