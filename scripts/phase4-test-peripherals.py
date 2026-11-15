#!/usr/bin/env python3
"""Retain and execute the exact portable UFS/input cores with ASan/UBSan models."""
from __future__ import annotations
import difflib
import json
import os
from pathlib import Path
import shutil
import subprocess
from phase4_support import PROJECT, command, documents, index_packet, new_packet, pin, require, write_json

def main():
    if os.name == "nt":
        script = "/mnt/c" + str(Path(__file__).resolve()).replace("\\", "/")[2:]
        return subprocess.call(["wsl", "-d", "A51-KernelBuilder", "--exec", "python3", "-B", script])
    checkpoint = json.loads((PROJECT / "manifests/phase4-peripheral-checkpoint.json").read_text())
    require(checkpoint["captured"], "Retain original helper bytes first")
    packet = new_packet("peripheral-native-tests", __file__)
    build = Path("/opt/a51-hakios/experimental/phase4-protocol-tests") / packet.name
    build.mkdir(parents=True, exist_ok=False)
    result = {"packet": packet.relative_to(PROJECT).as_posix(), "build": str(build),
              "passed": False, "device_operations": False, "phase_4_gate_passed": False,
              "sources": {}, "suites": {}}
    records = []
    try:
        patches = []
        for rel in ("a51_ufs_readonly.h", "a51_input.h", "tests/ufs_model.c", "tests/input_model.c"):
            source = PROJECT / "prototype/phase4-platform" / rel
            saved = packet / "sources" / rel
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, saved)
            result["sources"][rel] = pin(saved)
            require(pin(source) == pin(saved), "Source changed during capture: " + rel)
            dest = build / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(saved, dest)
            old = PROJECT / checkpoint["packet"] / "before/prototype/phase4-platform" / rel
            patches.append("".join(difflib.unified_diff(
                (old.read_text() if old.exists() else "").splitlines(True), saved.read_text().splitlines(True),
                fromfile="a/prototype/phase4-platform/" + rel, tofile="b/prototype/phase4-platform/" + rel)))
        (packet / "protocol-tests.patch").write_text("".join(patches))
        command(packet, records, "compiler", ["clang-18", "--version"])
        for suite in ("ufs", "input"):
            command(packet, records, suite + "-compile", ["clang-18", "-std=c11", "-O1", "-g",
                "-Wall", "-Wextra", "-Werror", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                "-fno-omit-frame-pointer", "-I", str(build), str(build / "tests" / (suite + "_model.c")),
                "-o", str(build / suite)], timeout=60)
            proc = command(packet, records, suite + "-execute", [str(build / suite)], timeout=30,
                env=dict(os.environ, ASAN_OPTIONS="detect_leaks=1:abort_on_error=1", UBSAN_OPTIONS="halt_on_error=1"), check=False)
            shutil.copy2(build / suite, packet / (suite + "-model"))
            if proc.returncode == 0:
                observed = json.loads(proc.stdout)
                require(observed["suite"] == suite and observed["passed"] is True and
                        type(observed["cases"]) is int and observed["cases"] > 0 and
                        type(observed["checks"]) is int and observed["checks"] > 0, "Invalid executed result")
                result["suites"][suite] = observed
            else:
                result["suites"][suite] = {"passed": False, "exit_code": proc.returncode,
                    "error": proc.stderr.decode(errors="replace")[:1500]}
        require(all(row["passed"] for row in result["suites"].values()) and len(result["suites"]) == 2,
                "Native protocol models failed")
        for rel, expected in result["sources"].items():
            require(pin(PROJECT / "prototype/phase4-platform" / rel) == expected, "Source drift after execution")
        result["passed"] = True
    except Exception as exc:
        result["error"] = str(exc)
    write_json(packet / "result.json", result)
    write_json(PROJECT / "manifests/phase4-peripheral-native-tests.json", result)
    state = json.loads((PROJECT / "state.json").read_text())
    state["phase_4_peripheral_protocols"] = {"result": result["packet"] + "/result.json",
        "native_verified": result["passed"], "integrated": False, "hardware_verified": False}
    state["phase_4"] = "in_progress"
    state["next_action"] = "integrate_tested_peripheral_core" if result["passed"] else "fix_peripheral_protocol_model_failures"
    note = (f"\n\n## P4-031 — Execute shared peripheral protocol models ({packet.name})\n\n"
        "Purpose/files: scripts/phase4-test-peripherals.py and prototype/phase4-platform/tests/{ufs,input}_model.c; "
        "retain exact shared headers, native programs, compiler, commands and sanitizer output. "
        "Coverage: write/unknown-op rejection with unusable pointers; boot/DMA/ownership bounds; inherited busy/error/configuration rejection; "
        "byte-unit UTRD/FMP layout; READ(10) and DMA contents; OCS/UPIU/residual/sense failures; timeout selected-slot cleanup; "
        "failed stop/restoration quarantine and reuse rejection; touch slots/states/coordinates/malformed-packet atomicity; "
        "key transitions/debounce/clock regression; I2C repeated START, final NACK, STOP, errors and restoration. "
        f"Verification: passed={result['passed']}; suites={result['suites']}; error={result.get('error')}; packet `{result['packet']}`. "
        "These models execute the same core intended for XNU, but simulated MMIO/DMA cannot establish any A51 peripheral gate. "
        "Rollback: the original helpers are pinned in the peripheral checkpoint; the packet's protocol-tests.patch records changes, "
        "and new tests/scripts may be removed before integration. No WSL platform-source or phone mutation occurred.\n")
    documents(packet, {"state.json": json.dumps(state, indent=2) + "\n",
        "docs/IMPLEMENTATION-LOG.md": (PROJECT / "docs/IMPLEMENTATION-LOG.md").read_text() + note})
    index_packet(packet)
    print(json.dumps({k:v for k,v in result.items() if k != "sources"}, indent=2), flush=True)
    return 0 if result["passed"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
