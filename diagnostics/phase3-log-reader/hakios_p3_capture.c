// SPDX-License-Identifier: GPL-2.0
/* Read-only snapshot of the historical Phase 3 record banks. No RAM writes. */
#include <linux/init.h>
#include <linux/io.h>
#include <linux/module.h>
#include <linux/proc_fs.h>
#include <linux/uaccess.h>
#include <linux/vmalloc.h>

#define CAP_HEADER 864U
#define CAP_MAX_LOG 65536U
#define OLD_LOG_MAGIC 0x48414b494f534c47ULL

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

static int __init capture_init(void)
{
    void __iomem *fb = NULL, *f9 = NULL;
    u64 *meta;
    u64 old_header[4];
    size_t log_bytes = 0;
    int err = -ENOMEM;

    capture = vzalloc(CAP_HEADER + CAP_MAX_LOG);
    if (!capture)
        return -ENOMEM;
    fb = ioremap_cache(0xfb000000UL, 512);
    f9 = ioremap_cache(0xf9000000UL, 768);
    if (!fb || !f9)
        goto failed;

    /* Preserve both overlapping old copies so their corruption is visible. */
    memcpy_fromio(capture + 64, fb, 256);
    memcpy_fromio(capture + 320, f9 + 0x40, 256);
    memcpy_fromio(capture + 576, f9 + 0x100, 256);
    memcpy_fromio(old_header, fb + 0x1e0, sizeof(old_header));
    memcpy(capture + 832, old_header, sizeof(old_header));
    iounmap(f9);
    f9 = NULL;
    iounmap(fb);
    fb = NULL;

    /* Never dereference an untrusted saved log pointer or copy an unbounded size. */
    if (old_header[0] == OLD_LOG_MAGIC && old_header[1] <= CAP_MAX_LOG &&
        old_header[2] >= 0x83000000ULL && old_header[2] < 0x84300000ULL &&
        old_header[3] >= 4 && old_header[3] <= 7) {
        log_bytes = (size_t)old_header[1];
        if (log_bytes) {
            fb = ioremap_cache(0xfb000200UL, log_bytes);
            if (!fb)
                goto failed;
            memcpy_fromio(capture + CAP_HEADER, fb, log_bytes);
            iounmap(fb);
            fb = NULL;
        }
    }
    /* Keep the whole bounded bank even if recovery overwrote its header. */
    fb = ioremap_cache(0xfb000200UL, CAP_MAX_LOG);
    if (!fb)
        goto failed;
    memcpy_fromio(capture + CAP_HEADER, fb, CAP_MAX_LOG);
    iounmap(fb);
    fb = NULL;
    capture_bytes = CAP_HEADER + CAP_MAX_LOG;
    memcpy(capture, "HKCAP001", 8);
    meta = (u64 *)capture;
    meta[1] = 1;
    meta[2] = CAP_HEADER;
    meta[3] = capture_bytes;
    meta[4] = log_bytes;
    meta[5] = old_header[1];
    meta[6] = CAP_MAX_LOG;
    meta[7] = 0xfb000000ULL;
    entry = proc_create("hakios_p3_capture", 0400, NULL, &capture_fops);
    if (!entry)
        goto failed;
    pr_info("HAKIOS_P3CAP ready bytes=%zu retained_log_bytes=%zu declared=%llu\n",
            capture_bytes, log_bytes, old_header[1]);
    return 0;

failed:
    if (fb)
        iounmap(fb);
    if (f9)
        iounmap(f9);
    vfree(capture);
    capture = NULL;
    return err;
}

static void __exit capture_exit(void)
{
    remove_proc_entry("hakios_p3_capture", NULL);
    vfree(capture);
    capture = NULL;
    pr_info("HAKIOS_P3CAP removed\n");
}

module_init(capture_init);
module_exit(capture_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Read-only bounded historical HakiOS Phase 3 RAM capture");
