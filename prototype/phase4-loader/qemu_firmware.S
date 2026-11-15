/* SPDX-License-Identifier: MIT */
/* Test firmware only: assign all implemented IRQs to Group 1, enter NS EL1 with the
 * retained Samsung FDT pointer, then execute the actual complete Image. */
#ifndef QEMU_IMAGE_BASE
#define QEMU_IMAGE_BASE 0x80080000
#endif
#ifndef QEMU_ENTRY_ICACHE
#define QEMU_ENTRY_ICACHE 0
#endif
    .section .text, "ax"
    .global _start
_start:
    msr daifset, #15
    ldr x10, =0x08000000
    ldr w12, [x10, #4]
    and w12, w12, #31
    add w12, w12, #1
    add x13, x10, #0x80
    mov w11, #0xffffffff
9:  str w11, [x13], #4
    subs w12, w12, #1
    b.ne 9b
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
#if QEMU_ENTRY_ICACHE
    orr x9, x9, #0x1000
#else
    bic x9, x9, #0x1000
#endif
    msr SCTLR_EL1, x9
    isb
    ldr x0, =0x8a100000
    ldr x9, =QEMU_IMAGE_BASE
    br x9
