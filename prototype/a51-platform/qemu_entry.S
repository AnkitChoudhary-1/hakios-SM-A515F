/* SPDX-License-Identifier: MIT */
/* Host-only nonsecure EL1 entry and bounded-by-host capture of an XNU return. */
    .section .text, "ax"
    .global _start
_start:
    msr daifset, #15
    mrs x9, CurrentEL
    cmp x9, #12
    b.ne 0f
    /* Model firmware that assigned the virtual timer to nonsecure Group 1.
     * These secure GIC registers cannot be configured later by EL1 NS. */
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
    mov x9, #0x501 /* SCR_EL3: NS, HCE, AArch64 lower levels */
    msr SCR_EL3, x9
    mov x9, #0x80000000
    msr HCR_EL2, x9
    mov x9, #3
    msr CNTHCTL_EL2, x9
    msr CNTVOFF_EL2, xzr
    adr x9, 1f
    msr ELR_EL3, x9
    mov x9, #0x3c5 /* EL1h, DAIF masked */
    msr SPSR_EL3, x9
    eret
0:
    cmp x9, #8
    b.ne 1f
    mov x9, #0x80000000
    msr HCR_EL2, x9
    mov x9, #3
    msr CNTHCTL_EL2, x9
    msr CNTVOFF_EL2, xzr
    adr x9, 1f
    msr ELR_EL2, x9
    mov x9, #0x3c5
    msr SPSR_EL2, x9
    eret
1:
    mrs x9, SCTLR_EL1
    bic x9, x9, #1
    bic x9, x9, #2
    bic x9, x9, #4
    msr SCTLR_EL1, x9
    isb
    ldr x9, =QEMU_STACK_PA
    mov sp, x9
    ldr x0, =QEMU_BOOTARGS_PA
    ldr x9, =QEMU_XNU_ENTRY_PA
    br x9

    .global qemu_loader_return
qemu_loader_return:
    msr daifset, #15
    mrs x9, SCTLR_EL1
    bic x9, x9, #1
    bic x9, x9, #4
    bic x9, x9, #0x1000
    msr SCTLR_EL1, x9
    isb
    ldr x10, =0x80090000
    stp x0, x1, [x10, #8]
    stp x2, x3, [x10, #24]
    mrs x11, MIDR_EL1
    mrs x12, CNTFRQ_EL0
    stp x11, x12, [x10, #40]
    mrs x11, MPIDR_EL1
    mrs x12, CurrentEL
    stp x11, x12, [x10, #56]
    dsb sy
    ldr x11, =0x315254514f494b48 /* HKIOQTR1: commit last */
    str x11, [x10]
    dsb sy
2:
    wfe
    b 2b
