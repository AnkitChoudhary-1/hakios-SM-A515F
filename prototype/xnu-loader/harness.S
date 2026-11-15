/* SPDX-License-Identifier: MIT */
.section .text.boot, "ax"
.global _start
_start:
    // Mask all interrupts
    msr     daifset, #15

    // SCTLR_EL1: MMU off, caches off (matching Samsung S-Boot EL1 entry)
    mrs     x0, sctlr_el1
    bic     x0, x0, #1          // MMU off
    bic     x0, x0, #4          // D-cache off
    msr     sctlr_el1, x0
    isb

    // Setup initial stack
    adrp    x1, __stack_top
    add     x1, x1, :lo12:__stack_top
    mov     sp, x1

    // Call test setup in C (sets up trampoline config & mock/real XNU slice)
    bl      harness_setup

    // Execute trampoline
    bl      xnu_trampoline_entry

.global harness_trampoline_continue
harness_trampoline_continue:
    // Re-establish stack if clobbered
    adrp    x1, __stack_top
    add     x1, x1, :lo12:__stack_top
    mov     sp, x1

    // Call test evaluation in C
    bl      harness_finish

    // PSCI shutdown
    mov     x0, #0x0008
    movk    x0, #0x8400, lsl #16
    hvc     #0
1:
    wfe
    b       1b

