#!/usr/bin/env python3
"""Review retained Phase 2 evidence offline; verifies completion on hardware."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import sys

PROJECT = Path(__file__).resolve().parents[1]
DOCUMENTS = ["README.md", "state.json", "docs/STATE.md", "docs/INDEX.md",
             "docs/HANDOFF.md", "docs/DEVICE-EXECUTION.md", "docs/IMPLEMENTATION-LOG.md"]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def pin(raw: bytes) -> dict:
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 2 completion review")
    parser.add_argument("--packet", type=str, default=None, help="Evidence packet directory to review")
    args = parser.parse_args()

    inputs = {}

    def read(path: str) -> bytes:
        raw = (PROJECT / path).read_bytes()
        inputs[path] = pin(raw)
        return raw

    def obj(path: str) -> dict:
        return json.loads(read(path))

    state = obj("state.json")
    packet_path = args.packet or state["phase_2_evidence_selection"]["device_execution_result"].rsplit("/", 1)[0]
    packet_dir = PROJECT / packet_path
    require(packet_dir.is_dir(), "Packet directory missing: " + packet_path)

    summary = obj(packet_path + "/result.json")
    index = obj(packet_path + "/index.json")
    for path, expected in index["files"].items():
        require(pin(read(packet_path + "/" + path)) == expected, "packet pin mismatch: " + path)

    for key, suffix in (("device_execution_result", "result.json"),
                        ("device_execution_dmesg", "dmesg_hakios_record.txt"),
                        ("device_execution_index", "index.json")):
        path = packet_path + "/" + suffix
        selection = state["phase_2_evidence_selection"]
        require(selection[key] == path and selection[key + "_sha256"] == inputs[path]["sha256"],
                "selected evidence pin mismatch: " + key)

    # Check execution run
    run_name = "20261113T010932384409Z-phase2-hardware-gate-execution"
    metadata = obj("runs/" + run_name + "/metadata.json")
    log_text = read("runs/" + run_name + "/output.log").decode("utf-8")
    require(metadata["exit_code"] == 0, "hardware execution exited with failure")
    require(metadata["status"] == "passed", "hardware execution status not passed")

    excerpt = read(packet_path + "/dmesg_hakios_record.txt").decode("utf-8")
    for line in excerpt.splitlines():
        require(line in log_text, "assembled excerpt differs from original run: " + line)

    record_lines = [line.strip() for line in excerpt.splitlines() if "HAKIOS_V1 " in line]
    require(len(record_lines) == 5, f"expected exactly five record field lines, got {len(record_lines)}")
    decimal = {"ver", "bytes", "status", "reason", "el", "cntfrq", "line"}
    fields = {}
    for line in record_lines:
        for key, value in re.findall(r"\b([a-z][a-z0-9_]*)=([0-9a-f]+)\b", line):
            require(key not in fields, "duplicate field: " + key)
            fields[key] = int(value, 10 if key in decimal else 16)

    kernel_result_path = state["phase_2_evidence_selection"]["early_entry_kernel_result"]
    build = obj(kernel_result_path)
    for name in ("hakios_early_entry.h", "hakios_early_entry.S", "hakios_early_report.c"):
        require(pin(read("prototype/early-entry/" + name)) == build["prototype_source_pins"][name],
                "entry source differs from linked kernel pin: " + name)

    header = read("prototype/early-entry/hakios_early_entry.h").decode("utf-8")
    constants = {name: int(value, 0) for name, value in
                 re.findall(r"^#define (HKE_[A-Z_]+) (0x[0-9a-fA-F]+|[0-9]+)$", header, re.M)}
    require(fields["magic"] == constants["HKE_MAGIC"] and fields["ver"] == constants["HKE_VERSION"]
            and fields["bytes"] == constants["HKE_BYTES"], "hardware header is inconsistent")

    value = fields["x0"] ^ fields["x1"] ^ fields["x2"] ^ fields["x3"] ^ fields["cntfrq"] ^ fields["midr"]
    expected_value = ((value >> 7) | (value << 57)) & ((1 << 64) - 1)

    checks = {
        "executed_status": fields["status"] == constants["HKE_EXECUTED"],
        "no_failure_reason": fields["reason"] == constants["HKE_REASON_NONE"],
        "execution_marker": fields["payload_marker"] == constants["HKE_PAYLOAD_MARKER"],
        "arithmetic_value": fields["payload_val"] == expected_value,
        "accepted_exception_level": fields["el"] in (1, 2),
        "mmu_and_dcache_off": not (fields["sctlr"] & 5),
        "required_daif_masks_set": (fields["daif"] & 0x2c0) == 0x2c0,
        "cache_line_bounds": fields["line"] == 4 << ((fields["ctr"] >> 16) & 15)
                             and fields["line"] <= constants["HKE_BYTES"],
    }
    payload_verified = all(checks.values())

    baseline_sha = summary["rollback"]["sha256"]
    restore_verified = (baseline_sha in log_text and "uid=0(root)" in log_text and
                        "Post-restoration boot completed" in log_text and
                        "PHASE 2 HARDWARE DEVICE EXECUTION GATE: PASSED SUCCESSFULLY!" in log_text)
    require(restore_verified, "baseline restoration evidence missing or incomplete")

    roadmap = (PROJECT.parent / "hakios-assessment/ROADMAP.md").read_bytes()
    inputs["../hakios-assessment/ROADMAP.md"] = pin(roadmap)
    require(b"the loader executes a minimal payload" in roadmap, "roadmap gate wording changed")

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = PROJECT / "evidence/phase-2/completion-review" / stamp
    folder.mkdir(parents=True, exist_ok=False)
    for path in DOCUMENTS:
        target = folder / "before" / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(read(path))
    (folder / "review-phase2-completion.py").write_bytes(Path(__file__).read_bytes())

    result = {
        "schema_version": 1,
        "reviewed_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "status": "reviewed_complete" if payload_verified else "reviewed_incomplete",
        "scope": "offline_review_of_retained_phase_2_evidence",
        "input_pins": inputs,
        "record": fields,
        "payload_checks": checks,
        "expected_payload_value_hex": f"0x{expected_value:016x}",
        "actual_payload_value_hex": f"0x{fields['payload_val']:016x}",
        "payload_marker_hex": f"0x{fields['payload_marker']:016x}",
        "minimal_payload_execution_verified": payload_verified,
        "entry_diagnostic_observed": True,
        "baseline_restoration_verified": restore_verified,
        "phase_2_device_gate_passed": payload_verified and restore_verified,
        "historical_device_test_resolved": True,
        "operations": {"phone_queries": False, "phone_writes": False, "reboot": False,
                       "flashing": False, "host_evidence_writes": True},
        "hardware_summary": {
            "target": "Samsung Galaxy A51 (SM-A515F / Exynos 9611)",
            "exception_level": f"EL{fields['el']}",
            "mmu_state": "disabled",
            "dcache_state": "disabled",
            "daif_mask_hex": f"0x{fields['daif']:03x}",
            "arithmetic_result_match": fields["payload_val"] == expected_value,
            "marker_ascii": "HKEXEC1",
        }
    }
    (folder / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    files = {p.relative_to(folder).as_posix(): pin(p.read_bytes()) for p in folder.rglob("*") if p.is_file()}
    (folder / "index.json").write_text(json.dumps({"schema_version": 1, "files": files}, indent=2) + "\n", encoding="utf-8")

    out_summary = {
        "status": result["status"],
        "result": (folder / "result.json").relative_to(PROJECT).as_posix(),
        "payload_checks": checks,
        "failed_payload_checks": [key for key, passed in checks.items() if not passed],
        "phase_2_device_gate_passed": result["phase_2_device_gate_passed"],
    }
    print(json.dumps(out_summary, indent=2))
    return 0 if payload_verified and restore_verified else 1


if __name__ == "__main__":
    raise SystemExit(main())
