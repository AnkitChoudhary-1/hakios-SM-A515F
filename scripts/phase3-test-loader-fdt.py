#!/usr/bin/env python3
"""Test the exact loader FDT guard with real bytes and adversarial inputs."""
from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import struct
from phase3_support import PROJECT, command, json_write, packet_new, packet_index, pin, require


def tree(reservation=None, reserved=None, cells=2):
    names = b"#address-cells\0#size-cells\0reg\0ranges\0"
    offsets = {s.decode(): names.index(s + b"\0") for s in names.split(b"\0") if s}
    tokens = bytearray()

    def node(name):
        raw = name.encode() + b"\0"
        tokens.extend(struct.pack(">I", 1) + raw + bytes(-len(raw) % 4))

    def prop(name, value):
        tokens.extend(struct.pack(">III", 3, len(value), offsets[name]) + value + bytes(-len(value) % 4))

    node("")
    prop("#address-cells", struct.pack(">I", 2))
    prop("#size-cells", struct.pack(">I", 2))
    node("memory@80000000")
    prop("reg", struct.pack(">QQ", 0x80000000, 0x40000000))
    tokens.extend(struct.pack(">I", 2))
    node("unrelated-bus")
    prop("#address-cells", struct.pack(">I", cells))
    tokens.extend(struct.pack(">I", 2))
    if reserved is not None:
        node("reserved-memory")
        prop("#address-cells", struct.pack(">I", 2))
        prop("#size-cells", struct.pack(">I", 2))
        prop("ranges", b"")
        node("fixed@" + format(reserved[0], "x"))
        prop("reg", struct.pack(">QQ", *reserved))
        tokens.extend(struct.pack(">II", 2, 2))
    tokens.extend(struct.pack(">II", 2, 9))
    reserves = (struct.pack(">QQ", *reservation) if reservation is not None else b"") + bytes(16)
    so = 40 + len(reserves)
    st = so + len(tokens)
    header = struct.pack(">10I", 0xd00dfeed, st + len(names), so, st, 40, 17, 16, 0, len(names), len(tokens))
    return header + reserves + tokens + names


def main():
    require(os.name == "posix", "Run inside A51-KernelBuilder")
    packet = packet_new("loader-fdt-tests", Path(__file__))
    records = []
    source = PROJECT / "prototype/phase3-loader"
    shutil.copytree(source, packet / "source")
    real = PROJECT / "evidence/phase-2/live-fdt-libfdt/20261111T073056068990Z/live.dtb"
    require(pin(real)["bytes"] > 40, "Missing retained real FDT")
    inputs = [("real-live-fdt", real.read_bytes(), 1), ("valid", tree(), 1),
              ("valid-zero-address-cells", tree(cells=0), 1),
              ("safe-memreserve", tree(reservation=(0xf9d10000, 0x200000)), 1),
              ("safe-reserved-memory", tree(reserved=(0xf9d10000, 0x200000)), 1),
              ("safe-el2-boundary", tree(reserved=(0x87000000, 0x200000)), 1),
              ("crosses-el2-boundary", tree(reserved=(0x86fff000, 0x10000)), 0),
              ("overlap-memreserve", tree(reservation=(0x83f00000, 0x10000)), 0),
              ("overlap-reserved-memory", tree(reserved=(0x86600000, 0x10000)), 0),
              ("overflow-reservation", tree(reservation=(0xfffffffffffffff0, 0x100)), 0),
              ("invalid-cells", tree(cells=3), 0)]
    valid = tree()
    for offset, values in {0: [0], 4: [0, 39, 0xffffffff], 8: [0, 0xffffffff, 41],
                           12: [0, 0xffffffff, 40], 16: [0, 0xfffffff8, 41],
                           20: [0, 18], 24: [18], 32: [0xffffffff], 36: [0xffffffff]}.items():
        for value in values:
            raw = bytearray(valid)
            struct.pack_into(">I", raw, offset, value)
            inputs.append((f"bad-header-{offset}-{value}", bytes(raw), 0))
    result = {"packet": packet.relative_to(PROJECT).as_posix(), "passed": False,
              "device_operations": False, "actual_fdt": pin(real)}
    try:
        runner = packet / "fdt-test"
        env = dict(os.environ, PATH="/usr/lib/llvm-18/bin:" + os.environ["PATH"])
        command(packet, records, "compile-sanitizer", ["clang", "-std=c11", "-O1", "-g",
            "-Wall", "-Wextra", "-Werror", "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
            str(source / "fdt_guard.c"), str(source / "fdt_test.c"), "-o", str(runner)], env=env)
        argv = [str(runner)]
        for name, raw, expected in inputs:
            path = packet / (name + ".dtb")
            path.write_bytes(raw)
            argv.extend([str(path), str(expected)])
        proc = command(packet, records, "sanitizer-runtime", argv, env=env, timeout=60)
        require(b"FDT_SANITIZER_PASS" in proc.stdout, "Missing runtime pass")
        result["passed"] = True
        result["inputs"] = len(inputs)
        result["summary"] = proc.stdout.decode().strip()
    except Exception as exc:
        result["error"] = str(exc)
        # Diagnose a rejection without changing the production guard's logic.
        raw = (source / "fdt_guard.c").read_text()
        prefix, marker, body = raw.partition("int phase3_fdt_guard")
        diagnostic = packet / "fdt_guard_diagnostic.c"
        diagnostic.write_text(prefix + marker + body.replace("return 0;", "return -__LINE__;"))
        debug_runner = packet / "fdt-diagnostic"
        command(packet, records, "compile-diagnostic", ["clang", "-std=c11", "-O0", "-g", "-I", str(source),
            str(diagnostic), str(source / "fdt_test.c"), "-o", str(debug_runner)], env=env)
        proc = command(packet, records, "diagnose-real-rejection",
                       [str(debug_runner), str(packet / "real-live-fdt.dtb"), "1"], check=False, env=env)
        print(proc.stderr.decode().strip(), flush=True)
    finally:
        json_write(packet / "result.json", result)
        packet_index(packet)
    print(json.dumps(result, indent=2), flush=True)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
