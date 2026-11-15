#!/usr/bin/env python3
"""Strict standalone Phase 4 packaging; importing never invokes a command."""
from __future__ import annotations
import hashlib
from pathlib import Path
import struct
import sys
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "xnu-loader"))
from hakios_macho import BootArgs, BootVideo, MachOFile
from hakios_devicetree import build_exynos9611_device_tree, DeviceTreeReader, DeviceTreeWriter

VIRT_BASE = 0xFFFFFFF004000000
PHYS_BASE = 0x80000000
SLIDE = PHYS_BASE - VIRT_BASE
DEST_MIN, DEST_END = 0x83000000, 0x847f0000
IMAGE_BASE, IMAGE_BYTES = 0x80080000, 36334080
INITIAL_LIMIT = 0x87000000
CONFIG_MAGIC = 0x34444c534f494b48
MAX_LOG = 1536 * 1024


def require(ok, message):
    if not ok:
        raise ValueError(message)


def span(start, size, lower, upper, name):
    require(isinstance(start, int) and isinstance(size, int) and size >= 0,
            name + ": invalid integer extent")
    require(lower <= start <= upper and size <= upper - start,
            name + ": outside allowed extent")


def validate_macho(raw):
    require(len(raw) >= 32, "Mach-O header truncated")
    magic, cpu, _, filetype, count, size, _, _ = struct.unpack_from("<8I", raw)
    require(magic == 0xFEEDFACF and cpu == 0x0100000C and filetype == 2,
            "Expected arm64 executable Mach-O")
    require(0 < count <= 4096 and count * 8 <= size, "Invalid load-command count")
    span(32, size, 0, len(raw), "load commands")
    offset, limit, entries, segments = 32, 32 + size, [], []
    for _ in range(count):
        span(offset, 8, 32, limit, "command header")
        cmd, cmdsize = struct.unpack_from("<2I", raw, offset)
        require(cmdsize >= 8 and cmdsize % 8 == 0, "Invalid command size")
        span(offset, cmdsize, 32, limit, "load command")
        if cmd == 0x19:
            require(cmdsize >= 72, "Segment command truncated")
            name, va, vmbytes, fileoff, filebytes, maxp, initp, ns, flags = struct.unpack_from("<16s4Q4I", raw, offset + 8)
            require(cmdsize == 72 + ns * 80, "Segment section count differs from command size")
            require(filebytes <= vmbytes, "Segment file size exceeds VM size")
            span(fileoff, filebytes, 0, len(raw), "segment source")
            span(va, vmbytes, 0, 1 << 64, "virtual segment")
            if vmbytes:
                dest = va + SLIDE
                span(dest, vmbytes, DEST_MIN, DEST_END, "kernel destination")
                for prior in segments:
                    require(dest + vmbytes <= prior["pa"] or prior["pa"] + prior["vmsize"] <= dest,
                            "Overlapping kernel destination segments")
                segments.append({"name": name.split(b"\0")[0].decode("ascii"), "pa": dest,
                    "va": va, "vmsize": vmbytes, "fileoff": fileoff, "filesize": filebytes,
                    "initprot": initp, "maxprot": maxp, "flags": flags})
        elif cmd == 5:
            require(cmdsize == 288, "Unsupported ARM64 thread state")
            flavor, words = struct.unpack_from("<2I", raw, offset + 8)
            require(flavor == 6 and words == 68, "Invalid ARM64 thread flavor/count")
            entries.append(struct.unpack_from("<Q", raw, offset + 16 + 32 * 8)[0] + SLIDE)
        offset += cmdsize
    require(offset == limit and len(entries) == 1 and segments, "Incomplete executable load commands")
    entry = entries[0]
    require(entry % 4 == 0 and any(s["initprot"] & 4 and s["pa"] <= entry and
            entry + 4 <= s["pa"] + s["filesize"] for s in segments), "Entry is not backed executable code")
    slots = []
    offset = raw.find(b"XNULDRST")
    while offset >= 0:
        for s in segments:
            if s["fileoff"] <= offset and offset + 32 <= s["fileoff"] + s["filesize"]:
                slots.append(offset - s["fileoff"] + s["pa"])
        offset = raw.find(b"XNULDRST", offset + 1)
    require(len(slots) == 1 and slots[0] % 8 == 0, "Missing/ambiguous/unaligned return-stub slot")
    # Cross-check against the independent parser used by the historical route.
    parsed = MachOFile(raw)
    require(parsed.entry_point_va + SLIDE == entry and parsed.find_loader_stub_slot()[1] + SLIDE == slots[0],
            "Independent Mach-O interpretations disagree")
    return {"entry_pa": entry, "stub_slot_pa": slots[0], "segments": segments}


def validate_toc(toc, payload_size):
    require(0 < len(toc) <= 64, "Empty/oversized TOC")
    for i, (src, dest, copy, zero) in enumerate(toc):
        span(src, copy, 0, payload_size, "TOC source")
        require(0 <= zero < 1 << 64 and copy + zero > 0, "Invalid TOC zero extent")
        span(dest, copy + zero, DEST_MIN, DEST_END, "TOC destination")
        for _, earlier, ec, ez in toc[:i]:
            require(dest + copy + zero <= earlier or earlier + ec + ez <= dest,
                    "Overlapping TOC destinations")


def make_tree(mode, rd_pa, rd_bytes, pram_pa):
    tree = DeviceTreeReader(build_exynos9611_device_tree(
        dram_base=PHYS_BASE, dram_size=INITIAL_LIMIT - PHYS_BASE,
        ramdisk_pa=rd_pa, ramdisk_size=rd_bytes, uart_pa=0x13820000,
        gic_dist_pa=0x12301000, gic_cpu_pa=0x12302000,
        timebase_hz=62500000 if mode == "qemu" else 26000000)).root
    writer = DeviceTreeWriter()
    import os
    overrides = {"/chosen": {"random-seed": os.urandom(64)},
                 "/pram": {"reg": struct.pack("<QQ", pram_pa, 0x80000)}}
    if mode == "qemu":
        overrides.update({
            "/arm-io": {"ranges": struct.pack("<QQQQ", 0, 0x08000000, 0x10000000, 0)},
            "/arm-io/gic": {"reg": struct.pack("<QQQQ", 0, 0x1000, 0x10000, 0x1000)},
            "/arm-io/uart0": {"reg": struct.pack("<QQ", 0x01000000, 0x1000), "compatible": b"arm,pl011\0"},
        })
    def emit(node, path):
        writer.begin_node(node["name"])
        for name, value in dict(node["props"], **overrides.get(path, {})).items():
            if name != "name":
                writer.add_prop(name, value)
        for child in node["children"]:
            emit(child, path + "/" + child["name"])
        writer.end_node()
    emit(tree, "")
    blob = writer.finish()
    require(DeviceTreeReader(blob).find_node("/pram")["props"]["reg"] == struct.pack("<QQ", pram_pa, 0x80000), "Panic buffer relocation failed")
    return blob


def find_logs(raw, layout):
    found, offset = [], raw.find(b"XNULIVE!")
    while offset >= 0:
        if offset + 64 <= len(raw):
            words = struct.unpack_from("<8Q", raw, offset)
            log, length = words[2] + SLIDE, words[3] + SLIDE
            in_vm = lambda a, n: any(s["pa"] <= a and a + n <= s["pa"] + s["vmsize"] for s in layout["segments"])
            if words[6:8] == (256 * 1024, 1024 * 1024) and in_vm(log, MAX_LOG) and in_vm(length, 4):
                found.append((log, length))
        offset = raw.find(b"XNULIVE!", offset + 1)
    require(len(found) == 1, "Expected exactly one bounded XNULIVE log contract")
    return found[0]


def prepare(kernel, hello, work, nonce, cmdline, watchdog_test=False, *,
            mode="hardware", diagnostic=None, checkpoint=0, watchdog_count=None):
    require(len(nonce) == 32 and all(c in "0123456789abcdef" for c in nonce), "Invalid nonce")
    require(len(cmdline.encode()) < 608 and "\0" not in cmdline and "\n" not in cmdline, "Boot arguments too long/invalid")
    require(cmdline.split().count("hakios_run_nonce=" + nonce) == 1, "Bootargs nonce differs from record")
    raw, hello_raw = Path(kernel).read_bytes(), Path(hello).read_bytes()
    layout = validate_macho(raw)
    log_pa, log_len_pa = find_logs(raw, layout)
    require(mode in ("hardware", "qemu"), "Invalid platform mode")
    diagnostic = (2 if watchdog_test else 0) if diagnostic is None else diagnostic
    require(0 <= diagnostic <= (4 if mode == "qemu" else 3), "Invalid diagnostic")
    watchdog_count = (4096 if diagnostic == 2 else 32768) if watchdog_count is None else watchdog_count
    require(100 <= watchdog_count <= 65535 and 0 <= checkpoint <= 40, "Invalid watchdog/checkpoint")
    require(32 <= len(hello_raw) <= 1048576 and hello_raw[:8] == struct.pack("<2I", 0xFEEDFACF, 0x0100000C), "Invalid static arm64 user image")
    align = lambda n, a=65536: (n + a - 1) & -a
    end = align(max(s["pa"] + s["vmsize"] for s in layout["segments"]))
    rd_pa, rd_bytes = end + 65536, align(len(hello_raw), 4096)
    ba_pa = align(rd_pa + rd_bytes)
    dt_pa = ba_pa + 65536
    dt = make_tree(mode, rd_pa, rd_bytes, 0)
    pram_pa = align(dt_pa + len(dt))
    dt = make_tree(mode, rd_pa, rd_bytes, pram_pa)
    require(dt_pa + len(dt) <= pram_pa, "Device-tree size changed after relocation")
    top = pram_pa + 0x80000
    span(pram_pa, 0x80000, DEST_MIN, DEST_END, "panic buffer")
    require(top + 0x2000000 < INITIAL_LIMIT, "Less than 32 MiB initial free RAM")
    ba = BootArgs(virtBase=VIRT_BASE, physBase=PHYS_BASE, memSize=INITIAL_LIMIT - PHYS_BASE,
        topOfKernelData=top, video=BootVideo(), deviceTreeP=dt_pa - SLIDE,
        deviceTreeLength=len(dt), commandLine=cmdline, memSizeActual=INITIAL_LIMIT - PHYS_BASE).pack()
    require(len(ba) == 736 and BootArgs.unpack(ba).commandLine == cmdline, "BootArgs ABI/round trip")
    payload, toc = bytearray(), []
    def chunk(dest, data, vmbytes):
        payload.extend(b"\0" * (-len(payload) % 16))
        src = len(payload)
        payload.extend(data)
        require(len(data) <= vmbytes, "Chunk file bytes exceed extent")
        toc.append((src, dest, len(data), vmbytes - len(data)))
    chunk(ba_pa, ba, len(ba))
    chunk(dt_pa, dt, len(dt))
    chunk(rd_pa, hello_raw, rd_bytes)
    chunk(pram_pa, b"", 0x80000)
    for s in layout["segments"]:
        chunk(s["pa"], raw[s["fileoff"]:s["fileoff"] + s["filesize"]], s["vmsize"])
    validate_toc(toc, len(payload))
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    blob = work / "payload.bin"
    blob.write_bytes(payload)
    kernel_base = min(s["pa"] for s in layout["segments"])
    kernel_limit = max(s["pa"] + s["vmsize"] for s in layout["segments"])
    config = [CONFIG_MAGIC, 1, len(toc), len(payload), DEST_MIN, DEST_END,
        layout["entry_pa"], ba_pa, layout["stub_slot_pa"], SLIDE & ((1 << 64) - 1),
        checkpoint, diagnostic, kernel_base, kernel_limit, log_pa, MAX_LOG,
        log_len_pa, watchdog_count, int(nonce[:16], 16), int(nonce[16:], 16)]
    entries = [{"source": s, "destination": d, "copy": c, "zero": z,
                "crc": zlib.crc32(payload[s:s+c]), "reserved": 0} for s,d,c,z in toc]
    assembly = ['.section .toc,"a"', '.balign 8', '.global payload_config', 'payload_config:',
        '.quad ' + ','.join(hex(v) for v in config), '.global payload_toc', 'payload_toc:']
    assembly += ['.quad ' + ','.join(hex(e[k]) for k in ("source", "destination", "copy", "zero", "crc", "reserved")) for e in entries]
    assembly += ['.global payload_toc_end', 'payload_toc_end:', '.section .payload,"a"',
        '.global payload_base', 'payload_base:', f'.incbin "{blob.as_posix()}"',
        '.global payload_end', 'payload_end:']
    (work / "payload.S").write_text("\n".join(assembly) + "\n", encoding="utf-8")
    layout.update({"boot_args_pa": ba_pa, "device_tree_pa": dt_pa, "ramdisk_pa": rd_pa,
        "pram_pa": pram_pa, "pram_bytes": 0x80000, "arena_base": DEST_MIN, "arena_limit": DEST_END,
        "kernel_base": kernel_base, "kernel_limit": kernel_limit, "log_pa": log_pa, "log_len_pa": log_len_pa,
        "top_of_kernel_data": top, "initial_memory_budget_bytes": INITIAL_LIMIT - PHYS_BASE,
        "payload_bytes": len(payload), "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "toc": entries, "config": config, "nonce": nonce, "cmdline": cmdline,
        "diagnostic": diagnostic, "watchdog_count": watchdog_count, "mode": mode,
        "video": "unavailable_zero_bootvideo"})
    return layout
