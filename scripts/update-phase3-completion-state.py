#!/usr/bin/env python3
"""Update state.json to record Milestone P3-005 completion and transition to P3-006."""
from __future__ import annotations

import json
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
STATE_FILE = PROJECT / "state.json"

def main() -> int:
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    state["updated_date_local"] = "2026-11-14"
    state["active_phase"] = 3
    state["active_task"] = "phase_3_p3_006_repeatable_stability_and_multi_cycle_validation"

    p3_crit = state.setdefault("phase_3_criteria", {})
    p3_crit["p3_005_status"] = "complete_silicon_execution_and_rollback_verified"
    p3_crit["p3_005_packaging"] = "complete_61865984_bytes_verified"
    p3_crit["p3_005_silicon_boot"] = "verified_silicon_execution_status_6_el_1_restored_eb30609a"
    p3_crit["p3_005_evidence"] = "evidence/phase-3/device-execution/20261114T003014997206Z"
    p3_crit["p3_006_status"] = "in_progress_repeatable_stability_runs"

    state.setdefault("phase_3_evidence_selection", {})
    state["phase_3_evidence_selection"]["p3_005_execution_result"] = "evidence/phase-3/device-execution/20261114T003014997206Z/result.json"
    state["phase_3_evidence_selection"]["p3_005_execution_dmesg"] = "evidence/phase-3/device-execution/20261114T003014997206Z/dmesg_hakios_record.txt"
    state["phase_3_evidence_selection"]["p3_005_execution_index"] = "evidence/phase-3/device-execution/20261114T003014997206Z/index.json"

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
        f.write("\n")

    print("[PASS] state.json updated: P3-005 COMPLETE, P3-006 IN PROGRESS.")
    return 0

if __name__ == "__main__":
    main()

