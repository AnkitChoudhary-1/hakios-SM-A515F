#!/usr/bin/env python3
"""Build the isolated Phase 4 C loader and an exactly pinned Samsung package."""
from __future__ import annotations
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import uuid
from phase4_support import PROJECT, new_packet, pin, require, command, write_json, documents, index_packet
from phase4_carrier import wrap


def main():
    if os.name == "nt":
        script = "/mnt/c" + str(Path(__file__).resolve()).replace("\\", "/")[2:]
        return subprocess.call(["wsl", "-d", "A51-KernelBuilder", "--exec", "python3", "-B", script, *sys.argv[1:]])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("hardware", "qemu"), default="hardware")
    parser.add_argument("--kind", choices=("watchdog", "snapshot", "full", "reset", "fault"), required=True)
    parser.add_argument("--probe", type=int, default=1)
    parser.add_argument("--checkpoint", type=int, default=0)
    parser.add_argument("--watchdog-count", type=int)
    args = parser.parse_args()
    require(1 <= args.probe <= 127 and 0 <= args.checkpoint <= 40, "Invalid probe/checkpoint")
    require(args.watchdog_count is None or 100 <= args.watchdog_count <= 65535, "Invalid watchdog count")
    packet = new_packet("device-path-build", __file__)
    work = Path("/opt/a51-hakios/experimental/phase4-loader") / packet.name
    work.mkdir(parents=True, exist_ok=False)
    records = []
    result = {"schema_version": 2, "built": False, "kind": args.kind, "mode": args.mode,
        "packet": packet.relative_to(PROJECT).as_posix(), "work": str(work),
        "device_operations": False, "phase_4_gate_passed": False, "entry_style": "accepted-carrier",
        "provenance": "Adapted Phase 3 C loader (full QEMU and phone entry diagnostic); historical full Phase 3 phone runs used the older assembly loader."}
    try:
        spec = importlib.util.spec_from_file_location("baseline_pins", PROJECT / "scripts/build-xnu-boot-candidate.py")
        baseline = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(baseline)
        template = baseline.pinned(baseline.TEMPLATE, "template")
        for name, path in (("original_boot", baseline.ORIGINAL_BOOT), ("recovery", baseline.RECOVERY), ("dtbo", baseline.DTBO)):
            baseline.pinned(path, name)
        result["rollback_pins"] = {name: {"path": str(path.relative_to(PROJECT.parent)), **pin(path)} for name,path in
            (("template", baseline.TEMPLATE), ("original_boot", baseline.ORIGINAL_BOOT), ("recovery", baseline.RECOVERY), ("dtbo", baseline.DTBO))}
        build = json.loads((PROJECT / "manifests/phase4-platform-build.json").read_text())
        workspace = json.loads((PROJECT / "manifests/phase4-workspace.json").read_text())
        require(build["build_verified"] and build["root"] == workspace["root"], "Wrong selected platform build")
        root = Path(build["root"]).resolve()
        require(root.is_relative_to(Path("/opt/a51-hakios/experimental/phase4-port")), "Wrong kernel tree")
        preservation = (PROJECT / workspace["packet"]).resolve()
        require(preservation.is_relative_to((PROJECT / "evidence/phase-4/source-preservation").resolve()), "Wrong source preservation packet")
        result["source_provenance"] = {"result": pin(preservation / "result.json"), "heads": {}}
        for key, path in (("common", root), ("native", root / "xnu-src/xnu-8796.121.2")):
            head = command(packet, records, "head-" + key, ["git", "-C", str(path), "rev-parse", "HEAD"]).stdout.decode().strip()
            original_head = preservation / (key + "-head.stdout.bin")
            expected = original_head.read_text(encoding="ascii").strip()
            require(len(expected) == 40 and all(c in "0123456789abcdef" for c in expected), "Invalid preserved HEAD: " + key)
            require(head == expected, "Selected source HEAD changed: " + key)
            result["source_provenance"]["heads"][key] = {"head": expected, "path": original_head.relative_to(PROJECT).as_posix(), **pin(original_head)}
        for rel in ("hakios-kernel", "userland/hello"):
            require(pin(root / rel) == build["artifacts"][rel], "Changed build input: " + rel)
            dest = work / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / rel, dest)
        source = PROJECT / "prototype/phase4-loader"
        shutil.copytree(source, work / "sources", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(source, packet / "sources", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy2(PROJECT / "scripts/phase4_carrier.py", packet / "phase4_carrier.py")
        result["sources"] = {p.relative_to(source).as_posix(): pin(p) for p in source.rglob("*") if p.is_file() and "__pycache__" not in p.parts}
        result["platform_build"] = {"path": "manifests/phase4-platform-build.json", **pin(PROJECT / "manifests/phase4-platform-build.json")}
        sys.path.insert(0, str(source))
        from pack_phase4_payload import prepare, IMAGE_BYTES, IMAGE_BASE
        nonce = uuid.uuid4().hex
        cmdline = f"rd=md0 -v cpus=1 serial={3 if args.mode == 'qemu' else 0} debug=0x8 hello_wait=3 loader_return_after=20 hakios_run_nonce={nonce} hakios_kver=p4-a51-guarded"
        if args.kind == "snapshot" or args.mode == "qemu":
            cmdline += f" hakios_a51_diag=1 hakios_a51_mmio=1 hakios_a51_probe={args.probe}"
        if args.mode == "qemu":
            cmdline += " hakios_qemu_spi=1"
        diagnostic = {"watchdog": 2, "reset": 1, "fault": 3}.get(args.kind, 0)
        layout = prepare(work / "hakios-kernel", work / "userland/hello", work, nonce, cmdline,
            mode=args.mode, diagnostic=diagnostic, checkpoint=args.checkpoint, watchdog_count=args.watchdog_count)
        result.update(layout=layout, nonce=nonce, cmdline=cmdline, config=layout["config"], toc=layout["toc"], diagnostic=diagnostic)
        env = dict(os.environ, PATH="/usr/lib/llvm-18/bin:" + os.environ["PATH"])
        command(packet, records, "compiler", ["clang", "--version"], env=env)
        flags = ["clang", "--target=aarch64-none-elf", "-mcpu=cortex-a53", "-mgeneral-regs-only",
            "-O2", "-std=c11", "-Wall", "-Wextra", "-Werror", "-ffreestanding", "-fno-builtin",
            "-fno-stack-protector", "-fno-unwind-tables", "-fno-asynchronous-unwind-tables", "-nostdlib", "-fuse-ld=lld",
            "-Wl,--build-id=none", "-Wl,-T," + str(work / "sources/loader.ld")]
        if args.mode == "qemu":
            flags.append("-DLOADER_QEMU=1")
        command(packet, records, "compile-loader", flags + [str(work / "sources" / name) for name in
            ("entry.S", "loader.c", "validate.c", "fdt_guard.c")] + [str(work / "payload.S"), "-o", str(work / "loader.elf")], env=env, timeout=90)
        nm = command(packet, records, "symbols", ["llvm-nm", "--defined-only", str(work / "loader.elf")], env=env).stdout.decode()
        symbols = {parts[2]: int(parts[0], 16) for line in nm.splitlines() if len(parts := line.split()) == 3}
        require(symbols["_start"] == IMAGE_BASE and symbols["loader_entry"] == IMAGE_BASE + 64, "Wrong entry/header contract")
        require(symbols["payload_toc_end"] - symbols["payload_toc"] == len(layout["toc"]) * 48, "TOC linker extent differs")
        require(symbols["payload_end"] == symbols["payload_base"] + layout["payload_bytes"] and
            IMAGE_BASE <= symbols["payload_toc"] < symbols["payload_toc_end"] <= symbols["payload_base"] < symbols["payload_end"] <= IMAGE_BASE + IMAGE_BYTES,
            "Linked source/TOC exceeds exact slot")
        for runtime in (IMAGE_BASE, 0x80278000, 0x800d0000):
            begin = symbols["loader_return_stub"] + runtime - IMAGE_BASE
            end = symbols["__bss_end"] + runtime - IMAGE_BASE
            require(begin <= end < (begin & ~0x1fffff) + 0x200000, "Return code/context crosses native identity block")
        command(packet, records, "objcopy", ["llvm-objcopy", "-O", "binary", str(work / "loader.elf"), str(work / "loader.bin")], env=env)
        unpadded = (work / "loader.bin").read_bytes()
        require(64 < len(unpadded) < 20643840 and unpadded[56:60] == b"ARM\x64" and
            struct.unpack_from("<5Q", unpadded, 8) == (0x80000, 47362048, 10, 0, 0xecefecef), "Linux/Samsung header differs")
        image, result["carrier"] = wrap(unpadded, symbols)
        (work / "loader.Image").write_bytes(image)
        result.update(symbols=symbols, initial_memory_budget_bytes=layout["initial_memory_budget_bytes"],
            outputs={rel: pin(work / rel) for rel in ("loader.elf", "loader.Image", "loader.bin", "payload.S", "payload.bin")})
        if args.mode == "hardware":
            from samsung_boot_dry_run import reconstruct_in_memory
            candidate, reconstruction = reconstruct_in_memory(template, image)
            require(len(candidate) == 61865984, "Candidate partition length differs")
            artifact = PROJECT / "artifacts/phase-4/device-candidate" / packet.name
            artifact.mkdir(parents=True, exist_ok=False)
            path = artifact / ("A51-HakiOS-P4-" + args.kind + "-boot.img")
            path.write_bytes(candidate)
            result["candidate"] = {"path": path.relative_to(PROJECT).as_posix(), **pin(path)}
            write_json(packet / "reconstruction.json", reconstruction)
        for name in ("payload.S", "loader.elf"):
            shutil.copy2(work / name, packet / name)
        result["built"] = True
        result["passed"] = True
        write_json(PROJECT / ("manifests/phase4-loader-qemu.json" if args.mode == "qemu" else "manifests/phase4-candidate-" + args.kind + ".json"), result)
    except Exception as exc:
        result["error"] = str(exc)
    finally:
        write_json(packet / "result.json", result)
        state = json.loads((PROJECT / "state.json").read_text())
        state["phase_4_device_path_build"] = {"result": (packet / "result.json").relative_to(PROJECT).as_posix(),
            "built": result["built"], "mode": args.mode, "error": result.get("error")}
        state["phase_4_status"] = "in_progress"
        state["phase_4_device_gate_passed"] = False
        note = f"\n\n## P4-016 — Corrected C loader build ({packet.name})\n\nPurpose/files: isolated prototype/phase4-loader C/assembly/validation/FDT sources, scripts/phase4-build-device-path.py, phase4_carrier.py, retained generated source/ELF/package and selection documents. Preserve the exact accepted 64-byte Samsung header/stext carrier; use CRC TOCs, dynamic runtime bounds, source-backed configuration, relocated zeroed panic RAM and the 112 MiB initial budget. Compile entry.S/loader.c/validate.c/fdt_guard.c; the older a51_loader.S is retained historical code and is not compiled. Phase 3 C-loader provenance is full QEMU execution and phone entry diagnostics, distinct from the older assembly used by full Phase 3 phone runs.\n\nVerification: built={result['built']}; mode={args.mode}; kind={args.kind}; error={result.get('error')}. Exact input pins, source snapshots, commands, outputs and compiler/linker checks are in `{result['packet']}`. This is host build/packaging evidence; no device operations occurred and no Phase 4 hardware gate is passed.\n\nLimitations/rollback: full-loader QEMU and phone logging/watchdog/XNU return must pass before peripheral work. Select preserved prior artifacts to undo this selection; restore the correction packet's before bytes to undo source changes. Rebuild through scripts/run.py using this packet's arguments and pins. Preserve original Android images and every failure.\n"
        documents(packet, {"state.json": json.dumps(state, indent=2) + "\n",
            "docs/IMPLEMENTATION-LOG.md": (PROJECT / "docs/IMPLEMENTATION-LOG.md").read_text() + note})
        index_packet(packet)
    print(json.dumps({k: result.get(k) for k in ("packet", "built", "mode", "kind", "error", "candidate", "nonce")}), flush=True)
    return 0 if result["built"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
