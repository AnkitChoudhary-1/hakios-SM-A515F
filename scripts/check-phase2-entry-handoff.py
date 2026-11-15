#!/usr/bin/env python3
"""Read-only P2-017/P2-018 handoff, documentation, and baseline checker.

This checker replays only retained evidence.  It never invokes ADB, QEMU, a
compiler, WSL, or a phone, and it does not treat host builds as device proof.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat
import sys
from typing import Any, Iterable
from urllib.parse import unquote


sys.dont_write_bytecode = True
PROJECT = Path(__file__).resolve().parents[1]
WORKSPACE = PROJECT.parent
SCRIPTS = PROJECT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
MAX_JSON = 32 * 1024 * 1024
MAX_TEXT = 32 * 1024 * 1024
HEX256 = re.compile(r"[0-9a-f]{64}\Z")

CPU_FOLDER = "evidence/phase-2/cpu-state-device/20261111T155948363876Z"
CPU_RESULT = CPU_FOLDER + "/result.json"
CPU_INDEX = CPU_FOLDER + "/index.json"
CPU_MODULE = CPU_FOLDER + "/hakios_cpu_state.ko"
CPU_RESULT_SHA256 = "6b6bcae092f51def03aa8b252e529eac644d59fb686798fec14c19fbc0078099"
CPU_INDEX_SHA256 = "d8e663eba2d438c8b9eb732df090271e8aa4a00821205784446bb1e74abe77bc"
CPU_MODULE_SHA256 = "617c830f970e21be9fa0a96b3a1e1fd67853a2f2c31dc292897aa3abbcc43280"

HOST_RESULT = "evidence/phase-2/early-entry-host/20261111T162536291908Z/result.json"
PREPARE_RESULT = "evidence/phase-2/early-entry-prepare/20261111T163522918342Z/result.json"
ADAPTATION_PATCH = "evidence/phase-2/early-entry-prepare/20261111T163522918342Z/early-entry.patch"
KERNEL_RESULT = "evidence/phase-2/early-entry-kernel/20261111T163522918342Z/result.json"
KERNEL_INDEX = "evidence/phase-2/early-entry-kernel/20261111T163522918342Z/index.json"
KERNEL_IMAGE = "evidence/phase-2/early-entry-kernel/20261111T163522918342Z/Image"
HOST_RESULT_SHA256 = "379f5c2a450632052fcb251575277151cbfef382bf1f59b984a157e4c4c23d4c"
PREPARE_RESULT_SHA256 = "557c6c90f306fbfc6b7219ffa5f570f4639daad12a107e364d21b3f3b14bd0ab"
ADAPTATION_PATCH_SHA256 = "bb958f092d82f5b1d5b81761d5198d2a8bf0e80657ecc48a02d27b6e207f409f"
KERNEL_RESULT_SHA256 = "5bbe01ecdfab1364cc9a0db05753fcc986fbe9a7e053469e899d02d8f44c7049"
KERNEL_INDEX_SHA256 = "60fef1b76fff189e256528a900c4b9afa31875c152f57f7ade6dbb7d388fb4f6"
KERNEL_IMAGE_SHA256 = "87c0401361d4503afb0b266b15ff0caf1e64f505d61d53be700e8b6c6d8e9cf6"

CPU_RUNS = {
    "replay_windows": "runs/20261111T161422753796Z-phase2-cpu-state-final-replay-windows/metadata.json",
    "replay_wsl": "runs/20261111T161422553413Z-phase2-cpu-state-final-replay-wsl/metadata.json",
    "guards_windows": "runs/20261111T161423017545Z-phase2-cpu-state-evidence-guards/metadata.json",
}
EARLY_RUNS = {
    "evidence_windows": "runs/20261111T172248699374Z-phase2-early-entry-evidence-final-windows/metadata.json",
    "corruption_windows": "runs/20261111T172248517634Z-phase2-early-entry-corruption-final-windows/metadata.json",
    "evidence_wsl": "runs/20261111T172248928798Z-phase2-early-entry-evidence-final-wsl/metadata.json",
    "corruption_wsl": "runs/20261111T172249251195Z-phase2-early-entry-corruption-final-wsl/metadata.json",
}

CPU_FLAGS = {
    "phone_queries": True,
    "phone_temporary_write": True,
    "module_load_unload_verified": True,
    "per_cpu_capture_verified": True,
    "same_android_boot_verified": True,
    "temporary_file_absent": True,
    "architectural_register_writes": False,
    "standalone_payload_execution": False,
    "physical_handoff_verified": False,
    "fault_return_verified": False,
    "phase_2_device_gate_passed": False,
}
EARLY_FLAGS = {
    "phone_queries": False,
    "phone_writes": False,
    "a51_payload_execution_verified": False,
    "standalone_execution_verified": False,
    "physical_handoff_verified": False,
    "persistent_fault_logging_verified": False,
    "fault_return_verified": False,
    "a51_return_verified": False,
    "phase_2_device_gate_passed": False,
}
CPU_LIMITATIONS = [
    "linux_callback_state_only",
    "firmware_and_pre_linux_entry_state_unknown",
    "standalone_handoff_fault_recovery_and_return_not_verified",
]
EARLY_LIMITATIONS = [
    "host_and_qemu_only_no_a51_execution",
    "no_standalone_hakios_or_xnu_launch",
    "no_experimental_samsung_boot_image_or_device_installation",
    "no_android_or_recovery_return",
    "no_independent_watchdog_exception_vector_or_persistent_fault_logger",
    "host_prepare_packets_lack_full_indexes_and_qemu_bins_vmlinux_are_not_fully_retained",
    "copied_output_tree_is_not_a_clean_rebuild",
    "unsupported_el_and_oversized_ctr_paths_lack_executed_coverage",
]
FORBIDDEN_TRUE_KEYS = {
    "a51_xnu_boot_verified",
    "no_flash_a51_launch_verified",
    "phase_2_device_gate_passed",
    "a51_payload_execution_verified",
    "standalone_execution_verified",
    "standalone_payload_execution",
    "physical_handoff_verified",
    "persistent_fault_logging_verified",
    "fault_return_verified",
    "a51_return_verified",
}


class HandoffError(ValueError):
    """Current handoff state is inconsistent with retained evidence."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise HandoffError(message)


def exact(value: Any, keys: Iterable[str], where: str) -> dict[str, Any]:
    expected = set(keys)
    require(type(value) is dict, where + ": object required")
    require(set(value) == expected,
            f"{where}: fields differ (missing={sorted(expected - set(value))}, extra={sorted(set(value) - expected)})")
    return value


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        require(type(key) is str and key not in result, "duplicate or non-text JSON key")
        result[key] = value
    return result


def _constant(value: str) -> Any:
    raise HandoffError("non-finite JSON rejected: " + value)


def regular(path: Path, where: str, maximum: int | None = None) -> int:
    try:
        info = path.lstat()
    except OSError as exc:
        raise HandoffError(where + ": missing or unreadable") from exc
    require(stat.S_ISREG(info.st_mode) and not path.is_symlink(), where + ": regular non-symlink file required")
    if maximum is not None:
        require(info.st_size <= maximum, where + ": file exceeds read bound")
    return info.st_size


def read_json(path: Path, where: str) -> Any:
    size = regular(path, where, MAX_JSON)
    data = path.read_bytes()
    require(len(data) == size, where + ": concurrent or short read")
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant,
                          parse_float=lambda _: (_ for _ in ()).throw(HandoffError("JSON floats rejected")))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HandoffError(where + ": invalid UTF-8 JSON") from exc


def read_text(path: Path, where: str) -> str:
    size = regular(path, where, MAX_TEXT)
    data = path.read_bytes()
    require(len(data) == size, where + ": concurrent or short read")
    try:
        return data.decode("utf-8").replace("\x00", "")
    except UnicodeDecodeError as exc:
        raise HandoffError(where + ": invalid UTF-8") from exc


def digest(path: Path) -> str:
    regular(path, str(path))
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def relative_path(value: Any, where: str) -> str:
    require(type(value) is str and value and "\\" not in value and "\x00" not in value,
            where + ": canonical POSIX relative path required")
    parsed = PurePosixPath(value)
    require(not parsed.is_absolute() and str(parsed) == value and all(part not in ("", ".", "..") for part in parsed.parts),
            where + ": path is absolute, noncanonical, or traverses")
    return value


def project_file(value: Any, where: str) -> Path:
    relative = relative_path(value, where)
    path = PROJECT.joinpath(*PurePosixPath(relative).parts)
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(PROJECT.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise HandoffError(where + ": path missing or outside project") from exc
    regular(resolved, where)
    return resolved


def pin(path: Path) -> dict[str, Any]:
    return {"bytes": regular(path, str(path)), "sha256": digest(path)}


def load_module(name: str, filename: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, PROJECT / "scripts" / filename)
    require(spec is not None and spec.loader is not None, "cannot load verifier " + filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def timestamp(value: Any, where: str) -> dt.datetime:
    require(type(value) is str, where + ": timestamp text required")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HandoffError(where + ": invalid timestamp") from exc
    require(parsed.tzinfo is not None and parsed.utcoffset() is not None, where + ": timezone required")
    return parsed


def check_run(relative: str, command: list[str], scripts: tuple[str, ...]) -> tuple[dict[str, Any], str]:
    metadata_path = project_file(relative, "run.metadata")
    record = read_json(metadata_path, "run.metadata")
    exact(record, {"schema_version", "run_id", "label", "cwd", "command", "started", "status", "exit_code", "finished"}, "run.metadata")
    require(record["schema_version"] == 1 and record["run_id"] == metadata_path.parent.name,
            "run.metadata: identity mismatch")
    require(record["label"] == record["run_id"].split("Z-", 1)[1], "run.metadata: label mismatch")
    require(Path(record["cwd"]).resolve() == PROJECT.resolve(), "run.metadata: project cwd required")
    require(record["command"] == command, "run.metadata: command mismatch for " + relative)
    require(record["status"] == "passed" and type(record["exit_code"]) is int and record["exit_code"] == 0,
            "run.metadata: selected run did not pass")
    exact(record["started"], {"utc", "ist"}, "run.started")
    exact(record["finished"], {"utc", "ist"}, "run.finished")
    started_utc, started_ist = timestamp(record["started"]["utc"], "run.started.utc"), timestamp(record["started"]["ist"], "run.started.ist")
    finished_utc, finished_ist = timestamp(record["finished"]["utc"], "run.finished.utc"), timestamp(record["finished"]["ist"], "run.finished.ist")
    require(started_utc.utcoffset() == dt.timedelta(0) and started_ist.utcoffset() == dt.timedelta(hours=5, minutes=30)
            and finished_utc.utcoffset() == dt.timedelta(0) and finished_ist.utcoffset() == dt.timedelta(hours=5, minutes=30),
            "run.metadata: UTC/IST offsets mismatch")
    require(started_utc == started_ist and finished_utc == finished_ist and started_utc <= finished_utc,
            "run.metadata: timestamp pairs or order mismatch")
    for script in scripts:
        snapshot = metadata_path.parent / "project-scripts" / script
        require(digest(snapshot) == digest(PROJECT / "scripts" / script),
                "run.metadata: current script differs from selected snapshot: " + script)
    return record, read_text(metadata_path.parent / "output.log", "run.output")


def trailing_json(contents: str, where: str) -> Any:
    stripped = contents.rstrip()
    for match in reversed(list(re.finditer(r"(?m)^\{", stripped))):
        try:
            return json.loads(stripped[match.start():], object_pairs_hook=_pairs, parse_constant=_constant,
                              parse_float=lambda _: (_ for _ in ()).throw(HandoffError("JSON floats rejected")))
        except json.JSONDecodeError:
            continue
    raise HandoffError(where + ": no trailing JSON object")


def check_cpu_state(state: dict[str, Any]) -> dict[str, Any]:
    validation = exact(state.get("phase_2_cpu_state_validation"),
        {"scope", "status", "selected_evidence", "verification_runs", "flags", "facts", "limitations"},
        "state.phase_2_cpu_state_validation")
    selected = {
        "result": CPU_RESULT, "result_sha256": CPU_RESULT_SHA256,
        "index": CPU_INDEX, "index_sha256": CPU_INDEX_SHA256,
        "module": CPU_MODULE, "module_sha256": CPU_MODULE_SHA256,
    }
    facts = {
        "cpu_records": 8, "cpu_ids": list(range(8)), "current_el_encoding": 4,
        "decoded_exception_level": "EL1", "cntfrq_hz": 26_000_000,
        "little_cpu_ids": [0, 1, 2, 3], "little_cpu": "Cortex-A53",
        "big_cpu_ids": [4, 5, 6, 7], "big_cpu": "Cortex-A73",
        "sctlr_m_c_i_enabled": True, "indexed_files": 75, "indexed_bytes": 330_058,
        "corruptions_rejected": 8,
    }
    require(validation["scope"] == "android_capture_only_per_cpu_architectural_state"
            and validation["status"] == "verified_linux_callback_only", "CPU state scope/status mismatch")
    require(validation["selected_evidence"] == selected and validation["verification_runs"] == CPU_RUNS
            and validation["flags"] == CPU_FLAGS and validation["facts"] == facts
            and validation["limitations"] == CPU_LIMITATIONS, "CPU state validation schema/value mismatch")
    require(digest(project_file(CPU_RESULT, "cpu.result")) == CPU_RESULT_SHA256
            and digest(project_file(CPU_INDEX, "cpu.index")) == CPU_INDEX_SHA256
            and digest(project_file(CPU_MODULE, "cpu.module")) == CPU_MODULE_SHA256,
            "CPU selected packet pin drift")
    verifier = load_module("phase2_cpu_state_handoff_verifier", "test-cpu-state-device.py")
    replay = verifier.verify(PROJECT / CPU_FOLDER)
    require(replay["flags"] == CPU_FLAGS and len(replay["cpu_records"]) == 8 and replay["log_lines"] == 26,
            "CPU semantic replay mismatch")
    records = replay["cpu_records"]
    require([item["cpu"] for item in records] == list(range(8)) and {item["el"] for item in records} == {4}
            and {item["cntfrq"] for item in records} == {26_000_000}, "CPU identity/EL/timer mismatch")
    require([item["midr"] for item in records[:4]] == [0x410FD034] * 4
            and [item["midr"] for item in records[4:]] == [0x410FD092] * 4,
            "CPU Cortex-A53/A73 topology mismatch")
    require(all(item["sctlr"] & 0x1005 == 0x1005 for item in records), "CPU SCTLR M/C/I flags mismatch")
    index = read_json(PROJECT / CPU_INDEX, "cpu.index")
    require(type(index) is dict and type(index.get("files")) is dict and len(index["files"]) == 75
            and sum(item["size"] for item in index["files"].values()) == 330_058, "CPU index totals mismatch")

    expected_commands = {
        "replay_windows": ["python", "scripts/test-cpu-state-device.py", "--verify", CPU_FOLDER],
        "replay_wsl": ["wsl", "-d", "A51-KernelBuilder", "--exec", "python3",
            "/mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/test-cpu-state-device.py", "--verify",
            "/mnt/c/Users/Ankit/Desktop/A51/hakios-a51/" + CPU_FOLDER],
        "guards_windows": ["python", "scripts/test-cpu-state-evidence.py", "--packet", CPU_FOLDER],
    }
    outputs: dict[str, str] = {}
    for role, relative in CPU_RUNS.items():
        scripts = ("test-cpu-state-device.py", "capture-live-loader.py")
        if role == "guards_windows":
            scripts += ("test-cpu-state-evidence.py",)
        _, outputs[role] = check_run(relative, expected_commands[role], scripts)
    for role in ("replay_windows", "replay_wsl"):
        recorded = trailing_json(outputs[role], "cpu." + role)
        require(recorded == replay, "CPU replay output differs from current semantic replay: " + role)
    guard_line = outputs["guards_windows"].strip()
    match = re.fullmatch(r"CPU_STATE_EVIDENCE_GUARDS 8/8 rejected (evidence/phase-2/cpu-state-corruption/[0-9TZ]+)", guard_line)
    require(match is not None, "CPU guard output mismatch")
    guard_result = read_json(project_file(match.group(1) + "/result.json", "cpu.guard_result"), "cpu.guard_result")
    expected_cases = ["phase_promotion", "architectural_write_claim", "boolean_cpu", "forged_translation",
                      "arbitrary_command", "forged_remote_status", "different_module", "extra_file"]
    require(guard_result["original"] == CPU_FOLDER
            and guard_result["original_pin"] == {"size": 30185, "sha256": CPU_RESULT_SHA256}
            and guard_result["phone_operations"] is False
            and [item["case"] for item in guard_result["cases"]] == expected_cases
            and all(item["rejected"] is True for item in guard_result["cases"]), "CPU guard result mismatch")
    return {"records": len(records), "indexed_files": 75, "guard_rejections": 8}


def check_early_entry(state: dict[str, Any]) -> dict[str, Any]:
    validation = exact(state.get("phase_2_early_entry_validation"),
        {"scope", "status", "selected_evidence", "verification_runs", "flags", "facts", "limitations"},
        "state.phase_2_early_entry_validation")
    selected = {
        "host_result": HOST_RESULT, "host_result_sha256": HOST_RESULT_SHA256,
        "prepare_result": PREPARE_RESULT, "prepare_result_sha256": PREPARE_RESULT_SHA256,
        "adaptation_patch": ADAPTATION_PATCH, "adaptation_patch_sha256": ADAPTATION_PATCH_SHA256,
        "kernel_result": KERNEL_RESULT, "kernel_result_sha256": KERNEL_RESULT_SHA256,
        "kernel_index": KERNEL_INDEX, "kernel_index_sha256": KERNEL_INDEX_SHA256,
        "image": KERNEL_IMAGE, "image_sha256": KERNEL_IMAGE_SHA256, "image_bytes": 36_334_080,
    }
    facts = {
        "qemu_cases": 5, "qemu_checks": 228, "preparation_changed_files": 6,
        "kernel_symbols": 12, "initialized_record_bytes": 256, "entry_branches_verified": 2,
        "image_bytes": 36_334_080, "kernel_indexed_files": 23, "kernel_indexed_bytes": 60_298_894,
        "corruptions_rejected_per_host": 9,
    }
    require(validation["scope"] == "host_qemu_and_isolated_android_kernel_build"
            and validation["status"] == "verified_host_only", "early-entry scope/status mismatch")
    require(validation["selected_evidence"] == selected and validation["verification_runs"] == EARLY_RUNS
            and validation["flags"] == EARLY_FLAGS and validation["facts"] == facts
            and validation["limitations"] == EARLY_LIMITATIONS, "early-entry validation schema/value mismatch")
    for relative, expected in {
        HOST_RESULT: HOST_RESULT_SHA256, PREPARE_RESULT: PREPARE_RESULT_SHA256,
        ADAPTATION_PATCH: ADAPTATION_PATCH_SHA256, KERNEL_RESULT: KERNEL_RESULT_SHA256,
        KERNEL_INDEX: KERNEL_INDEX_SHA256, KERNEL_IMAGE: KERNEL_IMAGE_SHA256,
    }.items():
        require(digest(project_file(relative, "early.selected")) == expected, "early-entry selected pin drift: " + relative)

    verifier = load_module("phase2_early_entry_handoff_verifier", "early_entry_evidence.py")
    replay = verifier.verify_all(PROJECT / PurePosixPath(HOST_RESULT).parent,
                                 PROJECT / PurePosixPath(PREPARE_RESULT).parent,
                                 PROJECT / PurePosixPath(KERNEL_RESULT).parent)
    require(replay["host"]["cases"] == 5 and replay["host"]["checks"] == 228
            and replay["prepare"]["changed_files"] == 6 and replay["symbols"] == 12
            and replay["record_bytes_verified"] == 256 and replay["entry_branches_verified"] == 2
            and replay["image"] == {"bytes": 36_334_080, "sha256": KERNEL_IMAGE_SHA256},
            "early-entry semantic replay counts mismatch")
    for key in ("phase_2_device_gate_passed", "a51_payload_execution_verified", "a51_return_verified",
                "standalone_execution_verified", "persistent_fault_logging_verified"):
        require(replay[key] is False, "early-entry replay promoted gate: " + key)
    kernel_index = read_json(PROJECT / KERNEL_INDEX, "early.kernel_index")
    require(type(kernel_index.get("files")) is dict and len(kernel_index["files"]) == 23
            and sum(item["bytes"] for item in kernel_index["files"].values()) == 60_298_894,
            "early-entry kernel index totals mismatch")

    wsl_root = "/mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/"
    expected_commands = {
        "evidence_windows": ["python", "-B", "scripts/early_entry_evidence.py", "verify-all"],
        "corruption_windows": ["python", "-B", "scripts/test-early-entry-evidence.py"],
        "evidence_wsl": ["wsl.exe", "-d", "A51-KernelBuilder", "--", "python3", "-B",
                         wsl_root + "early_entry_evidence.py", "verify-all"],
        "corruption_wsl": ["wsl.exe", "-d", "A51-KernelBuilder", "--", "python3", "-B",
                           wsl_root + "test-early-entry-evidence.py"],
    }
    outputs: dict[str, str] = {}
    for role, relative in EARLY_RUNS.items():
        scripts = ("early_entry_evidence.py",)
        if role.startswith("corruption_"):
            scripts += ("test-early-entry-evidence.py",)
        _, outputs[role] = check_run(relative, expected_commands[role], scripts)
    for role in ("evidence_windows", "evidence_wsl"):
        require(trailing_json(outputs[role], "early." + role) == replay,
                "early-entry replay output differs from current semantic replay: " + role)
    corruption_expected = {"schema_version": 1, "status": "passed", "corruptions_rejected": 9,
        "retained_evidence_modified": False, "phone_queries": False, "phone_writes": False,
        "phase_2_device_gate_passed": False}
    required_lines = {"PASS copied_baseline", "PASS restored_baseline",
        "PASS corruption_rejected host_check_count", "PASS corruption_rejected duplicate_json_key",
        "PASS corruption_rejected nonfinite_json", "PASS corruption_rejected preparation_patch",
        "PASS corruption_rejected forged_device_gate", "PASS corruption_rejected bool_for_integer_symbol",
        "PASS corruption_rejected reindexed_initialized_record", "PASS corruption_rejected extra_reindexed_role",
        "PASS corruption_rejected index_traversal"}
    for role in ("corruption_windows", "corruption_wsl"):
        require(trailing_json(outputs[role], "early." + role) == corruption_expected,
                "early-entry corruption summary mismatch: " + role)
        require(required_lines <= set(outputs[role].splitlines()), "early-entry corruption markers missing: " + role)
    return {"qemu_cases": 5, "qemu_checks": 228, "symbols": 12,
            "record_bytes": 256, "guard_rejections": 18}


def check_aggregate_state(state: dict[str, Any]) -> None:
    require(state.get("schema_version") == 1 and state.get("active_phase") == 2,
            "state phase/schema mismatch")
    require(state.get("phase_1_status") == "complete" and state.get("phase_2_status") == "in_progress"
            and state.get("planned_phases") == list(range(3, 11)) and state.get("outstanding_phase_1_checks") == [],
            "state phase decision mismatch")
    for key in ("a51_xnu_boot_verified", "no_flash_a51_launch_verified", "phase_2_device_gate_passed"):
        require(state.get(key) is False, "state promoted unsupported gate: " + key)
    criteria = state.get("phase_2_criteria")
    require(type(criteria) is dict and criteria.get("a51_loader_payload_execution") == "not_attempted"
            and criteria.get("demonstrated_return") == "not_verified", "state device/return criteria mismatch")

    def walk(value: Any) -> None:
        if type(value) is dict:
            for key, child in value.items():
                if key in FORBIDDEN_TRUE_KEYS:
                    require(child is False, "state promoted unsupported nested gate: " + key)
                walk(child)
        elif type(value) is list:
            for child in value:
                walk(child)
    walk(state)

    selection = state.get("phase_2_evidence_selection")
    require(type(selection) is dict, "state.phase_2_evidence_selection missing")
    expected = {
        "cpu_state_result": CPU_RESULT, "cpu_state_result_sha256": CPU_RESULT_SHA256,
        "cpu_state_index_sha256": CPU_INDEX_SHA256,
        "early_entry_host_result": HOST_RESULT, "early_entry_host_result_sha256": HOST_RESULT_SHA256,
        "early_entry_prepare_result": PREPARE_RESULT, "early_entry_prepare_result_sha256": PREPARE_RESULT_SHA256,
        "early_entry_adaptation_patch": ADAPTATION_PATCH, "early_entry_adaptation_patch_sha256": ADAPTATION_PATCH_SHA256,
        "early_entry_kernel_result": KERNEL_RESULT, "early_entry_kernel_result_sha256": KERNEL_RESULT_SHA256,
        "early_entry_kernel_index_sha256": KERNEL_INDEX_SHA256,
        "early_entry_image": KERNEL_IMAGE, "early_entry_image_sha256": KERNEL_IMAGE_SHA256,
    }
    require(all(selection.get(key) == value for key, value in expected.items()),
            "state aggregate evidence selection mismatch")
    evidence = state.get("evidence")
    require(type(evidence) is list and all(type(item) is str for item in evidence), "state evidence list missing")
    selected_paths = {CPU_RESULT, CPU_INDEX, CPU_MODULE, HOST_RESULT, PREPARE_RESULT, ADAPTATION_PATCH,
                      KERNEL_RESULT, KERNEL_INDEX, KERNEL_IMAGE, *CPU_RUNS.values(), *EARLY_RUNS.values()}
    require(selected_paths <= set(evidence), "state evidence list omits selected P2-017/P2-018 paths")


def check_phase1_bundle() -> int:
    folder = PROJECT / "evidence/phase-1/20261111-final"
    require(folder.is_dir() and not folder.is_symlink(), "Phase 1 bundle directory missing")
    index = read_json(folder / "index.json", "phase1.index")
    exact(index, {"schema_version", "created_utc", "files", "limits"}, "phase1.index")
    require(index["schema_version"] == 1 and type(index["files"]) is list and len(index["files"]) == 264,
            "Phase 1 bundle count/schema mismatch")
    names: set[str] = set()
    for number, record in enumerate(index["files"]):
        exact(record, {"path", "size", "sha256"}, f"phase1.files[{number}]")
        name = relative_path(record["path"], f"phase1.files[{number}].path")
        require(name != "index.json" and name not in names and type(record["size"]) is int and record["size"] >= 0
                and type(record["sha256"]) is str and HEX256.fullmatch(record["sha256"]) is not None,
                "Phase 1 bundle record invalid")
        names.add(name)
        path = folder.joinpath(*PurePosixPath(name).parts)
        require(path.resolve(strict=True).is_relative_to(folder.resolve(strict=True)), "Phase 1 path escaped bundle")
        require(regular(path, "phase1." + name) == record["size"] and digest(path) == record["sha256"],
                "Phase 1 bundle file changed: " + name)
    actual = {path.relative_to(folder).as_posix() for path in folder.rglob("*") if path.is_file()}
    require(actual == names | {"index.json"}, "Phase 1 bundle exact file set mismatch")
    return len(names)


def resolve_link(document: Path, target: str) -> Path:
    target = unquote(target.strip("<>").split("#", 1)[0])
    windows = PureWindowsPath(target)
    if windows.drive and windows.root:
        if os.name == "nt":
            return Path(target)
        return Path("/mnt") / windows.drive[0].lower() / Path(*windows.parts[1:])
    return document.parent / target


def check_documents() -> dict[str, int]:
    cpu_guide = PROJECT / "docs/CPU-STATE.md"
    early_guide = PROJECT / "docs/EARLY-ENTRY.md"
    cpu_text = read_text(cpu_guide, "docs.CPU-STATE")
    early_text = read_text(early_guide, "docs.EARLY-ENTRY")
    for marker in ("P2-017", CPU_RESULT, CPU_RESULT_SHA256, CPU_INDEX, CPU_INDEX_SHA256,
                   "CurrentEL", "0x4", "EL1", "26 MHz", "Cortex-A53", "Cortex-A73",
                   *(Path(path).parent.name for path in CPU_RUNS.values())):
        require(marker in cpu_text, "CPU guide missing marker: " + marker)
    for marker in ("P2-018", HOST_RESULT, HOST_RESULT_SHA256, PREPARE_RESULT, PREPARE_RESULT_SHA256,
                   ADAPTATION_PATCH, ADAPTATION_PATCH_SHA256, KERNEL_RESULT, KERNEL_RESULT_SHA256,
                   KERNEL_INDEX, KERNEL_INDEX_SHA256, KERNEL_IMAGE_SHA256, "228", "36,334,080",
                   "watchdog", "persistent", "return", *(Path(path).parent.name for path in EARLY_RUNS.values())):
        require(marker in early_text, "early-entry guide missing marker: " + marker)

    integration = [
        PROJECT / "README.md", PROJECT / "docs/STATE.md", PROJECT / "docs/HANDOFF.md",
        PROJECT / "docs/INDEX.md", PROJECT / "docs/FILE-MAP.md", PROJECT / "docs/BUILD.md",
        PROJECT / "docs/ARCHITECTURE.md", PROJECT / "docs/ENTRY-CONTRACT.md",
        PROJECT / "docs/IMPLEMENTATION-LOG.md", WORKSPACE / "hakios-assessment/ROADMAP.md",
    ]
    for document in integration:
        contents = read_text(document, "integration." + document.name)
        require("CPU-STATE.md" in contents and "EARLY-ENTRY.md" in contents,
                "integration document does not reference both guides: " + str(document))
    state_doc = read_text(PROJECT / "docs/STATE.md", "docs.STATE")
    handoff = read_text(PROJECT / "docs/HANDOFF.md", "docs.HANDOFF")
    for marker in (CPU_RESULT, CPU_RESULT_SHA256, KERNEL_RESULT, KERNEL_IMAGE_SHA256):
        require(marker in state_doc and marker in handoff, "STATE/HANDOFF missing selected marker: " + marker)
    implementation = read_text(PROJECT / "docs/IMPLEMENTATION-LOG.md", "docs.IMPLEMENTATION-LOG")
    require("P2-017" in implementation and "P2-018" in implementation
            and "check-phase2-entry-handoff.py" in implementation, "implementation log missing P2-017/P2-018 handoff entry")

    documents = [PROJECT / "README.md", WORKSPACE / "hakios-assessment/ROADMAP.md",
                 *sorted((PROJECT / "docs").glob("*.md"))]
    links = 0
    for document in documents:
        contents = read_text(document, "links." + document.name)
        for raw in re.findall(r"\[[^\]\n]*\]\(([^)\n]+)\)", contents):
            target = raw.strip("<>").split("#", 1)[0]
            if not target or re.match(r"(?:https?://|mailto:|codex:)", target):
                continue
            linked = resolve_link(document, raw)
            require(linked.exists(), "broken local Markdown link in " + str(document) + ": " + raw)
            links += 1
    return {"documents": len(documents), "local_links": links, "integration_documents": len(integration)}


def main() -> int:
    try:
        state = read_json(PROJECT / "state.json", "state")
        require(type(state) is dict, "state: object required")
        check_aggregate_state(state)
        cpu = check_cpu_state(state)
        early = check_early_entry(state)
        phase1 = check_phase1_bundle()
        documents = check_documents()
        result = {"passed": True, "phase_1_bundle_files": phase1,
                  "cpu_records": cpu["records"], "cpu_guard_rejections": cpu["guard_rejections"],
                  "qemu_cases": early["qemu_cases"], "qemu_checks": early["qemu_checks"],
                  "early_entry_symbols": early["symbols"], "early_entry_record_bytes": early["record_bytes"],
                  "early_entry_guard_rejections": early["guard_rejections"], **documents,
                  "phase_2_device_gate_passed": False, "standalone_execution_verified": False,
                  "fault_return_verified": False, "a51_return_verified": False}
        print(json.dumps(result, sort_keys=True))
        return 0
    except (HandoffError, OSError, ValueError, KeyError, TypeError) as exc:
        print("PHASE2_ENTRY_HANDOFF_REJECTED: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
