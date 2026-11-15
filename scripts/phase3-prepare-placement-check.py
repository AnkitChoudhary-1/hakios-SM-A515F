#!/usr/bin/env python3
"""Audit original silicon placement and add an attributable QEMU replay option."""
import json
from pathlib import Path
from boot_formats import parse_boot, parse_arm64_image
from phase3_support import PROJECT, packet_new, packet_index, packet_verify, pin, json_write, update_documents, require


def main():
    packet = packet_new("placement-audit", Path(__file__))
    build_path = PROJECT / "evidence/phase-2/early-entry-kernel/20261113T004224388744Z/result.json"
    execution_path = PROJECT / "evidence/phase-2/device-execution/20261113T010932628245Z/result.json"
    build = json.loads(build_path.read_text(encoding="utf-8"))
    execution = json.loads(execution_path.read_text(encoding="utf-8"))
    fields = execution["stages"]["stage_4_evidence"]["fields"]
    require(fields["status"] == 1 and fields["reason"] == 0, "Original silicon entry was rejected")
    symbols = build["symbols"]
    actual_base = fields["entry_pc"] - (symbols["stext"] - symbols["_text"])
    require(actual_base == fields["x3"] and actual_base == fields["x1"] + fields["x2"], "Entry placement records disagree")
    require(fields["payload_pc"] - actual_base == symbols["hakios_early_tiny_payload"] - symbols["_text"], "Payload displacement differs")
    require(fields["continue_pc"] - actual_base == symbols["hakios_early_entry_continue"] - symbols["_text"], "Continuation displacement differs")
    baseline = PROJECT.parent / "everline-ksu/artifacts/A51-PixelOS-Everline-KernelSU-Next-boot.img"
    require(pin(baseline)["sha256"] == "eb30609a62999e3282ac81e0a5e56411ef12ec1a39c107171bf3e01209c7cb67", "Baseline changed")
    raw = baseline.read_bytes()
    container = parse_boot(raw)
    section = container["sections"]["kernel"]
    header = parse_arm64_image(raw[section["offset"]:section["offset"] + section["size"]])
    failed = json.loads((PROJECT / "manifests/phase3-last-device-cycle.json").read_text(encoding="utf-8"))
    packet_verify(PROJECT / failed["packet"])
    require(not failed["passed"] and failed["baseline_restored"], "Unexpected latest phone result")
    report = {"original_inputs": {str(p.relative_to(PROJECT)): pin(p) for p in (build_path, execution_path)},
              "original_silicon_image_base": actual_base, "original_silicon_image_base_hex": hex(actual_base),
              "draft_image_base": 0x80080000, "load_displacement": actual_base - 0x80080000,
              "baseline_container_kernel_addr": container["kernel_addr"], "baseline_image_header": header,
              "scope": "Original Phase 2 silicon placement; Phase 3 entry remains unobserved",
              "device_operations": False, "phase_3_device_gate_passed": False}
    json_write(packet / "result.json", report)
    firmware = (PROJECT / "prototype/phase3-loader/qemu_firmware.S").read_text(encoding="utf-8")
    anchor = "    .section .text, \"ax\""
    require(firmware.count(anchor) == 1 and firmware.count("=0x80080000") == 1, "Firmware anchors changed")
    firmware = firmware.replace(anchor, "#ifndef QEMU_IMAGE_BASE\n#define QEMU_IMAGE_BASE 0x80080000\n#endif\n" + anchor, 1)
    firmware = firmware.replace("=0x80080000", "=QEMU_IMAGE_BASE", 1)
    source = (PROJECT / "scripts/phase3-qemu-loader.py").read_text(encoding="utf-8")
    replacements = [
        ('    args = parser.parse_args()', '    parser.add_argument("--load-address", type=lambda s: int(s, 0), default=0x80080000)\n    args = parser.parse_args()\n    require(0x80080000 <= args.load_address <= 0x84000000 and args.load_address % 4096 == 0, "Invalid replay placement")'),
        ('              "nonce": selected["nonce"], "loader_build_packet": selected["packet"],', '              "nonce": selected["nonce"], "loader_build_packet": selected["packet"],\n              "load_address": args.load_address,'),
        ('            str(packet / "firmware.S"), "-o", str(work / "firmware.elf")], env=env)', '            "-DQEMU_IMAGE_BASE=" + hex(args.load_address),\n            str(packet / "firmware.S"), "-o", str(work / "firmware.elf")], env=env)'),
        ('addr=0x80080000,force-raw=on', 'addr={hex(args.load_address)},force-raw=on'),
        ('selected["symbols"]["loader_context"]', '(selected["symbols"]["loader_context"] + args.load_address - 0x80080000)'),
        ('selected["symbols"]["loader_fault_frame"]', '(selected["symbols"]["loader_fault_frame"] + args.load_address - 0x80080000)'),
    ]
    for old, new in replacements:
        require(old in source, "QEMU placement anchor changed: " + old)
        source = source.replace(old, new)
    state = json.loads((PROJECT / "state.json").read_text(encoding="utf-8"))
    continuation = state["phase_3_continuation"]
    qemu = {}
    for case in ("full", "reset", "fault", "bad-toc", "bad-fdt"):
        item = json.loads((PROJECT / f"manifests/phase3-loader-qemu-{case}.json").read_text(encoding="utf-8"))
        packet_verify(PROJECT / item["packet"])
        require(item["passed"], "Missing corrected-header QEMU result")
        qemu[case] = {"result": item["packet"] + "/result.json", "pin": pin(PROJECT / item["packet"] / "result.json")}
    continuation.update({"latest_device_cycle": failed["packet"] + "/result.json",
                         "latest_device_cycle_pin": pin(PROJECT / failed["packet"] / "result.json"),
                         "latest_device_cycle_passed": False, "baseline_restored": True,
                         "last_verified_android_boot_id": failed["boot_id_after"], "last_device_error": failed["error"],
                         "complete_loader_qemu_results": qemu,
                         "complete_loader_qemu_scope": "Corrected Samsung header passed five fixed-placement QEMU cases; silicon placement replay pending",
                         "placement_audit_result": str((packet / "result.json").relative_to(PROJECT)),
                         "original_phase_2_load_base": hex(actual_base), "qualifying_a51_runs": 0})
    state["active_task"] = "phase_3_image_placement_and_entry_diagnostic"
    current = (PROJECT / "docs/STATE.md").read_text(encoding="utf-8")
    current += f"\n\nP3-022: corrected Samsung header passed all five fixed-placement QEMU cases. Hardware reset `{failed['packet']}` FAILED with no original console/pmsg envelope; baseline readback, fresh Android completion and root restored. Original Phase 2 entry PC, payload PC, continuation PC and x1/x2/x3 independently establish Image load base `{hex(actual_base)}`, versus the draft's fixed `0x80080000`. This is an observed historical placement discrepancy, not a proved Phase 3 failure cause. QEMU can now replay that placement; qualifying hardware runs remain 0/3.\n"
    log = (PROJECT / "docs/IMPLEMENTATION-LOG.md").read_text(encoding="utf-8")
    log += f"""

### P3-022 — Retain the corrected-header failure and audit original silicon placement

Date: 14 November 2026, Asia/Calcutta. Phase 3 IN PROGRESS, qualifying device runs 0/3; Phase 4 continuation remains authorized.

Purpose/files: scripts/phase3-prepare-placement-check.py, prototype/phase3-loader/qemu_firmware.S, scripts/phase3-qemu-loader.py, docs/STATE.md, state.json and this log. Replay a historically observed load address without attributing it to an unobserved Phase 3 launch. The firmware macro and bounded QEMU option preserve the default test and retain executed placement; context/fault addresses follow the loaded Image displacement.

Verification: corrected-header builds 20261114T042802854062Z and 20261114T042802468724Z passed. Fresh full/reset/fault/bad-TOC/bad-FDT packets 20261114T043045530889Z, 20261114T043045528124Z, 20261114T043045529593Z, 20261114T043045535233Z and 20261114T043045528760Z passed; full executed PID 1, three timer samples and physical return in 12.882 seconds. Hardware run 20261114T043155822461Z / {failed['packet']} failed despite verified candidate write/readback and recovery reconnection. No current envelope was present; all original bytes remain retained. Baseline restoration passed readback, fresh Android boot and root. Its nonce is retired.

Placement evidence: original Phase 2 symbol/PC differences independently yield `{hex(actual_base)}` and agree with original x3 and x1+x2. The fixed standalone Image base is 0x80080000, a displacement of {hex(actual_base - 0x80080000)}. Container/header addresses alone do not establish actual firmware placement. New placement execution is pending; no device operation occurs in this audit/tool change.

Limitations/rollback: the discrepancy is not yet a confirmed missing-log cause. Restore only this packet's indexed before files and rebuild in new isolated directories; retain original source pins, failed candidates/nonces, QEMU evidence and baseline/recovery/DTBO images. Phase 3 cannot pass from host execution or reconnection alone.
"""
    update_documents(packet, {"prototype/phase3-loader/qemu_firmware.S": firmware,
                             "scripts/phase3-qemu-loader.py": source,
                             "docs/STATE.md": current, "state.json": json.dumps(state, indent=2) + "\n",
                             "docs/IMPLEMENTATION-LOG.md": log})
    packet_index(packet)
    print(json.dumps({"packet": str(packet.relative_to(PROJECT)), "silicon_base": hex(actual_base), "draft_base": "0x80080000", "device_operations": False}, indent=2))


if __name__ == "__main__":
    main()
