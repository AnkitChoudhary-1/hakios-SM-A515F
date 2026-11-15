#!/usr/bin/env python3
"""Verify the connected supplement and historical handoff without phone access."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("historical_runtime_handoff", PROJECT / "scripts/check-runtime-map-handoff.py")
previous = importlib.util.module_from_spec(spec)
spec.loader.exec_module(previous)
base = previous.baseline
require = base.require


def main():
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        require(previous.main() == 0, "historical handoff failed")
    counts = json.loads(output.getvalue().splitlines()[-1])
    state = base.read_json(PROJECT / "state.json")
    current = state["phase_2_connected_device_validation"]
    selection = state["phase_2_evidence_selection"]
    report_path = base.selected_path(selection["device_prerequisites_report"])
    report = base.read_json(report_path)
    index_path = report_path.parent / "index.json"
    require(base.digest(index_path) == selection["device_prerequisites_index_sha256"], "supplemental index pin mismatch")
    require(current["report_size"] == report_path.stat().st_size
            and current["summary"] == report["summary"]
            and current["offline_replay_hosts"] == ["windows", "wsl"]
            and state["phone_queries_this_continuation"] is True, "supplemental state mismatch")
    packet = report_path.parent.relative_to(PROJECT).as_posix()
    capture_path, capture = base.check_role_run(current["capture_run"], ["python", "scripts/capture-device-prerequisites.py", "--serial", report["serial"]],
                                             "EXECUTABLE OWNERSHIP / A51 ENTRY / PAYLOAD LOGS / RETURN / PHASE 2 GATE: false")
    base.check_role_run(current["replay_runs"]["windows"], ["python", "scripts/capture-device-prerequisites.py", "--verify", packet],
                        "EXECUTABLE OWNERSHIP / A51 ENTRY / PAYLOAD LOGS / RETURN / PHASE 2 GATE: false")
    wsl_root = "/mnt/" + PROJECT.drive[0].lower() + PROJECT.as_posix()[2:]
    base.check_role_run(current["replay_runs"]["wsl"], ["wsl", "-d", "A51-KernelBuilder", "--", "python3", wsl_root + "/scripts/capture-device-prerequisites.py", "--verify", wsl_root + "/" + packet],
                        "EXECUTABLE OWNERSHIP / A51 ENTRY / PAYLOAD LOGS / RETURN / PHASE 2 GATE: false")
    require(base.digest(capture_path.parent / "project-scripts/capture-device-prerequisites.py") == base.digest(PROJECT / "scripts/capture-device-prerequisites.py"), "capture source changed")
    for name in current["source_review_runs"]:
        base.check_run(name)
    checks_path, _ = base.check_run(current["corruption_checks_run"])
    require("CORRUPTION_CHECKS_PASSED 3" in (checks_path.parent / "output.log").read_text(encoding="utf-8"), "missing corruption-check result")
    before = PROJECT / "evidence/phase-2/device-prerequisites-docs/20261111T1220Z/before"
    checkpoint = base.read_json(before / "index.json")
    require(len(checkpoint["files"]) == 9, "rollback-copy count mismatch")
    for item in checkpoint["files"]:
        path = before / item["copy"]
        require(path.stat().st_size == item["size"] and base.digest(path) == item["sha256"], "rollback copy changed")
        if item["original"] == "manifests/live-loader-current.json":
            require(base.digest(PROJECT / item["original"]) == item["sha256"], "historical live pointer changed")
    old_state = base.read_json(before / "05-state.json")
    require(all(selection[key] == value for key, value in old_state["phase_2_evidence_selection"].items()), "historical selection changed")
    for key in ("phase_2_source_trace_validation", "phase_2_loader_prototype_validation",
                "phase_2_runtime_map_validation", "phase_2_entry_route_review"):
        require(state[key]["phone_queries"] is False, "historical query scope changed")
    guide = (PROJECT / "docs/DEVICE-PREREQUISITES.md").read_text(encoding="utf-8")
    state_text = (PROJECT / "docs/STATE.md").read_text(encoding="utf-8")
    require(selection["device_prerequisites_report"] in guide and selection["device_prerequisites_report"] in state_text
            and selection["device_prerequisites_report_sha256"] in guide
            and "35" in guide and "33" in guide and "112" in guide, "supplemental evidence missing from guide/state")
    print(json.dumps({**counts, "phone_queries": True, "phone_writes": False,
                      "scope": current["scope"], "supplemental_queries": 35, "successful_queries": 33,
                      "remote_failures": 2, "supplemental_indexed_files": current["indexed_files"],
                      "supplemental_indexed_bytes": current["indexed_bytes"], "supplemental_rollback_copies": 9,
                      "corruption_checks": 3, "phase_2_device_gate_passed": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
