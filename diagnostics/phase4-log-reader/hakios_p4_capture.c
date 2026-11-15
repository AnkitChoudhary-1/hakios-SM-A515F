// SPDX-License-Identifier: GPL-2.0
/* Fixed-bank read-only capture. Saved physical pointers never select mappings. */
#include <linux/init.h>
#include <linux/io.h>
#include <linux/module.h>
#include <linux/proc_fs.h>
#include <linux/uaccess.h>
#include <linux/vmalloc.h>
#include "capture_contract.h"

#define CAP_HEADER 64U
#define BANK_HEADER 64U
#define BANK_BYTES(cap) (BANK_HEADER + HK4_RECORD_BYTES + HK4_LOG_HEADER_BYTES + (cap))

static unsigned long long nonce_hi, nonce_lo;
module_param(nonce_hi, ullong, 0400);
module_param(nonce_lo, ullong, 0400);
MODULE_PARM_DESC(nonce_hi, "Expected run nonce, high 64 bits (mandatory)");
MODULE_PARM_DESC(nonce_lo, "Expected run nonce, low 64 bits (mandatory)");

struct capture_bank {
    unsigned long pa;
    unsigned int header_offset, capacity;
};
static const struct capture_bank banks[] = {
    {0xfb000000UL, 0x1e0, HK4_MAX_LOG},
    {0xf9000040UL, 0x100, 400},
    {0x8f000000UL, 0x140, HK4_MAX_LOG},
};
static unsigned char *capture;
static size_t capture_bytes;
static struct proc_dir_entry *entry;

static ssize_t capture_read(struct file *file, char __user *buf,
                            size_t count, loff_t *pos)
{
    return simple_read_from_buffer(buf, count, pos, capture, capture_bytes);
}
static const struct file_operations capture_fops = {
    .owner = THIS_MODULE,
    .read = capture_read,
    .llseek = default_llseek,
};

static int capture_one(const struct capture_bank *bank, unsigned char *block)
{
    unsigned char *record = block + BANK_HEADER;
    unsigned char *header = record + HK4_RECORD_BYTES;
    unsigned char *log = header + HK4_LOG_HEADER_BYTES;
    unsigned char after_record[HK4_RECORD_BYTES], after_header[HK4_LOG_HEADER_BYTES];
    void __iomem *metadata = NULL, *data = NULL;
    u64 *meta = (u64 *)block;
    size_t copied = 0;
    unsigned int flags = 0;
    metadata = ioremap_cache(bank->pa, bank->header_offset + HK4_LOG_HEADER_BYTES);
    if (!metadata)
        return -ENOMEM;
    memcpy_fromio(record, metadata, HK4_RECORD_BYTES);
    memcpy_fromio(header, metadata + bank->header_offset, HK4_LOG_HEADER_BYTES);
    if (hk4_current_record(record, nonce_hi, nonce_lo)) {
        flags |= 1;
        if (hk4_committed_log(record, header, bank->capacity, nonce_hi, nonce_lo)) {
            flags |= 2;
            copied = (size_t)hk4_u64(header + 8);
            if (copied) {
                /* Only a compile-time bank base plus a fixed offset is used. */
                data = ioremap_cache(bank->pa + bank->header_offset +
                                    HK4_LOG_HEADER_BYTES, copied);
                if (!data) {
                    iounmap(metadata);
                    return -ENOMEM;
                }
                memcpy_fromio(log, data, copied);
                iounmap(data);
            }
        }
    }
    rmb();
    memcpy_fromio(after_record, metadata, HK4_RECORD_BYTES);
    memcpy_fromio(after_header, metadata + bank->header_offset, HK4_LOG_HEADER_BYTES);
    iounmap(metadata);
    if (!memcmp(record, after_record, HK4_RECORD_BYTES) &&
        !memcmp(header, after_header, HK4_LOG_HEADER_BYTES)) {
        flags |= 4;
    } else {
        memset(log, 0, bank->capacity);
        copied = 0;
        flags = 0;
    }
    meta[0] = bank->pa;
    meta[1] = bank->capacity;
    meta[2] = flags;
    meta[3] = copied;
    meta[4] = HK4_RECORD_BYTES;
    meta[5] = HK4_LOG_HEADER_BYTES;
    meta[6] = BANK_BYTES(bank->capacity);
    meta[7] = bank->header_offset;
    return 0;
}

static int __init capture_init(void)
{
    unsigned int i;
    size_t offset = CAP_HEADER;
    u64 *meta;
    int error;
    if (!nonce_hi && !nonce_lo)
        return -EINVAL;
    capture_bytes = CAP_HEADER;
    for (i = 0; i < ARRAY_SIZE(banks); ++i)
        capture_bytes += BANK_BYTES(banks[i].capacity);
    capture = vzalloc(capture_bytes);
    if (!capture)
        return -ENOMEM;
    memcpy(capture, "HK4CAP01", 8);
    meta = (u64 *)capture;
    meta[1] = 1;
    meta[2] = CAP_HEADER;
    meta[3] = capture_bytes;
    meta[4] = nonce_hi;
    meta[5] = nonce_lo;
    meta[6] = ARRAY_SIZE(banks);
    for (i = 0; i < ARRAY_SIZE(banks); ++i) {
        error = capture_one(&banks[i], capture + offset);
        if (error)
            goto failed;
        if (((u64 *)(capture + offset))[2] & 1)
            meta[7] |= 1ULL << i;
        offset += BANK_BYTES(banks[i].capacity);
    }
    entry = proc_create("hakios_p4_capture", 0400, NULL, &capture_fops);
    if (!entry) {
        error = -ENOMEM;
        goto failed;
    }
    pr_info("HAKIOS_P4CAP ready bytes=%zu current_banks=0x%llx\n",
            capture_bytes, meta[7]);
    return 0;
failed:
    vfree(capture);
    capture = NULL;
    return error;
}
static void __exit capture_exit(void)
{
    remove_proc_entry("hakios_p4_capture", NULL);
    vfree(capture);
    capture = NULL;
    pr_info("HAKIOS_P4CAP removed\n");
}
module_init(capture_init);
module_exit(capture_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Nonce-bound bounded read-only HakiOS Phase 4 log capture");
