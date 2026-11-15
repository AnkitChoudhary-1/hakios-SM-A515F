/* SPDX-License-Identifier: GPL-2.0 */
/* QEMU fixture only: owns its memory, page table, console and shutdown. */
.section .text.boot, "ax"
.global _start
_start:
	msr daifset, #15
	adrp x4, fixture_vectors
	add x4, x4, :lo12:fixture_vectors
	mrs x5, CurrentEL
	cmp x5, #4
	b.eq 1f
	msr vbar_el2, x4
	mov x4, #0x5151
	msr far_el2, x4
	b 2f
1:
	msr vbar_el1, x4
	mov x4, #0x5151
	msr far_el1, x4
2:
	isb
#if HKF_SP0
	msr spsel, #0
#endif
#if HKF_GUARD == 1
	msr daifclr, #2
#elif HKF_GUARD == 2
	cmp x5, #4
	b.eq 3f
	mrs x4, sctlr_el2
	orr x4, x4, #4
	msr sctlr_el2, x4
	b 4f
3:
	mrs x4, sctlr_el1
	orr x4, x4, #4
	msr sctlr_el1, x4
4:
	isb
#elif HKF_GUARD == 3
	/* EL1-only identity map of the fixture RAM block, caches still off. */
	mov x4, #0xff
	msr mair_el1, x4
	movz x4, #32
	movk x4, #0x00a0, lsl #16
	msr tcr_el1, x4
	adrp x4, fixture_idmap
	add x4, x4, :lo12:fixture_idmap
	msr ttbr0_el1, x4
	dsb sy
	isb
	mrs x4, sctlr_el1
	orr x4, x4, #1
	msr sctlr_el1, x4
	isb
#endif
	mov x0, #0x1010
	mov x1, #0x2020
	mov x2, #0x3030
	mov x3, #0x4040
	.irp r,18,19,20,21,22,23,24,25,26,27,28,29,30
	mov x\r, #(\r * 257)
	.endr
	mov x4, #0xa0000000
	msr nzcv, x4
	mov x4, #0
	mov sp, x4
	b hkf_entry
.global hkf_continue
hkf_continue:
	adrp x4, fixture_registers
	add x4, x4, :lo12:fixture_registers
	stp x0, x1, [x4, #0]
	stp x2, x3, [x4, #16]
	stp x18, x19, [x4, #32]
	stp x20, x21, [x4, #48]
	stp x22, x23, [x4, #64]
	stp x24, x25, [x4, #80]
	stp x26, x27, [x4, #96]
	stp x28, x29, [x4, #112]
	str x30, [x4, #128]
	mov x5, sp
	str x5, [x4, #136]
	mrs x5, nzcv
	str x5, [x4, #144]
	mrs x5, daif
	str x5, [x4, #152]
	mrs x5, spsel
	str x5, [x4, #160]
	mrs x5, CurrentEL
	str x5, [x4, #168]
	cmp x5, #4
	b.eq 5f
	mrs x6, vbar_el2
	mrs x7, sctlr_el2
	b 6f
5:
	mrs x6, vbar_el1
	mrs x7, sctlr_el1
6:
	str x6, [x4, #176]
	str x7, [x4, #184]
	/* Fixture teardown occurs after every preserved register is captured. */
	bic x7, x7, #1
	bic x7, x7, #4
	cmp x5, #4
	b.eq 7f
	msr sctlr_el2, x7
	b 8f
7:
	msr sctlr_el1, x7
8:
	isb
	msr daifset, #15
	adrp x6, __stack_top
	add x6, x6, :lo12:__stack_top
	mov sp, x6
	bl fixture_main
9:
	wfe
	b 9b
.balign 2048
.global fixture_vectors
fixture_vectors:
	.rept 16
	b 9b
	.balign 128
	.endr
.section .data, "aw", %progbits
.balign 8
.global fixture_registers
fixture_registers:
	.fill 24, 8, 0
/* Adjacent initialized guards detect writes outside the owned record. */
.section .fixture.record.before, "aw", %progbits
.global fixture_record_before
fixture_record_before:
	.rept 64
	.quad 0xcafedeadfacec0de
	.endr
.section .fixture.record.after, "aw", %progbits
.global fixture_record_after
fixture_record_after:
	.rept 64
	.quad 0xdeadbeefcafef00d
	.endr
#if HKF_GUARD == 3
.section .data.pagetables, "aw", %progbits
.balign 4096
fixture_idmap:
	.quad 0, 0x40000701
	.fill 510, 8, 0
#endif
