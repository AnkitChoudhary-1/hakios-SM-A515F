/* SPDX-License-Identifier: MIT */
/* Test firmware only: assign Group 1 timer ownership, enter NS EL1 with the
 * retained Samsung FDT pointer, then execute the actual complete Image. */
#ifndef QEMU_IMAGE_BASE
#define QEMU_IMAGE_BASE 0x80080000
#endif
    .section .text, "ax"
    .global _start
_start:
    msr daifset, #15
    ldr x10, =0x08000000
    mov w11, #0xffffffff
    str w11, [x10, #0x80]
    mov w11, #2
    str w11, [x10]
    ldr x10, =0x08010000
    str w11, [x10]
    mov w11, #0xff
    str w11, [x10, #4]
    dsb sy
    mov x9, #0x501
    msr SCR_EL3, x9
    mov x9, #0x80000000
    msr HCR_EL2, x9
    mov x9, #3
    msr CNTHCTL_EL2, x9
    msr CNTVOFF_EL2, xzr
    adr x9, 1f
    msr ELR_EL3, x9
    mov x9, #0x3c5
    msr SPSR_EL3, x9
    eret
1:
    mrs x9, SCTLR_EL1
    bic x9, x9, #1
    bic x9, x9, #2
    bic x9, x9, #4
    msr SCTLR_EL1, x9
    isb
    ldr x0, =0x8a100000
    ldr x9, =QEMU_IMAGE_BASE
    br x9
