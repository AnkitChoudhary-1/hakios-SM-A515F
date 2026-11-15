#!/usr/bin/env python3
"""Check selected offline observations, entry citations and retained handoff evidence.

Read-only: no phone access, builds, retained script or payload execution. Run via run.py.
The existing prototype checker retains its Phase 1/baseline/link/reference checks.
"""
import ast
import contextlib
import datetime as dt
import importlib.util
import io
import json
from pathlib import Path, PurePosixPath
import re

PROJECT = Path(__file__).resolve().parents[1]


def module_at(name, filename):
    spec = importlib.util.spec_from_file_location(name, PROJECT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


baseline = module_at("runtime_handoff_baseline", "check-loader-probe-handoff.py")
observations = module_at("runtime_handoff_observations", "runtime_observations.py")
require = baseline.require
digest = baseline.digest
read_json = observations.read_json


def selected_path(name):
    path = observations.contained(PROJECT, name)
    require(path.is_file(), "missing selected file: " + name)
    return path


def output_for(path):
    return (path.parent / "output.log").read_text(encoding="utf-8", errors="replace").replace("\x00", "")


def scripts_match(path):
    for name in observations.TOOLS:
        snapshot = path.parent / "project-scripts" / name
        require(snapshot.is_file() and digest(PROJECT / "scripts" / name) == digest(snapshot),
                "tool changed after selected run: " + name + " in " + path.parent.name)


def role_run(name, command, markers=()):
    selected_path(name)
    path, record = baseline.check_role_run(name, command)
    require(record["run_id"] == path.parent.name
            and name == "runs/" + record["run_id"] + "/metadata.json", "run identity/path mismatch")
    lines = output_for(path).splitlines()
    for marker in markers:
        require(lines.count(marker) == 1, "missing or repeated role output: " + marker)
    scripts_match(path)
    return path, record


def run_time(record, key):
    return observations.time_pair(record[key])


def mounted_project():
    require(re.fullmatch(r"[A-Za-z]:", PROJECT.drive) is not None,
            "this handoff checker must run in the Windows project")
    return "/mnt/" + PROJECT.drive[0].lower() + PROJECT.as_posix()[2:]


def check_preparation(validation, wsl_project):
    name = validation["native_guard_preparation_run"]
    selected_path(name)
    path, record = baseline.check_run(name)
    command = record["command"]
    native_root = validation["native_guard_work_dir"]
    require(type(native_root) is str and native_root.startswith("/opt/a51-hakios/validation/runtime-map/")
            and ".." not in Path(native_root).parts and Path(native_root).as_posix() == native_root,
            "invalid native guard directory")
    require(record["cwd"] == str(PROJECT)
            and record["run_id"] == path.parent.name
            and name == "runs/" + record["run_id"] + "/metadata.json"
            and type(command) is list and len(command) == 7
            and command[:6] == ["wsl.exe", "-d", "A51-KernelBuilder", "--", "python3", "-c"],
            "native preparation command/cwd does not match its role")
    # Read literal path/pin declarations from the recorded program without executing it.
    code = command[-1]
    require(type(code) is str and "hashlib" in code and "sha256" in code
            and "read_bytes()" in code and "write_bytes(raw)" in code,
            "native preparation does not bind fresh hash-checked copies")
    tree = ast.parse(code)
    declarations = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            key = node.targets[0].id
            require(key not in declarations, "duplicate preparation declaration: " + key)
            declarations[key] = node.value
    def path_literal(key):
        node = declarations[key]
        require(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "Path" and len(node.args) == 1 and not node.keywords,
                "invalid preparation path declaration")
        value = ast.literal_eval(node.args[0])
        require(type(value) is str, "invalid preparation path literal")
        return value
    source = path_literal("source")
    scope = path_literal("scope")
    target = declarations["target"]
    require(source == wsl_project + "/scripts"
            and scope == "/opt/a51-hakios/validation/runtime-map"
            and isinstance(target, ast.BinOp) and isinstance(target.op, ast.Div)
            and isinstance(target.left, ast.Name) and target.left.id == "scope",
            "native preparation source/root declarations disagree")
    suffix = ast.literal_eval(target.right)
    require(type(suffix) is str and (PurePosixPath(scope) / suffix).as_posix() == native_root,
            "native preparation target differs from selected guard directory")
    pins = ast.literal_eval(declarations["pins"])
    current_pins = {name: observations.identity(PROJECT / "scripts" / name) for name in observations.TOOLS}
    require(observations.canonical(pins) == observations.canonical(current_pins),
            "native preparation literal five-tool pins differ from current tools")
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    require(any(isinstance(node.func, ast.Attribute) and node.func.attr == "mkdir"
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "target"
                and any(item.arg == "exist_ok" and isinstance(item.value, ast.Constant)
                        and item.value.value is False for item in node.keywords) for node in calls)
            and sum(isinstance(node, ast.Assert) for node in ast.walk(tree)) >= 3,
            "native preparation lacks fresh-directory/hash/readback checks")
    lines = output_for(path).splitlines()
    require(lines.count("RUNTIME_MAP_NATIVE_HASH_COPY5 " + native_root) == 1,
            "native hash-copy5 output prefix/root mismatch")
    prepared_lines = [line[len("RUNTIME_MAP_NATIVE_PREPARED "):]
                      for line in lines if line.startswith("RUNTIME_MAP_NATIVE_PREPARED ")]
    require(len(prepared_lines) == 1, "missing or repeated native preparation result")
    prepared = observations.strict_json(prepared_lines[0].encode("utf-8"))
    require(type(prepared) is dict
            and set(prepared) == {"root", "files", "bytes", "checksums_verified", "manifest_sha256"}
            and prepared["root"] == native_root and type(prepared["files"]) is int and prepared["files"] == 5
            and type(prepared["bytes"]) is int
            and prepared["bytes"] == sum(pin["size"] for pin in current_pins.values())
            and prepared["checksums_verified"] is True
            and type(prepared["manifest_sha256"]) is str
            and re.fullmatch(r"[0-9a-f]{64}", prepared["manifest_sha256"])
            and prepared["manifest_sha256"] == validation["native_stage_manifest_sha256"],
            "native preparation output identities disagree")
    native_path = Path(r"\\wsl.localhost\A51-KernelBuilder") / native_root.lstrip("/")
    for tool in observations.TOOLS:
        require(observations.canonical(observations.identity(native_path / "scripts" / tool))
                == observations.canonical(current_pins[tool]), "native guard tool drift: " + tool)
    manifest_path = native_path / "stage-manifest.json"
    require(observations.identity(manifest_path)["sha256"] == prepared["manifest_sha256"],
            "native staging manifest hash drift")
    manifest = read_json(manifest_path)
    require(type(manifest) is dict and set(manifest) == {"schema_version", "created_utc", "distro",
            "source", "root", "files", "checksums_verified", "phone_queries", "phone_writes"}
            and type(manifest["schema_version"]) is int and manifest["schema_version"] == 1
            and manifest["distro"] == "A51-KernelBuilder" and manifest["source"] == source
            and manifest["root"] == native_root
            and observations.canonical(manifest["files"]) == observations.canonical(pins)
            and manifest["checksums_verified"] is True
            and manifest["phone_queries"] is False and manifest["phone_writes"] is False,
            "native staging manifest does not bind verified copies")
    manifest_time = dt.datetime.fromisoformat(manifest["created_utc"])
    require(manifest_time.utcoffset() == dt.timedelta(0)
            and run_time(record, "started") <= manifest_time <= run_time(record, "finished"),
            "native staging manifest falls outside selected preparation")
    scripts_match(path)
    return path, record


def check_runtime(state):
    validation = state["phase_2_runtime_map_validation"]
    selection = state["phase_2_evidence_selection"]
    require(type(validation["schema_version"]) is int and validation["schema_version"] == 1
            and validation["scope"] == "historical_linux_observations_only"
            and validation["phone_queries"] is False and validation["phone_writes"] is False,
            "runtime validation scope/device flags disagree")
    require(set(validation["guard_runs"]) == {"windows", "wsl"}
            and set(validation["replay_runs"]) == {"windows", "wsl"}
            and type(validation["guards_per_host"]) is int and validation["guards_per_host"] > 0,
            "runtime guards/replays lack both hosts")
    false_flags = {name: False for name in observations.FALSE_FLAGS}
    require(observations.canonical(validation["flags"]) == observations.canonical(false_flags),
            "runtime validation promotes an unproved gate")
    result_path = selected_path(selection["runtime_map_result"])
    require(result_path.name == "result.json"
            and result_path.is_relative_to(PROJECT / "evidence/phase-2/runtime-map")
            and digest(result_path) == selection["runtime_map_result_sha256"],
            "selected runtime result path/hash drift")
    pointer = read_json(PROJECT / "manifests/runtime-map-current.json")
    expected_pointer = {"schema_version": 1, "result": selection["runtime_map_result"],
                        **observations.identity(result_path), "scope": validation["scope"],
                        "safe_for_loader_placement": False, "phase_2_device_gate_passed": False}
    require(observations.canonical(pointer) == observations.canonical(expected_pointer),
            "runtime current pointer mismatch")
    result = observations.validate_packet(result_path.parent)
    index = read_json(result_path.parent / "index.json")
    require(type(validation["result_size"]) is int
            and validation["result_size"] == result_path.stat().st_size
            and type(validation["indexed_files"]) is int
            and validation["indexed_files"] == len(index["files"]) == 10
            and type(validation["indexed_bytes"]) is int
            and validation["indexed_bytes"] == sum(item["size"] for item in index["files"].values())
            and type(validation["source_capture_files"]) is int
            and validation["source_capture_files"] == result["source_capture_files"] == 153
            and observations.canonical(validation["counts"]) == observations.canonical(result["counts"])
            and observations.canonical(validation["flags"]) == observations.canonical(result["flags"]),
            "runtime state sizes/counts/flags disagree")
    source_name = selection["live_observation_report"]
    require(result["source"]["report"]["path"] == source_name
            and result["source"]["report"]["sha256"] == selection["live_observation_report_sha256"],
            "runtime map uses a different selected live capture")
    marker = "RUNTIME_MAP_VERIFIED " + observations.canonical(result["counts"])
    import_path, import_record = role_run(validation["import_run"],
        ["python", "scripts/import-runtime-map.py", "--import-report", source_name],
        ["RUNTIME_MAP_RESULT " + str(result_path), marker])
    require(run_time(import_record, "started") <= observations.time_pair(result["created"])
            <= observations.time_pair(result["finished"]) <= run_time(import_record, "finished"),
            "runtime result falls outside selected import run")
    wsl_project = mounted_project()
    preparation_path, preparation_record = check_preparation(validation, wsl_project)
    native_root = validation["native_guard_work_dir"]
    guard_commands = {
        "windows": ["python", "scripts/test-runtime-map.py"],
        "wsl": ["wsl.exe", "-d", "A51-KernelBuilder", "--", "python3",
                native_root + "/scripts/test-runtime-map.py"],
    }
    guard_records = {}
    for host, name in validation["guard_runs"].items():
        path, record = role_run(name, guard_commands[host])
        output = output_for(path)
        counts = re.findall(r"^Ran ([0-9]+) tests(?: in [^\r\n]+)?$", output, re.M)
        require(len(counts) == 1 and int(counts[0]) == validation["guards_per_host"]
                and output.splitlines().count("OK") == 1,
                "guard suite evidence mismatch: " + host)
        guard_records[host] = record
    require(run_time(preparation_record, "finished") <= run_time(guard_records["wsl"], "started"),
            "native guards precede verified preparation")
    replay_commands = {
        "windows": ["python", "scripts/import-runtime-map.py", "--verify-result",
                    selection["runtime_map_result"]],
        "wsl": ["wsl", "-d", "A51-KernelBuilder", "-u", "root", "--", "python3",
                wsl_project + "/scripts/import-runtime-map.py", "--verify-result",
                wsl_project + "/" + selection["runtime_map_result"]],
    }
    for host, name in validation["replay_runs"].items():
        path, record = role_run(name, replay_commands[host], [marker])
        require(run_time(import_record, "finished") <= run_time(record, "started"),
                "replay precedes selected import: " + host)
        require(not any(line.startswith("RUNTIME_MAP_RESULT ") for line in output_for(path).splitlines()),
                "replay unexpectedly publishes a result: " + host)
    return validation, result


ANDROID_FILES = (
    "Documentation/arm64/booting.txt", "arch/arm64/kernel/head.S", "arch/arm64/kernel/image.h",
    "arch/arm64/kernel/vmlinux.lds.S", "arch/arm64/boot/Makefile", "arch/arm64/Kconfig",
    "arch/arm64/kernel/Makefile", "kernel/Makefile", "kernel/sys_ni.c",
    "arch/arm64/kernel/machine_kexec.c", "arch/arm64/kernel/cpu-reset.S",
    "arch/arm64/kernel/cpu-reset.h", "arch/arm64/kernel/relocate_kernel.S", "kernel/kexec_core.c",
    "kernel/kexec.c", "arch/arm64/kernel/process.c", "include/linux/kexec.h",
    "arch/arm64/include/asm/mmu_context.h", "drivers/base/core.c", "kernel/reboot.c",
    "arch/arm64/kernel/smp.c", "arch/arm64/kernel/psci.c", "kernel/module.c",
    "KernelSU-Next/kernel/supercalls.c", "KernelSU-Next/kernel/supercalls.h",
    "KernelSU-Next/kernel/app_profile.c",
)
FACTS = {
    "native-proca-word": ("android/arch/arm64/kernel/head.S", 97, 101),
    "native-effective-extent": ("android/arch/arm64/kernel/image.h", 75, 79),
    "native-bss-page-table-extent": ("android/arch/arm64/kernel/vmlinux.lds.S", 232, 255),
    "native-raw-build": ("android/arch/arm64/boot/Makefile", 19, 44),
    "native-entry-protocol": ("android/Documentation/arm64/booting.txt", 144, 210),
    "native-placement-protocol": ("android/Documentation/arm64/booting.txt", 98, 130),
    "kaslr-register-loss": ("android/arch/arm64/kernel/head.S", 147, 163),
    "kexec-config-dependency": ("android/arch/arm64/Kconfig", 802, 810),
    "kexec-object-selection": ("android/arch/arm64/kernel/Makefile", 53, 54),
    "kexec-adapter-required": ("android/arch/arm64/kernel/relocate_kernel.S", 109, 114),
    "kexec-single-cpu-guard": ("android/arch/arm64/kernel/machine_kexec.c", 150, 158),
    "kexec-architectural-handoff": ("android/arch/arm64/kernel/machine_kexec.c", 199, 212),
    "kexec-noreturn-identity-map": ("android/arch/arm64/kernel/cpu-reset.h", 19, 31),
    "kexec-ordinary-shutdown": ("android/kernel/kexec_core.c", 1159, 1174),
    "kexec-capability": ("android/kernel/kexec.c", 195, 203),
    "dma-source-limits": ("android/drivers/base/core.c", 2956, 2969),
    "ksu-management-not-loader": ("android/KernelSU-Next/kernel/supercalls.c", 680, 825),
    "module-capability": ("android/kernel/module.c", 3639, 3644),
    "ksu-profile-capabilities": ("android/KernelSU-Next/kernel/app_profile.c", 290, 318),
    "efi-application-build": ("upstream/xnuloader/build.sh", 8, 12),
    "efi-entry-service-dependency": ("upstream/xnuloader/loader.c", 4311, 4321),
    "efi-memory-allocation": ("upstream/xnuloader/loader.c", 2773, 2811),
    "efi-resident-return": ("upstream/xnuloader/loader.c", 3468, 3488),
    "efi-return-contract": ("upstream/xnuloader/loader.c", 603, 612),
}


def check_entry(selection, validation):
    summary_path = selected_path(selection["entry_route_summary"])
    folder = summary_path.parent
    require(summary_path.name == "summary.json"
            and summary_path.is_relative_to(PROJECT / "evidence/phase-2/entry-route")
            and digest(summary_path) == selection["entry_route_summary_sha256"]
            and digest(folder / "index.json") == selection["entry_route_index_sha256"],
            "entry-route selected hashes drift")
    baseline.check_index(folder, 30)
    index = read_json(folder / "index.json")
    indexed = {item["path"]: item for item in index["files"]}
    expected_names = {"sources/android/" + name for name in ANDROID_FILES}
    expected_names |= {"sources/upstream/xnuloader/loader.c", "sources/upstream/xnuloader/build.sh",
                       "inputs/kernel.config", "summary.json"}
    require(set(indexed) == expected_names and len(expected_names) == 30,
            "entry-route source/configuration roles changed")
    summary = read_json(summary_path)
    require(type(summary["schema_version"]) is int and summary["schema_version"] == 1
            and summary["android_source"] == {
                "git_metadata_present": False, "lineage_is_recorded_not_verified_git_checkout": True,
                "logical_root": "/opt/a51-everline/src",
                "recorded_lineage_commit": "468ab8343364e4d3a267e670fa6a22fd4197a805"}
            and summary["upstream_source"] == {
                "logical_root": "/opt/a51-hakios/src/hakios-xnu-kernel",
                "verified_head": "63fc2b4633bac3af8e57dadab9f5a8d4cb940438"},
            "entry-route recorded lineage/verified upstream distinction changed")
    for key in ("a51_destination_selected", "no_flash_a51_launch_verified", "phase_2_device_gate_passed",
                "phone_queries", "phone_writes", "probe_log_retrieval_verified",
                "return_to_android_verified", "runtime_memory_ownership_verified", "safe_for_loader_placement"):
        require(summary[key] is False, "entry-route promotes an unproved flag: " + key)
    facts = summary["facts"]
    require(type(facts) is list and len(facts) == 24, "entry-route fact count changed")
    seen = set()
    for fact in facts:
        require(type(fact) is dict and set(fact) == {"claim", "id", "inclusive_lines", "path", "source_sha256"}
                and fact["id"] in FACTS and fact["id"] not in seen, "entry-route fact schema/id changed")
        seen.add(fact["id"])
        source, first, last = FACTS[fact["id"]]
        require(fact["path"] == "sources/" + source
                and type(fact["inclusive_lines"]) is list
                and all(type(line) is int for line in fact["inclusive_lines"])
                and fact["inclusive_lines"] == [first, last]
                and fact["source_sha256"] == indexed[fact["path"]]["sha256"]
                and type(fact["claim"]) is str and fact["claim"], "entry-route citation/pin changed")
        lines = observations.bounded_read(folder / fact["path"]).decode("utf-8").splitlines()
        require(1 <= first <= last <= len(lines), "entry-route citation outside retained full source")
    require(seen == set(FACTS), "entry-route fact set changed")
    reviews = summary["review_runs"]
    require(type(reviews) is list and len(reviews) == 11, "entry-route review-run count changed")
    seen_runs = set()
    failures = 0
    for review in reviews:
        run_id = review["run_id"]
        require(type(run_id) is str and run_id not in seen_runs
                and review["metadata_path"] == "runs/" + run_id + "/metadata.json"
                and review["output_path"] == "runs/" + run_id + "/output.log", "entry-route run association changed")
        seen_runs.add(run_id)
        metadata_path = selected_path(review["metadata_path"])
        output_path = selected_path(review["output_path"])
        require(digest(metadata_path) == review["metadata_sha256"]
                and digest(output_path) == review["output_sha256"]
                and output_path.stat().st_size == review["output_size"], "entry-route review bytes changed")
        record = read_json(metadata_path)
        require(record["run_id"] == run_id and record["cwd"] == str(PROJECT)
                and type(record["exit_code"]) is int
                and all(record[key] == review[key] for key in ("status", "exit_code", "started", "finished"))
                and run_time(record, "started") <= run_time(record, "finished"), "entry-route run record mismatch")
        if record["status"] == "failed":
            failures += 1
            require(run_id == "20261111T111648136735Z-phase2-loader-image-extent-efi-source-review"
                    and record["exit_code"] == 1, "unexpected entry-route failure")
        else:
            require(record["status"] == "passed" and record["exit_code"] == 0,
                    "entry-route review did not pass")
    require(failures == 1 and len(summary["failures"]) == 3, "historical entry-route failure evidence changed")
    boot = summary["retained_boot_report"]
    boot_path = selected_path(boot["path"])
    require(boot["path"] == selection["boot_report"]
            and boot["sha256"] == selection["boot_report_sha256"] == digest(boot_path)
            and boot["size"] == boot_path.stat().st_size, "entry-route historical boot-report pin drift")
    require(indexed["inputs/kernel.config"]["sha256"]
            == "9862a2b3ca684c08a0423681e77bf8503c2b7c2e18bd182ca3c1370681f8adb1",
            "entry-route retained installed configuration changed")
    total = sum(item["size"] for item in index["files"])
    require(validation["scope"] == "source_configuration_and_retained_image_facts_only"
            and all(type(validation[key]) is int and validation[key] == value for key, value in {
                "source_files": 29, "facts": len(facts), "review_runs": len(reviews),
                "indexed_files": len(index["files"]), "indexed_bytes": total}.items())
            and all(validation[key] is False for key in ("android_lineage_verified_git_head",
                "actual_entry_route_verified", "phone_queries", "phone_writes", "phase_2_device_gate_passed")),
            "entry-route state counts/scope/unproved flags disagree")
    return summary, total


def documented_number(value, text):
    normalized = text.replace(",", "")
    words = {0: "zero", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}
    return (re.search(r"(?<![0-9])" + str(value) + r"(?![0-9])", normalized) is not None
            or value in words and re.search(r"\b" + words[value] + r"\b", normalized, re.I) is not None)


def check_docs(selection, validation):
    state_text = (PROJECT / "docs/STATE.md").read_text(encoding="utf-8")
    guide_text = (PROJECT / "docs/RUNTIME-MAP.md").read_text(encoding="utf-8")
    entry_text = (PROJECT / "docs/ENTRY-CONTRACT.md").read_text(encoding="utf-8")
    require(selection["runtime_map_result"] in state_text
            and selection["runtime_map_result"] in guide_text
            and selection["runtime_map_result_sha256"] in guide_text
            and documented_number(validation["guards_per_host"], guide_text)
            and all(documented_number(value, guide_text) for value in validation["counts"].values())
            and documented_number(validation["indexed_files"], guide_text)
            and documented_number(validation["indexed_bytes"], guide_text)
            and documented_number(validation["result_size"], guide_text),
            "selected runtime result/hash/counts missing from documentation")
    require(selection["entry_route_summary"] in entry_text
            and selection["entry_route_summary_sha256"] in entry_text
            and selection["entry_route_index_sha256"] in entry_text
            and all(name in entry_text for name in (
                "arch/arm64/kernel/cpu-reset.h", "arch/arm64/include/asm/mmu_context.h",
                "KernelSU-Next/kernel/supercalls.c", "KernelSU-Next/kernel/app_profile.c"))
            and "kernel/ksu/supercalls.c" not in entry_text and "asm/cpu-reset.h" not in entry_text,
            "entry-route selected pins/correct source paths missing from documentation")


def main():
    # Reuse all existing prototype, Phase 1, rollback, document-link and reference checks.
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        require(baseline.main() == 0, "prototype baseline checker failed")
    baseline_lines = captured.getvalue().splitlines()
    require(baseline_lines, "prototype checker returned no summary")
    baseline_counts = json.loads(baseline_lines[-1])
    require(type(baseline_counts) is dict and baseline_counts["passed"] is True,
            "prototype checker returned an invalid summary")
    for line in baseline_lines[:-1]:
        print(line)
    state = read_json(PROJECT / "state.json")
    validation, result = check_runtime(state)
    selection = state["phase_2_evidence_selection"]
    summary, entry_bytes = check_entry(selection, state["phase_2_entry_route_review"])
    baseline.check_index(PROJECT / "evidence/phase-2/runtime-map-docs/20261111T111836955101Z", 14)
    check_docs(selection, validation)
    print(json.dumps({**baseline_counts, "rollback_copies": 14,
                      "prototype_rollback_copies": baseline_counts["rollback_copies"],
                      "prototype_guards_per_host": baseline_counts["guards_per_host"],
                      "guards_per_host": validation["guards_per_host"],
                      "runtime_map_indexed_files": validation["indexed_files"],
                      "runtime_map_indexed_bytes": validation["indexed_bytes"],
                      "source_capture_files": result["source_capture_files"],
                      "runtime_map_counts": result["counts"], "entry_route_indexed_files": 30,
                      "entry_route_indexed_bytes": entry_bytes, "entry_route_source_config_files": 29,
                      "entry_route_facts": len(summary["facts"]),
                      "entry_route_review_runs": len(summary["review_runs"]),
                      "scope": validation["scope"], "phone_queries": False, "phone_writes": False,
                      "runtime_memory_ownership_verified": False, "safe_for_loader_placement": False,
                      "phase_2_device_gate_passed": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
