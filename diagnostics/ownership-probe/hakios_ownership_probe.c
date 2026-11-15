// SPDX-License-Identifier: GPL-2.0
/* Android allocation/plan diagnostic. The lock never grants an external lease. */
#include <linux/init.h>
#include <linux/mm.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/random.h>
#include <linux/string.h>
#include <linux/sysfs.h>
#include "arena_budget.h"
#include "ownership_core.h"

static char *run_id;
module_param(run_id, charp, 0);
static bool fail_after_alloc;
module_param(fail_after_alloc, bool, 0);
static const struct op_region regions[] = { AR_LAYOUT };
static DEFINE_MUTEX(ownership_lock);
static struct op_state owner;
static struct page *owned_pages;
static unsigned char *owned_bytes;
static phys_addr_t owned_phys;
static bool patterns_ready;

static bool check_bytes(bool zero)
{
	unsigned long i, r;
	for (r = 0; r < ARRAY_SIZE(regions); r++)
		for (i = 0; i < regions[r].size; i++)
			if (READ_ONCE(owned_bytes[regions[r].start + i]) !=
			    (zero ? 0 : regions[r].pattern))
				return false;
	return true;
}
/* Caller holds ownership_lock; revoke before touching/freeing allocation. */
static void release_locked(const char *reason)
{
	const char *integrity = "not_checked", *cleared = "no_mapping";
	owner.active = 0;
	owner.bound = 0;
	if (!owned_pages)
		return;
	if (owned_bytes) {
		if (patterns_ready)
			integrity = check_bytes(false) ? "pass" : "fail";
		memset(owned_bytes, 0, AR_BYTES);
		cleared = check_bytes(true) ? "pass" : "fail";
	}
	__free_pages(owned_pages, AR_ORDER);
	owned_pages = NULL;
	owned_bytes = NULL;
	patterns_ready = false;
	pr_info("HAKIOS_OWNER run=%s token=%s stage=release phys=%pa bytes=%lu reason=%s integrity=%s cleared=%s seq=%u\n",
		run_id, owner.token, &owned_phys, AR_BYTES, reason, integrity,
		cleared, owner.last_seq);
}
static ssize_t status_show(struct module_attribute *attr, struct module_kobject *kobj,
			   char *buffer)
{
	int written;
	(void)kobj;
	(void)attr;
	mutex_lock(&ownership_lock);
	/* No released address is exposed as current ownership. */
	written = scnprintf(buffer, PAGE_SIZE,
		"run=%s token=%s plan=%s active=%d bound=%d last_seq=%u bytes=%lu\n",
		run_id, owner.token, owner.plan, owner.active, owner.bound,
		owner.last_seq, owner.active ? AR_BYTES : 0UL);
	mutex_unlock(&ownership_lock);
	return written;
}
static ssize_t command_store(struct module_attribute *attr, struct module_kobject *kobj,
			     const char *value, size_t count)
{
	struct op_request request;
	enum op_result result;
	int rc = 0;
	(void)kobj;
	(void)attr;
	result = count > OP_REQUEST_MAX ? OP_MALFORMED :
		 op_parse(value, (unsigned int)count, &request);
	mutex_lock(&ownership_lock);
	if (result == OP_OK)
		result = op_check(&owner, &request);
	if (result != OP_OK) {
		pr_info("HAKIOS_OWNER run=%s token=%s stage=reject code=%u last_seq=%u active=%d\n",
			run_id, owner.token, result, owner.last_seq, owner.active);
		rc = result == OP_INACTIVE ? -ENODEV :
		     result == OP_STALE ? -ESTALE : -EINVAL;
		goto out;
	}
	/* Ownership, complete offsets and pattern checks belong to one lock scope.
	 * Receipt becomes historical when this callback unlocks. No copied bytes,
	 * function pointer, execution permission or external destination is granted.
	 */
	if (!owned_pages || !owned_bytes || !patterns_ready ||
	    op_layout(regions, ARRAY_SIZE(regions), AR_BYTES,
		      (unsigned long)owned_phys) != OP_OK || !check_bytes(false)) {
		release_locked("binding_integrity_failure");
		rc = -EIO;
		goto out;
	}
	owner.last_seq = request.seq;
	if (request.action == OP_RELEASE) {
		release_locked("requested_release");
	} else {
		owner.bound = 1;
		pr_info("HAKIOS_OWNER run=%s token=%s stage=bind plan=%s seq=%u regions=%lu phys=%pa bytes=%lu pattern=pass\n",
			run_id, owner.token, owner.plan, owner.last_seq,
			(unsigned long)ARRAY_SIZE(regions), &owned_phys, AR_BYTES);
	}
out:
	mutex_unlock(&ownership_lock);
	return rc ? rc : (ssize_t)count;
}
static struct module_attribute status_attr = __ATTR(status, 0400, status_show, NULL);
static struct module_attribute command_attr = __ATTR(command, 0200, NULL, command_store);
static struct attribute *ownership_attrs[] = { &status_attr.attr, &command_attr.attr, NULL };
static const struct attribute_group ownership_group = {
	.name = "ownership", .attrs = ownership_attrs,
};

static int __init ownership_init(void)
{
	unsigned long i, r;
	unsigned char random_token[16];
	static const char hex[] = "0123456789abcdef";
	int rc = 0;
	BUILD_BUG_ON(PAGE_SIZE != 4096);
	BUILD_BUG_ON(AR_BYTES != (PAGE_SIZE << AR_ORDER));
	if (!run_id || strlen(run_id) != 16)
		return -EINVAL;
	for (i = 0; i < 16; i++)
		if (!op_hex(run_id[i]))
			return -EINVAL;
	if (op_layout(regions, ARRAY_SIZE(regions), AR_BYTES, 0) != OP_OK)
		return -EINVAL;
	mutex_lock(&ownership_lock);
	/* A random identity prevents old boot/run requests matching a new instance;
	 * it is an identity check, not authentication or a physical handoff lease.
	 */
	get_random_bytes(random_token, sizeof(random_token));
	for (i = 0; i < sizeof(random_token); i++) {
		owner.token[i * 2] = hex[random_token[i] >> 4];
		owner.token[i * 2 + 1] = hex[random_token[i] & 15];
	}
	memcpy(owner.plan, OP_PLAN_SHA, OP_PLAN_LEN + 1);
	owned_pages = alloc_pages(GFP_NOWAIT | __GFP_ZERO | __GFP_NOWARN |
				 __GFP_NOMEMALLOC, AR_ORDER);
	if (!owned_pages) {
		rc = -ENOMEM;
		goto out;
	}
	owned_phys = page_to_phys(owned_pages);
	owned_bytes = page_address(owned_pages);
	pr_info("HAKIOS_OWNER run=%s token=%s stage=acquire phys=%pa bytes=%lu\n",
		run_id, owner.token, &owned_phys, AR_BYTES);
	if (!owned_bytes || op_layout(regions, ARRAY_SIZE(regions), AR_BYTES,
			(unsigned long)owned_phys) != OP_OK || !check_bytes(true)) {
		release_locked("mapping_alignment_or_zero_failure");
		rc = -EIO;
		goto out;
	}
	for (r = 0; r < ARRAY_SIZE(regions); r++)
		memset(owned_bytes + regions[r].start, regions[r].pattern, regions[r].size);
	patterns_ready = true;
	if (!check_bytes(false)) {
		release_locked("pattern_failure");
		rc = -EIO;
		goto out;
	}
	owner.active = 1;
	pr_info("HAKIOS_OWNER run=%s token=%s stage=ready plan=%s regions=%lu zero=pass pattern=pass\n",
		run_id, owner.token, owner.plan, (unsigned long)ARRAY_SIZE(regions));
	if (fail_after_alloc) {
		release_locked("requested_init_failure");
		rc = -ECANCELED;
	}
out:
	mutex_unlock(&ownership_lock);
	if (!rc) {
		/* Publish initialized state without the callback lock: create's failure
		 * rollback can drain an already published status reader. */
		rc = sysfs_create_group(&THIS_MODULE->mkobj.kobj, &ownership_group);
		if (rc) {
			mutex_lock(&ownership_lock);
			release_locked("sysfs_failure");
			mutex_unlock(&ownership_lock);
		}
	}
	return rc;
}
static void __exit ownership_exit(void)
{
	/* Drain callbacks before taking their lock, preventing teardown deadlock. */
	sysfs_remove_group(&THIS_MODULE->mkobj.kobj, &ownership_group);
	mutex_lock(&ownership_lock);
	release_locked("unload");
	pr_info("HAKIOS_OWNER run=%s token=%s stage=unloaded\n", run_id, owner.token);
	mutex_unlock(&ownership_lock);
}
module_init(ownership_init);
module_exit(ownership_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("HakiOS A51 allocation lifetime and fixed diagnostic plan binding");
MODULE_VERSION("1");
