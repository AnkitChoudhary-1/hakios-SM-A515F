#!/usr/bin/env python3
"""Select measured recovery evidence and retain the user's Phase 4 continuation."""
import json
from pathlib import Path
from phase3_support import PROJECT, json_write, packet_new, packet_index, packet_verify, pin, require, update_documents


def main():
    manifest = json.loads((PROJECT / "manifests/phase3-recovery-contract.json").read_text(encoding="utf-8"))
    measured = PROJECT / manifest["packet"]
    packet_verify(measured)
    result = json.loads((measured / "result.json").read_text(encoding="utf-8"))
    require(result["passed"] and result["baseline_restored"], "Recovery/baseline measurement did not pass")
    params = result["recovery_ramoops_parameters"]
    require(all(params.get(k) == v for k, v in {
        "mem_address": "4191223808", "mem_size": "2097152", "record_size": "524288",
        "console_size": "524288", "ftrace_size": "524288", "pmsg_size": "524288", "ecc": "0",
    }.items()), "Recovery region allocation differs from the intended console contract")
    packet = packet_new("recovery-contract-selection", Path(__file__))
    rel = packet.relative_to(PROJECT).as_posix()
    selected = measured.relative_to(PROJECT).as_posix()
    state = json.loads((PROJECT / "state.json").read_text(encoding="utf-8"))
    state["phase_3_continuation"].update({"recovery_contract_result": selected + "/result.json",
        "recovery_contract_pin": pin(measured / "result.json"), "recovery_log_layout_verified": True,
        "recovery_persistence_verified": False, "standalone_reset_verified": False,
        "independent_device_watchdog_verified": False, "last_verified_android_boot_id": result["android_boot_id_after"]})
    state["user_authorized_continuation"] = {"date": "2026-11-14", "sequence": [3, 4],
        "instruction": "Finish Phase 3, then start and finish Phase 4 without requesting permission again.",
        "phase_4_dependency": "Phase 3 hardware gate must actually pass before Phase 4 execution work."}
    doc = (PROJECT / "docs/STATE.md").read_text(encoding="utf-8")
    marker = "\n\nUpdated 14 November"
    require(marker in doc, "STATE marker absent")
    summary = (f"P3-013 controlled recovery measurement `{selected}` PASSED: recovery root, unchanged baseline boot, "
        "identical Android/recovery ramoops layout (2 MiB at 0xF9D10000, four 512 KiB regions, console at 0xF9D90000, ECC off), "
        "and return to boot-completed rooted baseline Android. Two controlled reboots, zero partition writes. "
        "This verifies recovery layout and baseline return, not a standalone loader reset or XNU-log persistence. "
        "Qualifying A51 XNU runs remain 0/3. The user has authorized continuing into and completing Phase 4 after the Phase 3 gate passes.")
    log = (PROJECT / "docs/IMPLEMENTATION-LOG.md").read_text(encoding="utf-8")
    entry = f"""

### P3-013 — Measure actual recovery log layout and verify baseline Android return

Date: 14 November 2026, Asia/Calcutta. Status: recovery layout and Android return VERIFIED; Phase 3 IN PROGRESS, hardware gate UNPASSED, qualifying XNU runs 0/3.

Purpose: verify that the existing recovery can retrieve the intended ramoops region and return to the pinned Android baseline before repairing the standalone loader. Files: scripts/phase3-recovery-contract.py, scripts/phase3-record-recovery-contract.py, manifests/phase3-recovery-contract.json, docs/STATE.md, state.json and this log. Exact original commands/output/times are in `{selected}`. The selector verifies every indexed file and all nine expected allocation parameters before recording this outcome.

Verification: run `20261114T032015976970Z-phase3-measure-recovery-contract` exited 0. Android root/model/boot completion and live boot/recovery SHA-256 pins were verified first. ADB reboot recovery reached the existing rooted TWRP. Actual recovery parameters are mem_address=4191223808, mem_size=2097152, record/console/ftrace/pmsg_size=524288 each, ecc=0, mem_type=0 and dump_oops=1. The boot partition still matched the baseline in recovery. ADB reboot returned to boot-completed rooted Android with the same baseline boot SHA-256. Android boot IDs before/after are `{result['android_boot_id_before']}` and `{result['android_boot_id_after']}`. The actual primary CPU GIC live DT query reports distributor 0x12301000 and CPU interface 0x12302000; 0x14AF1000/0x14AF2000 are ABOX audio-controller registers and must not replace the primary addresses.

Scope/limitations: two controlled reboots, zero partition/module/loader/pstore writes. Matching layout does not prove a new standalone log persists across reset. Standalone PMU/ACPM reset, independent watchdog, owned memory budget, bounded loader/fault/log behavior and three qualifying A51 XNU cycles remain pending. Source labels remain hypotheses until their relevant execution is verified.

User steering: on 14 November the user requested faster completion and explicitly authorized starting and finishing Phase 4 after Phase 3 without another permission request. Preserve that authorization across turns; gate Phase 4 work on actual Phase 3 completion evidence, not compilation or QEMU.

Rollback/rebuild: preserve both measured and selection packets. Restore only indexed documentation before copies from `{rel}` for bookkeeping rollback, retaining this historical entry. No boot/recovery/DTBO bytes changed, and the phone is verified on its baseline Android image. Re-run the measured script through scripts/run.py to repeat the two-reboot contract check.
"""
    update_documents(packet, {"state.json": json.dumps(state, indent=2) + "\n",
        "docs/STATE.md": doc.replace(marker, "\n\n" + summary + marker, 1),
        "docs/IMPLEMENTATION-LOG.md": log + entry})
    json_write(packet / "result.json", {"selected": selected, "passed": True, "device_gate_passed": False})
    packet_index(packet)
    print(json.dumps({"packet": rel, "recovery_layout_verified": True, "qualifying_a51_runs": 0}))


if __name__ == "__main__":
    main()
