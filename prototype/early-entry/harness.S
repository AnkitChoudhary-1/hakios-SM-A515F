/* SPDX-License-Identifier: GPL-2.0 */
/* Synthetic QEMU fixture only: its MSR/MMIO/stack code is not the payload. */
.section .text.boot, "ax"
.global _start
_start:
	msr daifset, #15
#if HKE_CASE == 1
	msr daifclr, #2
#elif HKE_CASE == 2
	mrs x6, sctlr_el1
	orr x6, x6, #4
	msr sctlr_el1, x6
	isb
#elif HKE_CASE == 3
	/* EL1 identity-map fixture: only the 1 GiB block containing this image. */
	mov x6, #0xff
	msr mair_el1, x6
	movz x6, #32
	movk x6, #0x00a0, lsl #16
	msr tcr_el1, x6
	adrp x6, harness_idmap
	add x6, x6, :lo12:harness_idmap
	msr ttbr0_el1, x6
	dsb sy
	isb
	mrs x6, sctlr_el1
	orr x6, x6, #1
	msr sctlr_el1, x6
	isb
#endif
	/* Deliberately nonzero x1-x3 prove exact capture instead of ABI guesses. */
	mov x0, #0x1010
	mov x1, #0x2020
	mov x2, #0x3030
	mov x3, #0x4040
	mov x18, #0x1818
	mov x19, #0x1919
	mov x20, #0x2020
	mov x21, #0x2121
	mov x22, #0x2222
	mov x23, #0x2323
	mov x24, #0x2424
	mov x25, #0x2525
	mov x26, #0x2626
	mov x27, #0x2727
	mov x28, #0x2828
	mov x29, #0x2929
	mov x30, #0x3030
	mov x4, #0xa0000000
	msr nzcv, x4
	mov x4, #0
	mov sp, x4
.global stext
stext:
	b hakios_early_entry
.global hakios_early_entry_continue
hakios_early_entry_continue:
	adrp x4, harness_registers
	add x4, x4, :lo12:harness_registers
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
#if HKE_CASE == 2 || HKE_CASE == 3
	mrs x6, sctlr_el1
	bic x6, x6, #1
	bic x6, x6, #4
	msr sctlr_el1, x6
	isb
#endif
	msr daifset, #15
	adrp x6, __stack_top
	add x6, x6, :lo12:__stack_top
	mov sp, x6
	bl harness_main
1:
	wfe
	b 1b

.section .data, "aw", %progbits
.balign 8
.global harness_registers
harness_registers:
	.fill 19, 8, 0

#if HKE_CASE == 3
.section .data.pagetables, "aw", %progbits
.balign 4096
harness_idmap:
	.quad 0, 0x40000701
	.fill 510, 8, 0
#endif
