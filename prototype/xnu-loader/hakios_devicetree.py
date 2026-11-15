#!/usr/bin/env python3
"""Apple Device Tree (DeviceTreeP) builder and validator for HakiOS Exynos 9611.

Generates byte-accurate flattened Apple Device Trees compatible with Darwin/XNU
SecureDTInit() and IOKit. Includes CHRP NVRAM proxy bank generator with Adler-32.
"""
import struct
import time
from typing import Any, Dict, List, Optional, Tuple

PROP_NAME_LENGTH = 32
NVRAM_BANK_SIZE = 0x2000  # 8 KB


def adler32_custom(data: bytes) -> int:
    """Computes Adler-32 with modulo 65521 matching XNU bootloader."""
    lo = 1
    hi = 0
    for b in data:
        lo = (lo + b) % 65521
        hi = (hi + lo) % 65521
    return (hi << 16) | lo


def nvram_chrp_header(sig: int, length: int, name: str) -> bytes:
    """Creates a 16-byte CHRP partition header."""
    blocks = length // 16
    h = bytearray(16)
    h[0] = sig & 0xFF
    h[2] = blocks & 0xFF
    h[3] = (blocks >> 8) & 0xFF
    name_bytes = name.encode("ascii")[:12]
    h[4 : 4 + len(name_bytes)] = name_bytes

    # Folded 8-bit checksum over signature, length and name
    s = h[0]
    for b in h[2:16]:
        s += b
    while s > 0xFF:
        s = (s & 0xFF) + (s >> 8)
    h[1] = s & 0xFF
    return bytes(h)


def build_nvram_image(bank_size: int = NVRAM_BANK_SIZE) -> bytes:
    """Builds a valid CHRP NVRAM bank with Apple and common partitions."""
    img = bytearray(bank_size)
    # 0x00: Apple header (32 bytes)
    img[0:16] = nvram_chrp_header(0x5A, 0x20, "nvram")
    # 0x20: Common partition (remaining bytes)
    img[0x20:0x30] = nvram_chrp_header(0x70, bank_size - 0x20, "common")

    # Generation counter at offset 20
    generation = 1
    struct.pack_into("<I", img, 20, generation)

    # Adler-32 over everything after the checksum field (offset 20 onwards)
    checksum = adler32_custom(bytes(img[20:]))
    struct.pack_into("<I", img, 16, checksum)
    return bytes(img)


class DeviceTreeWriter:
    """Constructs a flattened Apple Device Tree."""

    def __init__(self):
        self.buf = bytearray()
        self.node_stack: List[int] = []  # Stack of offsets to (nProperties, nChildren)
        self.prop_counts: List[int] = []
        self.child_counts: List[int] = []

    def begin_node(self, name: str):
        if self.node_stack:
            self.child_counts[-1] += 1
        off = len(self.buf)
        self.node_stack.append(off)
        self.prop_counts.append(0)
        self.child_counts.append(0)
        # Allocate 8 bytes for uint32 nProperties, uint32 nChildren
        self.buf.extend(b"\x00" * 8)
        # The first property of every node is its name
        self.add_prop_str("name", name)

    def add_prop(self, name: str, data: bytes):
        assert self.node_stack, "add_prop called outside of any node"
        name_bytes = name.encode("ascii")[: PROP_NAME_LENGTH - 1]
        name_field = name_bytes + b"\x00" * (PROP_NAME_LENGTH - len(name_bytes))
        length = len(data)
        padded_len = (length + 3) & ~3
        pad = b"\x00" * (padded_len - length)

        self.buf.extend(name_field)
        self.buf.extend(struct.pack("<I", length))
        self.buf.extend(data)
        self.buf.extend(pad)
        self.prop_counts[-1] += 1

    def add_prop_str(self, name: str, value: str):
        self.add_prop(name, value.encode("utf-8") + b"\x00")

    def add_prop_u32(self, name: str, value: int):
        self.add_prop(name, struct.pack("<I", value & 0xFFFFFFFF))

    def add_prop_u64(self, name: str, value: int):
        self.add_prop(name, struct.pack("<Q", value & 0xFFFFFFFFFFFFFFFF))

    def add_prop_reg2(self, name: str, addr: int, size: int):
        self.add_prop(name, struct.pack("<QQ", addr, size))

    def end_node(self):
        assert self.node_stack, "end_node called with empty stack"
        off = self.node_stack.pop()
        n_props = self.prop_counts.pop()
        n_children = self.child_counts.pop()
        struct.pack_into("<II", self.buf, off, n_props, n_children)

    def finish(self) -> bytes:
        assert not self.node_stack, f"Unclosed nodes: {len(self.node_stack)}"
        return bytes(self.buf)


class DeviceTreeReader:
    """Parses and validates a flattened Apple Device Tree."""

    def __init__(self, data: bytes):
        self.data = data
        self.root: Optional[Dict[str, Any]] = None
        self._parse()

    def _parse(self):
        offset = 0

        def parse_node() -> Tuple[Dict[str, Any], int]:
            nonlocal offset
            n_props, n_children = struct.unpack("<II", self.data[offset : offset + 8])
            node_off = offset
            offset += 8
            props: Dict[str, bytes] = {}
            for _ in range(n_props):
                name_raw = self.data[offset : offset + PROP_NAME_LENGTH]
                name = name_raw.split(b"\x00")[0].decode("ascii", errors="replace")
                offset += PROP_NAME_LENGTH
                length = struct.unpack("<I", self.data[offset : offset + 4])[0]
                offset += 4
                padded_len = (length + 3) & ~3
                val = self.data[offset : offset + length]
                offset += padded_len
                props[name] = val

            children: List[Dict[str, Any]] = []
            for _ in range(n_children):
                child, _ = parse_node()
                children.append(child)

            node_name = props.get("name", b"").split(b"\x00")[0].decode("ascii", errors="replace")
            return {
                "name": node_name,
                "offset": node_off,
                "props": props,
                "children": children,
            }, offset

        if len(self.data) >= 8:
            self.root, _ = parse_node()

    def find_node(self, path: str) -> Optional[Dict[str, Any]]:
        """Finds a node by path, e.g. '/chosen/memory-map'."""
        if not self.root:
            return None
        parts = [p for p in path.split("/") if p]
        cur = self.root
        for part in parts:
            found = False
            for child in cur.get("children", []):
                if child.get("name") == part:
                    cur = child
                    found = True
                    break
            if not found:
                return None
        return cur


def build_exynos9611_device_tree(
    dram_base: int = 0x80000000,
    dram_size: int = 0x40000000,  # 1 GB
    ramdisk_pa: Optional[int] = None,
    ramdisk_size: int = 0,
    uart_pa: int = 0x13820000,
    gic_dist_pa: int = 0x12301000,
    gic_cpu_pa: int = 0x12302000,
    timebase_hz: int = 26000000,  # 26 MHz
    fb_base_pa: Optional[int] = 0xCA000000,
    fb_size: int = 0x01000000,    # 16 MB
    enable_phase4_peripherals: bool = True,
) -> bytes:
    """Synthesizes the complete flattened Apple Device Tree for Exynos 9611 / Galaxy A51."""
    w = DeviceTreeWriter()

    # Root Node
    w.begin_node("device-tree")
    w.add_prop_str("model", "iPhone10,3")
    w.add_prop_str("target-type", "t8015")
    w.add_prop_str("platform-name", "t8015")
    w.add_prop_str("compatible", "iPhone10,3\0ApplePhone\0")
    w.add_prop("serial-number", b"RDW00A515F0001\x00" + b"\x00" * 17)
    w.add_prop("mlb-serial-number", b"RDW00A515FMLB01\x00" + b"\x00" * 15)
    w.add_prop_str("model-number", "MQAC2")
    w.add_prop_str("region-info", "LL/A")
    w.add_prop_str("regulatory-model-number", "A1865")
    w.add_prop_u32("#address-cells", 2)
    w.add_prop_u32("#size-cells", 2)

    # /chosen
    w.begin_node("chosen")
    # 64-byte random seed
    seed = bytes((i * 37) & 0xFF for i in range(64))
    w.add_prop("random-seed", seed)
    w.add_prop_u64("dram-base", dram_base)
    w.add_prop_u64("dram-size", dram_size)
    w.add_prop_u32("debug-enabled", 1)
    w.add_prop_u32("display-scale", 3)
    w.add_prop_u32("display-rotation", 0)
    w.add_prop_str("psci-method", "smc")
    w.add_prop_u64("boot-epoch", int(time.time()))
    w.add_prop_u64("unique-chip-id", 0x000052445730001)
    w.add_prop_u32("chip-id", 0x8015)
    w.add_prop_u32("board-id", 0x06)
    w.add_prop_str("firmware-version", "iBoot-8422.100.650")
    w.add_prop_u32("certificate-production-status", 1)
    w.add_prop_u32("certificate-security-mode", 1)
    w.add_prop_u32("effective-production-status-ap", 1)
    w.add_prop_u32("effective-security-mode-ap", 1)
    w.add_prop_u32("secure-boot", 1)
    w.add_prop_u32("production-cert", 1)
    w.add_prop_u32("development-cert", 0)
    w.add_prop_u32("embedded-panic-log-size", 0x80000)

    # NVRAM proxy bank
    nvram_data = build_nvram_image(NVRAM_BANK_SIZE)
    w.add_prop_u32("nvram-bank-size", NVRAM_BANK_SIZE)
    w.add_prop_u32("nvram-bank-count", 1)
    w.add_prop_u32("nvram-current-bank", 0)
    w.add_prop("nvram-proxy-data", nvram_data)

    # /chosen/memory-map
    w.begin_node("memory-map")
    if ramdisk_pa is not None and ramdisk_size > 0:
        w.add_prop_reg2("RAMDisk", ramdisk_pa, ramdisk_size)
    if fb_base_pa is not None and fb_size > 0:
        w.add_prop_reg2("BootFramebuffer", fb_base_pa, fb_size)
    w.end_node()  # memory-map

    w.end_node()  # chosen

    # /defaults
    w.begin_node("defaults")
    w.add_prop_u32("kern.vm_compressor", 2)
    w.end_node()  # defaults

    # /product
    w.begin_node("product")
    w.add_prop_str("product-name", "iPhone X")
    w.end_node()  # product

    # /options (IOKit NVRAM anchor)
    w.begin_node("options")
    w.end_node()  # options

    # /pram (Panic log DRAM span: 512 KB at 0x80180000)
    w.begin_node("pram")
    w.add_prop_reg2("reg", 0x80180000, 0x80000)
    w.end_node()  # pram

    # /cpus
    w.begin_node("cpus")
    w.begin_node("cpu0")
    w.add_prop_str("device_type", "cpu")
    w.add_prop_str("state", "running")
    w.add_prop_u32("reg", 0)
    w.add_prop_u32("cpu-id", 0)
    w.add_prop_u64("timebase-frequency", timebase_hz)
    w.add_prop_u64("fixed-frequency", timebase_hz)
    w.add_prop_u64("clock-frequency", 2300000000)  # 2.3 GHz
    w.add_prop_u64("bus-frequency", 100000000)
    w.add_prop_u64("memory-frequency", 100000000)
    w.add_prop_u64("peripheral-frequency", timebase_hz)
    w.end_node()  # cpu0
    w.end_node()  # cpus

    # /arm-io (Exynos 9611 MMIO peripherals: base 0x10000000)
    soc_base = 0x10000000
    w.begin_node("arm-io")
    w.add_prop_str("device_type", "exynos9611")
    # ranges: child-offset(0), parent-base(soc_base), size(0x10000000 = 256MB)
    ranges = struct.pack("<QQQQ", 0, soc_base, 0x10000000, 0)
    w.add_prop("ranges", ranges)
    w.add_prop_u32("#address-cells", 2)
    w.add_prop_u32("#size-cells", 2)

    # /arm-io/gic (GICv2 on Exynos 9611)
    w.begin_node("gic")
    w.add_prop_str("device_type", "interrupt-controller")
    w.add_prop_str("compatible", "arm,cortex-a15-gic")
    # reg: offsets relative to soc_base (GICD 0x12301000 -> 0x02301000, GICC 0x12302000 -> 0x02302000)
    gic_regs = struct.pack(
        "<QQQQ",
        gic_dist_pa - soc_base, 0x1000,
        gic_cpu_pa - soc_base, 0x1000
    )
    w.add_prop("reg", gic_regs)
    w.end_node()  # gic

    # /arm-io/uart0 (Exynos 9611 serial console at physical 0x13820000)
    w.begin_node("uart0")
    w.add_prop_str("device_type", "uart")
    w.add_prop_str("compatible", "uart-1,samsung")
    uart_offset = uart_pa - soc_base  # 0x13820000 - 0x10000000 = 0x03820000
    uart_regs = struct.pack("<QQ", uart_offset, 0x1000)
    w.add_prop("reg", uart_regs)
    w.add_prop_u32("boot-console", 1)
    w.add_prop_u32("enable-legacy-serial", 1)
    w.add_prop_u32("sampling", 16)
    w.add_prop_u32("ubrdiv", 14)
    w.end_node()  # uart0

    if enable_phase4_peripherals:
        # /arm-io/decon0 (Display controller at 0x148B0000)
        w.begin_node("decon0")
        w.add_prop_str("device_type", "display")
        w.add_prop_str("compatible", "samsung,exynos-decon")
        decon_regs = struct.pack("<QQ", 0x148B0000 - soc_base, 0x1000)
        w.add_prop("reg", decon_regs)
        w.add_prop_u32("width", 1080)
        w.add_prop_u32("height", 2400)
        w.add_prop_u32("stride", 4320)
        w.add_prop_u32("bpp", 32)
        w.end_node()  # decon0

        # /arm-io/dsim0 (MIPI DSI controller at 0x148E0000)
        w.begin_node("dsim0")
        w.add_prop_str("device_type", "dsim")
        w.add_prop_str("compatible", "samsung,exynos-dsim")
        dsim_regs = struct.pack("<QQ", 0x148E0000 - soc_base, 0x1000)
        w.add_prop("reg", dsim_regs)
        w.add_prop_str("panel", "s6e3fa9")
        w.end_node()  # dsim0

        # /arm-io/i2c4 (I2C-4 at 0x13870000 with Melfas Touchscreen)
        w.begin_node("i2c4")
        w.add_prop_str("device_type", "i2c")
        w.add_prop_str("compatible", "samsung,exynos-i2c")
        i2c_regs = struct.pack("<QQ", 0x13870000 - soc_base, 0x1000)
        w.add_prop("reg", i2c_regs)
        w.begin_node("mms_ts")
        w.add_prop_str("device_type", "touchscreen")
        w.add_prop_str("compatible", "melfas,mms_ts")
        w.add_prop_u32("reg", 0x48)
        w.add_prop_u32("max-x", 1080)
        w.add_prop_u32("max-y", 2400)
        w.end_node()  # mms_ts
        w.end_node()  # i2c4

        # /arm-io/gpio-keys (Hardware buttons)
        w.begin_node("gpio-keys")
        w.add_prop_str("device_type", "input")
        w.add_prop_str("compatible", "gpio-keys")
        w.begin_node("button_power")
        w.add_prop_u32("linux,code", 116)
        w.add_prop_str("label", "KEY_POWER")
        w.end_node()
        w.begin_node("button_volup")
        w.add_prop_u32("linux,code", 115)
        w.add_prop_str("label", "KEY_VOLUMEUP")
        w.end_node()
        w.begin_node("button_voldown")
        w.add_prop_u32("linux,code", 114)
        w.add_prop_str("label", "KEY_VOLUMEDOWN")
        w.end_node()
        w.end_node()  # gpio-keys

        # /arm-io/ufs0 (UFS 2.1 Storage Controller at 0x13520000)
        w.begin_node("ufs0")
        w.add_prop_str("device_type", "block")
        w.add_prop_str("compatible", "samsung,exynos-ufs")
        ufs_regs = struct.pack("<QQ", 0x13520000 - soc_base, 0x1000)
        w.add_prop("reg", ufs_regs)
        w.add_prop_u32("read-only", 1)
        w.end_node()  # ufs0

    w.end_node()  # arm-io

    w.end_node()  # device-tree

    return w.finish()

