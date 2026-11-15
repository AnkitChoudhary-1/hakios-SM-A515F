.section .text.boot, "ax"
.global _start
_start:
    // Single CPU, QEMU virt only. Preserve x0-x3 and entry SP before changing SP.
    adrp x4, boot_entry
    add x4, x4, :lo12:boot_entry
    stp x0, x1, [x4, #0]
    stp x2, x3, [x4, #16]
    adr x5, _start
    str x5, [x4, #32]
    mov x5, sp
    str x5, [x4, #40]
    mrs x5, CurrentEL
    lsr x5, x5, #2
    str x5, [x4, #48]
    mrs x6, CNTFRQ_EL0
    str x6, [x4, #56]
    mrs x6, DAIF
    str x6, [x4, #72]
    cmp x5, #1
    b.ne 1f
    mrs x6, SCTLR_EL1
    str x6, [x4, #64]
    mrs x6, TCR_EL1
    str x6, [x4, #80]
    mrs x6, TTBR0_EL1
    str x6, [x4, #88]
    mrs x6, TTBR1_EL1
    str x6, [x4, #96]
    mrs x6, VBAR_EL1
    str x6, [x4, #104]
1:
    // Capture above precedes BSS clearing, stack setup and the C call.
    adrp x6, __bss_start
    add x6, x6, :lo12:__bss_start
    adrp x7, __bss_end
    add x7, x7, :lo12:__bss_end
2:
    cmp x6, x7
    b.hs 3f
    str xzr, [x6], #8
    b 2b
3:
    adrp x6, __stack_top
    add x6, x6, :lo12:__stack_top
    mov sp, x6
    bl qemu_main
4:
    wfe
    b 4b
