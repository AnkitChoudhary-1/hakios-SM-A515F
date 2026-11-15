#!/usr/bin/env python3
"""Bind the standalone Image header to the retained Samsung vendor fields."""
import json
from pathlib import Path
import struct
from boot_formats import parse_boot
from phase3_support import PROJECT, packet_new, packet_index, packet_verify, pin, json_write, update_documents, require


def main():
    packet = packet_new("vendor-header-correction", Path(__file__))
    baseline = PROJECT.parent / "everline-ksu/artifacts/A51-PixelOS-Everline-KernelSU-Next-boot.img"
    require(pin(baseline)["sha256"] == "eb30609a62999e3282ac81e0a5e56411ef12ec1a39c107171bf3e01209c7cb67", "Baseline changed")
    raw = baseline.read_bytes()
    offset = parse_boot(raw)["sections"]["kernel"]["offset"]
    header = raw[offset:offset + 64]
    words = struct.unpack("<8Q", header)
    require(words[3:7] == (10, 0, 0xecefecef, 0), "Unrecognized Samsung header contract")
    (packet / "baseline-header.bin").write_bytes(header)
    failed_rel = "evidence/phase-3/loader-device-cycle/20261114T042250506272Z"
    packet_verify(PROJECT / failed_rel)
    failed = json.loads((PROJECT / failed_rel / "result.json").read_text(encoding="utf-8"))
    require(failed["baseline_restored"] and not failed["passed"], "Unexpected diagnostic result")
    core = (PROJECT / "prototype/phase3-loader/entry.S").read_text(encoding="utf-8")
    old = "    .quad 2\n    .quad 0, 0, 0"
    require(core.count(old) == 1, "Header anchor changed")
    core = core.replace(old, "    .quad 10\n    /* Match the measured Samsung non-PROCA sentinel at header offset 40. */\n    .quad 0, 0xecefecef, 0", 1)
    build_source = (PROJECT / "scripts/phase3-build-loader.py").read_text(encoding="utf-8")
    old = '        (work / "loader.Image").write_bytes(image + bytes(IMAGE_BYTES - len(image)))'
    require(build_source.count(old) == 1, "Build header anchor changed")
    build_source = build_source.replace(old, '''        require(struct.unpack_from("<4Q", image, 24) == (10, 0, 0xecefecef, 0), "Samsung vendor header contract changed")
''' + old, 1)
    state = json.loads((PROJECT / "state.json").read_text(encoding="utf-8"))
    continuation = state["phase_3_continuation"]
    qemu = {}
    for case in ("full", "reset", "fault", "bad-toc", "bad-fdt"):
        item = json.loads((PROJECT / f"manifests/phase3-loader-qemu-{case}.json").read_text(encoding="utf-8"))
        packet_verify(PROJECT / item["packet"])
        require(item["passed"], "Missing fresh QEMU success")
        qemu[case] = {"result": item["packet"] + "/result.json", "pin": pin(PROJECT / item["packet"] / "result.json")}
    continuation.update({"latest_device_cycle": failed_rel + "/result.json",
        "latest_device_cycle_pin": pin(PROJECT / failed_rel / "result.json"), "latest_device_cycle_passed": False,
        "baseline_restored": True, "last_verified_android_boot_id": failed["boot_id_after"],
        "last_device_error": failed["error"], "qualifying_a51_runs": 0,
        "complete_loader_qemu_results": qemu, "complete_loader_qemu_scope": "publication/pmsg correction passed; vendor-header change awaits new validation",
        "standalone_reset_verified": False, "recovery_persistence_verified": False})
    state["active_task"] = "phase_3_samsung_image_header_and_entry_diagnostic"
    current = (PROJECT / "docs/STATE.md").read_text(encoding="utf-8")
    current += """

P3-021: corrected dual-bank loader passed all five fresh QEMU cases and 13 envelope corruption checks. Second standalone reset attempt `evidence/phase-3/loader-device-cycle/20261114T042250506272Z` FAILED: recovery attached the expected ramoops region but console was absent and pmsg contained historical bytes. Baseline readback, fresh Android completion and root restored. Qualifying full hardware runs remain 0/3. Header comparison found flags 2/vendor word 0 in the draft versus flags 10/vendor sentinel 0xECEFECEF in the pinned Samsung baseline; these fields are now corrected, with fresh build/QEMU/hardware evidence pending. This discrepancy is a hypothesis for the missing entry, not a confirmed root cause.
"""
    log = (PROJECT / "docs/IMPLEMENTATION-LOG.md").read_text(encoding="utf-8")
    log += """

### P3-021 — Retain second reset failure and restore Samsung Image header fields

Date: 14 November 2026, Asia/Calcutta. Phase 3 IN PROGRESS, gate 0/3. Phase 4 remains authorized after Phase 3 passes.

Verification: strict QEMU build run 20261114T042006144751Z passed. Complete-loader full/reset/fault/bad-TOC/bad-FDT runs 20261114T042048905846Z, 20261114T042048531748Z, 20261114T042049358145Z, 20261114T042049943466Z and 20261114T042050652383Z all passed; full reached PID 1, three timer samples and physical return in 12.52 seconds. Both original pstore banks matched. Envelope replay run 20261114T042147952813Z passed two original forms and rejected 13 corruptions. Hardware reset build 20261114T042148309803Z and packaging 20261114T042228652230Z passed.

Failed hardware run 20261114T042249351688Z / evidence/phase-3/loader-device-cycle/20261114T042250506272Z: candidate hash/write/readback passed, recovery reconnected, but there was no current console and the 252-byte pmsg contained historical data. Attachment dmesg confirms 0x200000@0xF9D10000 with ECC off; this proves layout only. No loader/reset/watchdog execution is attributable. The cycle restored pinned baseline with readback, a fresh completed Android boot and root; the used nonce is retired. Original bytes, timings and commands are retained.

Purpose/files: scripts/phase3-fix-vendor-header.py, prototype/phase3-loader/entry.S, scripts/phase3-build-loader.py, docs/STATE.md, state.json and this log. Read-only header comparison run 20261114T042616878618Z found the baseline's flags=10, zero RKP field and Samsung non-PROCA sentinel=0xECEFECEF at offset 40, while the draft used flags=2 and a zero sentinel. Restore these measured fields and enforce them in every fresh build. Baseline's effective Image size includes its Linux BSS and is not copied into the different standalone image. Exact baseline header, before/after files and patch are retained. Original Android source and images remain unchanged.

Limitations: the vendor/header discrepancy is a candidate explanation, not verified firmware rejection evidence. Fresh source-bound strict builds, five QEMU cases and a fresh hardware reset diagnostic are required. Do not repeat the prior candidate or infer execution from reconnection. Rollback: restore only this packet's indexed before files and rebuild in a new isolated directory; preserve all failed candidates/nonces and original baseline/recovery/DTBO pins.
"""
    update_documents(packet, {"prototype/phase3-loader/entry.S": core, "scripts/phase3-build-loader.py": build_source,
        "docs/STATE.md": current, "state.json": json.dumps(state, indent=2) + "\n", "docs/IMPLEMENTATION-LOG.md": log})
    json_write(packet / "result.json", {"baseline_header_words": [hex(x) for x in words], "failed_cycle": failed_rel,
        "baseline_restored": True, "qualifying_runs": 0, "device_operations": False, "firmware_rejection_cause_verified": False})
    packet_index(packet)
    print(packet.relative_to(PROJECT).as_posix(), flush=True)


if __name__ == "__main__":
    main()
