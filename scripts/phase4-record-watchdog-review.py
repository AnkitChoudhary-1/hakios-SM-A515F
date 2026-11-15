#!/usr/bin/env python3
"""Record the failed watchdog trial and measured-placement correction without device actions."""
from __future__ import annotations

import argparse
import importlib.util
import json
import re

from phase3_entry_probe import decode
from phase4_support import PROJECT, documents, index_packet, new_packet, pin, require, write_json


def read(relative):
    return json.loads((PROJECT / relative).read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("pending", "host-verified"), required=True)
    parser.add_argument("--trial", required=True)
    parser.add_argument("--probe", required=True)
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--restored-inventory", help="Inventory of the trial's restored boot, if Android subsequently rebooted")
    parser.add_argument("--connection-run", required=True)
    args = parser.parse_args()
    paths = {key: (PROJECT / getattr(args, key)).resolve() for key in ("trial", "probe", "inventory")}
    if args.restored_inventory:
        paths["restored_inventory"] = (PROJECT / args.restored_inventory).resolve()
    for key, path in paths.items():
        require(path.is_relative_to((PROJECT / "evidence").resolve()), "Wrong evidence root: " + key)
    trial, probe, inventory = (read(getattr(args, key)) for key in ("trial", "probe", "inventory"))
    require(trial["case"] == "watchdog" and trial["passed"] is False and trial["baseline_restored"] and
            trial["baseline_verified"] and trial["candidate_write_attempted"], "Unexpected trial outcome")
    require(probe["passed"] and probe["baseline_restored"], "Unpassed measured entry probe")
    entry = decode((paths["probe"].parent / "console.original").read_bytes(), probe["nonce"])
    require(entry == decode((paths["probe"].parent / "pmsg.original").read_bytes(), probe["nonce"]) == probe["entry"],
            "Original entry banks disagree")
    require(entry["pc"] == 0x800d0040 and entry["x3"] == 0x800d0000 and entry["entry_el"] == 4 and
            entry["sctlr"] & 5 == 0, "Unexpected measured placement/entry state")
    require(inventory["inventory_valid"] and all(inventory["checks"].values()), "Baseline inventory failed")
    boot_id = (paths["inventory"].parent / "boot-id-after.stdout.bin").read_text(encoding="utf-8").strip()
    require(re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", boot_id), "Invalid current inventory boot UUID")
    restored_path = paths.get("restored_inventory", paths["inventory"])
    restored = json.loads(restored_path.read_text(encoding="utf-8"))
    restored_id = (restored_path.parent / "boot-id-after.stdout.bin").read_text(encoding="utf-8").strip()
    require(restored["inventory_valid"] and all(restored["checks"].values()) and restored_id == trial["boot_id_after"],
            "Restored inventory is not the trial's verified Android boot")
    require(paths["inventory"].parent.name >= restored_path.parent.name, "Current inventory predates restoration evidence")
    connection = PROJECT / "runs" / args.connection_run
    require(connection.resolve().is_relative_to((PROJECT / "runs").resolve()), "Wrong connection run")
    require(read("runs/" + args.connection_run + "/metadata.json")["status"] == "passed" and
            re.search(r"(?m)^device\s*$", (connection / "output.log").read_text(encoding="utf-8")),
            "ADB connection check did not pass")
    current = {name: read("manifests/" + filename) for name, filename in (
        ("native", "phase4-loader-native-tests.json"), ("qemu", "phase4-complete-loader-qemu.json"),
        ("models", "phase4-device-cycle-tests.json"))}
    host_ready = args.stage == "host-verified"
    spec = importlib.util.spec_from_file_location("phase4_review_cycle", PROJECT / "scripts/phase4-device-cycle.py")
    cycle = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cycle)
    required = {(case, address) for case in cycle.CASES for address in cycle.PLACEMENTS}
    require("early-fault" in cycle.CASES and len(required) == 63, "Missing early-entry fault coverage")
    if host_ready:
        require(current["native"]["passed"] and current["native"]["native_checks"] >= 4112 and
                current["native"]["envelope_checks"] >= 106, "Native correction checks are unpassed")
        native_packet = PROJECT / current["native"]["packet"]
        for name in ("loader.h", "validate.c", "test_validate.c", "fdt_guard.c", "fdt_guard.h", "validate.h"):
            require(pin(native_packet / name) == pin(PROJECT / "prototype/phase4-loader" / name),
                    "Native tested source differs: " + name)
        require(current["qemu"]["passed"] and current["qemu"]["suite_complete"] and
                len(current["qemu"]["results"]) == len(required) and
                {(r["case"], r["placement"]) for r in current["qemu"]["results"]} == required,
                "Measured-placement QEMU suite is incomplete")
        for row in current["qemu"]["results"]:
            require(pin(PROJECT / row["result"]) == {k: row[k] for k in ("bytes", "sha256")} and row["passed"],
                    "QEMU result pin differs")
            selected = read(str((PROJECT / row["result"]).parent.relative_to(PROJECT) / "selected-loader.json"))
            for name in ("entry.S", "loader.c", "loader.h", "validate.c", "fdt_guard.c", "loader.ld"):
                require(selected["sources"][name] == pin(PROJECT / "prototype/phase4-loader" / name),
                        "QEMU tested source differs: " + name)
        require(current["models"]["passed"] and current["models"]["tests"] >= 119 and
                current["models"]["device_operations"] is False, "Cycle models are incomplete")
        for name, expected in current["models"]["sources"].items():
            require(pin(PROJECT / "scripts" / name) == expected, "Cycle tested source differs: " + name)
    packet = new_packet("watchdog-review", __file__)
    result = {"recorded": True, "stage": args.stage, "host_ready": host_ready,
        "input_pins": {key: {"path": getattr(args, key), **pin(path)} for key, path in paths.items()},
        "original_entry_banks": {name: pin(paths["probe"].parent / (name + ".original")) for name in ("console", "pmsg")},
        "measured_entry": entry, "consumed_nonce": trial["nonce"],
        "trial_attributable_capture": False, "baseline_verified": True,
        "restored_android_boot_id": restored_id, "current_inventory_boot_id": boot_id,
        "inventory_same_boot_as_trial_restoration": boot_id == restored_id,
        "loader_entry_verified": False, "watchdog_reset_verified": False,
        "persistent_envelope_survival_verified": False, "device_operations": False,
        "phase_4_gate_passed": False,
        "host_selections": {key: {"result": value["packet"] + "/result.json",
            **pin(PROJECT / value["packet"] / "result.json")} for key, value in current.items()}}
    write_json(packet / "result.json", result)
    state = read("state.json")
    state.update(phase_4_status="in_progress", phase_4_device_gate_passed=False,
                 phase_4_loader_host_ready=host_ready,
                 next_action="resolve_missing_prevalidation_envelope_then_attributable_watchdog_and_full_loader_before_real_peripherals")
    state["phase_4_watchdog_review"] = {"result": (packet / "result.json").relative_to(PROJECT).as_posix(), **pin(packet / "result.json")}
    state["phase_4_inventory"] = {"result": args.inventory, **pin(paths["inventory"])}
    state["phase_4_connection"] = {"run": args.connection_run, "adb_serial_present": True,
        "captured_boot_id": boot_id, "inventory": args.inventory, "scope": "Android observation at capture; recheck at trial entry"}
    for key in ("phase_4_loader_native_tests", "phase_4_complete_loader_qemu", "phase_4_device_cycle_tests"):
        state[key]["matches_current_sources"] = host_ready
    status = (f"The current loader passed {current['native'].get('native_checks', 0):,} ASan/UBSan validator checks, "
              f"{current['native'].get('envelope_checks', 0)} envelope checks, all {len(required)} complete-loader QEMU cases and "
              f"{current['models'].get('tests', 0)} capture/cycle models. Fresh nonce-bound hardware packages and preflights are still required."
              if host_ready else "Exception vectors, stack, cleared BSS and saved entry context now precede cache changes. Matching 63-case QEMU execution and cycle-model validation are pending; the previous passing 60-case suite predates these entry changes.")
    status += " An injected pre-cache-transition exception with I-cache enabled is checked at all three placements; hardware entry and persistence remain separate gates."
    lead = ("## Current Phase 4 hardware investigation\n\n" + status +
        f" The last watchdog trial `{args.trial}` returned to recovery after {trial['return_seconds']} seconds but produced no attributable Phase 4 envelope. "
        "Loader entry, watchdog reset and persistent-record survival remain unverified. The pinned Android baseline was restored and verified, with unchanged recovery/DTBO and no staging files. "
        f"Subsequent rooted inventory `{args.inventory}` passed (Android UUID `{boot_id}`), and ADB is connected in `{args.connection_run}`. "
        f"The trial's restored Android UUID `{restored_id}` is retained separately. "
        "The original successful entry probe measured Image base `0x800d0000`; the corrected loader accepts that placement alongside `0x80080000` and `0x80278000`. "
        "An envelope is emitted before C validation, so the old placement rejection does not by itself explain the absent log. "
        "Actual display/brightness, physical touch/keys, UFS DMA/image loading and read-only submission gates remain unpassed. "
        "See [device path and recovery](C:/Users/Ankit/Desktop/A51/hakios-a51/docs/PHASE-4-DEVICE-PATH.md).")
    replacements = {"state.json": json.dumps(state, indent=2) + "\n"}
    for rel in ("README.md", "docs/STATE.md", "docs/INDEX.md"):
        old = (PROJECT / rel).read_text(encoding="utf-8")
        updated, count = re.subn(r"## Current Phase 4 (?:loader readiness|hardware investigation)\n\n.*?(?=\n\nPhase 1)",
                                lambda _: lead, old, count=1, flags=re.S)
        require(count == 1, "Missing current-state section: " + rel)
        replacements[rel] = updated
    guide = (PROJECT / "docs/PHASE-4-DEVICE-PATH.md").read_text(encoding="utf-8")
    guide = guide.replace("QEMU covers placements `0x80080000` and `0x80278000`; neither host result establishes a current device placement.",
        "The original successful accepted-carrier entry probe measured PC `0x800d0040`, Image base/x3 `0x800d0000` and FDT/x0 `0x8a100000`. "
        "The corrected loader accepts `0x80080000`, `0x80278000` and `0x800d0000`; current C-loader hardware placement still requires attributable evidence.")
    marker = "## Measured-placement correction and failed watchdog review"
    if marker in guide:
        guide = guide[:guide.index(marker)].rstrip() + "\n"
    guide += (f"\n{marker}\n\n{status}\n\n"
        f"Original probe: `{args.probe}`; both original nonce/CRC-bound banks replayed identically. Last trial: `{args.trial}`. "
        f"Candidate staging/write/readback passed and recovery reconnected in {trial['return_seconds']} seconds, but console acquisition failed and pmsg was unrelated Android data. "
        "No attributable envelope was captured. Entry failure and persistence loss remain separate hypotheses because loader_main publishes stage 1 before validation. "
        f"The baseline was restored/readback verified and returned to completed rooted Android UUID `{restored_id}`, with unchanged recovery/DTBO and no staging. "
        f"The later current baseline inventory has Android UUID `{boot_id}`. "
        f"Inventory `{args.inventory}` independently rechecked the baseline and first 1 MiB.\n\n"
        f"Nonce `{trial['nonce']}` is consumed. All hardware packages/preflights listed above predate the measured-placement correction and must be rebuilt before another trial. "
        "Keep unrelated pmsg bytes private in the original evidence; do not print them.\n\n"
        "Rebuild changed sources through scripts/run.py: phase4-test-device-cycle.py; "
        "phase4-build-device-path.py --mode qemu --kind full; phase4-qemu-device-path.py --case all. "
        "The full suite now requires 63 cases at three exact placements, including early exceptions before cache changes. The unchanged native validator/envelope evidence remains reusable when its source pins match. Build a fresh watchdog nonce/package and run a matching preflight after matching host execution passes. "
        "Require attributable watchdog evidence and verified restoration before full corrected-loader execution; require full execution before passive snapshots/peripheral work.\n\n"
        "Rollback: restore the exact source before bytes in loader-contract-correction/20261114T233200428604Z and this review packet's document before copies; "
        "retain every old source/result/failed bank and run matching host checks before reuse. No device operation occurred while recording this review.\n")
    replacements["docs/PHASE-4-DEVICE-PATH.md"] = guide
    note = (f"\n\n## P4-025 — Early exception context and hardware readiness review ({packet.name})\n\n"
        "Purpose/files: entry.S establishes vectors, a physical stack, cleared BSS and saved firmware context before SCTLR/cache changes. "
        "qemu_firmware.S and phase4-qemu-device-path.py inject a BRK into that first transition instruction in a test Image, with incoming I-cache enabled. "
        "Require exact PC/SP, saved firmware registers, syndrome and unchanged arena at all three placements. phase4-device-cycle.py requires all 63 cases. "
        "phase4-record-loader-correction.py and phase4-record-watchdog-review.py retain the change and distinguish the restored UUID from a later independently verified baseline boot. "
        "Synchronize README.md, STATE.md, INDEX.md, PHASE-4-DEVICE-PATH.md and state.json. Indexed source before copies are in loader-contract-correction/20261114T233200428604Z; this packet retains document before/after bytes.\n\n"
        f"Verification: {status} Original measured probe banks replayed with equal nonce/CRC-checked entry fields. "
        f"Trial `{args.trial}` wrote/readback verified the candidate and returned to recovery, but acquired no attributable Phase 4 envelope. "
        f"Baseline restoration/readback/root/boot UUID and unchanged recovery/DTBO/staging checks passed; subsequent inventory `{args.inventory}` passed. "
        "The exception-context correction is not proof of the missing-record cause. "
        "Loader entry/watchdog reset/persistence and every real peripheral gate remain unverified. No device operation occurred during this recorder.\n\n"
        "Limitations/rollback: retain the consumed trial nonce and original failed outputs privately. Restore indexed source/document before bytes to undo the correction, "
        "rebuild matching source-pin prerequisites and a new hardware nonce, and use the independent pinned-baseline recovery guide after any attempted candidate write. "
        "Never mark Phase 4 complete from host validation.\n")
    replacements["docs/IMPLEMENTATION-LOG.md"] = (PROJECT / "docs/IMPLEMENTATION-LOG.md").read_text(encoding="utf-8") + note
    documents(packet, replacements)
    index_packet(packet)
    print(json.dumps({"packet": packet.relative_to(PROJECT).as_posix(), "recorded": True, "host_ready": host_ready}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
