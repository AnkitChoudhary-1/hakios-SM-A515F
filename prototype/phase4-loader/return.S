/* SPDX-License-Identifier: MIT */
/* MMU-off return ABI: x0=log PA, x1=length, x2=reason, x3=code. */
    .section .text.phase4_return, "ax", %progbits
    .align 3
    .global xnu_loader_return_stub
xnu_loader_return_stub:
    msr daifset, #0xf
    mrs x9, sctlr_el1
    bic x9, x9, #1
    bic x9, x9, #4
    msr sctlr_el1, x9
    isb
    adrp x10, xnu_boot_record
    add x10, x10, :lo12:xnu_boot_record
    stp x0, x1, [x10, #48]
    stp x2, x3, [x10, #32]
    str lr, [x10, #128]
    mov x4, #6
    cmp x2, #1
    b.ne 1f
    mov x4, #5
1:  cmp x2, #2
    b.ne 2f
    mov x4, #4
2:  cmp x2, #4
    b.ne 3f
    mov x4, #7
3:  str x4, [x10, #24]
    /* Preserve caller inputs across the record publisher. */
    mov x20, x0
    mov x21, x1
    mov x22, x4
    bl phase4_publish_record
    /* Validate the full source span before copying, then cap all destinations. */
    mov x23, #0
    cbz x20, .Lphase4_copy_logs
    cbz x21, .Lphase4_copy_logs
    ldr x6, =0x83000000
    cmp x20, x6
    b.lo .Lphase4_copy_logs
    adds x7, x20, x21
    b.cs .Lphase4_copy_logs
    ldr x6, =0x847f0000
    cmp x7, x6
    b.hi .Lphase4_copy_logs
    mov x23, #65536
    cmp x21, x23
    csel x23, x21, x23, lo
.Lphase4_copy_logs:
    /* A header records declared and copied lengths separately. Invalid spans
     * have copied=0; the reader never follows the saved physical pointer. */
#ifndef PHASE4_LOADER_QEMU
    ldr x24, =0xfb0001e0
    mov x25, x23
    bl phase4_copy_log
    ldr x24, =0xf9000140
    mov x25, #400
    cmp x23, x25
    csel x25, x23, x25, lo
    bl phase4_copy_log
    /* ramoops console is 512 KiB. The same 64 KiB source cap applies. */
    ldr x6, =0xf9d90000
    ldr w7, =0x43474244
    str w7, [x6]
    str wzr, [x6, #4]
    str w23, [x6, #8]
    add x6, x6, #12
    mov x7, x20
    mov x8, x23
1:  cbz x8, 2f
    ldrb w9, [x7], #1
    strb w9, [x6], #1
    subs x8, x8, #1
    b.ne 1b
2:
#endif
    ldr x24, =0x8f000140
    mov x25, x23
    bl phase4_copy_log
    dsb sy
    b phase4_reset

phase4_copy_log:
    str xzr, [x24]
    str x25, [x24, #8]
    stp x21, x22, [x24, #16]
    add x6, x24, #32
    mov x7, x20
    mov x8, x25
1:  cbz x8, 2f
    ldrb w9, [x7], #1
    strb w9, [x6], #1
    subs x8, x8, #1
    b.ne 1b
2:  dsb sy
    ldr x6, =0x3150474c344b4848 /* Commit header only after copying. */
    str x6, [x24]
    dsb sy
    ret
