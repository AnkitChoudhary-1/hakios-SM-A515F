#!/usr/bin/env python3
"""Retain sanitizer and envelope corruption checks for the Phase 4 loader."""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from phase4_support import PROJECT, new_packet, command, write_json, pin, documents, index_packet, require


def main():
    if os.name == "nt":
        source = "/mnt/c" + str(Path(__file__).resolve()).replace("\\", "/")[2:]
        return subprocess.call(["wsl", "-d", "A51-KernelBuilder", "--exec", "python3", "-B", source, *sys.argv[1:]])
    packet = new_packet("loader-native-tests", __file__)
    work = Path("/opt/a51-hakios/experimental/phase4-loader-tests") / packet.name
    work.mkdir(parents=True, exist_ok=False)
    result = {"packet": packet.relative_to(PROJECT).as_posix(), "passed": False,
              "device_operations": False, "phase_4_gate_passed": False}
    records = []
    try:
        source = PROJECT / "prototype/phase4-loader"
        for rel in ("validate.c", "validate.h", "loader.h", "fdt_guard.c", "fdt_guard.h", "test_validate.c"):
            shutil.copy2(source / rel, packet / rel)
        for rel in ("phase4_envelope.py", "phase4-test-capture.py"):
            shutil.copy2(PROJECT / "scripts" / rel, packet / rel)
        original = PROJECT / "evidence/phase-4/live-inventory/20261114T162645749263Z/live-fdt.stdout.bin"
        result["original_fdt"] = {"path": original.relative_to(PROJECT).as_posix(), **pin(original)}
        env = dict(os.environ, PATH="/usr/lib/llvm-18/bin:" + os.environ["PATH"],
                   ASAN_OPTIONS="detect_leaks=1:abort_on_error=1", UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
        command(packet, records, "compile-native", ["clang", "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
            "-fsanitize=address,undefined", "-fno-omit-frame-pointer", str(packet / "test_validate.c"),
            str(packet / "validate.c"), str(packet / "fdt_guard.c"), "-o", str(work / "test_validate")], env=env)
        native = command(packet, records, "native-sanitizers", [str(work / "test_validate"), str(original)], timeout=90, env=env)
        match = re.fullmatch(rb"PHASE4_VALIDATE_PASS checks=([0-9]+) ASAN_UBSAN=1\n", native.stdout)
        require(match, "Missing exact native sanitizer result")
        result["native_checks"] = int(match.group(1))
        command(packet, records, "envelope-corruptions", ["python3", "-B", str(PROJECT / "scripts/phase4-test-capture.py"),
                "--packet", str(packet)], timeout=45)
        envelope = json.loads((packet / "envelope-tests.json").read_text())
        require(envelope["passed"] and all(envelope["checks"].values()), "Envelope tests failed")
        result["envelope_checks"] = len(envelope["checks"])
        result["passed"] = True
        result["binary"] = pin(work / "test_validate")
    except Exception as exc:
        result["error"] = str(exc)
    finally:
        write_json(packet / "result.json", result)
        write_json(PROJECT / "manifests/phase4-loader-native-tests.json", result)
        state = json.loads((PROJECT / "state.json").read_text(encoding="utf-8"))
        state["phase_4_loader_native_tests"] = {"result": (packet / "result.json").relative_to(PROJECT).as_posix(),
              "passed": result["passed"], "error": result.get("error")}
        note = f"\n\n## P4-017 — Loader pre-write sanitizer and envelope checks ({packet.name})\n\nPurpose/files: prototype/phase4-loader/test_validate.c, scripts/phase4-test-loader.py, phase4-test-capture.py and phase4_envelope.py. The exact validator and FDT guard are compiled with ASan/UBSan. Valid layouts at all three supported placements, source backing, count/overflow/overlap/CRC/slot rejection and mutations of the original FDT are checked. Console/pmsg fixtures require exact attribution, bounded copies, payload CRC and whole-envelope CRC.\n\nVerification: passed={result['passed']}; native_checks={result.get('native_checks')}; envelope_checks={result.get('envelope_checks')}; error={result.get('error')}. Sources, original input pin, exact commands and outputs are retained in `{result['packet']}`. Full AArch64 loader and peripheral execution require separate evidence; no device operation occurred.\n\nLimitations/rollback: fixtures are contract tests and cannot establish A51 behavior. Select retained prior scripts and correction before bytes to undo changes. Rerun through scripts/run.py and preserve every failed result. Phase 4 remains incomplete.\n"
        documents(packet, {"state.json": json.dumps(state, indent=2) + "\n",
            "docs/IMPLEMENTATION-LOG.md": (PROJECT / "docs/IMPLEMENTATION-LOG.md").read_text(encoding="utf-8") + note})
        index_packet(packet)
    print(json.dumps(result), flush=True)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
