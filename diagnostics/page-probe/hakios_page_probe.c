// SPDX-License-Identifier: GPL-2.0
/* Android-only diagnostic: one owned page, no device access or handoff. */
#include <linux/errno.h>
#include <linux/gfp.h>
#include <linux/init.h>
#include <linux/mm.h>
#include <linux/module.h>
#include <linux/moduleparam.h>
#include <linux/printk.h>
#include <linux/string.h>

static char *run_id;
module_param(run_id, charp, 0);
MODULE_PARM_DESC(run_id, "Required 16 lowercase hexadecimal characters");
static bool fail_after_alloc;
module_param(fail_after_alloc, bool, 0);
MODULE_PARM_DESC(fail_after_alloc, "Release page and return ECANCELED from init");

static struct page *owned_page;
static phys_addr_t owned_phys;

static void release_page(const char *reason)
{
	if (!owned_page)
		return;
	__free_page(owned_page);
	owned_page = NULL;
	pr_info("HAKIOS_PAGE run=%s stage=release phys=%pa bytes=%lu reason=%s\n",
		run_id, &owned_phys, PAGE_SIZE, reason);
}

static int __init page_probe_init(void)
{
	unsigned char *bytes;
	unsigned long i;

	if (!run_id || strlen(run_id) != 16)
		return -EINVAL;
	for (i = 0; i < 16; i++)
		if (!((run_id[i] >= '0' && run_id[i] <= '9') ||
		      (run_id[i] >= 'a' && run_id[i] <= 'f')))
			return -EINVAL;

	owned_page = alloc_page(GFP_KERNEL | __GFP_ZERO | __GFP_NOWARN |
				__GFP_NORETRY);
	if (!owned_page) {
		pr_info("HAKIOS_PAGE run=%s stage=allocation_failed\n", run_id);
		return -ENOMEM;
	}
	owned_phys = page_to_phys(owned_page);
	pr_info("HAKIOS_PAGE run=%s stage=acquire phys=%pa bytes=%lu\n",
		run_id, &owned_phys, PAGE_SIZE);
	bytes = page_address(owned_page);
	if (!bytes) {
		release_page("no_mapping");
		return -EFAULT;
	}
	for (i = 0; i < PAGE_SIZE; i++)
		if (bytes[i] != 0) {
			release_page("zero_check_failed");
			return -EIO;
		}
	memset(bytes, 0xa5, PAGE_SIZE);
	for (i = 0; i < PAGE_SIZE; i++)
		if (bytes[i] != 0xa5) {
			release_page("pattern_check_failed");
			return -EIO;
		}
	pr_info("HAKIOS_PAGE run=%s stage=selfcheck zero=pass pattern=pass\n",
		run_id);
	if (fail_after_alloc) {
		release_page("requested_init_failure");
		return -ECANCELED;
	}
	pr_info("HAKIOS_PAGE run=%s stage=loaded\n", run_id);
	return 0;
}

static void __exit page_probe_exit(void)
{
	release_page("unload");
}

module_init(page_probe_init);
module_exit(page_probe_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("HakiOS A51 one-page Android allocation diagnostic");
MODULE_VERSION("1");
