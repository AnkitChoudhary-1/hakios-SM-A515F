#!/usr/bin/env python3
"""
Phase 4 Hardware Inventory Probe
Queries live Samsung Galaxy A51 (SM-A515F / Exynos 9611) via ADB root
to extract hardware configurations for:
  1. Display (DECON, DSIM, Panel, Framebuffer)
  2. Touch (I2C Touchscreen Controller)
  3. Keys (GPIO Keys: Power, Vol+, Vol-)
  4. Storage (UFS Controller & Partitions)
"""

import subprocess
import json
import os
import sys

def adb_su(cmd: str) -> str:
    """Run command via adb shell su -c with safe argument list."""
    try:
        proc = subprocess.run(
            ["adb", "shell", "su", "-c", cmd],
            capture_output=True,
            text=True,
            timeout=15
        )
        return proc.stdout.strip()
    except Exception as e:
        return f"ERROR: {e}"

def parse_hex_words(raw_bytes_str: str) -> list:
    """Parse output of od -An -tx4 into hex values."""
    words = []
    for line in raw_bytes_str.splitlines():
        for tok in line.split():
            try:
                words.append(f"0x{int(tok, 16):08x}")
            except ValueError:
                pass
    return words

def main():
    print("=== Phase 4 Hardware Inventory Probe ===")
    inventory = {
        "device": "Samsung Galaxy A51 (SM-A515F)",
        "soc": "Exynos 9611",
        "display": {},
        "touch": {},
        "keys": {},
        "storage": {}
    }

    # 1. Framebuffer & Display
    print("[1/4] Probing Display & Framebuffer...")
    fb_res = adb_su("cat /sys/class/graphics/fb0/virtual_size")
    fb_bpp = adb_su("cat /sys/class/graphics/fb0/bits_per_pixel")
    decon_compat = adb_su("tr '\\0' ' ' < /proc/device-tree/decon_f@0x148B0000/compatible")
    decon_reg = parse_hex_words(adb_su("od -An -tx4 /proc/device-tree/decon_f@0x148B0000/reg"))
    decon_irq = parse_hex_words(adb_su("od -An -tx4 /proc/device-tree/decon_f@0x148B0000/interrupts"))
    dsim_reg = parse_hex_words(adb_su("od -An -tx4 /proc/device-tree/dsim@0x148E0000/reg"))
    dsim_compat = adb_su("tr '\\0' ' ' < /proc/device-tree/dsim@0x148E0000/compatible")
    iomem_fb = adb_su("grep -iE 'fb|decon|display|framebuffer' /proc/iomem")

    inventory["display"] = {
        "virtual_size": fb_res,
        "bits_per_pixel": fb_bpp,
        "decon_compatible": decon_compat,
        "decon_registers": decon_reg,
        "decon_interrupts": decon_irq,
        "dsim_registers": dsim_reg,
        "dsim_compatible": dsim_compat,
        "iomem_display_entries": iomem_fb.splitlines()
    }
    print(f"  DECON: {decon_reg[:2]} IRQs: {decon_irq[:4]}")
    print(f"  DSIM:  {dsim_reg[:2]}")
    print(f"  FB:    {fb_res} @ {fb_bpp} bpp")

    # 2. Touch
    print("[2/4] Probing Touchscreen Controller...")
    input_devs = adb_su("cat /proc/bus/input/devices")
    touch_nodes = adb_su("find /proc/device-tree/ -name '*tsp*' -o -name '*touch*' -o -name '*mms*'")
    touch_dmesg = adb_su("dmesg | grep -iE 'mms|touch|tsp' | tail -n 20")

    inventory["touch"] = {
        "input_devices": input_devs,
        "touch_dt_nodes": touch_nodes.splitlines(),
        "touch_dmesg": touch_dmesg.splitlines()
    }

    # 3. Keys
    print("[3/4] Probing Hardware Keys (Power, Vol+, Vol-)...")
    gpio_keys_nodes = adb_su("find /proc/device-tree/ -name '*gpio_keys*' -o -name '*keys*'")
    keys_dmesg = adb_su("dmesg | grep -iE 'gpio.*key|sec_keys' | tail -n 20")

    inventory["keys"] = {
        "dt_nodes": gpio_keys_nodes.splitlines(),
        "dmesg": keys_dmesg.splitlines()
    }

    # 4. Storage (UFS)
    print("[4/4] Probing UFS Storage Subsystem...")
    ufs_nodes = adb_su("find /proc/device-tree/ -name '*ufs*'")
    ufs_reg = parse_hex_words(adb_su("od -An -tx4 /proc/device-tree/ufs@0x15570000/reg 2>/dev/null || od -An -tx4 /proc/device-tree/ufs@15570000/reg 2>/dev/null"))
    ufs_compat = adb_su("tr '\\0' ' ' < /proc/device-tree/ufs@*/compatible 2>/dev/null")
    block_partitions = adb_su("cat /proc/partitions | grep sda | head -n 30")

    inventory["storage"] = {
        "ufs_dt_nodes": ufs_nodes.splitlines(),
        "ufs_registers": ufs_reg,
        "ufs_compatible": ufs_compat,
        "partitions_sample": block_partitions.splitlines()
    }

    out_dir = "evidence/phase-4/hardware-inventory"
    os.makedirs(out_dir, exist_ok=True)
    out_file = os.path.join(out_dir, "report.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(inventory, f, indent=2)

    print(f"\n[OK] Hardware inventory saved to: {out_file}")

if __name__ == "__main__":
    main()
