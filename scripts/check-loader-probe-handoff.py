#!/usr/bin/env python3
"""Check the selected prototype, host checks, state, links and preserved baseline.

Read-only: no phone access, build or retained artifact execution. Run through run.py.
"""
import datetime as dt
import hashlib
import importlib.util
import json
import re
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def selected_path(name):
    require(type(name) is str and "\\" not in name, "invalid selected path")
    path = PROJECT / name
    require(path.resolve().is_relative_to(PROJECT.resolve()) and path.is_file(),
            "missing or escaped selected path: " + name)
    return path


def check_run(name):
    path = selected_path(name)
    record = read_json(path)
    require(record["status"] == "passed" and type(record["exit_code"]) is int
            and record["exit_code"] == 0, "selected run did not pass: " + name)
    times = []
    for field in ("started", "finished"):
        utc = dt.datetime.fromisoformat(record[field]["utc"])
        ist = dt.datetime.fromisoformat(record[field]["ist"])
        require(utc.utcoffset() == dt.timedelta(0)
                and ist.utcoffset() == dt.timedelta(hours=5, minutes=30)
                and utc == ist, "timestamp labels disagree: " + name)
        times.append(utc)
    require(times[0] <= times[1], "run timestamps reversed: " + name)
    require((path.parent / "output.log").is_file(), "missing run output: " + name)
    return path, record


def check_role_run(name, command, marker=None):
    path, record = check_run(name)
    require(record["cwd"] == str(PROJECT) and record["command"] == command,
            "selected run command/cwd does not match its role: " + name)
    if marker is not None:
        # WSL diagnostics can prepend UTF-16 NULs to an otherwise UTF-8 stream.
        output = (path.parent / "output.log").read_text(encoding="utf-8", errors="replace").replace("\x00", "")
        require(marker in output.splitlines(), "selected run output does not match its role: " + name)
    return path, record


def check_index(folder, expected_count):
    index = read_json(folder / "index.json")
    require(len(index["files"]) == expected_count, "unexpected preserved index count")
    names = set()
    for item in index["files"]:
        name = item["path"]
        require(type(name) is str and "\\" not in name and ":" not in name
                and not Path(name).is_absolute() and ".." not in Path(name).parts
                and Path(name).as_posix() == name and name not in names,
                "noncanonical or duplicate preserved index path")
        names.add(name)
        path = folder / name
        require(path.resolve().is_relative_to(folder.resolve()) and path.is_file(),
                "missing or escaped preserved file")
        require(path.stat().st_size == item["size"] and digest(path) == item["sha256"],
                "preserved file changed: " + item["path"])
    require({p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()}
            == names | {"index.json"}, "preserved file set mismatch")


def main():
    state = read_json(PROJECT / "state.json")
    require(state["phase_1_status"] == "complete" and state["phase_2_status"] == "in_progress"
            and state["active_phase"] == 2 and state["planned_phases"] == list(range(3, 11))
            and state["outstanding_phase_1_checks"] == [], "phase decision mismatch")
    require("host_qemu_loader_prototype_verified" in state["active_task"], "stale active task")
    for key in ("a51_xnu_boot_verified", "no_flash_a51_launch_verified",
                "phase_2_device_gate_passed"):
        require(state[key] is False, "unproved device/continuation flag: " + key)
    require(type(state["device_writes_this_phase"]) is bool, "invalid aggregate write flag")
    if state["device_writes_this_phase"]:
        selected = state["phase_2_evidence_selection"]
        diagnostic_path = selected_path(selected["page_probe_device_result"])
        require(digest(diagnostic_path) == selected["page_probe_device_result_sha256"], "diagnostic result pin drift")
        diagnostic_spec = importlib.util.spec_from_file_location("page_probe_session_reader", PROJECT / "scripts/test-page-probe-device.py")
        diagnostic = importlib.util.module_from_spec(diagnostic_spec)
        diagnostic_spec.loader.exec_module(diagnostic)
        diagnostic_flags = diagnostic.verify(diagnostic_path.parent)
        require(state["phase_2_page_probe_validation"]["flags"] == diagnostic_flags
                and diagnostic_flags["phone_writes"] is True
                and diagnostic_flags["phase_2_device_gate_passed"] is False,
                "unverified aggregate diagnostic writes")
    # Aggregate session status can advance while historical prototype flags stay false.
    require(type(state["phone_queries_this_continuation"]) is bool, "invalid aggregate query flag")
    if state["phone_queries_this_continuation"]:
        supplement = state["phase_2_connected_device_validation"]
        selected = state["phase_2_evidence_selection"]
        report_path = selected_path(selected["device_prerequisites_report"])
        require(digest(report_path) == selected["device_prerequisites_report_sha256"],
                "supplemental report hash drift")
        probe_spec = importlib.util.spec_from_file_location("connected_prerequisite_reader", PROJECT / "scripts/capture-device-prerequisites.py")
        probe = importlib.util.module_from_spec(probe_spec)
        probe_spec.loader.exec_module(probe)
        report, files, size = probe.verify(report_path.parent)
        require(report["previous_report"] == selected["live_observation_report"]
                and report["previous_report_sha256"] == selected["live_observation_report_sha256"]
                and supplement["scope"] == report["scope"]
                and supplement["phone_queries"] is True and supplement["phone_writes"] is False
                and supplement["indexed_files"] == files and supplement["indexed_bytes"] == size
                and supplement["summary"] == report["summary"], "supplemental state/historical binding mismatch")
        require(all(report["summary"][key] is True for key in (
            "capture_complete", "adb_root_verified", "model_verified", "single_boot_observation_verified",
            "linux_exported_fdt_stable", "configuration_stable")), "unverified supplemental capture")
    criteria = state["phase_2_criteria"]
    require(criteria["loader_source"] == "implemented_verified_host_qemu_prototype_a51_adapter_not_implemented"
            and criteria["a51_loader_payload_execution"] == "not_attempted"
            and criteria["experimental_image"] == "not_created"
            and criteria["retrievable_probe_logs"] == "not_implemented"
            and criteria["demonstrated_return"] == "not_verified", "device criteria mismatch")
    validation = state["phase_2_loader_prototype_validation"]
    require(set(validation["guard_runs"]) == {"windows", "wsl"}
            and set(validation["replay_runs"]) == {"windows", "wsl"}
            and type(validation["guards_per_host"]) is int and validation["guards_per_host"] == 93,
            "missing host or unexpected guard count")
    selection = state["phase_2_evidence_selection"]
    result_path = selected_path(selection["loader_probe_result"])
    require(digest(result_path) == selection["loader_probe_result_sha256"], "selected result hash drift")
    pointer = read_json(PROJECT / "manifests/loader-probe-current.json")
    require(pointer["result"] == selection["loader_probe_result"]
            and pointer["sha256"] == selection["loader_probe_result_sha256"]
            and pointer["phase_2_device_gate_passed"] is False, "current pointer mismatch")
    spec = importlib.util.spec_from_file_location("loader_probe_handoff_reader", PROJECT / "scripts/build-loader-probe.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.verify(result_path.parent)
    index = read_json(result_path.parent / "index.json")
    config = read_json(result_path.parent / "identity-input.json")
    require(validation["result_size"] == result_path.stat().st_size
            and validation["host_checks"] == result["host_checks"] == 2609
            and validation["indexed_files"] == len(index["files"]) == 55
            and validation["indexed_bytes"] == sum(x["size"] for x in index["files"])
            and validation["build_identity_sha256"] == result["build_identity_sha256"]
            and validation["command_count"] == len(result["commands"]) == 14
            and validation["qemu_frames"] == len(result["qemu"]["frames"]) == 7
            and validation["qemu_entry_el"] == result["qemu"]["entry_fields"][6] == 1
            and validation["qemu_cntfrq_hz"] == result["qemu"]["entry_fields"][7]
            and validation["fdt_consumed"] is False
            and validation["cooperative_fuel"] is True, "prototype state counts/semantics disagree")
    for name, hash_value in config["sources"].items():
        original = PROJECT / ("scripts" if name == "build-loader-probe.py" else "prototype/loader") / name
        require(digest(original) == hash_value, "source changed after selected build: " + name)
    wsl_project = "/mnt/" + PROJECT.drive[0].lower() + PROJECT.as_posix()[2:]
    native_guard_root = "/opt/a51-hakios/validation/loader-probe/20261111T1050Z"
    require(validation["native_guard_work_dir"] == native_guard_root,
            "unexpected native guard work directory")
    native_preparation = (
        'import hashlib,json,shutil\nfrom pathlib import Path\n'
        f'src=Path("{wsl_project}")\n'
        f'dst=Path("{native_guard_root}")\n'
        'dst.mkdir(parents=True,exist_ok=False)\n'
        'pointer=json.loads((src/"manifests/loader-probe-current.json").read_bytes())\n'
        'paths=[Path("scripts/build-loader-probe.py"),Path("scripts/test-loader-probe-evidence.py"),Path("manifests/loader-probe-current.json")]\n'
        'paths += [p.relative_to(src) for p in (src/pointer["result"]).parent.rglob("*") if p.is_file()]\n'
        'for rel in paths:\n out=dst/rel\n out.parent.mkdir(parents=True,exist_ok=True)\n'
        ' shutil.copyfile(src/rel,out)\n'
        ' if hashlib.sha256((src/rel).read_bytes()).digest()!=hashlib.sha256(out.read_bytes()).digest(): raise ValueError(str(rel))\n'
        'print("NATIVE_GUARD_INPUTS_VERIFIED",len(paths),str(dst))\n'
    )
    preparation_path, preparation_record = check_role_run(
        validation["native_guard_preparation_run"],
        ["wsl.exe", "-d", "A51-KernelBuilder", "--", "python3", "-c", native_preparation],
        "NATIVE_GUARD_INPUTS_VERIFIED 59 " + native_guard_root)
    guard_commands = {
        "windows": ["python", "scripts/test-loader-probe-evidence.py"],
        "wsl": ["wsl.exe", "-d", "A51-KernelBuilder", "--", "python3",
                native_guard_root + "/scripts/test-loader-probe-evidence.py"],
    }
    for host, name in validation["guard_runs"].items():
        path, record = check_role_run(name, guard_commands[host])
        output = (path.parent / "output.log").read_text(encoding="utf-8", errors="replace")
        require(re.search(r"Ran " + str(validation["guards_per_host"]) + r" tests", output)
                and re.search(r"^OK\s*$", output, re.M), "guard suite evidence mismatch: " + host)
        for script in ("build-loader-probe.py", "test-loader-probe-evidence.py"):
            require(digest(PROJECT / "scripts" / script)
                    == digest(path.parent / "project-scripts" / script), "script changed after guards")
            if host == "wsl":
                require(digest(PROJECT / "scripts" / script)
                        == digest(preparation_path.parent / "project-scripts" / script),
                        "native staging script identity changed")
        if host == "wsl":
            require(dt.datetime.fromisoformat(preparation_record["finished"]["utc"])
                    <= dt.datetime.fromisoformat(record["started"]["utc"]),
                    "native guards precede their verified preparation")
    builder = wsl_project + "/scripts/build-loader-probe.py"
    check_role_run(validation["build_run"],
                   ["wsl.exe", "-d", "A51-KernelBuilder", "-u", "root", "--",
                    "python3", builder, "--build"],
                   "PROBE_RESULT " + wsl_project + "/" + selection["loader_probe_result"])
    replay_commands = {
        "windows": ["python", "./scripts/build-loader-probe.py", "--verify-result",
                    selection["loader_probe_result"]],
        "wsl": ["wsl", "-d", "A51-KernelBuilder", "-u", "root", "--", "python3",
                builder, "--verify-result", wsl_project + "/" + selection["loader_probe_result"]],
    }
    replay_marker = (f'PROBE_EVIDENCE_VERIFIED files=55 bytes={validation["indexed_bytes"]} '
                     'host_checks=2609 frames=7')
    for host, name in validation["replay_runs"].items():
        path, record = check_role_run(name, replay_commands[host], replay_marker)
        require(digest(PROJECT / "scripts/build-loader-probe.py")
                == digest(path.parent / "project-scripts/build-loader-probe.py"),
                "builder changed after replay")
    for name in [validation["phase_1_integrity_run"], validation["phase_1_bundle_run"]]:
        check_run(name)
    first = selected_path(validation["first_result"])
    require(digest(first) == validation["first_result_sha256"], "first accepted result changed")
    module.verify(first.parent)
    check_index(PROJECT / "evidence/phase-1/20261111-final", 264)
    check_index(PROJECT / "evidence/phase-2/loader-probe-docs/20261111T102921621458Z", 13)
    references = 0
    selected_runs = 0
    for name in state["evidence"]:
        selected_path(name)
        references += 1
        if name.startswith("runs/") and name.endswith("/metadata.json"):
            check_run(name)
            selected_runs += 1
    documents = [PROJECT / "README.md", PROJECT.parent / "hakios-assessment/ROADMAP.md",
                 *sorted((PROJECT / "docs").glob("*.md"))]
    links = 0
    for path in documents:
        for target in re.findall(r"\[[^\]\n]*\]\(([^)\n]+)\)", path.read_text(encoding="utf-8")):
            target = target.strip("<>").split("#", 1)[0]
            if not target or re.match(r"(?:https?://|mailto:|codex:)", target):
                continue
            linked = Path(target) if re.match(r"^[A-Za-z]:[/\\]", target) else path.parent / target
            require(linked.exists(), "broken link in " + path.name + ": " + target)
            links += 1
    state_text = (PROJECT / "docs/STATE.md").read_text(encoding="utf-8")
    guide_text = (PROJECT / "docs/LOADER-PROTOTYPE.md").read_text(encoding="utf-8")
    require(selection["loader_probe_result"] in state_text and selection["loader_probe_result_sha256"] in guide_text
            and "2,609" in state_text and str(validation["guards_per_host"]) in guide_text,
            "selected execution missing from current documentation")
    print(json.dumps({"passed": True, "references": references, "successful_runs": selected_runs,
                      "documents": len(documents), "links": links, "phase_1_bundle_files": 264,
                      "rollback_copies": 13, "host_checks": 2609, "qemu_frames": 7,
                      "guards_per_host": validation["guards_per_host"], "phone_queries": False,
                      "phone_writes": False, "phase_2_device_gate_passed": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
