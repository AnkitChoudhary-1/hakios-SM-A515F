// SPDX-License-Identifier: GPL-2.0
#include <linux/build_bug.h>
#include <linux/init.h>
#include <linux/kernel.h>
#include <linux/stddef.h>
#include "hakios_early_entry.h"

void __init hakios_early_report(void)
{
	const struct hakios_early_record *r = &hakios_early_record;
	u64 value;
	BUILD_BUG_ON(sizeof(*r) != HKE_BYTES);
	BUILD_BUG_ON(offsetof(struct hakios_early_record, entry_x) != HKE_O_X0);
	BUILD_BUG_ON(offsetof(struct hakios_early_record, nzcv) != HKE_O_NZCV);
	if (r->magic != HKE_MAGIC || r->version != HKE_VERSION ||
	    r->bytes != HKE_BYTES) {
		pr_err("HAKIOS_EARLY_V1 record=invalid-header setup_arch=reached\n");
		return;
	}
	if (r->status == HKE_UNOBSERVED) {
		pr_warn("HAKIOS_EARLY_V1 record=unobserved-or-skipped setup_arch=reached standalone_os=0\n");
		return;
	}
	pr_info("HAKIOS_EARLY_V1 status=%llu reason=%llu setup_arch=reached standalone_os=0\n",
		r->status, r->reason);
	pr_info("HAKIOS_EARLY_V1 x0=%016llx x1=%016llx x2=%016llx x3=%016llx\n",
		r->entry_x[0], r->entry_x[1], r->entry_x[2], r->entry_x[3]);
	pr_info("HAKIOS_EARLY_V1 el=%llu entry_pc=%016llx payload_pc=%016llx continue_pc=%016llx sp=%016llx\n",
		r->current_el >> 2, r->entry_pc, r->payload_pc,
		r->continuation_pc, r->entry_sp);
	pr_info("HAKIOS_EARLY_V1 daif=%016llx cntfrq=%llu midr=%016llx sctlr=%016llx ctr=%016llx line=%llu\n",
		r->daif, r->cntfrq, r->midr, r->sctlr, r->ctr, r->cache_line_bytes);
	value = r->entry_x[0] ^ r->entry_x[1] ^ r->entry_x[2] ^
		r->entry_x[3] ^ r->cntfrq ^ r->midr;
	value = (value >> 7) | (value << 57);
	if (r->status == HKE_EXECUTED && r->reason == HKE_REASON_NONE &&
	    r->payload_marker == HKE_PAYLOAD_MARKER && r->payload_value == value &&
	    (r->current_el == 4 || r->current_el == 8) &&
	    !(r->sctlr & 5) && (r->daif & 0x3c0) == 0x3c0 &&
	    r->cache_line_bytes == (4ULL << ((r->ctr >> 16) & 15)) &&
	    r->cache_line_bytes <= HKE_BYTES)
		pr_info("HAKIOS_EARLY_V1 payload=executed record=consistent value=%016llx continuation=setup_arch_reached\n",
			r->payload_value);
	else
		pr_warn("HAKIOS_EARLY_V1 payload=unverified record=invalid-or-inconsistent marker=%016llx\n",
			r->payload_marker);
}
