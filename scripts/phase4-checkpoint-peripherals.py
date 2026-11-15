#!/usr/bin/env python3
"""Retain Windows templates and additional matching references before edits."""
from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import subprocess
from phase4_support import PROJECT, documents, index_packet, new_packet, pin, require, write_json

FILES = (
    "prototype/phase4-platform/a51_ufs_readonly.h",
    "prototype/phase4-platform/a51_input.h",
    "prototype/phase4-platform/hakios.a51.c",
    "prototype/phase4-platform/hakios.a51.h",
    "prototype/phase4-platform/hello.c",
    "scripts/phase4-revise-platform.py",
    "scripts/phase4-build-platform.py",
    "scripts/phase4-qemu-platform.py",
    "scripts/phase4-build-device-path.py",
    "scripts/phase4-device-cycle.py",
)
REFERENCES = (
    "include/crypto/fmp.h",
    "drivers/input/touchscreen/melfas/mss100/melfas_mss100.h",
    "arch/arm64/boot/dts/exynos/exynos9610.dts",
    "drivers/i2c/busses/i2c-s3c2410.c",
)

def main():
    if os.name == "nt":
        source = "/mnt/c" + str(Path(__file__).resolve()).replace("\\", "/")[2:]
        return subprocess.call(["wsl", "-d", "A51-KernelBuilder", "--exec", "python3", "-B", source])
    selection = PROJECT / "manifests/phase4-peripheral-checkpoint.json"
    require(not selection.exists(), "Checkpoint already retained; do not overwrite it")
    packet = new_packet("peripheral-source-checkpoint", __file__)
    result = {"packet": packet.relative_to(PROJECT).as_posix(), "device_operations": False,
              "captured": False, "phase_4_gate_passed": False, "files": {}, "references": {}}
    try:
        for rel in FILES:
            saved = packet / "before" / rel
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(PROJECT / rel, saved)
            result["files"][rel] = pin(saved)
            require(pin(PROJECT / rel) == result["files"][rel], "Concurrent template edit: " + rel)
        for rel in REFERENCES:
            saved = packet / "references" / rel
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(Path("/opt/a51-everline/src") / rel, saved)
            result["references"][rel] = pin(saved)
        result["captured"] = True
    except Exception as exc:
        result["error"] = str(exc)
    write_json(packet / "result.json", result)
    if result["captured"]:
        write_json(selection, result)
    note = (f"\n\n## P4-030 — Retain new protocol helpers before integration ({packet.name})\n\n"
        "Purpose/files: scripts/phase4-checkpoint-peripherals.py, two new portable headers "
        "a51_ufs_readonly.h/a51_input.h and retained templates/build/device scripts. Preserve the "
        "initial uncompiled helper bytes and matching Android FMP/MSS100/DTS/I2C references "
        "without changing the closed P4-028 capture. The UFS helper restricts READ(10), LUN 0 and "
        "boot LBAs; the input helper decodes format 10 and bounds fixed-address I2C reads. "
        f"Verification: captured={result['captured']}; error={result.get('error')}; exact pins in `{result['packet']}`. "
        "These helpers are not yet integrated or hardware validated. Native error-path tests, "
        "restoration review and source/build provenance are pending. "
        "The first checkpoint attempt 20261115T121455657028Z failed on a stale regs-iic.h "
        "path; the matching controller defines these registers directly in i2c-s3c2410.c, "
        "now retained here. The failed packet is preserved. "
        "Reference search run 20261115T121120146081Z retained an erroneous melfas_mss100_reg.c "
        "glob and exit 1; the matching header/reference bytes are retained separately. "
        "ADB presence run 20261115T121120510081Z saw Android, without a reboot or write. "
        "Rollback: restore only checkpoint before files after checking their pins; retain original "
        "capture and evidence. The new headers can be removed before integration. No WSL source "
        "mutation, build, phone write or reboot occurred. Phase 4 remains in progress.\n")
    documents(packet, {"docs/IMPLEMENTATION-LOG.md":
        (PROJECT / "docs/IMPLEMENTATION-LOG.md").read_text(encoding="utf-8") + note})
    index_packet(packet)
    print(json.dumps({k: v for k, v in result.items() if k not in ("files", "references")}), flush=True)
    return 0 if result["captured"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
