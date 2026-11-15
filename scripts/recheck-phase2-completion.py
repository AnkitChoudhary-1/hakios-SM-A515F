#!/usr/bin/env python3
"""Independently recheck the retained successful Phase 2 run, without a device."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import sys
import tarfile

from samsung_boot_dry_run import reconstruct_in_memory

PROJECT = Path(__file__).resolve().parents[1]
DEVICE = "evidence/phase-2/device-execution/20261113T010932628245Z"
REVIEW = "evidence/phase-2/completion-review/20261113T012258713899Z"
BUILD = "evidence/phase-2/early-entry-kernel/20261113T004224388744Z"
HOST = "evidence/phase-2/early-entry-host/20261113T004009288671Z"
CANDIDATE = "artifacts/phase-2/samsung-boot-candidate/20261113T010751116216Z"
RUN = "runs/20261113T010932384409Z-phase2-hardware-gate-execution"
DOCUMENTS = ["README.md", "state.json", "docs/STATE.md", "docs/INDEX.md",
             "docs/HANDOFF.md", "docs/DEVICE-EXECUTION.md", "docs/IMPLEMENTATION-LOG.md"]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def pin(raw: bytes) -> dict:
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-documentation", action="store_true")
    args = parser.parse_args()
    inputs = {}

    def read(path: str | Path) -> bytes:
        path = Path(path)
        resolved = path if path.is_absolute() else PROJECT / path
        raw = resolved.read_bytes()
        inputs[str(path).replace("\\", "/")] = pin(raw)
        return raw

    def obj(path: str) -> dict:
        return json.loads(read(path))

    def check_index(folder: str) -> int:
        index = obj(folder + "/index.json")
        for name, expected in index["files"].items():
            require(pin(read(folder + "/" + name)) == expected, "index mismatch: " + folder + "/" + name)
        return len(index["files"])

    counts = {p: check_index(p) for p in (DEVICE, REVIEW, BUILD)}
    state = obj("state.json")
    selection = state["phase_2_evidence_selection"]
    for key in ("device_execution_result", "device_execution_dmesg", "device_execution_index",
                "early_entry_host_result", "early_entry_prepare_result", "early_entry_adaptation_patch",
                "early_entry_kernel_result", "early_entry_image", "boot_candidate_image", "boot_candidate_tar"):
        require(pin(read(selection[key]))["sha256"] == selection[key + "_sha256"], "selection mismatch: " + key)

    review = obj(REVIEW + "/result.json")
    for path, expected in review["input_pins"].items():
        # Documentation may have changed after the review; validate its original copies.
        original = REVIEW + "/before/" + path if path in DOCUMENTS else path
        require(pin(read(original)) == expected, "review input mismatch: " + path)
    require(review["status"] == "reviewed_complete" and review["phase_2_device_gate_passed"], "review did not pass")
    require(all(review["payload_checks"].values()), "review has failed payload predicates")

    for name in (RUN,
                 "runs/20261113T004001253454Z-early-entry-host-tests",
                 "runs/20261113T004218150818Z-build-early-entry-kernel",
                 "runs/20261113T010750141773Z-package-samsung-boot-candidate",
                 "runs/20261113T012258446372Z-phase2-final-completion-review"):
        meta = obj(name + "/metadata.json")
        require(meta["status"] == "passed" and meta["exit_code"] == 0, "original run failed: " + name)

    device = obj(DEVICE + "/result.json")
    log = read(RUN + "/output.log").decode("utf-8")
    require(pin(log.encode())["sha256"] == "f5f83617febf84e740aa204a8531e60a80ff8f6a6d45f0f978d473b564db0e2a", "original hardware log changed")
    full_dmesg = read(DEVICE + "/candidate_dmesg.txt").decode("utf-8")
    excerpt = read(DEVICE + "/dmesg_hakios_record.txt").decode("utf-8")
    for line in excerpt.splitlines():
        require(line in log and line in full_dmesg, "record differs from original output/dmesg")
    require(device["stages"]["stage_4_evidence"]["matching_lines"] == excerpt.splitlines(), "summary record differs")
    decimal = {"ver", "bytes", "status", "reason", "el", "cntfrq", "line"}
    fields = {}
    lines = [s for s in excerpt.splitlines() if "HAKIOS_V1 " in s]
    require(len(lines) == 5, "unexpected hardware field line count")
    for line in lines:
        for key, value in re.findall(r"\b([a-z][a-z0-9_]*)=([0-9a-f]+)\b", line):
            require(key not in fields, "duplicate record field: " + key)
            fields[key] = int(value, 10 if key in decimal else 16)
    require(fields == device["stages"]["stage_4_evidence"]["fields"] == review["record"], "decoded record mismatch")

    build = obj(BUILD + "/result.json")
    host = obj(HOST + "/result.json")
    for name, expected in build["prototype_source_pins"].items():
        require(pin(read(BUILD + "/prototype/" + name)) == expected, "retained build source differs: " + name)
        require(pin(read("prototype/early-entry/" + name)) == expected, "current source differs from build: " + name)
    for name, expected in host["source_pins"].items():
        require(expected == build["prototype_source_pins"][name], "QEMU/build source association mismatch: " + name)
    for key in ("qemu_test_result", "preparation_result", "adaptation_patch"):
        expected = build[key]
        require(pin(read(expected["path"])) == {k: expected[k] for k in ("bytes", "sha256")}, "build input mismatch: " + key)
    require(len(host["cases"]) == 5 and all(c["verified"] for c in host["cases"]), "host cases failed")
    require(sum(c["harness_checks"] for c in host["cases"]) == 228, "host count differs")
    for command in host["commands"]:
        require(command["exit_code"] == 0, "host command failed")
        require(pin(read(HOST + "/" + command["output"]))["sha256"] == command["output_sha256"], "host command log mismatch")
    symbols = build["symbols"]
    for field, symbol in (("payload_pc", "hakios_early_tiny_payload"), ("continue_pc", "hakios_early_entry_continue")):
        require(fields[field] - fields["entry_pc"] == symbols[symbol] - symbols["stext"], "hardware/build symbol displacement differs")

    header = read("prototype/early-entry/hakios_early_entry.h").decode()
    constants = {n: int(v, 0) for n, v in re.findall(r"^#define (HKE_[A-Z_]+) (0x[0-9a-fA-F]+|[0-9]+)$", header, re.M)}
    require(fields["magic"] == constants["HKE_MAGIC"] and fields["ver"] == constants["HKE_VERSION"]
            and fields["bytes"] == constants["HKE_BYTES"], "hardware schema mismatch")
    raw = fields["x0"] ^ fields["x1"] ^ fields["x2"] ^ fields["x3"] ^ fields["cntfrq"] ^ fields["midr"]
    value = ((raw >> 7) | (raw << 57)) & ((1 << 64) - 1)
    require(fields["status"] == constants["HKE_EXECUTED"] and fields["reason"] == 0, "payload skipped")
    require(fields["payload_marker"] == constants["HKE_PAYLOAD_MARKER"] and fields["payload_val"] == value, "payload result mismatch")
    require(fields["el"] in (1, 2) and not fields["sctlr"] & 5, "invalid execution state")
    require(fields["daif"] & 0x2c0 == 0x2c0, "invalid incoming interrupt masks")
    require(fields["line"] == 4 << ((fields["ctr"] >> 16) & 15) and fields["line"] <= 256, "invalid cache geometry")

    kernel = read(BUILD + "/Image")
    require(pin(kernel) == build["image"], "Image differs from build")
    baseline = read(Path(device["rollback"]["path"]))
    require(pin(baseline) == {k: device["rollback"][k] for k in ("bytes", "sha256")}, "rollback pin mismatch")
    candidate = read(CANDIDATE + "/A51-HakiOS-Early-Entry-boot.img")
    require(pin(candidate) == {k: device["candidate"][k] for k in ("bytes", "sha256")}, "candidate pin mismatch")
    reconstructed, packaging = reconstruct_in_memory(baseline, kernel)
    require(reconstructed == candidate, "candidate reconstruction differs")
    with tarfile.open(PROJECT / CANDIDATE / "boot.tar", "r:") as archive:
        members = archive.getmembers()
        require(len(members) == 1 and members[0].name == "boot.img" and members[0].isfile(), "unexpected tar contents")
        require(archive.extractfile(members[0]).read() == candidate, "tar boot member differs")

    stages = device["stages"]
    baseline_sha = device["rollback"]["sha256"]
    require(stages["stage_0_preflight"]["initial_boot_id"] != stages["stage_4_evidence"]["candidate_boot_id"], "candidate reboot unproven")
    require(stages["stage_5_restoration"]["restored_boot_sha"] == baseline_sha, "restored hash differs")
    require("Restored boot partition SHA-256: " + baseline_sha in log and "Post-restoration boot completed" in log
            and "uid=0(root)" in log, "restoration evidence missing")
    executed_script = read(RUN + "/project-scripts/execute-phase2-hardware-gate.py").decode()
    require('require(final_boot_sha == ROLLBACK_SHA256' in executed_script, "final partition readback not checked")
    require(device["phase_2_device_gate_passed"] and device["status"] == "completed_successfully", "device result not successful")

    if args.check_documentation:
        require(state["phase_2_status"] == "complete" and state["phase_2_device_gate_passed"], "top-level status inconsistent")
        for key in ("phase_2_device_execution_validation", "phase_2_completion_review"):
            require(state[key]["phase_2_device_gate_passed"], "stale current status: " + key)
        require(state["phase_2_completion_review"]["result"] == REVIEW + "/result.json", "wrong current review")
        require(state["phase_2_completion_review"]["result_sha256"] == pin(read(REVIEW + "/result.json"))["sha256"], "current review pin mismatch")
        for path in ("README.md", "docs/STATE.md", "docs/INDEX.md", "docs/HANDOFF.md", "docs/DEVICE-EXECUTION.md", "docs/PHASE-2-COMPLETION-REVIEW.md"):
            lead = read(path).decode("utf-8").split("\n\n", 4)
            require("COMPLETE" in "\n\n".join(lead[:4]), "document lacks current completion lead: " + path)
        require(3 in state["planned_phases"] and not state["a51_xnu_boot_verified"] and not state["no_flash_a51_launch_verified"], "downstream limits changed")

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = PROJECT / "evidence/phase-2/completion-recheck" / stamp
    folder.mkdir(parents=True, exist_ok=False)
    result = {"schema_version": 1, "status": "verified_complete", "reviewed_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
              "phase_2_device_gate_passed": True, "input_pins": inputs, "indexed_file_counts": counts,
              "hardware_record": fields, "expected_payload_value_hex": f"0x{value:016x}",
              "candidate_reconstruction": packaging, "documentation_checked": args.check_documentation,
              "limitations": ["normal_return_and_restoration_only_no_actual_fault_reset_test", "printed_fields_not_raw_record_dump",
                              "no_sustained_baseline_stability_test_in_this_run", "staging_cleanup_command_unchecked",
                              "no_xnu_or_no_flash_launch"],
              "operations": {"phone_queries": False, "phone_writes": False, "reboot": False, "flashing": False}}
    (folder / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    (folder / "recheck-phase2-completion.py").write_bytes(Path(__file__).read_bytes())
    (folder / "index.json").write_text(json.dumps({"files": {p.name: pin(p.read_bytes()) for p in folder.iterdir() if p.is_file()}}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "result": folder.relative_to(PROJECT).as_posix() + "/result.json",
                      "indexed_file_counts": counts, "payload_value": f"0x{value:016x}",
                      "candidate_reconstructed": True, "documentation_checked": args.check_documentation,
                      "phase_2_device_gate_passed": True}, indent=2))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
