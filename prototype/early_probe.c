// SPDX-License-Identifier: GPL-2.0
#include <linux/init.h>
#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/io.h>
#include <linux/string.h>

MODULE_LICENSE("GPL");

static int __init probe_init(void)
{
    void __iomem *f9 = ioremap_cache(0xF9000040UL, 1024);
    void __iomem *fb = ioremap_cache(0xFB000000UL, 8192);
    void __iomem *m8f = ioremap_cache(0x8F000000UL, 8192);
    u64 p[32] = {0};
    u64 log_hdr[4] = {0};
    unsigned long va;
    u64 dump_sz;
    char *line;
    char *next;
    static char log_text[4096];

    if (m8f) {
        for (va = (unsigned long)m8f; va < (unsigned long)m8f + 4096; va += 64) {
            asm volatile("dc civac, %0" : : "r"(va) : "memory");
        }
        asm volatile("dsb sy; isb" : : : "memory");

        memcpy_fromio(p, m8f, 256);
        pr_emerg("=== HAKIOS_8F_SAFE DETAIL ===\n");
        pr_emerg("HAKIOS_8F magic=%016llx ver=%llu bytes=%llu status=%llu\n",
                 p[0], p[1], p[2], p[3]);
        pr_emerg("HAKIOS_8F reason=%llu code=%llu log_pa=%016llx log_len=%llu\n",
                 p[4], p[5], p[6], p[7]);
        pr_emerg("HAKIOS_8F el=%llu daif=%016llx sctlr=%016llx cntfrq=%llu midr=%016llx\n",
                 p[8], p[9], p[10], p[11], p[12]);
        pr_emerg("HAKIOS_8F entry_pc=%016llx ba_pa=%016llx cp_req=%llu ret_pc=%016llx\n",
                 p[13], p[14], p[15], p[16]);

        memcpy_fromio(log_hdr, m8f + 0x140, 32);
        pr_emerg("=== HAKIOS_8F_LOG_HDR ===\n");
        pr_emerg("8F_LOG_HDR magic=%016llx size=%llu log_pa=%016llx status=%llu\n",
                 log_hdr[0], log_hdr[1], log_hdr[2], log_hdr[3]);

        dump_sz = log_hdr[1];
        if (dump_sz > 4000) dump_sz = 4000;
        if (dump_sz == 0) dump_sz = 400;

        memset(log_text, 0, sizeof(log_text));
        memcpy_fromio(log_text, m8f + 0x160, dump_sz);
        log_text[dump_sz] = '\0';

        pr_emerg("=== HAKIOS_8F_LOG_DUMP_START ===\n");
        print_hex_dump(KERN_EMERG, "HAKIOS_8F_LOG: ", DUMP_PREFIX_OFFSET,
                       16, 1, log_text, dump_sz < 256 ? dump_sz : 256, true);
        pr_emerg("=== HAKIOS_8F_LOG_DUMP_END ===\n");

        pr_emerg("=== HAKIOS_ASCII_LOG_START ===\n");
        line = log_text;
        while (line && *line) {
            next = strchr(line, '\n');
            if (next) *next = '\0';
            pr_emerg("HAKIOS_OUT: %s\n", line);
            if (next) line = next + 1;
            else break;
        }
        pr_emerg("=== HAKIOS_ASCII_LOG_END ===\n");

        iounmap(m8f);
    }

    if (fb) {
        memcpy_fromio(p, fb, 256);
        pr_emerg("=== HAKIOS_FB_SAFE DETAIL ===\n");
        pr_emerg("HAKIOS_FB magic=%016llx ver=%llu bytes=%llu status=%llu\n",
                 p[0], p[1], p[2], p[3]);
        pr_emerg("HAKIOS_FB reason=%llu code=%llu log_pa=%016llx log_len=%llu\n",
                 p[4], p[5], p[6], p[7]);
        pr_emerg("HAKIOS_FB el=%llu daif=%016llx sctlr=%016llx cntfrq=%llu midr=%016llx\n",
                 p[8], p[9], p[10], p[11], p[12]);
        pr_emerg("HAKIOS_FB entry_pc=%016llx ba_pa=%016llx cp_req=%llu ret_pc=%016llx\n",
                 p[13], p[14], p[15], p[16]);

        memcpy_fromio(log_hdr, fb + 0x1E0, 32);
        pr_emerg("=== HAKIOS_FB_LOG_HDR ===\n");
        pr_emerg("FB_LOG_HDR magic=%016llx size=%llu log_pa=%016llx status=%llu\n",
                 log_hdr[0], log_hdr[1], log_hdr[2], log_hdr[3]);

        iounmap(fb);
    }

    if (f9) {
        for (va = (unsigned long)f9; va < (unsigned long)f9 + 1024; va += 64) {
            asm volatile("dc civac, %0" : : "r"(va) : "memory");
        }
        asm volatile("dsb sy; isb" : : : "memory");

        memcpy_fromio(p, f9, 256);
        pr_emerg("=== HAKIOS_F9_SAFE DETAIL ===\n");
        pr_emerg("HAKIOS_F9 magic=%016llx ver=%llu bytes=%llu status=%llu\n",
                 p[0], p[1], p[2], p[3]);
        pr_emerg("HAKIOS_F9 reason=%llu code=%llu log_pa=%016llx log_len=%llu\n",
                 p[4], p[5], p[6], p[7]);
        pr_emerg("HAKIOS_F9 el=%llu daif=%016llx sctlr=%016llx cntfrq=%llu midr=%016llx\n",
                 p[8], p[9], p[10], p[11], p[12]);
        pr_emerg("HAKIOS_F9 entry_pc=%016llx ba_pa=%016llx cp_req=%llu ret_pc=%016llx\n",
                 p[13], p[14], p[15], p[16]);

        memcpy_fromio(log_hdr, f9 + 0x100, 32);
        pr_emerg("=== HAKIOS_F9_LOG_HDR ===\n");
        pr_emerg("F9_LOG_HDR magic=%016llx size=%llu log_pa=%016llx status=%llu\n",
                 log_hdr[0], log_hdr[1], log_hdr[2], log_hdr[3]);

        dump_sz = log_hdr[1];
        if (dump_sz > 400) dump_sz = 400;
        if (dump_sz == 0) dump_sz = 256;

        memset(log_text, 0, sizeof(log_text));
        memcpy_fromio(log_text, f9 + 0x120, dump_sz);
        log_text[dump_sz] = '\0';

        pr_emerg("=== HAKIOS_F9_LOG_DUMP_START ===\n");
        print_hex_dump(KERN_EMERG, "HAKIOS_LOG: ", DUMP_PREFIX_OFFSET,
                       16, 1, log_text, dump_sz < 256 ? dump_sz : 256, true);
        pr_emerg("=== HAKIOS_F9_LOG_DUMP_END ===\n");

        pr_emerg("=== HAKIOS_F9_ASCII_LOG_START ===\n");
        line = log_text;
        while (line && *line) {
            next = strchr(line, '\n');
            if (next) *next = '\0';
            pr_emerg("HAKIOS_OUT: %s\n", line);
            if (next) line = next + 1;
            else break;
        }
        pr_emerg("=== HAKIOS_F9_ASCII_LOG_END ===\n");

        iounmap(f9);
    }

    return 0;
}

static void __exit probe_exit(void) {}
module_init(probe_init);
module_exit(probe_exit);
