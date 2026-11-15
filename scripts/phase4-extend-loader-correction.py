#!/usr/bin/env python3
"""Extend the already-started correction packet before adapting the C loader."""
import json
import shutil
from phase4_support import PROJECT, pin, require, write_json, index_packet

NEW = (
    "prototype/phase4-loader/entry.S", "prototype/phase4-loader/loader.c",
    "prototype/phase4-loader/loader.h", "prototype/phase4-loader/loader.ld",
    "prototype/phase4-loader/fdt_guard.c", "prototype/phase4-loader/fdt_guard.h",
    "prototype/phase4-loader/validate.c", "prototype/phase4-loader/validate.h",
    "prototype/phase4-loader/test_validate.c", "scripts/phase4_envelope.py",
    "scripts/phase4-test-loader.py", "scripts/phase4-extend-loader-correction.py",
)


def main():
    selection = json.loads((PROJECT / "manifests/phase4-loader-correction-work.json").read_text())
    packet = PROJECT / selection["packet"]
    require(not (packet / "result.json").exists(), "Correction already finished")
    require(not (packet / "extension.json").exists(), "Extension already recorded")
    previous = json.loads((packet / "before-pins.json").read_text())
    recorder = "scripts/phase4-record-loader-correction.py"
    require(recorder not in previous, "Recorder already retained")
    previous[recorder] = pin(PROJECT / recorder)
    target = packet / "before" / recorder
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(PROJECT / recorder, target)
    for rel in NEW:
        require(rel not in previous, "Already covered: " + rel)
        require(not (PROJECT / rel).exists() or rel == "scripts/phase4-extend-loader-correction.py",
                "New path unexpectedly exists: " + rel)
        previous[rel] = None
    write_json(packet / "before-pins.json", previous)
    parent = json.loads((packet / "parent-pins.json").read_text())
    for rel, expected in parent.items():
        require(pin(PROJECT / rel) == expected, "Preserved parent changed: " + rel)
    copied = []
    for name in ("entry.S", "loader.c", "loader.h", "loader.ld", "fdt_guard.c", "fdt_guard.h", "qemu_firmware.S"):
        src = PROJECT / "prototype/phase3-loader" / name
        dest = PROJECT / "prototype/phase4-loader" / name
        require(name == "qemu_firmware.S" or not dest.exists(), "Adaptation already exists")
        if name == "qemu_firmware.S" and dest.exists():
            require(previous[dest.relative_to(PROJECT).as_posix()] == pin(dest), "Unretained firmware")
        shutil.copy2(src, dest)
        copied.append({"source": src.relative_to(PROJECT).as_posix(), "destination": dest.relative_to(PROJECT).as_posix(), **pin(src)})
    write_json(packet / "extension.json", {
        "added_before_entries": list(NEW) + [recorder], "adaptation_sources": copied,
        "provenance": "Phase 3 C loader: full QEMU success and phone entry diagnostic. Accepted full Phase 3 phone runs used the older assembly loader.",
        "cpu_gic": {"distributor": "0x12301000", "cpu_interface": "0x12302000",
                    "evidence_run": "20261114T170856779223Z-phase4-confirm-cpu-gic-original-fdt"},
        "device_operations": False,
    })
    index_packet(packet)
    print(json.dumps({"packet": selection["packet"], "copied": len(copied), "parents_unchanged": True}))


if __name__ == "__main__":
    main()
