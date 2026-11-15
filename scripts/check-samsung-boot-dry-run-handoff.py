#!/usr/bin/env python3
"""Read-only P2-019 handoff, evidence, documentation and regression checker."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
from typing import Any


sys.dont_write_bytecode = True
PROJECT = Path(__file__).resolve().parents[1]
WORKSPACE = PROJECT.parent

FOLDER = "evidence/phase-2/samsung-boot-dry-run/20261112T010401492946Z"
REPORT = FOLDER + "/report.json"
INDEX = FOLDER + "/index.json"
REPORT_SHA256 = "ab636baa11543a6da7fce252baa835547f72eb39c3c863cebee251a2607bfd02"
INDEX_SHA256 = "34007a50202a11667e0646875f6baf8de3a68f9fb53388764d78a3083f79ffbd"
CANDIDATE_SHA256 = "73d88c699dda238238b7b2b1105caea248b9ef3aef282a3f01b566f0fd894a58"

TEMPLATE = "everline-ksu/artifacts/A51-PixelOS-Everline-KernelSU-Next-boot.img"
TEMPLATE_PIN = {"bytes": 61_865_984, "sha256": "eb30609a62999e3282ac81e0a5e56411ef12ec1a39c107171bf3e01209c7cb67"}
KERNEL = "evidence/phase-2/early-entry-kernel/20261111T163522918342Z/Image"
KERNEL_PIN = {"bytes": 36_334_080, "sha256": "87c0401361d4503afb0b266b15ff0caf1e64f505d61d53be700e8b6c6d8e9cf6"}
REPACK = "everline-ksu/artifacts/repack-validation.json"
REPACK_PIN = {"bytes": 1_911, "sha256": "2ced1959920eb5a1daf1343c89b36c40caf1a3d7d419a73957385597c8e8712b"}

RUNS = {
    "capture": "runs/20261112T010359925342Z-phase2-samsung-boot-dry-run-capture-hardened-3/metadata.json",
    "core_windows": "runs/20261112T005453932895Z-phase2-samsung-boot-dry-run-tests-hardened-windows/metadata.json",
    "core_wsl": "runs/20261112T005748242395Z-phase2-samsung-boot-dry-run-tests-hardened-wsl/metadata.json",
    "replay_windows": "runs/20261112T010409189329Z-phase2-samsung-boot-dry-run-replay-final-windows/metadata.json",
    "guards_windows": "runs/20261112T010456977064Z-phase2-samsung-boot-dry-run-evidence-guards-final-windows/metadata.json",
    "replay_wsl": "runs/20261112T010514159526Z-phase2-samsung-boot-dry-run-replay-final-wsl/metadata.json",
    "guards_wsl": "runs/20261112T010532637885Z-phase2-samsung-boot-dry-run-evidence-guards-final-wsl/metadata.json",
}

FAILED_RUNS = {
    "boot_id_formula": (
        "runs/20261111T180424005604Z-phase2-samsung-boot-dry-run-tests-windows/metadata.json",
        "template Android boot identifier is stale or malformed",
    ),
    "avb_expectation": (
        "runs/20261111T180515402338Z-phase2-samsung-boot-dry-run-tests-windows-2/metadata.json",
        "kernel substitution unexpectedly retained the old AVB digest",
    ),
    "windows_depth_fixture": (
        "runs/20261112T005524061821Z-phase2-samsung-boot-dry-run-evidence-guards-windows/metadata.json",
        "tree_depth_limit: wrong rejection: evidence directory set differs",
    ),
    "wsl_lstat_recursion": (
        "runs/20261112T005822893860Z-phase2-samsung-boot-dry-run-evidence-guards-wsl/metadata.json",
        "RecursionError: maximum recursion depth exceeded",
    ),
}

FLAGS = {
    "full_image_emitted": False,
    "candidate_bytes_retained": False,
    "installable_image_created": False,
    "phone_queries": False,
    "phone_writes": False,
    "flashing": False,
    "repartitioning": False,
    "reboot": False,
    "a51_payload_execution_verified": False,
    "standalone_execution_verified": False,
    "physical_handoff_verified": False,
    "persistent_fault_logging_verified": False,
    "fault_return_verified": False,
    "a51_return_verified": False,
    "phase_2_device_gate_passed": False,
}

FACTS = {
    "template_bytes": 61_865_984,
    "kernel_bytes": 36_334_080,
    "kernel_runtime_bytes": 47_362_048,
    "kernel_slot_bytes": 36_335_616,
    "boot_page_size": 2_048,
    "candidate_bytes": 61_865_984,
    "candidate_sha256": CANDIDATE_SHA256,
    "android_boot_id_sha1": "e8c00ec632687d9a8ba6099dc847448220ee9155",
    "changed_regions": 4,
    "indexed_files": 7,
    "indexed_bytes": 58_533,
    "core_tests_per_host": 11,
    "evidence_guards_per_host": 30,
    "verified_hosts": ["windows", "wsl"],
    "verification_runs": 7,
    "failed_runs_preserved": 4,
}

LIMITATIONS = [
    "in_memory_host_reconstruction_only_no_candidate_bytes_retained",
    "unsigned_avb_algorithm_zero_does_not_establish_complete_device_policy",
    "no_odin_archive_or_installable_image_created",
    "no_samsung_firmware_entry_or_a51_execution",
    "no_exception_watchdog_persistent_fault_log_or_return",
    "prior_device_boot_test_applies_only_to_android_template_kernel",
    "phase_2_device_gate_unpassed",
]


def load(name: str, filename: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, PROJECT / "scripts" / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load " + filename)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def check_failed(previous: Any, relative: str, marker: str) -> None:
    metadata_path = previous.project_file(relative, "failed.metadata")
    metadata = previous.read_json(metadata_path, "failed.metadata")
    previous.exact(metadata,
        {"schema_version", "run_id", "label", "cwd", "command", "started", "status", "exit_code", "finished"},
        "failed.metadata")
    previous.require(metadata["schema_version"] == 1
                     and metadata["run_id"] == metadata_path.parent.name
                     and metadata["status"] == "failed"
                     and type(metadata["exit_code"]) is int and metadata["exit_code"] != 0,
                     "failed run identity/status changed: " + relative)
    previous.require(Path(metadata["cwd"]).resolve() == PROJECT.resolve(),
                     "failed run cwd changed: " + relative)
    previous.require(marker in previous.read_text(metadata_path.parent / "output.log", "failed.output"),
                     "failed run diagnostic changed: " + relative)


def main() -> int:
    try:
        previous = load("p2019_previous_handoff", "check-phase2-entry-handoff.py")
        inherited_output = io.StringIO()
        with contextlib.redirect_stdout(inherited_output):
            previous.require(previous.main() == 0, "P2-017/P2-018 handoff regression failed")
        inherited = json.loads(inherited_output.getvalue().splitlines()[-1])

        state = previous.read_json(PROJECT / "state.json", "state")
        validation = previous.exact(state.get("phase_2_samsung_boot_dry_run_validation"),
            {"scope", "status", "selected_evidence", "verification_runs", "failed_runs",
             "flags", "facts", "limitations", "documentation_consistency",
             "documentation_consistency_run", "documentation_consistency_counts"},
            "state.phase_2_samsung_boot_dry_run_validation")
        selected = {
            "folder": FOLDER,
            "report": REPORT,
            "report_sha256": REPORT_SHA256,
            "index": INDEX,
            "index_sha256": INDEX_SHA256,
            "template": TEMPLATE,
            "template_pin": TEMPLATE_PIN,
            "kernel": KERNEL,
            "kernel_pin": KERNEL_PIN,
            "prior_repack_record": REPACK,
            "prior_repack_record_pin": REPACK_PIN,
        }
        expected_failed = {key: value[0] for key, value in FAILED_RUNS.items()}
        previous.require(validation["scope"] == "retained_a51_android_v2_unsigned_avb_in_memory_reconstruction"
                         and validation["status"] == "verified_host_only"
                         and validation["selected_evidence"] == selected
                         and validation["verification_runs"] == RUNS
                         and validation["failed_runs"] == expected_failed
                         and validation["flags"] == FLAGS
                         and validation["facts"] == FACTS
                         and validation["limitations"] == LIMITATIONS,
                         "P2-019 state values differ from selected evidence")

        previous.require(state.get("updated_date_local") == "2026-11-12"
                         and state.get("phase_1_status") == "complete"
                         and state.get("phase_2_status") == "in_progress"
                         and state.get("phase_2_device_gate_passed") is False,
                         "phase decision or update date changed")
        selection = state.get("phase_2_evidence_selection")
        previous.require(type(selection) is dict
                         and selection.get("samsung_boot_dry_run_report") == REPORT
                         and selection.get("samsung_boot_dry_run_report_sha256") == REPORT_SHA256
                         and selection.get("samsung_boot_dry_run_index") == INDEX
                         and selection.get("samsung_boot_dry_run_index_sha256") == INDEX_SHA256,
                         "aggregate P2-019 evidence selection changed")
        evidence = state.get("evidence")
        required_evidence = {REPORT, INDEX, *RUNS.values(), *(value[0] for value in FAILED_RUNS.values())}
        previous.require(type(evidence) is list and required_evidence <= set(evidence),
                         "state evidence list omits P2-019 records")

        previous.require(previous.pin(PROJECT / REPORT) == {"bytes": 5_281, "sha256": REPORT_SHA256}
                         and previous.pin(PROJECT / INDEX) == {"bytes": 1_349, "sha256": INDEX_SHA256},
                         "selected report/index pin changed")
        previous.require(previous.pin(WORKSPACE / TEMPLATE) == TEMPLATE_PIN
                         and previous.pin(PROJECT / KERNEL) == KERNEL_PIN
                         and previous.pin(WORKSPACE / REPACK) == REPACK_PIN,
                         "P2-019 live input pin changed")

        verifier = load("p2019_packet_verifier", "verify-samsung-boot-dry-run.py")
        replay = verifier.verify_packet(PROJECT / FOLDER)
        expected_replay = {
            "status": "passed", "evidence": FOLDER, "indexed_files": 7,
            "indexed_bytes": 58_533, "candidate_sha256": CANDIDATE_SHA256,
            "changed_regions": 4, "full_image_emitted": False,
            "candidate_bytes_retained": False, "phone_writes": False,
            "phase_2_device_gate_passed": False,
        }
        previous.require(replay == expected_replay, "P2-019 semantic replay changed")

        commands = {
            "capture": ["python", ".\\scripts\\capture-samsung-boot-dry-run.py"],
            "core_windows": ["python", ".\\scripts\\test-samsung-boot-dry-run.py"],
            "core_wsl": ["wsl.exe", "-d", "A51-KernelBuilder", "--", "python3", "-B",
                         "/mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/test-samsung-boot-dry-run.py"],
            "replay_windows": ["python", ".\\scripts\\verify-samsung-boot-dry-run.py",
                               ".\\evidence\\phase-2\\samsung-boot-dry-run\\20261112T010401492946Z"],
            "guards_windows": ["python", ".\\scripts\\test-samsung-boot-dry-run-evidence.py",
                               ".\\evidence\\phase-2\\samsung-boot-dry-run\\20261112T010401492946Z"],
            "replay_wsl": ["wsl.exe", "-d", "A51-KernelBuilder", "--", "python3", "-B",
                           "/mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/verify-samsung-boot-dry-run.py",
                           "/mnt/c/Users/Ankit/Desktop/A51/hakios-a51/evidence/phase-2/samsung-boot-dry-run/20261112T010401492946Z"],
            "guards_wsl": ["wsl.exe", "-d", "A51-KernelBuilder", "--", "python3", "-B",
                           "/mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/test-samsung-boot-dry-run-evidence.py",
                           "/mnt/c/Users/Ankit/Desktop/A51/hakios-a51/evidence/phase-2/samsung-boot-dry-run/20261112T010401492946Z"],
        }
        outputs: dict[str, str] = {}
        for role, relative in RUNS.items():
            scripts = ("samsung_boot_dry_run.py",)
            if role == "capture":
                scripts += ("capture-samsung-boot-dry-run.py",)
            elif role.startswith("core_"):
                scripts += ("test-samsung-boot-dry-run.py",)
            elif role.startswith("replay_"):
                scripts += ("verify-samsung-boot-dry-run.py",)
            else:
                scripts += ("verify-samsung-boot-dry-run.py", "test-samsung-boot-dry-run-evidence.py")
            _, outputs[role] = previous.check_run(relative, commands[role], scripts)

        capture_expected = {
            "candidate_sha256": CANDIDATE_SHA256, "changed_regions": 4,
            "evidence": FOLDER, "full_image_emitted": False,
            "phase_2_device_gate_passed": False, "phone_writes": False, "status": "passed",
        }
        previous.require(previous.trailing_json(outputs["capture"], "capture.output") == capture_expected,
                         "capture output changed")
        for role in ("replay_windows", "replay_wsl"):
            previous.require(previous.trailing_json(outputs[role], role + ".output") == expected_replay,
                             "replay output changed: " + role)
        for role in ("core_windows", "core_wsl"):
            lines = outputs[role].splitlines()
            previous.require(sum(line.startswith("PASS ") for line in lines) == 11
                             and "SAMSUNG_BOOT_DRY_RUN_TESTS cases=11 result=PASS full_image_emitted=0 phone_writes=0 device_gate=0" in lines,
                             "core test result changed: " + role)
        for role in ("guards_windows", "guards_wsl"):
            lines = outputs[role].splitlines()
            previous.require(sum(line.startswith("PASS ") for line in lines) == 30
                             and "SAMSUNG_BOOT_DRY_RUN_EVIDENCE_TESTS cases=30 result=PASS full_image_emitted=0 phone_writes=0 device_gate=0" in lines,
                             "evidence guard result changed: " + role)

        for relative, marker in FAILED_RUNS.values():
            check_failed(previous, relative, marker)
        evidence_root = PROJECT / "evidence/phase-2/samsung-boot-dry-run"
        previous.require(not any(path.is_file() and path.suffix.lower() == ".img"
                                 for path in evidence_root.rglob("*")),
                         "P2-019 evidence unexpectedly contains an image")

        guide = previous.read_text(PROJECT / "docs/SAMSUNG-BOOT-DRY-RUN.md", "docs.P2-019")
        guide_markers = ["P2-019", FOLDER, REPORT_SHA256, INDEX_SHA256, CANDIDATE_SHA256,
                         "58,533", "four regions", "No candidate boot image was emitted",
                         *[Path(value).parent.name for value in RUNS.values()],
                         *[Path(value[0]).parent.name for value in FAILED_RUNS.values()]]
        for marker in guide_markers:
            previous.require(marker in guide, "P2-019 guide missing marker: " + marker)

        integration = [
            PROJECT / "README.md", PROJECT / "docs/STATE.md", PROJECT / "docs/INDEX.md",
            PROJECT / "docs/HANDOFF.md", PROJECT / "docs/BUILD.md", PROJECT / "docs/FILE-MAP.md",
            PROJECT / "docs/ARCHITECTURE.md", PROJECT / "docs/EARLY-ENTRY.md",
            PROJECT / "docs/ENTRY-CONTRACT.md", PROJECT / "docs/IMPLEMENTATION-LOG.md",
            WORKSPACE / "hakios-assessment/ROADMAP.md",
        ]
        for document in integration:
            contents = previous.read_text(document, "integration." + document.name)
            previous.require("SAMSUNG-BOOT-DRY-RUN.md" in contents and "P2-019" in contents
                             and CANDIDATE_SHA256 in contents,
                             "integration document missing P2-019 markers: " + str(document))

        result = {
            **inherited,
            "passed": True,
            "samsung_boot_dry_run_indexed_files": 7,
            "samsung_boot_dry_run_indexed_bytes": 58_533,
            "samsung_boot_dry_run_candidate_bytes": 61_865_984,
            "samsung_boot_dry_run_changed_regions": 4,
            "samsung_boot_dry_run_core_tests_per_host": 11,
            "samsung_boot_dry_run_guards_per_host": 30,
            "samsung_boot_dry_run_verification_runs": 7,
            "samsung_boot_dry_run_failed_runs_preserved": 4,
            "samsung_boot_dry_run_full_image_emitted": False,
            "samsung_boot_dry_run_candidate_bytes_retained": False,
            "samsung_boot_dry_run_installable_image_created": False,
            "phase_2_device_gate_passed": False,
            "standalone_execution_verified": False,
            "persistent_fault_logging_verified": False,
            "fault_return_verified": False,
            "a51_return_verified": False,
        }

        consistency = validation["documentation_consistency"]
        if consistency == "pending":
            previous.require(validation["documentation_consistency_run"] is None
                             and validation["documentation_consistency_counts"] is None,
                             "pending documentation consistency has selected output")
        else:
            previous.require(consistency == "verified", "invalid documentation consistency state")
            relative = validation["documentation_consistency_run"]
            run_path = previous.project_file(relative, "documentation.metadata")
            metadata = previous.read_json(run_path, "documentation.metadata")
            previous.require(metadata["status"] == "passed" and metadata["exit_code"] == 0
                             and metadata["command"] == ["python", "scripts/check-samsung-boot-dry-run-handoff.py"],
                             "selected documentation checker run changed")
            recorded = previous.trailing_json(
                previous.read_text(run_path.parent / "output.log", "documentation.output"),
                "documentation.output")
            previous.require(recorded == validation["documentation_consistency_counts"]
                             and recorded == result,
                             "selected documentation checker result changed")
            previous.require(previous.pin(run_path.parent / "project-scripts/check-samsung-boot-dry-run-handoff.py")
                             == previous.pin(Path(__file__)),
                             "selected documentation checker source changed")

        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:  # Keep a single stable rejection prefix for handoff automation.
        print("SAMSUNG_BOOT_DRY_RUN_HANDOFF_REJECTED: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
