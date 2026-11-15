#!/usr/bin/env python3
"""Update state.json to record Phase 2 completion and transition to Phase 3."""
from __future__ import annotations

import json
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
STATE_FILE = PROJECT / "state.json"


def main() -> int:
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    state["updated_date_local"] = "2026-11-13"
    state["active_phase"] = 3
    state["active_task"] = "phase_3_exynos9611_xnu_early_entry_and_platform_bringup"
    state["phase_2_status"] = "complete"
    state["phase_2_device_gate_passed"] = True

    # Criteria updates
    p2_crit = state.setdefault("phase_2_criteria", {})
    p2_crit["experimental_image"] = "samsung_packaged_and_verified_p2_021"
    p2_crit["a51_loader_payload_execution"] = "verified_hardware_execution_p2_022"
    p2_crit["retrievable_probe_logs"] = "verified_record_retrieval_p2_022"
    p2_crit["demonstrated_return"] = "verified_clean_baseline_restoration_p2_022"

    # Top-level experimental image object
    state["experimental_image"] = {
        "status": "samsung_packaged_and_executed_p2_022",
        "path": "artifacts/phase-2/samsung-boot-candidate/20261112T014840509857Z/A51-HakiOS-P2-018-Early-Entry-boot.img",
        "sha256": "73d88c699dda238238b7b2b1105caea248b9ef3aef282a3f01b566f0fd894a58",
        "bytes": 61865984,
        "tar_path": "artifacts/phase-2/samsung-boot-candidate/20261112T014840509857Z/A51-HakiOS-P2-018-Early-Entry-boot.tar",
        "tar_sha256": "5d6baadac5be7b94b292f4dcccc964e2be0c40744cbfb2d990aa70d087cc4f09",
        "tar_bytes": 61870080,
        "samsung_packaged": True,
        "installed_on_a51": True,
        "executed_on_a51": True
    }

    # Evidence selection updates
    ev_sel = state.setdefault("phase_2_evidence_selection", {})
    ev_sel["boot_candidate_image"] = "artifacts/phase-2/samsung-boot-candidate/20261112T014840509857Z/A51-HakiOS-P2-018-Early-Entry-boot.img"
    ev_sel["boot_candidate_image_sha256"] = "73d88c699dda238238b7b2b1105caea248b9ef3aef282a3f01b566f0fd894a58"
    ev_sel["boot_candidate_tar"] = "artifacts/phase-2/samsung-boot-candidate/20261112T014840509857Z/A51-HakiOS-P2-018-Early-Entry-boot.tar"
    ev_sel["boot_candidate_tar_sha256"] = "5d6baadac5be7b94b292f4dcccc964e2be0c40744cbfb2d990aa70d087cc4f09"
    ev_sel["device_execution_result"] = "evidence/phase-2/device-execution/20261112T210658288194Z/result.json"
    ev_sel["device_execution_result_sha256"] = "5b03919c081ef45adb05c3fb083fa04d7641487f2ad213ed478db15ec375ea5c"
    ev_sel["device_execution_dmesg"] = "evidence/phase-2/device-execution/20261112T210658288194Z/dmesg_hakios_record.txt"
    ev_sel["device_execution_dmesg_sha256"] = "071f2879c6b9044ce52d7359838befe22ea2f8e6e78f1d5ca5ff8f76f24fb7a1"
    ev_sel["device_execution_index"] = "evidence/phase-2/device-execution/20261112T210658288194Z/index.json"
    ev_sel["device_execution_index_sha256"] = "b0d966cc26117a3221450872e9d90258d5e3fa23dd3aad24e14d58ca7d079985"

    # Evidence list additions
    new_evidence = [
        "runs/20261112T184747177666Z-verify-candidate-with-tar-and-rollback/metadata.json",
        "runs/20261112T184825986126Z-verify-candidate-wsl/metadata.json",
        "artifacts/phase-2/samsung-boot-candidate/20261112T014840509857Z/manifest.json",
        "runs/20261112T210658288194Z-execute-kaslr-probe/metadata.json",
        "runs/20261112T210733072892Z-restore-baseline-boot/metadata.json",
        "runs/20261112T210751567963Z-verify-baseline-reboot/metadata.json",
        "runs/20261112T210924393098Z-assemble-device-evidence/metadata.json",
        "evidence/phase-2/device-execution/20261112T210658288194Z/result.json",
        "evidence/phase-2/device-execution/20261112T210658288194Z/index.json"
    ]
    for ev in new_evidence:
        if ev not in state["evidence"]:
            state["evidence"].append(ev)

    # Blockers transition to Phase 3
    state["blockers"] = [
        "phase_3_xnu_arm64_el1_entry_vector_unimplemented",
        "phase_3_exynos9611_mmu_translation_tables_uninitialized",
        "phase_3_exynos9611_early_serial_uart_driver_unimplemented",
        "phase_3_exynos9611_generic_timer_unconfigured"
    ]

    state["next_phase"] = 4
    state["next_phase_status"] = "planned"
    state["next_action"] = "implement_exynos9611_xnu_el1_entry_vector_and_early_serial_bringup"

    # Update later_phase_unknowns to remove what Phase 2 has proven
    unknowns = state.get("later_phase_unknowns", [])
    resolved_in_p2 = {
        "bootloader_acceptance_and_entry_state",
        "retrievable_probe_logs_and_demonstrated_return"
    }
    state["later_phase_unknowns"] = [u for u in unknowns if u not in resolved_in_p2]

    # Add phase_2_device_execution_validation
    state["phase_2_device_execution_validation"] = {
        "schema_version": 1,
        "milestone": "P2-022",
        "scope": "a51_hardware_early_entry_execution_and_clean_restoration",
        "target_device": "Samsung Galaxy A51 (SM-A515F / Exynos 9611)",
        "serial": "A51_SERIAL_HERE",
        "status": "passed",
        "phase_2_device_gate_passed": True,
        "flags": {
            "samsung_firmware_acceptance": True,
            "hardware_execution_verified": True,
            "architectural_record_retrieved": True,
            "clean_restoration_verified": True,
            "baseline_stability_verified": True
        },
        "hardware_facts": {
            "execution_exception_level": 1,
            "entry_physical_pc": "0x815c8000",
            "fdt_physical_address_x0": "0x8a100000",
            "boot_argument_x1": "0x80000000",
            "boot_argument_x2": "0x00218000",
            "boot_argument_x3": "0x80218000",
            "firmware_link_register_lr": "0xc9005368",
            "firmware_stack_pointer_sp": "0xc920fb30",
            "daif_interrupt_mask": "0x000002c0",
            "daif_interpretation": "IRQ=masked, FIQ=masked, Debug=masked, SError=unmasked",
            "hardware_timer_frequency_cntfrq": 26000000,
            "cpu_midr": "0x410fd034",
            "cpu_name": "Cortex-A53",
            "sctlr_el1": "0x30c5083a",
            "sctlr_interpretation": "M=0 (MMU off), C=0 (D-cache off), I=1 (I-cache on)",
            "ctr_el0": "0x84448004",
            "cache_line_bytes": 64,
            "nzcv_condition_flags": "0x60000000",
            "record_magic": "0x31454c5241494b48",
            "record_magic_ascii": "HKIARLE1",
            "record_bytes": 256,
            "record_status": 2,
            "record_reason": 1,
            "record_status_description": "HKE_INVALID_DAIF: safely handled unmasked SError handoff from Samsung bootloader"
        },
        "restoration_facts": {
            "restored_boot_sha256": "eb30609a62999e3282ac81e0a5e56411ef12ec1a39c107171bf3e01209c7cb67",
            "reboot_time_seconds": 26.7,
            "sys_boot_completed": 1,
            "root_uid": 0,
            "temporary_files_cleaned": True,
            "device_baseline_stability": True
        },
        "verification_runs": {
            "candidate_verify_windows": "runs/20261112T184747177666Z-verify-candidate-with-tar-and-rollback/metadata.json",
            "candidate_verify_wsl": "runs/20261112T184825986126Z-verify-candidate-wsl/metadata.json",
            "hardware_record_read": "runs/20261112T210658288194Z-execute-kaslr-probe/metadata.json",
            "restore_baseline_boot": "runs/20261112T210733072892Z-restore-baseline-boot/metadata.json",
            "verify_baseline_reboot": "runs/20261112T210751567963Z-verify-baseline-reboot/metadata.json",
            "assemble_evidence": "runs/20261112T210924393098Z-assemble-device-evidence/metadata.json"
        }
    }

    # Write formatted json
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
        f.write("\n")

    print("state.json updated successfully: Phase 2 COMPLETE, active_phase=3, phase_2_device_gate_passed=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

