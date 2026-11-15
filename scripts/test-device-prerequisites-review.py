#!/usr/bin/env python3
"""Independently replay one retained packet and three offline corruptions.

No device operation occurs. Fixture packets and exact subprocess commands are
retained under evidence/test-fixtures; the original packet is checked unchanged.
Run through scripts/run.py with --source pointing to the frozen capture folder.
"""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
COLLECTOR = PROJECT / "scripts/capture-device-prerequisites.py"
FALSE_GATES = (
    "phone_writes", "phone_rebooted", "phone_mounts_changed", "payload_executed",
    "actual_entry_route_verified", "runtime_memory_ownership_verified",
    "safe_for_loader_placement", "a51_destination_selected",
    "physical_state_transitions_verified", "probe_log_retrieval_verified",
    "fault_logging_verified", "return_to_android_verified",
    "no_flash_a51_launch_verified", "phase_2_device_gate_passed",
)


def require(value, message):
    if not value:
        raise AssertionError(message)


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def digest(path):
    value = path.read_bytes()
    return {"size": len(value), "sha256": hashlib.sha256(value).hexdigest()}


def identities(folder):
    return {p.relative_to(folder).as_posix(): digest(p)
            for p in sorted(folder.rglob("*")) if p.is_file()}


def replay(folder):
    argv = [sys.executable, "-B", str(COLLECTOR), "--verify", str(folder)]
    started = dt.datetime.now(dt.timezone.utc).isoformat()
    result = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            timeout=30, shell=False)
    return {"argv": argv, "started_utc": started,
            "finished_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "exit_code": result.returncode,
            "output": result.stdout.decode("utf-8", errors="replace")}


def repin_report(folder, report):
    write(folder / "report.json", report)
    index = read(folder / "index.json")
    item = next(item for item in index["files"] if item["path"] == "report.json")
    item.update(digest(folder / "report.json"))
    write(folder / "index.json", index)


def audit(source):
    report = read(source / "report.json")
    summary = report["summary"]
    require(len(report["queries"]) == 35 and summary["successful_queries"] == 33,
            "unexpected selected capture counts")
    require(set(summary["flags"]) == set(FALSE_GATES)
            and all(summary["flags"][key] is False for key in FALSE_GATES),
            "device gate promoted")
    require(report["phone_queries"] is True and report["phone_writes"] is False,
            "wrong capture query/write scope")
    by_id = {q["id"]: q for q in report["queries"]}
    failures = [q for q in report["queries"] if q["status"] != "ok"]
    require({q["id"] for q in failures} == {
        "policy_kexec_load_disabled", "device_node_metadata"}, "unexpected failures")
    for query in failures:
        response = (source / query["response"]).read_bytes()
        footer = b"\nHAKIOS_A51_STATUS_" + report["remote_status_nonce"].encode() + b"=1\n"
        require(query["exit_code"] == 1 and query["status"] == "command_failed"
                and query["transport_status"] == "ok" and query["transport_exit_code"] == 0
                and response.endswith(footer), "remote failure is not independently retained")
    pairs = (("root_begin", "root_end"), ("model_begin", "model_end"),
             ("boot_id_begin", "boot_id_end"), ("fdt_begin", "fdt_end"),
             ("config_begin", "config_end"))
    for begin, end in pairs:
        require(by_id[begin]["status"] == by_id[end]["status"] == "ok"
                and (source / by_id[begin]["stdout"]).read_bytes()
                == (source / by_id[end]["stdout"]).read_bytes(), "unstable endpoints: " + begin)
    require(re.search(rb"\buid=0\(root\)", (source / by_id["root_begin"]["stdout"]).read_bytes()),
            "begin root observation missing")
    selection = read(PROJECT / "state.json")["phase_2_evidence_selection"]
    require(report["previous_report"] == selection["live_observation_report"]
            and report["previous_report_sha256"] == selection["live_observation_report_sha256"],
            "historical selected report association changed")
    original_previous = PROJECT / selection["live_observation_report"]
    require((source / "inputs/previous-report.json").read_bytes()
            == original_previous.read_bytes(), "historical report copy changed")
    previous = read(original_previous)
    for query_id, copy_name in (("config_gz", "previous-config.gz"),
                               ("boot_id_begin", "previous-boot-id.stdout")):
        query = next(q for q in previous["queries"] if q["id"] == query_id)
        require(digest(source / "inputs" / copy_name)
                == {"size": query["stdout_size"], "sha256": query["stdout_sha256"]}
                and (source / "inputs" / copy_name).read_bytes()
                == (original_previous.parent / query["stdout"]).read_bytes(),
                "historical query copy changed: " + query_id)
    for key in ("adb_root_verified", "model_verified", "single_boot_observation_verified",
                "linux_exported_fdt_stable", "linux_exported_fdt_matches_previous",
                "configuration_stable", "configuration_matches_previous",
                "same_boot_as_previous_capture"):
        require(summary[key] is True, "required observation unavailable: " + key)
    return {"query_count": 35, "successful_queries": 33,
            "remote_failures_despite_transport_zero": [q["id"] for q in failures],
            "historical_report_sha256": report["previous_report_sha256"],
            "false_gate_count": len(FALSE_GATES), "stable_endpoint_pair_count": len(pairs)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()
    source = args.source.resolve()
    require(source.is_relative_to(PROJECT / "evidence/phase-2/device-prerequisites"),
            "source must be a retained device-prerequisites packet")
    original = identities(source)
    baseline = replay(source)
    require(baseline["exit_code"] == 0, "original packet replay failed: " + baseline["output"])
    observations = audit(source)
    fixture_root = (PROJECT / "evidence/test-fixtures").resolve()
    require(fixture_root.is_relative_to(PROJECT.resolve()), "fixture root escapes project")
    fixture_root.mkdir(parents=True, exist_ok=True)
    fixture = Path(tempfile.mkdtemp(prefix="device-prerequisites-independent-", dir=fixture_root))
    require(fixture.resolve().is_relative_to(fixture_root), "fixture escapes intended root")
    evidence = {"schema_version": 1, "scope": "three_offline_corruption_checks",
                "phone_queries": False, "phone_writes": False,
                "source_packet": source.relative_to(PROJECT).as_posix(),
                "source_identities": original, "baseline_replay": baseline,
                "independent_observations": observations, "tests": []}
    cases = (("remote_exit_metadata", "remote status reconstruction failed"),
             ("repinned_summary_gate", "summary reconstruction failed"),
             ("corrupt_file_bytes", "packet file identity mismatch"))
    for name, expected in cases:
        folder = fixture / name
        shutil.copytree(source, folder)
        report = read(folder / "report.json")
        if name == "remote_exit_metadata":
            query = next(q for q in report["queries"] if q["id"] == "policy_kexec_load_disabled")
            query.update(exit_code=0, status="ok")
            repin_report(folder, report)
            mutation = "Promote remote exit 1 to exit 0/ok; repin report in index; retained footer stays =1."
        elif name == "repinned_summary_gate":
            report["summary"]["flags"]["phase_2_device_gate_passed"] = True
            repin_report(folder, report)
            mutation = "Promote Phase 2 gate to true and repin report in index; original queries unchanged."
        else:
            path = folder / report["queries"][0]["stdout"]
            value = bytearray(path.read_bytes())
            value[0] ^= 1
            path.write_bytes(value)
            mutation = "Flip one root stdout byte while retaining original report and index pins."
        run = replay(folder)
        require(run["exit_code"] != 0 and expected in run["output"],
                name + " did not fail for expected reason: " + run["output"])
        evidence["tests"].append(dict(run, name=name, mutation=mutation,
                                      expected_rejection=expected, rejected=True))
        print("PASS " + name + ": " + expected, flush=True)
    require(identities(source) == original, "original packet changed during offline review")
    evidence.update(original_packet_unchanged=True, corruption_checks=3, status="passed")
    write(fixture / "review-result.json", evidence)
    print("INDEPENDENT_REVIEW " + str((fixture / "review-result.json").relative_to(PROJECT)), flush=True)
    print("PASS original replay; 3/3 corruptions rejected; original unchanged; phone_queries=false phone_writes=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
