#!/usr/bin/env python3
"""Unit tests for hakios_devicetree.py"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from hakios_devicetree import build_exynos9611_device_tree, DeviceTreeReader, build_nvram_image


def main():
    dt_bytes = build_exynos9611_device_tree(
        dram_base=0x80000000,
        dram_size=0x40000000,
        ramdisk_pa=0x84000000,
        ramdisk_size=0x01000000,
        uart_pa=0x13820000,
        gic_dist_pa=0x12301000,
        gic_cpu_pa=0x12302000,
        timebase_hz=26000000,
    )

    print(f"Device tree binary size: {len(dt_bytes)} bytes")
    assert len(dt_bytes) > 8192, f"Device tree too small: {len(dt_bytes)}"

    reader = DeviceTreeReader(dt_bytes)
    assert reader.root is not None, "Failed to parse root node"
    root_name = reader.root["name"]
    n_props = len(reader.root["props"])
    n_children = len(reader.root["children"])
    print(f"Root node: {root_name}, props: {n_props}, children: {n_children}")
    assert root_name == "device-tree"

    chosen = reader.find_node("/chosen")
    assert chosen is not None, "Failed to find /chosen"
    print(f"/chosen node props: {len(chosen['props'])}")
    assert "dram-base" in chosen["props"]
    assert "dram-size" in chosen["props"]
    assert "nvram-proxy-data" in chosen["props"]

    cpus = reader.find_node("/cpus/cpu0")
    assert cpus is not None, "Failed to find /cpus/cpu0"
    tb_freq = int.from_bytes(cpus["props"]["timebase-frequency"], "little")
    print(f"cpu0 timebase-frequency: {tb_freq} Hz (expected 26000000)")
    assert tb_freq == 26000000

    gic = reader.find_node("/arm-io/gic")
    assert gic is not None, "Failed to find /arm-io/gic"
    gic_compat = gic["props"]["compatible"].split(b"\x00")[0].decode()
    print(f"gic compatible: {gic_compat}")
    assert gic_compat == "arm,cortex-a15-gic"

    uart = reader.find_node("/arm-io/uart0")
    assert uart is not None, "Failed to find /arm-io/uart0"
    uart_compat = uart["props"]["compatible"].split(b"\x00")[0].decode()
    print(f"uart0 compatible: {uart_compat}")
    assert uart_compat in ("samsung,exynos-uart", "uart-1,samsung")

    nvram = build_nvram_image(8192)
    assert len(nvram) == 8192
    assert nvram[0] == 0x5A, "Invalid Apple NVRAM signature"
    assert nvram[0x20] == 0x70, "Invalid Common NVRAM signature"
    print("Device tree pack/unpack and NVRAM generator verified 100%!")


if __name__ == "__main__":
    main()

