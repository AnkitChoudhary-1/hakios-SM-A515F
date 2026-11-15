#!/usr/bin/env python3
"""Build early_probe kernel module to read HAKIOS log from DRAM banks 0x8F000000, 0xFB000000, and 0xF9000040."""
from pathlib import Path
import shutil
import subprocess

code = """// SPDX-License-Identifier: GPL-2.0
#include <linux/init.h>
#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/io.h>
#include <linux/string.h>

MODULE_LICENSE("GPL");

static void dump_io_lines(void __iomem *src, size_t len, const char *tag)
{
    static char line[512];
    size_t i = 0, lpos = 0;
    if (!src || len == 0) return;
    if (len > 65536) len = 65536;
    for (i = 0; i < len; i++) {
        char c = ioread8(src + i);
        if (c == '\\0') break;
        if (c == '\\r') continue;
        if (c == '\\n') {
            line[lpos] = '\\0';
            if (lpos > 0) {
                pr_emerg("%s: %s\\n", tag, line);
            }
            lpos = 0;
        } else {
            if (lpos < sizeof(line) - 1) {
                line[lpos++] = c;
            }
        }
    }
    if (lpos > 0) {
        line[lpos] = '\\0';
        pr_emerg("%s: %s\\n", tag, line);
    }
}

static int __init probe_init(void)
{
    void __iomem *m8f = ioremap_cache(0x8F000000UL, 16384);
    void __iomem *fb = ioremap_cache(0xFB000000UL, 65536);
    void __iomem *f9 = ioremap_cache(0xF9000040UL, 2048);
    u64 p[32] = {0};
    u64 log_hdr[4] = {0};
    bool dumped = false;

    /* 1. Bank 0x8F000000: Safe DRAM */
    if (m8f) {
        memcpy_fromio(p, m8f, 256);
        pr_emerg("HAKIOS_8F magic=%016llx ver=%llu bytes=%llu status=%llu\\n",
                 p[0], p[1], p[2], p[3]);
        pr_emerg("HAKIOS_8F reason=%llu code=%llu log_pa=%016llx log_len=%llu\\n",
                 p[4], p[5], p[6], p[7]);

        memcpy_fromio(log_hdr, m8f + 0x140, 32);
        pr_emerg("8F_LOG_HDR magic=%016llx size=%llu log_pa=%016llx status=%llu\\n",
                 log_hdr[0], log_hdr[1], log_hdr[2], log_hdr[3]);

        if (log_hdr[0] == 0x48414B494F534C47ULL && log_hdr[1] > 0) {
            pr_emerg("=== HAKIOS_8F_LOG_START (sz=%llu) ===\\n", log_hdr[1]);
            dump_io_lines(m8f + 0x160, log_hdr[1], "HAKIOS_OUT");
            pr_emerg("=== HAKIOS_8F_LOG_END ===\\n");
            dumped = true;
        }

        if (p[6] >= 0x80000000ULL && p[7] > 0 && p[7] <= 131072ULL) {
            void __iomem *klog = ioremap_cache(p[6], p[7]);
            if (klog) {
                pr_emerg("=== HAKIOS_KERN_LOG_START (pa=%016llx sz=%llu) ===\\n", p[6], p[7]);
                dump_io_lines(klog, p[7], "HAKIOS_KERN");
                pr_emerg("=== HAKIOS_KERN_LOG_END ===\\n");
                iounmap(klog);
            }
        }
        iounmap(m8f);
    }

    /* 2. Bank 0xFB000000: GNSS Reserved DRAM */
    if (fb) {
        memcpy_fromio(p, fb, 256);
        pr_emerg("HAKIOS_FB magic=%016llx ver=%llu bytes=%llu status=%llu\\n",
                 p[0], p[1], p[2], p[3]);
        pr_emerg("HAKIOS_FB reason=%llu code=%llu log_pa=%016llx log_len=%llu\\n",
                 p[4], p[5], p[6], p[7]);

        memcpy_fromio(log_hdr, fb + 0x1E0, 32);
        pr_emerg("FB_LOG_HDR magic=%016llx size=%llu log_pa=%016llx status=%llu\\n",
                 log_hdr[0], log_hdr[1], log_hdr[2], log_hdr[3]);

        if (log_hdr[0] == 0x48414B494F534C47ULL && log_hdr[1] > 0) {
            pr_emerg("=== HAKIOS_FB_LOG_START (sz=%llu) ===\\n", log_hdr[1]);
            dump_io_lines(fb + 0x200, log_hdr[1], "HAKIOS_OUT");
            pr_emerg("=== HAKIOS_FB_LOG_END ===\\n");
            dumped = true;
        }
        iounmap(fb);
    }

    /* 3. Bank 0xF9000040: DSS Safe Header */
    if (f9) {
        memcpy_fromio(p, f9, 256);
        pr_emerg("HAKIOS_F9 magic=%016llx ver=%llu bytes=%llu status=%llu\\n",
                 p[0], p[1], p[2], p[3]);
        pr_emerg("HAKIOS_F9 reason=%llu code=%llu log_pa=%016llx log_len=%llu\\n",
                 p[4], p[5], p[6], p[7]);

        memcpy_fromio(log_hdr, f9 + 0x100, 32);
        pr_emerg("F9_LOG_HDR magic=%016llx size=%llu log_pa=%016llx status=%llu\\n",
                 log_hdr[0], log_hdr[1], log_hdr[2], log_hdr[3]);

        if (!dumped && log_hdr[0] == 0x48414B494F534C47ULL && log_hdr[1] > 0) {
            pr_emerg("=== HAKIOS_F9_LOG_START (sz=%llu) ===\\n", log_hdr[1]);
            dump_io_lines(f9 + 0x120, log_hdr[1] > 400 ? 400 : log_hdr[1], "HAKIOS_OUT");
            pr_emerg("=== HAKIOS_F9_LOG_END ===\\n");
        }

        if (p[6] >= 0x80000000ULL && p[7] > 0 && p[7] <= 131072ULL) {
            void __iomem *klog = ioremap_cache(p[6], p[7]);
            if (klog) {
                pr_emerg("=== HAKIOS_KERN_LOG_START (pa=%016llx sz=%llu) ===\\n", p[6], p[7]);
                dump_io_lines(klog, p[7], "HAKIOS_KERN");
                pr_emerg("=== HAKIOS_KERN_LOG_END ===\\n");
                iounmap(klog);
            }
        }
        iounmap(f9);
    }

    return 0;
}

static void __exit probe_exit(void) {}
module_init(probe_init);
module_exit(probe_exit);
"""

src_path = Path("/opt/a51-hakios/diagnostics/early-probe/early_probe.c")
src_path.write_text(code, encoding="utf-8")

cmd = [
    "make", "-C", "/opt/a51-everline/src", "O=/opt/a51-everline/out",
    "M=/opt/a51-hakios/diagnostics/early-probe", "ARCH=arm64", "LLVM=1",
    "LLVM_IAS=1", "CC=clang", "LD=ld.lld", "AR=llvm-ar", "NM=llvm-nm",
    "OBJCOPY=llvm-objcopy", "OBJDUMP=llvm-objdump", "READELF=llvm-readelf",
    "CROSS_COMPILE=aarch64-linux-gnu-", "CROSS_COMPILE_ARM32=arm-linux-gnueabi-",
    "CLANG_TRIPLE=aarch64-linux-gnu-", "-j4", "modules"
]
subprocess.run(cmd, check=True)
shutil.copy("/opt/a51-hakios/diagnostics/early-probe/early_probe.ko", "/mnt/c/Users/Ankit/Desktop/A51/hakios-a51/artifacts/early_probe.ko")
print("SUCCESS: Built and copied early_probe.ko")
