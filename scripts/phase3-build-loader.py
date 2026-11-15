#!/usr/bin/env python3
"""Build a fresh bounded Phase 3 loader from the selected pinned kernel/hello.

Run inside A51-KernelBuilder through scripts/run.py. This never writes a device
or replaces upstream sources, old loaders, or previous build evidence.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import struct
import sys
import uuid
import zlib
from phase3_support import PROJECT, command, json_write, packet_new, packet_index, pin, require
from phase3_carrier import wrap as wrap_carrier

sys.path.insert(0, str(PROJECT / "prototype/xnu-loader"))
from hakios_macho import BootArgs, MachOFile
from hakios_devicetree import DeviceTreeReader, DeviceTreeWriter, build_exynos9611_device_tree

IMAGE_BASE = 0x80080000
IMAGE_BYTES = 36334080
DRAM_BASE = 0x80000000
ARENA_LIMIT = 0x87000000  # Preserve Samsung EL2 code at [0x87000000,0x87200000).
SLIDE = DRAM_BASE - 0xfffffff004000000
CONFIG_MAGIC = 0x33444c534f494b48
MAX_LOG = 1536 * 1024
MASK64 = (1 << 64) - 1


def align(n, a=65536):
    return (n + a - 1) & -a


def checked_macho(raw):
    require(len(raw) >= 32, "Truncated Mach-O header")
    n, size = struct.unpack_from("<II", raw, 16)
    require(0 < n <= 256 and 32 + size <= len(raw), "Mach-O command bounds")
    at = 32
    for _ in range(n):
        require(at + 8 <= 32 + size, "Truncated load command")
        cmd, length = struct.unpack_from("<II", raw, at)
        require(length >= 8 and length % 8 == 0 and at + length <= 32 + size, "Invalid load command size")
        if cmd == 0x19:
            require(length >= 72, "Truncated segment")
            require(length == 72 + struct.unpack_from("<I", raw, at + 64)[0] * 80, "Segment section bounds")
        if cmd == 5:
            require(length >= 16 + 34 * 8, "Truncated ARM64 thread state")
        at += length
    require(at == 32 + size, "Load commands do not cover sizeofcmds")
    macho = MachOFile(raw)
    ranges = []
    for seg in macho.segments:
        require(seg.filesize <= seg.vmsize and seg.fileoff + seg.filesize <= len(raw), "Invalid file/VM extent: " + seg.name)
        if not seg.vmsize:
            continue
        lo, hi = seg.vmaddr + SLIDE, seg.vmaddr + SLIDE + seg.vmsize
        require(IMAGE_BASE + IMAGE_BYTES <= lo < hi < ARENA_LIMIT, "Unsafe kernel extent: " + seg.name)
        require(all(hi <= a or b <= lo for a, b in ranges), "Kernel destination overlap")
        ranges.append((lo, hi))
    require(ranges and any(a <= macho.entry_point_va + SLIDE < b for a, b in ranges), "Kernel entry is outside segments")
    return macho, ranges


def find_live(raw, macho, ranges):
    matches, at = [], 0
    while True:
        at = raw.find(b"XNULIVE!", at)
        if at < 0:
            break
        if at + 64 <= len(raw):
            words = struct.unpack_from("<8Q", raw, at)
            log, length = words[2] + SLIDE, words[3] + SLIDE
            if words[6:8] == (256 * 1024, 1024 * 1024) and any(a <= log and log + MAX_LOG <= b for a, b in ranges) and any(a <= length and length + 4 <= b for a, b in ranges):
                matches.append((at, log, length))
        at += 8
    require(len(matches) == 1, "Expected one valid XNULIVE log contract")
    return matches[0]


def make_tree(mode, hello_pa, hello_size, pram_pa):
    tree = DeviceTreeReader(build_exynos9611_device_tree(
        dram_base=DRAM_BASE, dram_size=ARENA_LIMIT - DRAM_BASE,
        ramdisk_pa=hello_pa, ramdisk_size=hello_size,
        timebase_hz=62500000 if mode == "qemu" else 26000000)).root
    writer = DeviceTreeWriter()
    overrides = {
        "/chosen": {"random-seed": os.urandom(64)},
        "/pram": {"reg": struct.pack("<QQ", pram_pa, 0x80000)},
    }
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("hardware", "qemu"), required=True)
    parser.add_argument("--entry-style", choices=("standalone", "accepted-carrier"), default="standalone")
    parser.add_argument("--diagnostic", type=int, choices=(0, 1, 2, 3), default=0)
    parser.add_argument("--checkpoint", type=int, default=0)
    parser.add_argument("--watchdog-count", type=int, default=65535)
    args = parser.parse_args()
    require(os.name == "posix" and Path("/opt/a51-hakios").is_dir(), "Use A51-KernelBuilder WSL")
    require(0 <= args.checkpoint <= 40 and 100 <= args.watchdog_count <= 65535, "Invalid checkpoint/watchdog range")
    build = json.loads((PROJECT / "manifests/phase3-platform-build.json").read_text(encoding="utf-8"))
    workspace = json.loads((PROJECT / "manifests/phase3-workspace.json").read_text(encoding="utf-8"))
    root = Path(build["root"])
    require(build["build_verified"] and root == Path(workspace["root"]) and root.is_relative_to("/opt/a51-hakios/experimental/phase3-port"), "Wrong selected build root")
    for rel in ("hakios-kernel", "userland/hello"):
        require(pin(root / rel) == build["artifacts"][rel], "Selected artifact changed: " + rel)
    packet = packet_new("loader-build", Path(__file__))
    work = Path("/opt/a51-hakios/experimental/phase3-loader") / packet.name
    work.mkdir(parents=True, exist_ok=False)
    records = []
    result = {"schema_version": 1, "packet": packet.relative_to(PROJECT).as_posix(),
              "work": str(work), "mode": args.mode, "diagnostic": args.diagnostic, "entry_style": args.entry_style,
              "checkpoint": args.checkpoint, "build_packet": build["packet"],
              "passed": False, "device_operations": False, "phase_3_device_gate_passed": False}
    try:
        for key, path in (("common", root), ("native", root / "xnu-src/xnu-8796.121.2")):
            head = command(packet, records, "head-" + key, ["git", "-C", str(path), "rev-parse", "HEAD"]).stdout.decode().strip()
            require(head == workspace["trees"][key]["head"], "Source HEAD changed: " + key)
        source = work / "source"
        shutil.copytree(PROJECT / "prototype/phase3-loader", source)
        shutil.copytree(source, packet / "source")
        raw = (root / "hakios-kernel").read_bytes()
        macho, ranges = checked_macho(raw)
        slot = macho.find_loader_stub_slot()
        require(slot and slot[1] and raw.count(b"XNULDRST") == 1, "Ambiguous loader stub slot")
        _, log_pa, length_pa = find_live(raw, macho, ranges)
        hello = (root / "userland/hello").read_bytes()
        hello_pa, hello_size = align(max(b for a, b in ranges)), align(len(hello), 4096)
        ba_pa = align(hello_pa + hello_size)
        dt_pa = ba_pa + 65536
        dt_blob = make_tree(args.mode, hello_pa, hello_size, 0)
        pram_pa = align(dt_pa + len(dt_blob))
        dt_blob = make_tree(args.mode, hello_pa, hello_size, pram_pa)
        require(dt_pa + len(dt_blob) <= pram_pa, "Device tree changed layout size")
        top = pram_pa + 0x80000
        require(top + 0x2000000 < ARENA_LIMIT, "Less than 32 MiB of initial free RAM")
        nonce = uuid.uuid4().hex
        cmdline = (f"rd=md0 -v cpus=1 serial={3 if args.mode == 'qemu' else 0} debug=0x8 "
                   f"hello_wait=3 loader_return_after=20 hakios_run_nonce={nonce} hakios_kver=p3-a53-gicv2")
        require(len(cmdline.encode()) < 608, "Boot command line would be truncated")
        ba = BootArgs(physBase=DRAM_BASE, virtBase=0xfffffff004000000,
                      memSize=ARENA_LIMIT - DRAM_BASE, memSizeActual=ARENA_LIMIT - DRAM_BASE,
                      topOfKernelData=top, deviceTreeP=dt_pa - SLIDE,
                      deviceTreeLength=len(dt_blob), commandLine=cmdline)
        require(BootArgs.unpack(ba.pack()).commandLine == cmdline, "Boot argument round trip failed")
        entries, payload = [], bytearray()

        def append(name, destination, data, zero=0):
            require(data or zero, "Empty TOC entry")
            start = align(len(payload), 16)
            payload.extend(bytes(start - len(payload)))
            payload.extend(data)
            entries.append({"name": name, "source": start, "destination": destination,
                            "copy": len(data), "zero": zero, "crc": zlib.crc32(data), "reserved": 0})
        for seg in macho.segments:
            if seg.vmsize:
                append(seg.name, seg.vmaddr + SLIDE, raw[seg.fileoff:seg.fileoff + seg.filesize], seg.vmsize - seg.filesize)
        append("hello", hello_pa, hello, hello_size - len(hello))
        append("bootargs", ba_pa, ba.pack())
        append("Apple-device-tree", dt_pa, dt_blob)
        append("panic-buffer", pram_pa, b"", 0x80000)
        require(0 < len(entries) <= 64, "Too many loader entries")
        for i, e in enumerate(entries):
            lo, hi = e["destination"], e["destination"] + e["copy"] + e["zero"]
            require(min(a for a, b in ranges) <= lo < hi <= ARENA_LIMIT, "Destination exceeds arena")
            require(all(hi <= p["destination"] or p["destination"] + p["copy"] + p["zero"] <= lo for p in entries[:i]), "Payload destination overlap")
        (work / "payload.bin").write_bytes(payload)
        config = [CONFIG_MAGIC, 1, len(entries), len(payload), min(a for a, b in ranges), ARENA_LIMIT,
                  macho.entry_point_va + SLIDE, ba_pa, slot[1] + SLIDE, SLIDE & MASK64,
                  args.checkpoint, args.diagnostic, min(a for a, b in ranges), max(b for a, b in ranges),
                  log_pa, MAX_LOG, length_pa, args.watchdog_count,
                  int(nonce[:16], 16), int(nonce[16:], 16)]
        toc = [".section .toc, \"a\"", ".balign 8", ".global payload_config", "payload_config:",
               ".quad " + ", ".join(hex(x) for x in config), ".global payload_toc", "payload_toc:"]
        toc += [".quad " + ", ".join(hex(e[k]) for k in ("source", "destination", "copy", "zero", "crc", "reserved")) for e in entries]
        toc += [".global payload_toc_end", "payload_toc_end:", ".section .payload, \"a\"", ".global payload_base", "payload_base:",
                f'.incbin "{work / "payload.bin"}"', ".global payload_end", "payload_end:"]
        (work / "payload.S").write_text("\n".join(toc) + "\n", encoding="utf-8")
        env = dict(os.environ, PATH="/usr/lib/llvm-18/bin:" + os.environ["PATH"])
        flags = ["clang", "--target=aarch64-none-elf", "-mcpu=cortex-a53", "-mgeneral-regs-only",
                 "-O2", "-std=c11", "-Wall", "-Wextra", "-Werror", "-ffreestanding", "-fno-builtin",
                 "-fno-stack-protector", "-fno-unwind-tables", "-fno-asynchronous-unwind-tables", "-nostdlib", "-fuse-ld=lld",
                 "-Wl,--build-id=none", "-Wl,-T," + str(source / "loader.ld")]
        if args.mode == "qemu":
            flags.append("-DLOADER_QEMU=1")
        command(packet, records, "compile-loader", flags + [str(source / "entry.S"), str(source / "loader.c"),
                str(source / "fdt_guard.c"), str(work / "payload.S"), "-o", str(work / "loader.elf")], timeout=90, env=env)
        command(packet, records, "objcopy", ["llvm-objcopy", "-O", "binary", str(work / "loader.elf"), str(work / "loader.bin")], env=env)
        nm = command(packet, records, "symbols", ["llvm-nm", "-n", str(work / "loader.elf")], env=env).stdout.decode()
        symbols = {parts[2]: int(parts[0], 16) for line in nm.splitlines() if len(parts := line.split()) == 3}
        require(symbols["_start"] == IMAGE_BASE and symbols["__bss_end"] < 0x80200000 and symbols["payload_end"] <= IMAGE_BASE + IMAGE_BYTES, "Linker placement mismatch")
        image = (work / "loader.bin").read_bytes()
        require(len(image) <= IMAGE_BYTES and image[56:60] == b"ARM\x64" and struct.unpack_from("<Q", image, 16)[0] == IMAGE_BYTES, "Invalid ARM64 Image header")
        require(struct.unpack_from("<4Q", image, 24) == (10, 0, 0xecefecef, 0), "Samsung vendor header contract changed")
        if args.entry_style == "accepted-carrier":
            emitted, carrier = wrap_carrier(image, symbols)
            result["carrier"] = carrier
            shutil.copy2(PROJECT / "scripts/phase3_carrier.py", packet / "phase3_carrier.py")
        else:
            emitted = image + bytes(IMAGE_BYTES - len(image))
        require(len(emitted) == IMAGE_BYTES, "Final Image length differs")
        (work / "loader.Image").write_bytes(emitted)
        result.update({"passed": True, "nonce": nonce, "watchdog_count": args.watchdog_count,
                       "initial_memory_budget_bytes": ARENA_LIMIT - DRAM_BASE,
                       "layout": {"kernel_ranges": ranges, "kernel_entry": config[6], "arena_base": config[4], "arena_limit": ARENA_LIMIT,
                                  "hello_pa": hello_pa, "hello_bytes": len(hello), "bootargs_pa": ba_pa, "dt_pa": dt_pa,
                                  "pram_pa": pram_pa, "top": top, "log_pa": log_pa, "log_len_pa": length_pa, "stub_slot_pa": config[8]},
                       "config": config, "toc": entries, "symbols": symbols, "cmdline": cmdline,
                       "input_artifacts": {rel: build["artifacts"][rel] for rel in ("hakios-kernel", "userland/hello")},
                       "outputs": {rel: pin(work / rel) for rel in ("loader.elf", "loader.Image", "payload.S", "payload.bin")},
                       "source_pins": {p.name: pin(p) for p in source.iterdir() if p.is_file()}})
        for rel in ("loader.elf", "payload.S"):
            shutil.copy2(work / rel, packet / rel)
        json_write(PROJECT / f"manifests/phase3-loader-{args.mode}.json", result)
    except Exception as exc:
        result["error"] = str(exc)
    finally:
        json_write(packet / "result.json", result)
        packet_index(packet)
    print(json.dumps({k: result[k] for k in ("packet", "work", "mode", "diagnostic", "nonce", "passed", "error") if k in result}, indent=2), flush=True)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
