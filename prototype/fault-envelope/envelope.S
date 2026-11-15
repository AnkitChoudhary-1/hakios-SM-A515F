/* SPDX-License-Identifier: GPL-2.0 */
#include "envelope.h"
#ifndef HKF_TEST_FAULT
#define HKF_TEST_FAULT 0
#endif
#if HKF_TEST_FAULT < 0 || HKF_TEST_FAULT > 5
#error Unsupported host fault-injection build
#endif
/* Host prototype only. Native Image coherency and writable image storage are
 * prerequisites, not established facts about the A51. No stack or MMIO.
 * x0-x3, x18-x30, SP, NZCV, DAIF, SPSel and incoming VBAR are preserved on
 * continuation. x4-x17 are scratch. No arbitrary fault can resume execution.
 */
.section .text.envelope, "ax"
.balign 4
.global hkf_entry
hkf_entry:
	mrs x17, nzcv
	mrs x12, CurrentEL
	eor x4, x12, #4
	cbz x4, .Lread_el1
	eor x4, x12, #8
	cbnz x4, hkf_continue
	mrs x5, sctlr_el2
	b .Lguards
.Lread_el1:
	mrs x5, sctlr_el1
.Lguards:
	/* All guards precede record addressing and VBAR writes; none set flags. */
	tbnz x5, #0, hkf_continue
	tbnz x5, #2, hkf_continue
	mrs x6, daif
	eor x4, x6, #0x3c0
	cbnz x4, hkf_continue
	mrs x7, ctr_el0
	ubfx x9, x7, #16, #4
	tbnz x9, #3, hkf_continue
	eor x4, x9, #7
	cbz x4, hkf_continue
	mov x10, #4
	lsl x10, x10, x9
	adrp x8, hkf_record
	add x8, x8, :lo12:hkf_record
	str x12, [x8, #HKF_EL]
	str x5, [x8, #HKF_SCTLR]
	str x6, [x8, #HKF_DAIF]
	str x17, [x8, #HKF_NZCV]
	mrs x4, spsel
	str x4, [x8, #HKF_SPSEL]
	mov x4, sp
	str x4, [x8, #HKF_SP]
	str x30, [x8, #HKF_LR]
	stp x0, x1, [x8, #HKF_ARGS]
	stp x2, x3, [x8, #(HKF_ARGS + 16)]
	str x7, [x8, #HKF_CTR]
	str x10, [x8, #HKF_LINE]
	adr x4, hkf_entry
	str x4, [x8, #HKF_ENTRY]
	adr x4, hkf_fault_site
	str x4, [x8, #HKF_SITE]
	adr x4, hkf_continue
	str x4, [x8, #HKF_RESUME]
	mov x4, #1
	str x4, [x8, #HKF_STATUS]
	/* Initialized single-use record. Re-entry/reuse is outside this ABI. */
	str x4, [x8, #HKF_ARMED]
	adrp x11, hkf_vectors
	add x11, x11, :lo12:hkf_vectors
	cmp x12, #4
	b.eq .Larm_el1
	mrs x4, vbar_el2
	str x4, [x8, #HKF_VBAR]
	msr vbar_el2, x11
	b .Larmed
.Larm_el1:
	mrs x4, vbar_el1
	str x4, [x8, #HKF_VBAR]
	msr vbar_el1, x11
.Larmed:
	isb
	/* VBAR selection used CMP; the payload sees the incoming NZCV. */
	msr nzcv, x17
#if HKF_TEST_FAULT == 4
	b hkf_wrong_site
#endif
.global hkf_fault_site
hkf_fault_site:
#if HKF_TEST_FAULT == 1 || HKF_TEST_FAULT == 4 || HKF_TEST_FAULT == 5
	brk #0x42
#elif HKF_TEST_FAULT == 2
	.inst 0
#elif HKF_TEST_FAULT == 3
	brk #0x43
#else
	eor x4, x0, x1
	eor x4, x4, x2
	eor x4, x4, x3
	ror x4, x4, #7
	str x4, [x8, #HKF_VALUE]
#endif
	mov x4, #2
	str x4, [x8, #HKF_STATUS]
	b .Lfinish
#if HKF_TEST_FAULT == 4
.global hkf_wrong_site
hkf_wrong_site:
	brk #0x42
	b hkf_park
#endif

/* Sixteen 128-byte vector slots; all record their exact slot then converge.
 * No incoming stack is required, including for the current-EL SP0 slots. */
.balign 2048
.global hkf_vectors
hkf_vectors:
.macro SLOT n
	mov x4, #\n
	b .Lexception
	.balign 128
.endm
.irp n,0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15
	SLOT \n
.endr
.global hkf_vectors_end
hkf_vectors_end:
.Lexception:
	adrp x8, hkf_record
	add x8, x8, :lo12:hkf_record
	/* A nested handler fault parks; an incomplete record is not committed. */
	ldr x5, [x8, #HKF_FAULTS]
	cbnz x5, hkf_park
	mov x5, #1
	str x5, [x8, #HKF_FAULTS]
	str x4, [x8, #HKF_VECTOR]
	mrs x12, CurrentEL
	cmp x12, #4
	b.eq .Lexception_el1
	mrs x5, esr_el2
	mrs x6, elr_el2
	mrs x7, far_el2
	mrs x9, spsr_el2
	b .Lcapture
.Lexception_el1:
	mrs x5, esr_el1
	mrs x6, elr_el1
	mrs x7, far_el1
	mrs x9, spsr_el1
.Lcapture:
	str x5, [x8, #HKF_ESR]
	str x6, [x8, #HKF_ELR]
	str x7, [x8, #HKF_FAR]
	str x9, [x8, #HKF_SPSR]
	/* Test builds 3/4 exercise wrong-syndrome/PC rejection by the same
	 * allowlist as build 1. Build 5 injects BRK with no recovery enabled. */
#if HKF_TEST_FAULT >= 1 && HKF_TEST_FAULT <= 4
	ldr x7, [x8, #HKF_SPSEL]
	lsl x7, x7, #2
	cmp x4, x7
	b.ne .Lfatal
	adr x7, hkf_fault_site
	cmp x6, x7
	b.ne .Lfatal
#if HKF_TEST_FAULT == 2
	mov x7, #0x02000000
#else
	movz x7, #0x42
	movk x7, #0xf200, lsl #16
#endif
	cmp x5, x7
	b.ne .Lfatal
	mov x4, #3
	str x4, [x8, #HKF_STATUS]
	/* Reconstruct the tested ELt/ELh return state, with all DAIF masks.
 * Do not advance the fault PC or retry an arbitrary instruction. */
	ldr x4, [x8, #HKF_NZCV]
	orr x4, x4, #0x3c0
	orr x4, x4, x12
	ldr x5, [x8, #HKF_SPSEL]
	orr x4, x4, x5
	adr x5, .Lfinish
	cmp x12, #4
	b.eq .Leret_el1
	msr spsr_el2, x4
	msr elr_el2, x5
	eret
.Leret_el1:
	msr spsr_el1, x4
	msr elr_el1, x5
	eret
#endif
.Lfatal:
	mov x4, #4
	str x4, [x8, #HKF_STATUS]
	b .Lcommit
.Lfinish:
	ldr x4, [x8, #HKF_VBAR]
	cmp x12, #4
	b.eq .Lrestore_el1
	msr vbar_el2, x4
	b .Lrestored
.Lrestore_el1:
	msr vbar_el1, x4
.Lrestored:
	isb
	str xzr, [x8, #HKF_ARMED]
.Lcommit:
	mov x4, #1
	str x4, [x8, #HKF_COMMIT]
	/* Same native Image coherency assumption as P2-018. Full owned lines,
 * 2..128 operations; no writes outside this initialized 512-byte record. */
	dmb sy
	ldr x10, [x8, #HKF_LINE]
	mov x4, x8
	add x5, x8, #HKF_BYTES
.Linvalidate:
	dc ivac, x4
	add x4, x4, x10
	cmp x4, x5
	b.lo .Linvalidate
	dsb sy
	ldr x4, [x8, #HKF_STATUS]
	cmp x4, #4
	b.eq hkf_park
	ldr x17, [x8, #HKF_NZCV]
	msr nzcv, x17
	b hkf_continue
.global hkf_park
hkf_park:
	wfe
	b hkf_park

.section .mmuoff.data.write, "aw", %progbits
.balign 512
.global hkf_record
hkf_record:
	.quad HKF_MAGIC, 1, HKF_BYTES
	.fill (HKF_BYTES - 24) / 8, 8, 0
.global hkf_record_end
hkf_record_end:
