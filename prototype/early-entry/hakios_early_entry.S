/* SPDX-License-Identifier: GPL-2.0 */
#include "hakios_early_entry.h"

/*
 * Trusted diagnostic entered by B at sttext, before preserve_boot_args.
 * No stack, MSR, MMIO, input-byte execution, Linux call or EL transition.
 * Preserves x0-x3, x18-x30, SP and NZCV. Scratch: x4-x12 and x17.
 * System reads can still trap under an unsupported higher-EL policy; this
 * payload provides no exception vectors or independent fault/reset path.
 */
.section ".idmap.text", "ax"
.balign 4
.global hakios_early_entry
.type hakios_early_entry, %function
hakios_early_entry:
	mrs x17, nzcv
	mrs x4, CurrentEL
	eor x9, x4, #4
	cbz x9, .Lel1
	eor x9, x4, #8
	cbnz x9, .Lskip
	mrs x5, sctlr_el2
	b .Lsctlr
.Lel1:
	mrs x5, sctlr_el1
.Lsctlr:
	/* Never address the physical record under M=1 or C=1. */
	tbnz x5, #0, .Lskip
	tbnz x5, #2, .Lskip
	mrs x7, ctr_el0
	ubfx x9, x7, #16, #4
	/* CTR DminLine <= 6: 4..256 bytes, whole record cache lines only. */
	tbnz x9, #3, .Lskip
	eor x10, x9, #7
	cbz x10, .Lskip
	mov x10, #4
	lsl x10, x10, x9
	mrs x6, daif
	adrp x8, hakios_early_record
	add x8, x8, :lo12:hakios_early_record
	stp x0, x1, [x8, #HKE_O_X0]
	stp x2, x3, [x8, #(HKE_O_X0 + 16)]
	str x4, [x8, #HKE_O_EL]
	adrp x11, stext
	add x11, x11, :lo12:stext
	str x11, [x8, #HKE_O_ENTRY_PC]
	adrp x11, hakios_early_tiny_payload
	add x11, x11, :lo12:hakios_early_tiny_payload
	str x11, [x8, #HKE_O_PAYLOAD_PC]
	adrp x11, hakios_early_entry_continue
	add x11, x11, :lo12:hakios_early_entry_continue
	str x11, [x8, #HKE_O_CONTINUE_PC]
	mov x11, sp
	str x11, [x8, #HKE_O_SP]
	str x6, [x8, #HKE_O_DAIF]
	mrs x11, cntfrq_el0
	str x11, [x8, #HKE_O_CNTFRQ]
	mrs x12, midr_el1
	str x12, [x8, #HKE_O_MIDR]
	str x5, [x8, #HKE_O_SCTLR]
	str x7, [x8, #HKE_O_CTR]
	str x10, [x8, #HKE_O_LINE_BYTES]
	str x30, [x8, #HKE_O_LR]
	str x17, [x8, #HKE_O_NZCV]
	/* Verify IRQ, FIQ, and Debug are masked (0x2c0).
	 * On Exynos 9611 firmware, SError is unmasked at handoff (0x2c0).
	 * In QEMU, all masks are set (0x3c0). Both have (daif & 0x2c0) == 0x2c0.
	 */
	mov x7, #0x2c0
	and x7, x6, x7
	sub x7, x7, #0x2c0
	cbnz x7, .Linvalid_daif

	/* A51 adapter: safely mask SError (A=1) during early payload execution */
	msr daifset, #4

.global hakios_early_tiny_payload
.type hakios_early_tiny_payload, %function
hakios_early_tiny_payload:
	/* Fixed arithmetic payload; all inputs are registers, no callback. */
	eor x7, x0, x1
	eor x7, x7, x2
	eor x7, x7, x3
	eor x7, x7, x11
	eor x7, x7, x12
	ror x7, x7, #7
	str x7, [x8, #HKE_O_VALUE]
	movz x7, #0x4b48
	movk x7, #0x4549, lsl #16
	movk x7, #0x4558, lsl #32
	movk x7, #0x3143, lsl #48
	str x7, [x8, #HKE_O_MARKER]
	str xzr, [x8, #HKE_O_REASON]
	mov x7, #HKE_EXECUTED
	b .Lcommit
.size hakios_early_tiny_payload, . - hakios_early_tiny_payload
.Linvalid_daif:
	str xzr, [x8, #HKE_O_VALUE]
	str xzr, [x8, #HKE_O_MARKER]
	mov x7, #HKE_REASON_DAIF
	str x7, [x8, #HKE_O_REASON]
	mov x7, #HKE_INVALID_DAIF
.Lcommit:
	str x7, [x8, #HKE_O_STATUS]
	/* Same dmb sy -> dc ivac -> dsb sy contract as preserve_boot_args.
	 * Record is initialized file-backed .mmuoff.data.write, not BSS.
	 * 256-byte alignment and line <=256 mean no partial/shared lines.
	 * 64 >> DminLine bounds the loop to 1..64 cache maintenance ops.
	 */
	dmb sy
	mov x11, x8
	mov x12, #64
	lsr x12, x12, x9
.Linvalidate:
	dc ivac, x11
	add x11, x11, x10
	sub x12, x12, #1
	cbnz x12, .Linvalidate
	dsb sy
	/* Restore exact incoming firmware DAIF handoff state and NZCV */
	msr daif, x6
	msr nzcv, x17
.Lskip:
	b hakios_early_entry_continue
.size hakios_early_entry, . - hakios_early_entry

.section ".mmuoff.data.write", "aw", %progbits
.balign 256
.global hakios_early_record
.type hakios_early_record, %object
hakios_early_record:
	.quad HKE_MAGIC, HKE_VERSION, HKE_BYTES
	.fill (HKE_BYTES - 24) / 8, 8, 0
.size hakios_early_record, . - hakios_early_record
