#!/usr/bin/env python3
"""Preserve the actual Samsung EL2 reservation; retain exact loader changes."""
from pathlib import Path
import json
from boot_formats import parse_fdt, summarize_fdt
from phase3_support import PROJECT, packet_new, packet_index, pin, require, update_documents, json_write


def main():
    real = PROJECT / "evidence/phase-2/live-fdt-libfdt/20261111T073056068990Z/live.dtb"
    require(pin(real) == {"bytes": 224774, "sha256": "c6a08859495a32310a10918fc50fbd3238daa546eb40c665407d1559b75eaaf6"}, "Real FDT pin changed")
    summary = summarize_fdt(parse_fdt(real.read_bytes()))
    conflicts = [r for n in summary["reserved_memory"] for r in n["ranges"]
                 if r["start"] < 0x8a000000 and r["end_exclusive"] > 0x83430000]
    require(len(conflicts) == 1 and conflicts[0]["start"] == 0x87000000 and
            conflicts[0]["end_exclusive"] == 0x87200000, "Unexpected arena conflict")
    packet = packet_new("loader-memory-correction", Path(__file__))
    (packet / "actual-fdt.dtb").write_bytes(real.read_bytes())
    json_write(packet / "actual-memory-and-reservations.json", summary)
    changes = {}
    replacements = {
        "scripts/phase3-build-loader.py": [("ARENA_LIMIT = 0x8a000000", "ARENA_LIMIT = 0x87000000  # Preserve Samsung EL2 code at [0x87000000,0x87200000).")],
        "prototype/phase3-loader/loader.c": [("c->arena_limit > 0x8a000000", "c->arena_limit > 0x87000000")],
        "prototype/phase3-loader/fdt_test.c": [("UINT64_C(0x8a000000)", "UINT64_C(0x87000000)")],
        "scripts/phase3-test-loader-fdt.py": [
            ('("safe-reserved-memory", tree(reserved=(0xf9d10000, 0x200000)), 1),',
             '("safe-reserved-memory", tree(reserved=(0xf9d10000, 0x200000)), 1),\n              ("safe-el2-boundary", tree(reserved=(0x87000000, 0x200000)), 1),\n              ("crosses-el2-boundary", tree(reserved=(0x86fff000, 0x10000)), 0),'),
            ("tree(reserved=(0x89800000, 0x10000))", "tree(reserved=(0x86600000, 0x10000))")],
    }
    for rel, substitutions in replacements.items():
        text = (PROJECT / rel).read_text(encoding="utf-8")
        for old, new in substitutions:
            require(old in text, "Missing replacement in " + rel)
            text = text.replace(old, new)
        changes[rel] = text
    log = (PROJECT / "docs/IMPLEMENTATION-LOG.md").read_text(encoding="utf-8")
    changes["docs/IMPLEMENTATION-LOG.md"] = log + """

### P3-016 — Preserve the measured Samsung EL2 reservation in the loader arena

Date: 14 November 2026, Asia/Calcutta. Status: source correction IMPLEMENTED; new runtime checks pending; A51 qualifying runs 0/3.

The real-FDT rejection at fdt_guard.c:104 is correct: /reserved-memory/el2_code owns [0x87000000,0x87200000). The draft 160 MiB budget overlapped it. Purpose/files: scripts/phase3-refine-loader-memory.py, scripts/phase3-build-loader.py, prototype/phase3-loader/{loader.c,fdt_test.c}, scripts/phase3-test-loader-fdt.py and this log. The budget now ends at 0x87000000 (112 MiB from DRAM base). The guard is retained; safe/exact/crossing EL2 boundary cases were added. The incoming FDT at 0x8A100000 remains outside the arena. Original FDT, parsed reservations and exact before/after bytes are retained in the loader-memory-correction packet. The smaller budget still requires execution to establish sufficient XNU free memory.

Verification pending: repeated ASan/UBSan real-FDT tests, strict fresh loader build and complete loader/XNU/PID 1 execution in QEMU at this budget, followed by actual A51 reset/watchdog/fault/log persistence and three qualifying hardware runs. The native bounded-return rebuild is running separately. No phone write/reboot/flash occurred in this correction. Phase 4 remains authorized after Phase 3 passes.

Rollback: restore only this packet's indexed before files and rebuild in a new isolated directory; preserve its actual-FDT pin, patch and all prior failed tests. Original upstream sources and baseline Android artifacts remain separate.
"""
    update_documents(packet, changes)
    json_write(packet / "result.json", {"packet": packet.relative_to(PROJECT).as_posix(), "passed": True,
        "actual_fdt": pin(real), "preserved_el2": conflicts[0], "budget_bytes": 0x7000000,
        "device_operations": False, "phase_3_device_gate_passed": False})
    packet_index(packet)
    print(json.dumps({"packet": packet.relative_to(PROJECT).as_posix(), "budget_bytes": 0x7000000}), flush=True)


if __name__ == "__main__":
    main()
