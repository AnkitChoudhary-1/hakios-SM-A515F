#!/usr/bin/env python3
"""Retain before/after loader changes and the unchanged Phase 3 source pins."""
from __future__ import annotations
import argparse
import difflib
import json
from pathlib import Path
import shutil
from phase4_support import PROJECT, new_packet, pin, require, write_json, documents, index_packet

CHANGED = (
    "prototype/phase4-loader/a51_loader.S", "prototype/phase4-loader/a51_loader.ld",
    "prototype/phase4-loader/xnu_trampoline.S", "prototype/phase4-loader/xnu_trampoline.h",
    "prototype/phase4-loader/return.S", "prototype/phase4-loader/recovery.S",
    "prototype/phase4-loader/pack_phase4_payload.py", "scripts/phase4-build-device-path.py",
    "scripts/phase4_carrier.py", "prototype/phase4-loader/qemu_firmware.S",
    "scripts/phase4-qemu-device-path.py", "scripts/phase4-test-capture.py",
    "scripts/phase4_capture.py", "docs/PHASE-4-DEVICE-PATH.md",
    "scripts/phase4-record-loader-correction.py", "scripts/phase4-extend-loader-correction.py",
    "prototype/phase4-loader/entry.S", "prototype/phase4-loader/loader.c",
    "prototype/phase4-loader/loader.h", "prototype/phase4-loader/loader.ld",
    "prototype/phase4-loader/fdt_guard.c", "prototype/phase4-loader/fdt_guard.h",
    "prototype/phase4-loader/validate.c", "prototype/phase4-loader/validate.h",
    "prototype/phase4-loader/test_validate.c", "scripts/phase4_envelope.py",
    "scripts/phase4-test-loader.py", "scripts/phase4-retain-qemu-scratch.py",
    "scripts/phase4-device-cycle.py", "scripts/phase4-test-device-cycle.py", "scripts/phase4_pstore.py",
    "scripts/phase4-record-watchdog-review.py",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("begin", "finish"), required=True)
    parser.add_argument("--packet")
    parser.add_argument("--purpose", default="Correct the Phase 4 loader carrier, memory and runtime contract")
    args = parser.parse_args()
    if args.stage == "begin":
        require(args.packet is None, "Begin creates a fresh packet")
        packet = new_packet("loader-contract-correction", __file__)
        previous = {}
        for rel in CHANGED:
            path = PROJECT / rel
            previous[rel] = pin(path) if path.exists() else None
            if path.exists():
                dest = packet / "before" / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, dest)
        parent = {p.relative_to(PROJECT).as_posix(): pin(p)
            for folder in ("prototype/phase3-loader", "prototype/xnu-loader")
            for p in (PROJECT / folder).rglob("*") if p.is_file() and "__pycache__" not in p.parts}
        write_json(packet / "before-pins.json", previous)
        write_json(packet / "parent-pins.json", parent)
        write_json(PROJECT / "manifests/phase4-loader-correction-work.json", {"packet": packet.relative_to(PROJECT).as_posix()})
        index_packet(packet)
        print(packet.relative_to(PROJECT).as_posix(), flush=True)
        return 0
    require(args.packet, "Finish requires the exact begin packet")
    packet = (PROJECT / args.packet).resolve()
    require(packet.is_relative_to((PROJECT / "evidence/phase-4/loader-contract-correction").resolve()), "Wrong evidence root")
    require(not (packet / "result.json").exists(), "Correction packet already finalized")
    previous = json.loads((packet / "before-pins.json").read_text(encoding="utf-8"))
    require(set(previous) == set(CHANGED), "Correction file inventory differs from the retained before pins")
    parent = json.loads((packet / "parent-pins.json").read_text(encoding="utf-8"))
    for rel, expected in parent.items():
        require(pin(PROJECT / rel) == expected, "Preserved parent changed: " + rel)
    changes, patches = [], []
    for rel, oldpin in previous.items():
        path = PROJECT / rel
        old = (packet / "before" / rel).read_bytes() if oldpin else b""
        require(not oldpin or pin(packet / "before" / rel) == oldpin, "Before snapshot changed")
        new = path.read_bytes() if path.exists() else b""
        if old == new:
            continue
        dest = packet / "after" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(new)
        changes.append({"path": rel, "before": oldpin, "after": pin(path) if path.exists() else None})
        patches.append("".join(difflib.unified_diff(old.decode("utf-8").splitlines(True), new.decode("utf-8").splitlines(True),
            fromfile="a/" + rel, tofile="b/" + rel)))
    (packet / "loader.patch").write_text("".join(patches), encoding="utf-8")
    host_evidence = {}
    for name in ("phase4-complete-loader-qemu.json", "phase4-loader-native-tests.json", "phase4-device-cycle-tests.json"):
        selection_path = PROJECT / "manifests" / name
        selection = json.loads(selection_path.read_text(encoding="utf-8"))
        require(selection["passed"] and (name != "phase4-complete-loader-qemu.json" or selection["suite_complete"]),
                "Unpassed host evidence: " + name)
        host_evidence[name] = {"path": selection_path.relative_to(PROJECT).as_posix(), **pin(selection_path)}
    result = {"recorded": True, "changes": changes, "parent_unchanged": True,
        "host_evidence_selections": host_evidence,
        "verification": "See selected fresh build/QEMU/capture packets; this records changes only",
        "hardware_verified": False, "phase_4_gate_passed": False, "device_operations": False}
    write_json(packet / "result.json", result)
    state = json.loads((PROJECT / "state.json").read_text(encoding="utf-8"))
    state["phase_4_loader_correction"] = {"result": (packet / "result.json").relative_to(PROJECT).as_posix(), **pin(packet / "result.json")}
    state["phase_4_status"] = "in_progress"
    state["phase_4_device_gate_passed"] = False
    if not state.get("next_action"):
        state["next_action"] = "validate_corrected_loader_capture_and_actual_watchdog_then_real_phase4_drivers"
    note = f"""\n\n## P4-015 — Record Phase 4 loader source correction ({packet.name})

Purpose/files: {args.purpose}. The exact file list and patch are retained in `{packet.relative_to(PROJECT).as_posix()}`. Preserve the accepted Samsung header/stext carrier, 112 MiB initial RAM budget and pre-copy validation. Historical full Phase 3 phone runs used the older assembly loader; the current C loader's matching QEMU runs do not establish hardware entry or persistent capture. Original recovery exports require framing, nonce and both CRCs. Device cycles journal intent before writes and verify the restored baseline readback before rebooting.

Verification: the correction recorder verifies exact before pins and unchanged historical/Phase 3 source and retains selected passing complete-loader QEMU, sanitizer/envelope and cycle-model manifest pins. The current evidence, every failed attempt, hardware candidate preflights and USB blocker are documented in docs/PHASE-4-DEVICE-PATH.md and state.json. Model fixtures and their filesystem/transport histories are explicitly host-only. No device write, module load or reboot occurred during this correction. Host/QEMU work cannot satisfy Phase 4's peripheral hardware gate.

Limitations/rollback: the new loader and reader require hardware execution and preserved-record survival checks. Restore this packet's before bytes (remove newly added files listed with before=null), select the retained original Phase 3 loader/build and pinned Android boot image, and preserve every failed/accepted result. Rebuild through scripts/run.py with the exact mode/kind shown in the selected packet. Never use phase4-device-gate.py.
"""
    documents(packet, {"state.json": json.dumps(state, indent=2) + "\n",
        "docs/IMPLEMENTATION-LOG.md": (PROJECT / "docs/IMPLEMENTATION-LOG.md").read_text(encoding="utf-8") + note})
    index_packet(packet)
    print(json.dumps({"recorded": True, "packet": packet.relative_to(PROJECT).as_posix(), "changed_files": len(changes)}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
