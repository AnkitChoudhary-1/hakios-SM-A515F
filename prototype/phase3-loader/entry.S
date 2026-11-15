/* SPDX-License-Identifier: MIT */
    .section .text.entry, "ax"
    .global _start
_start:
    b loader_entry
    .word 0
    .quad 0x80000
    .quad 36334080
    .quad 10
    /* Match the measured Samsung non-PROCA sentinel at header offset 40. */
    .quad 0, 0xecefecef, 0
    .ascii "ARM\x64"
    .word 0
    /* ARM64 Image header is exactly 64 bytes. */
loader_entry:
    mov x18, x0
    mrs x19, CurrentEL
    mrs x20, DAIF
    msr daifset, #15
    mrs x21, SCTLR_EL1
    mrs x22, CNTFRQ_EL0
    mrs x23, MIDR_EL1
    mrs x24, MPIDR_EL1
    /* Samsung's verified entry is EL1 with M/C off. The bounded return
     * contract applies to that state. An unsupported translation/EL cannot
     * safely address physical reset registers and is never accepted. */
    cmp x19, #4
    b.ne loader_bad_entry
    tbnz x21, #0, loader_bad_entry
    tbnz x21, #2, loader_bad_entry
    bic x9, x21, #2
    bic x9, x9, #0x1000
    msr SCTLR_EL1, x9
    isb
    ic iallu
    dsb sy
    isb
    adrp x9, loader_vectors
    add x9, x9, :lo12:loader_vectors
    msr VBAR_EL1, x9
    msr SPSel, #1
    adrp x9, loader_stack_top
    add x9, x9, :lo12:loader_stack_top
    mov sp, x9
    /* Clear only this loader's BSS, before the saved context is published. */
    adrp x9, __bss_start
    add x9, x9, :lo12:__bss_start
    adrp x10, __bss_end
    add x10, x10, :lo12:__bss_end
1:  cmp x9, x10
    b.hs 2f
    str xzr, [x9], #8
    b 1b
2:  adrp x9, loader_context
    add x9, x9, :lo12:loader_context
    stp x18, x19, [x9, #88]
    stp x20, x21, [x9, #104]
    stp x22, x23, [x9, #120]
    str x24, [x9, #136]
    b loader_main
loader_bad_entry:
    /* Keep an inspectable rejection tag in x0. No exception is deliberately
     * raised before a usable vector/translation contract exists. Host or
     * manual recovery is required outside the supported firmware contract. */
    mov x0, #0x351
3:  wfe
    b 3b

    .global loader_branch
loader_branch:
    mov x9, x0
    mov x0, x1
    msr daifset, #15
    dsb sy
    ic iallu
    dsb sy
    isb
    br x9

    .global loader_return_stub
loader_return_stub:
    /* Native orderly return arrives with MMU ON through a 2 MiB TTBR0
     * identity block. Preserve every documented argument in registers before
     * switching to physical memory and this loader's physical stack. */
    msr daifset, #15
    mov x19, x0
    mov x20, x1
    mov x21, x2
    mov x22, x3
    mov x23, x4
    mov x24, x5
    mov x25, x6
    mov x26, x7
    mov x27, x8
    mov x28, lr
    mrs x29, SCTLR_EL1
    dsb sy
    bic x9, x29, #1
    bic x9, x9, #4
    bic x9, x9, #0x1000
    msr SCTLR_EL1, x9
    isb
    msr SPSel, #1
    adrp x9, loader_stack_top
    add x9, x9, :lo12:loader_stack_top
    mov sp, x9
    adrp x9, loader_vectors
    add x9, x9, :lo12:loader_vectors
    msr VBAR_EL1, x9
    isb
    adrp x9, loader_context
    add x9, x9, :lo12:loader_context
    stp x19, x20, [x9, #0]
    stp x21, x22, [x9, #16]
    stp x23, x24, [x9, #32]
    stp x25, x26, [x9, #48]
    stp x27, x28, [x9, #64]
    str x29, [x9, #80]
    b loader_return_main

    .balign 2048
    .global loader_vectors
loader_vectors:
    .rept 16
    b loader_fault
    .balign 128
    .endr
loader_fault:
    /* Stackless capture: save scratch x16 in TPIDR_EL1, then every original
     * GPR, SP and syndrome. Fatal loader exceptions never return to XNU. */
    msr TPIDR_EL1, x16
    adrp x16, loader_fault_frame
    add x16, x16, :lo12:loader_fault_frame
    stp x0, x1, [x16, #8]
    stp x2, x3, [x16, #24]
    stp x4, x5, [x16, #40]
    stp x6, x7, [x16, #56]
    stp x8, x9, [x16, #72]
    stp x10, x11, [x16, #88]
    stp x12, x13, [x16, #104]
    stp x14, x15, [x16, #120]
    str x17, [x16, #144]
    mrs x17, TPIDR_EL1
    str x17, [x16, #136]
    stp x18, x19, [x16, #152]
    stp x20, x21, [x16, #168]
    stp x22, x23, [x16, #184]
    stp x24, x25, [x16, #200]
    stp x26, x27, [x16, #216]
    stp x28, x29, [x16, #232]
    str x30, [x16, #248]
    mov x17, sp
    str x17, [x16, #256]
    mrs x17, ESR_EL1
    str x17, [x16, #264]
    mrs x17, ELR_EL1
    str x17, [x16, #272]
    mrs x17, FAR_EL1
    str x17, [x16, #280]
    mrs x17, SCTLR_EL1
    str x17, [x16, #288]
    mrs x17, CurrentEL
    str x17, [x16, #296]
    dsb sy
    ldr x17, =0x33544c464f494b48
    str x17, [x16]
    dsb sy
    adrp x9, loader_stack_top
    add x9, x9, :lo12:loader_stack_top
    msr SPSel, #1
    mov sp, x9
    b loader_fault_main

    .section .bss, "aw", %nobits
    .balign 64
    .global loader_context
loader_context:
    .skip 192
    .balign 64
    .global loader_fault_frame
loader_fault_frame:
    .skip 320
    .balign 16
    .skip 32768
    .global loader_stack_top
loader_stack_top:
