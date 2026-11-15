#!/usr/bin/env python3
"""Build probe to read hakios_early_record using exact KASLR symbol address."""
from pathlib import Path
import subprocess

PROBE_C = """// SPDX-License-Identifier: GPL-2.0
#include <linux/init.h>
#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/kallsyms.h>

MODULE_LICENSE("GPL");

static int __init probe_init(void)
{
    unsigned long rec_addr = kallsyms_lookup_name("hakios_early_record");
    unsigned long stext_addr = kallsyms_lookup_name("stext");
    unsigned long slide = stext_addr - 0xffffff8009430000UL;
    unsigned long calculated = 0xffffff800a326900UL + slide;
    unsigned long target = rec_addr ? rec_addr : calculated;
    u64 *p = (u64 *)target;

    pr_emerg("HAKIOS_RECORD_LOC rec_sym=%lx stext=%lx slide=%lx target=%lx\\n",
             rec_addr, stext_addr, slide, target);

    pr_emerg("HAKIOS_V1 magic=%016llx ver=%llu bytes=%llu status=%llu reason=%llu\\n",
             p[0], p[1], p[2], p[3], p[4]);
    pr_emerg("HAKIOS_V1 x0=%016llx x1=%016llx x2=%016llx x3=%016llx\\n",
             p[5], p[6], p[7], p[8]);
    pr_emerg("HAKIOS_V1 el=%llu entry_pc=%016llx payload_pc=%016llx continue_pc=%016llx sp=%016llx\\n",
             p[9] >> 2, p[10], p[11], p[12], p[13]);
    pr_emerg("HAKIOS_V1 daif=%016llx cntfrq=%llu midr=%016llx sctlr=%016llx ctr=%016llx line=%llu\\n",
             p[14], p[15], p[16], p[17], p[18], p[19]);
    pr_emerg("HAKIOS_V1 payload_val=%016llx payload_marker=%016llx lr=%016llx nzcv=%016llx\\n",
             p[20], p[21], p[22], p[23]);

    return 0;
}

static void __exit probe_exit(void)
{
}

module_init(probe_init);
module_exit(probe_exit);
"""

MAKEFILE = """obj-m += early_probe.o
"""

def main():
    build_dir = Path("/opt/a51-hakios/diagnostics/early-probe")
    build_dir.mkdir(parents=True, exist_ok=True)
    (build_dir / "early_probe.c").write_text(PROBE_C, encoding="utf-8")
    (build_dir / "Makefile").write_text(MAKEFILE, encoding="utf-8")

    argv = [
        "make",
        "-C", "/opt/a51-everline/src",
        "O=/opt/a51-everline/out",
        f"M={build_dir}",
        "ARCH=arm64",
        "LLVM=1",
        "LLVM_IAS=1",
        "CC=clang",
        "LD=ld.lld",
        "AR=llvm-ar",
        "NM=llvm-nm",
        "OBJCOPY=llvm-objcopy",
        "OBJDUMP=llvm-objdump",
        "READELF=llvm-readelf",
        "CROSS_COMPILE=aarch64-linux-gnu-",
        "CROSS_COMPILE_ARM32=arm-linux-gnueabi-",
        "CLANG_TRIPLE=aarch64-linux-gnu-",
        "-j4",
        "modules"
    ]
    res = subprocess.run(argv, capture_output=True, text=True)
    print("STDOUT:\n", res.stdout)
    print("STDERR:\n", res.stderr)
    return res.returncode

if __name__ == "__main__":
    raise SystemExit(main())
