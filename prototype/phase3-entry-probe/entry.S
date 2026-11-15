/* SPDX-License-Identifier: MIT */
/* Stackless pre-Linux entry/pstore diagnostic. Only x9-x17 are scratch;
 * x0-x3, callee-saved registers, SP, DAIF, NZCV and SCTLR are preserved.
 * The original accepted Linux entry runs after both records are committed.
 * This diagnostic does not launch XNU and cannot qualify for Phase 3. */
    .section .text, "ax"
    .global probe_entry
probe_entry:
    adr x9, probe_record
    stp x0, x1, [x9, #88]
    stp x2, x3, [x9, #104]
    mrs x10, CurrentEL
    str x10, [x9, #24]
    mrs x10, DAIF
    str x10, [x9, #32]
    msr daifset, #15
    mrs x10, SCTLR_EL1
    str x10, [x9, #40]
    mrs x10, CNTFRQ_EL0
    str x10, [x9, #48]
    mrs x10, MIDR_EL1
    str x10, [x9, #56]
    mrs x10, MPIDR_EL1
    str x10, [x9, #64]
    adr x10, probe_entry
    str x10, [x9, #72]
    mov x10, sp
    str x10, [x9, #80]
    mrs x10, NZCV
    str x10, [x9, #120]
    adrp x10, __continue
    add x10, x10, :lo12:__continue
    str x10, [x9, #128]
    /* CRC over the exact first 144 bytes, including measured registers. */
    mov w10, #-1
    mov x11, #0
    mov w15, #0x8320
    movk w15, #0xedb8, lsl #16
1:
    ldrb w12, [x9, x11]
    eor w10, w10, w12
    mov w13, #8
2:
    and w14, w10, #1
    neg w14, w14
    and w14, w14, w15
    eor w10, w14, w10, lsr #1
    subs w13, w13, #1
    b.ne 2b
    add x11, x11, #1
    cmp x11, #144
    b.lo 1b
    mvn w10, w10
    str x10, [x9, #144]
    /* Exact measured ramoops console and pmsg banks; no other RAM mirror. */
    ldr x16, =0xf9d90000
    ldr x17, =0xf9e90000
    str wzr, [x16]
    str wzr, [x17]
    mov x11, #0
3:
    ldrb w10, [x9, x11]
    add x12, x16, #12
    strb w10, [x12, x11]
    add x12, x17, #12
    strb w10, [x12, x11]
    add x11, x11, #1
    cmp x11, #160
    b.lo 3b
    dsb sy
    mov w10, #160
    stp w10, w10, [x16, #4]
    stp w10, w10, [x17, #4]
    mov w10, #0x4244
    movk w10, #0x4347, lsl #16
    str w10, [x17]
    dsb sy
    str w10, [x16]
    dsb sy
    ldr x10, [x9, #32]
    msr DAIF, x10
    ldr x10, [x9, #120]
    msr NZCV, x10
    b __continue
    .ltorg
    .balign 8
    .global probe_record
probe_record:
    .quad 0x315052544e454b48, NONCE_HI, NONCE_LO
    .quad 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
    .quad 160, 0, 0x3158444e45504b48
    .global probe_end
probe_end:
