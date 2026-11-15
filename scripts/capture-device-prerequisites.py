#!/usr/bin/env python3
"""Capture fixed read-only Android launch prerequisites, or replay them offline.

This supplement leaves the selected historical live-loader capture untouched.
It never opens hardware device nodes, invokes a launcher or certifies ownership.
Run through scripts/run.py with an explicit --serial, or --verify FOLDER.
"""
import argparse
import datetime as dt
import gzip
import importlib.util
import io
import re
import secrets
import shlex
import shutil
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("live_prerequisite_helpers", PROJECT / "scripts/capture-live-loader.py")
live = importlib.util.module_from_spec(spec)
spec.loader.exec_module(live)
require = live.require
MIB = 1024 * 1024
QUERIES = [
    ("root_begin", "id", 4096),
    ("model_begin", "getprop ro.product.model", 4096),
    ("boot_id_begin", "cat /proc/sys/kernel/random/boot_id", 4096),
    ("uname", "uname -a", 16384),
    ("fdt_begin", "cat /sys/firmware/fdt", 2 * MIB),
    ("config_begin", "cat /proc/config.gz", 2 * MIB),
    ("capabilities", "grep -E '^(Uid|Gid|CapInh|CapPrm|CapEff|CapBnd|CapAmb|NoNewPrivs|Seccomp):' /proc/self/status", 16384),
    ("modules_disabled", "cat /proc/sys/kernel/modules_disabled", 4096),
    ("loaded_modules", "cat /proc/modules", 65536),
] + [("cpu_" + key, "cat /sys/devices/system/cpu/" + key, 4096)
     for key in ("possible", "present", "online", "offline", "kernel_max")] + [
    ("meminfo", "cat /proc/meminfo", 65536),
    ("buddyinfo", "cat /proc/buddyinfo", 65536),
    ("zoneinfo", "cat /proc/zoneinfo", 512 * 1024),
    ("vmstat_allocator", "grep -E '^(nr_free_pages|nr_free_cma|compact_[a-z_]+|cma_[a-z_]+) ' /proc/vmstat", 16384),
] + [("policy_" + key, "cat /proc/sys/kernel/" + key, 4096)
     for key in ("kexec_load_disabled", "dmesg_restrict", "kptr_restrict", "panic", "panic_on_oops", "sysrq")] + [
    ("console_active", "cat /sys/class/tty/console/active", 4096),
    ("log_metadata", "ls -ld /dev/kmsg /proc/last_kmsg /sys/fs/pstore", 16384),
    ("pstore_listing", "ls -la /sys/fs/pstore", 65536),
    ("log_mounts", "grep -E ' (pstore|debugfs) ' /proc/mounts", 16384),
    ("device_node_metadata", "ls -ld /dev/mem /dev/kmem /dev/ion /dev/watchdog /dev/watchdog0", 16384),
    ("cpu_online_end", "cat /sys/devices/system/cpu/online", 4096),
    ("config_end", "cat /proc/config.gz", 2 * MIB),
    ("fdt_end", "cat /sys/firmware/fdt", 2 * MIB),
    ("boot_id_end", "cat /proc/sys/kernel/random/boot_id", 4096),
    ("model_end", "getprop ro.product.model", 4096),
    ("root_end", "id", 4096),
]
SYMBOLS = ("CONFIG_KEXEC", "CONFIG_KEXEC_CORE", "CONFIG_KEXEC_FILE", "CONFIG_EFI",
           "CONFIG_MODULES", "CONFIG_MODULE_UNLOAD", "CONFIG_MODULE_FORCE_LOAD",
           "CONFIG_MODVERSIONS", "CONFIG_MODULE_SIG", "CONFIG_MODULE_SIG_FORCE",
           "CONFIG_KALLSYMS", "CONFIG_DEBUG_FS", "CONFIG_DEVMEM", "CONFIG_DEVKMEM",
           "CONFIG_STRICT_DEVMEM", "CONFIG_ION", "CONFIG_CMA", "CONFIG_DMA_CMA",
           "CONFIG_DMA_SHARED_BUFFER", "CONFIG_OF_RESERVED_MEM", "CONFIG_PSTORE",
           "CONFIG_PSTORE_RAM", "CONFIG_SEC_DEBUG_LAST_KMSG", "CONFIG_SEC_LOG",
           "CONFIG_HOTPLUG_CPU", "CONFIG_ARM_PSCI_FW", "CONFIG_S3C2410_WATCHDOG",
           "CONFIG_EXYNOS_WATCHDOG", "CONFIG_WATCHDOG_SYSFS", "CONFIG_PAGE_OWNER", "CONFIG_KSU")
FALSE_FLAGS = ("phone_writes", "phone_rebooted", "phone_mounts_changed", "payload_executed",
               "actual_entry_route_verified", "runtime_memory_ownership_verified",
               "safe_for_loader_placement", "a51_destination_selected",
               "physical_state_transitions_verified", "probe_log_retrieval_verified",
               "fault_logging_verified", "return_to_android_verified",
               "no_flash_a51_launch_verified", "phase_2_device_gate_passed")
TOOLS = ("capture-device-prerequisites.py", "capture-live-loader.py", "boot_formats.py")
INPUTS = ("previous-report.json", "previous-config.gz", "previous-boot-id.stdout")


def symbols(value):
    with gzip.GzipFile(fileobj=io.BytesIO(value)) as stream:
        data = stream.read(2 * MIB + 1)
    require(len(data) <= 2 * MIB, "decompressed configuration exceeds bound")
    result = {key: None for key in SYMBOLS}
    for line in data.decode("utf-8", errors="strict").splitlines():
        match = re.fullmatch(r"(CONFIG_[A-Z0-9_]+)=(.*)", line)
        absent = re.fullmatch(r"# (CONFIG_[A-Z0-9_]+) is not set", line)
        if match and match[1] in result:
            require(result[match[1]] is None, "duplicate selected config symbol")
            result[match[1]] = match[2]
        elif absent and absent[1] in result:
            require(result[absent[1]] is None, "duplicate selected config symbol")
            result[absent[1]] = "n"
    return result


def summarize(folder, report):
    successful = {}
    failures = []
    for record in report["queries"]:
        if record["status"] == "ok":
            successful[record["id"]] = live.bounded_read(live.inside(folder, record["stdout"]), 2 * MIB)
        else:
            failures.append({"id": record["id"], "status": record["status"],
                             "remote_exit_code": record["exit_code"],
                             "transport_exit_code": record["transport_exit_code"]})
    same = lambda a, b: a in successful and b in successful and successful[a] == successful[b]
    root = all(key in successful and re.search(rb"\buid=0\(root\)", successful[key])
               for key in ("root_begin", "root_end"))
    model = same("model_begin", "model_end") and successful["model_begin"].strip() == b"SM-A515F"
    boot = same("boot_id_begin", "boot_id_end") and re.fullmatch(
        rb"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\n", successful["boot_id_begin"]) is not None
    previous = live.json_read(folder / "inputs/previous-report.json")
    require(previous["schema_version"] == 2 and previous["serial"] == report["serial"], "historical capture identity mismatch")
    caps = {}
    if "capabilities" in successful:
        for line in successful["capabilities"].decode("ascii").splitlines():
            key, value = line.split(":", 1)
            if key.startswith("Cap"):
                require(re.fullmatch(r"[0-9a-fA-F]{1,16}", value.strip()), "invalid capability mask")
                caps[key] = int(value.strip(), 16)
            elif key in ("NoNewPrivs", "Seccomp"):
                caps[key] = int(value.strip())
    config = symbols(successful["config_begin"]) if "config_begin" in successful else {}
    previous_config = symbols(live.bounded_read(folder / "inputs/previous-config.gz", 2 * MIB))
    policies = {key.removeprefix("policy_"): successful[key].decode("ascii").strip()
                for key in successful if key.startswith("policy_")}
    memory = {}
    if "meminfo" in successful:
        for line in successful["meminfo"].decode("ascii").splitlines():
            match = re.fullmatch(r"(MemTotal|MemFree|MemAvailable|CmaTotal|CmaFree):\s+(\d+) kB", line)
            if match:
                memory[match[1] + "_KiB"] = int(match[2])
    return {"capture_complete": len(report["queries"]) == len(QUERIES),
            "query_count": len(report["queries"]), "successful_queries": len(successful),
            "query_failures": failures, "adb_root_verified": bool(root), "model_verified": bool(model),
            "single_boot_observation_verified": bool(boot),
            "linux_exported_fdt_stable": same("fdt_begin", "fdt_end"),
            "linux_exported_fdt_sha256": live.sha256(successful["fdt_begin"]) if "fdt_begin" in successful else None,
            "linux_exported_fdt_matches_previous": "fdt_begin" in successful and live.sha256(successful["fdt_begin"]) == previous["summary"]["live_fdt"]["sha256"],
            "configuration_stable": same("config_begin", "config_end"),
            "configuration_matches_previous": "config_begin" in successful and successful["config_begin"] == live.bounded_read(folder / "inputs/previous-config.gz", 2 * MIB),
            "same_boot_as_previous_capture": "boot_id_begin" in successful and successful["boot_id_begin"] == live.bounded_read(folder / "inputs/previous-boot-id.stdout", 4096),
            "configuration_available": "config_begin" in successful,
            "configuration_symbols": config, "configuration_symbol_changes": {key: [previous_config[key], config[key]] for key in SYMBOLS if previous_config[key] != config[key]} if config else {},
            "collector_child_capabilities": caps,
            "collector_child_has_CAP_SYS_MODULE": bool(caps["CapEff"] & (1 << 16)) if "CapEff" in caps else None,
            "collector_child_has_CAP_SYS_BOOT": bool(caps["CapEff"] & (1 << 22)) if "CapEff" in caps else None,
            "modules_disabled": successful["modules_disabled"].decode("ascii").strip() if "modules_disabled" in successful else None,
            "loaded_module_records": len(successful["loaded_modules"].splitlines()) if "loaded_modules" in successful else None,
            "cpu_masks": {key.removeprefix("cpu_"): successful[key].decode("ascii").strip() for key in successful if key.startswith("cpu_")},
            "online_cpu_mask_stable": same("cpu_online", "cpu_online_end"),
            "memory_snapshot": memory, "kernel_policies": policies,
            "memory_statistics_are_nonatomic_and_not_ownership": True,
            "metadata_does_not_verify_log_persistence_or_return": True,
            "flags": {key: False for key in FALSE_FLAGS}}


def expected_names():
    return {"report.json"} | {"tools/" + key for key in TOOLS} | {"inputs/" + key for key in INPUTS} | {
        f"queries/{number:02d}-{name}.{suffix}" for number, (name, _, _) in enumerate(QUERIES)
        for suffix in ("stdout", "stderr", "response")}


def verify(folder):
    folder = Path(folder).resolve()
    report = live.json_read(folder / "report.json")
    require(report["schema_version"] == 1 and report["scope"] == "supplemental_android_read_only_prerequisites"
            and report["phone_queries"] is True and report["phone_writes"] is False, "invalid scope or write flag")
    require(re.fullmatch(r"[A-Za-z0-9_-]{1,80}", report["serial"]), "invalid serial")
    index = live.json_read(folder / "index.json")
    require(len(index["files"]) == len(expected_names()), "unexpected packet count")
    indexed = set()
    total = 0
    for item in index["files"]:
        require(item["path"] not in indexed and type(item["size"]) is int and 0 <= item["size"] <= 4 * MIB, "duplicate or oversized file")
        indexed.add(item["path"])
        value = live.bounded_read(live.inside(folder, item["path"]), 4 * MIB)
        require(len(value) == item["size"] and live.sha256(value) == item["sha256"], "packet file identity mismatch: " + item["path"])
        total += len(value)
    require(total <= 16 * MIB and indexed == expected_names(), "packet roles or aggregate bound mismatch")
    require({p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()} == indexed | {"index.json"}, "unexpected packet file")
    for key in TOOLS:
        require(live.digest_file(folder / "tools" / key) == live.digest_file(PROJECT / "scripts" / key), "tool changed since capture: " + key)
    require(live.digest_file(folder / "inputs/previous-report.json")["sha256"] == report["previous_report_sha256"], "previous report pin mismatch")
    previous = live.json_read(folder / "inputs/previous-report.json")
    for source_id, copy in (("config_gz", "previous-config.gz"), ("boot_id_begin", "previous-boot-id.stdout")):
        source = next(item for item in previous["queries"] if item["id"] == source_id)
        require(source["status"] == "ok" and live.digest_file(folder / "inputs" / copy) == {"size": source["stdout_size"], "sha256": source["stdout_sha256"]}, "previous query pin mismatch")
    require(len(report["queries"]) == len(QUERIES), "incomplete fixed query list")
    last_time = live.time_pair(report["created"])
    for number, (record, (name, command, limit)) in enumerate(zip(report["queries"], QUERIES)):
        require(record["id"] == name and record["command"] == command and type(record["limit"]) is int
                and record["limit"] == limit and type(record["timeout_seconds"]) is int
                and record["timeout_seconds"] == 15, "fixed query mismatch")
        require(record["argv"] == [report["adb_path"], "-s", report["serial"], "exec-out", "su -c " + shlex.quote(live.remote_script(command, report["remote_status_nonce"]))], "transport command mismatch")
        started, finished = live.time_pair(record["started"]), live.time_pair(record["finished"])
        require(last_time <= started <= finished, "query times reversed")
        last_time = finished
        for suffix in ("stdout", "stderr", "response"):
            require(record[suffix] == f"queries/{number:02d}-{name}.{suffix}", "query file role mismatch")
            value = live.bounded_read(live.inside(folder, record[suffix]), limit + live.STATUS_ALLOWANCE if suffix != "stderr" else 65536)
            require(len(value) == record[suffix + "_size"] and live.sha256(value) == record[suffix + "_sha256"], "query output pin mismatch")
        response = live.bounded_read(live.inside(folder, record["response"]), limit + live.STATUS_ALLOWANCE)
        stdout, code, status = live.decode_response(response, report["remote_status_nonce"], record["transport_status"], record["transport_exit_code"], limit)
        require(stdout == live.bounded_read(live.inside(folder, record["stdout"]), limit)
                and type(record["exit_code"]) is type(code) and code == record["exit_code"] and status == record["status"], "remote status reconstruction failed")
    require(last_time <= live.time_pair(report["finished"]), "capture finished before query")
    rebuilt = summarize(folder, report)
    require(live.canonical(rebuilt) == live.canonical(report["summary"]), "summary reconstruction failed")
    return report, len(indexed), total


def capture(serial):
    require(re.fullmatch(r"[A-Za-z0-9_-]{1,80}", serial), "explicit valid serial required")
    adb = shutil.which("adb")
    require(adb, "adb is unavailable")
    selection = live.json_read(PROJECT / "state.json")["phase_2_evidence_selection"]
    previous_path = live.inside(PROJECT, selection["live_observation_report"])
    previous_bytes = live.bounded_read(previous_path, 2 * MIB)
    require(live.sha256(previous_bytes) == selection["live_observation_report_sha256"], "selected historical report pin mismatch")
    previous = live.json_read(previous_path)
    require(previous["serial"] == serial, "selected phone differs from historical target")
    folder = PROJECT / "evidence/phase-2/device-prerequisites" / dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder.mkdir(parents=True, exist_ok=False)
    for key in ("queries", "tools", "inputs"):
        (folder / key).mkdir()
    for key in TOOLS:
        shutil.copyfile(PROJECT / "scripts" / key, folder / "tools" / key)
    (folder / "inputs/previous-report.json").write_bytes(previous_bytes)
    for source_id, copy in (("config_gz", "previous-config.gz"), ("boot_id_begin", "previous-boot-id.stdout")):
        source = next(item for item in previous["queries"] if item["id"] == source_id)
        value = live.bounded_read(live.inside(previous_path.parent, source["stdout"]), 2 * MIB)
        require(source["status"] == "ok" and len(value) == source["stdout_size"] and live.sha256(value) == source["stdout_sha256"], "historical source changed")
        (folder / "inputs" / copy).write_bytes(value)
    nonce = secrets.token_hex(16)
    report = {"schema_version": 1, "scope": "supplemental_android_read_only_prerequisites", "created": live.stamp(),
              "serial": serial, "adb_path": adb, "adb_executable": live.digest_file(adb),
              "remote_status_nonce": nonce, "remote_stdout_may_include_stderr": True,
              "phone_queries": True, "phone_writes": False, "queries": [],
              "previous_report": selection["live_observation_report"], "previous_report_sha256": live.sha256(previous_bytes)}
    print("CAPTURE " + folder.relative_to(PROJECT).as_posix(), flush=True)
    for number, (name, command, limit) in enumerate(QUERIES):
        argv = [adb, "-s", serial, "exec-out", "su -c " + shlex.quote(live.remote_script(command, nonce))]
        metadata, response, stderr = live.run_bounded(argv, limit + live.STATUS_ALLOWANCE, timeout=15)
        metadata["transport_status"], metadata["transport_exit_code"] = metadata["status"], metadata["exit_code"]
        stdout, metadata["exit_code"], metadata["status"] = live.decode_response(response, nonce, metadata["transport_status"], metadata["transport_exit_code"], limit)
        record = dict(metadata, id=name, command=command, limit=limit, timeout_seconds=15, argv=argv)
        for suffix, value in (("stdout", stdout), ("stderr", stderr), ("response", response)):
            path = f"queries/{number:02d}-{name}.{suffix}"
            (folder / path).write_bytes(value)
            record.update({suffix: path, suffix + "_size": len(value), suffix + "_sha256": live.sha256(value)})
        report["queries"].append(record)
        print(f"{number + 1}/{len(QUERIES)} {name}: {metadata['status']} ({len(stdout)} bytes)", flush=True)
        if name == "root_begin" and (metadata["status"] != "ok" or not re.search(rb"\buid=0\(root\)", stdout)):
            break
        if name == "model_begin" and (metadata["status"] != "ok" or stdout.strip() != b"SM-A515F"):
            break
    report["finished"] = live.stamp()
    report["summary"] = summarize(folder, report)
    live.write_json(folder / "report.json", report)
    live.write_json(folder / "index.json", {"schema_version": 1, "files": [dict(path=path, **live.digest_file(folder / path)) for path in sorted(expected_names()) if (folder / path).is_file()]})
    _, count, total = verify(folder)
    summary = report["summary"]
    print(f"VERIFIED {count} files / {total} bytes; {summary['successful_queries']}/{len(QUERIES)} successful queries; {len(summary['query_failures'])} failures retained.")
    print("EXECUTABLE OWNERSHIP / A51 ENTRY / PAYLOAD LOGS / RETURN / PHASE 2 GATE: false")
    return 0 if all(summary[key] for key in ("capture_complete", "adb_root_verified", "model_verified", "single_boot_observation_verified", "linux_exported_fdt_stable", "configuration_stable")) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--serial")
    modes.add_argument("--verify", type=Path)
    args = parser.parse_args()
    if args.verify:
        report, count, total = verify(args.verify)
        print(f"VERIFIED {count} files / {total} bytes; {report['summary']['successful_queries']}/{len(QUERIES)} successful queries; {len(report['summary']['query_failures'])} failures retained.")
        print("EXECUTABLE OWNERSHIP / A51 ENTRY / PAYLOAD LOGS / RETURN / PHASE 2 GATE: false")
        return 0
    return capture(args.serial)


if __name__ == "__main__":
    raise SystemExit(main())
