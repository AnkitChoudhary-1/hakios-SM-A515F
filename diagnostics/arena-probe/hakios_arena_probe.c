// SPDX-License-Identifier: GPL-2.0
/* Bounded Android allocator diagnostic. No payload execution or hardware I/O. */
#include <linux/init.h>
#include <linux/mm.h>
#include <linux/module.h>
#include <linux/string.h>
#include "arena_budget.h"

static char *run_id;
module_param(run_id, charp, 0);
MODULE_PARM_DESC(run_id, "Required 16 lowercase hexadecimal characters");
static bool fail_after_alloc;
module_param(fail_after_alloc, bool, 0);
MODULE_PARM_DESC(fail_after_alloc, "Release arena then return ECANCELED");

struct arena_region { unsigned long start, size; unsigned char pattern; };
static const struct arena_region regions[] = { AR_LAYOUT };
static struct page *owned_pages;
static phys_addr_t owned_phys;
static unsigned char *owned_bytes;
static bool patterns_ready;

static bool zero_ok(void)
{
	unsigned long i;
	for (i = 0; i < AR_BYTES; i++)
		if (READ_ONCE(owned_bytes[i]))
			return false;
	return true;
}

static bool pattern_ok(void)
{
	unsigned long i, r;
	for (r = 0; r < ARRAY_SIZE(regions); r++)
		for (i = 0; i < regions[r].size; i++)
			if (READ_ONCE(owned_bytes[regions[r].start + i]) != regions[r].pattern)
				return false;
	return true;
}

static void release_arena(const char *reason)
{
	const char *integrity = "not_checked", *cleared = "no_mapping";
	if (!owned_pages)
		return;
	if (owned_bytes) {
		if (patterns_ready)
			integrity = pattern_ok() ? "pass" : "fail";
		memset(owned_bytes, 0, AR_BYTES);
		cleared = zero_ok() ? "pass" : "fail";
	}
	__free_pages(owned_pages, AR_ORDER);
	owned_pages = NULL;
	owned_bytes = NULL;
	patterns_ready = false;
	pr_info("HAKIOS_ARENA run=%s stage=release phys=%pa bytes=%lu order=%u reason=%s integrity=%s cleared=%s\n",
		run_id, &owned_phys, AR_BYTES, AR_ORDER, reason, integrity, cleared);
}

static int __init arena_probe_init(void)
{
	unsigned long i, r, end = 0;
	BUILD_BUG_ON(PAGE_SIZE != 4096);
	BUILD_BUG_ON(AR_BYTES != (PAGE_SIZE << AR_ORDER));
	if (!run_id || strlen(run_id) != 16)
		return -EINVAL;
	for (i = 0; i < 16; i++)
		if (!((run_id[i] >= '0' && run_id[i] <= '9') ||
		      (run_id[i] >= 'a' && run_id[i] <= 'f')))
			return -EINVAL;
	/* Validate the entire generated partition before any allocation or write. */
	for (r = 0; r < ARRAY_SIZE(regions); r++) {
		if (regions[r].start != end || !regions[r].size ||
		    regions[r].size > AR_BYTES - end)
			return -EINVAL;
		end += regions[r].size;
	}
	if (end != AR_BYTES)
		return -EINVAL;
	owned_pages = alloc_pages(GFP_NOWAIT | __GFP_ZERO | __GFP_NOWARN |
				  __GFP_NOMEMALLOC, AR_ORDER);
	if (!owned_pages) {
		pr_info("HAKIOS_ARENA run=%s stage=allocation_failed bytes=%lu order=%u\n",
			run_id, AR_BYTES, AR_ORDER);
		return -ENOMEM;
	}
	owned_phys = page_to_phys(owned_pages);
	pr_info("HAKIOS_ARENA run=%s stage=acquire phys=%pa bytes=%lu order=%u\n",
		run_id, &owned_phys, AR_BYTES, AR_ORDER);
	owned_bytes = page_address(owned_pages);
	if (!owned_bytes || (owned_phys & (AR_BYTES - 1))) {
		release_arena("mapping_or_alignment_failed");
		return -EFAULT;
	}
	if (!zero_ok()) {
		release_arena("zero_check_failed");
		return -EIO;
	}
	for (r = 0; r < ARRAY_SIZE(regions); r++)
		memset(owned_bytes + regions[r].start, regions[r].pattern, regions[r].size);
	patterns_ready = true;
	if (!pattern_ok()) {
		release_arena("pattern_check_failed");
		return -EIO;
	}
	pr_info("HAKIOS_ARENA run=%s stage=selfcheck regions=%lu zero=pass pattern=pass\n",
		run_id, (unsigned long)ARRAY_SIZE(regions));
	if (fail_after_alloc) {
		release_arena("requested_init_failure");
		return -ECANCELED;
	}
	pr_info("HAKIOS_ARENA run=%s stage=loaded\n", run_id);
	return 0;
}

static void __exit arena_probe_exit(void) { release_arena("unload"); }
module_init(arena_probe_init);
module_exit(arena_probe_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("HakiOS A51 bounded 64 KiB arena lifetime diagnostic");
MODULE_VERSION("1");
