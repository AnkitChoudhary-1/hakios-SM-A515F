#!/usr/bin/env python3
"""Capture a short Android boot window and return an A51 to recovery.

This incident helper performs no partition writes.  Its default mode only
inventories KernelSU module metadata and relevant process/property state.  An
explicit option can add KernelSU's reversible ``disable`` marker to each
currently enabled module.  It always requests recovery immediately after the
bounded Android query so a known reboot loop is not allowed to continue
unattended.
"""

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import time


PROJECT = Path(__file__).resolve().parents[1]


def stamp():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def run(argv, timeout=20):
    started = stamp()
    try:
        proc = subprocess.run(argv, capture_output=True, timeout=timeout, shell=False)
        return {
            "argv": argv,
            "started": started,
            "finished": stamp(),
            "exit_code": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "status": "passed" if proc.returncode == 0 else "failed",
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "argv": argv,
            "started": started,
            "finished": stamp(),
            "exit_code": None,
            "stdout": exc.stdout or b"",
            "stderr": exc.stderr or b"",
            "status": "timeout",
        }


def retain(folder, number, name, result):
    stem = f"{number:02d}-{name}"
    out_name = stem + ".stdout"
    err_name = stem + ".stderr"
    (folder / out_name).write_bytes(result.pop("stdout"))
    (folder / err_name).write_bytes(result.pop("stderr"))
    result["stdout"] = out_name
    result["stderr"] = err_name
    result["stdout_pin"] = pin(folder / out_name)
    result["stderr_pin"] = pin(folder / err_name)
    result["id"] = name
    return result


def pin(path):
    data = Path(path).read_bytes()
    return {"bytes": len(data), "sha256": sha256(data)}


def wait_for_mode(adb, serial, wanted, timeout, observations):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        devices = run([adb, "devices"], timeout=5)
        state = "absent"
        text = devices["stdout"].decode("utf-8", errors="replace")
        for line in text.splitlines()[1:]:
            fields = line.split()
            if fields and fields[0] == serial:
                state = fields[1] if len(fields) > 1 else "unknown"
                break
        mode = state
        if state == "device":
            prop = run([adb, "-s", serial, "shell", "getprop", "ro.twrp.boot"], timeout=5)
            if prop["exit_code"] == 0:
                mode = "recovery" if prop["stdout"].strip() == b"1" else "android"
        current = {"at": stamp(), "transport": state, "mode": mode}
        if (state, mode) != last:
            observations.append(current)
            print(f"DEVICE transport={state} mode={mode}", flush=True)
            last = (state, mode)
        if mode == wanted:
            return True
        time.sleep(0.25)
    return False


def make_index(folder):
    return {
        path.relative_to(folder).as_posix(): pin(path)
        for path in sorted(folder.rglob("*"))
        if path.is_file() and path.name != "index.json"
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", default="A51_SERIAL_HERE")
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--android-timeout", type=int, default=120)
    parser.add_argument("--recovery-timeout", type=int, default=120)
    parser.add_argument("--disable-modules", action="store_true")
    args = parser.parse_args()

    adb = shutil.which(args.adb)
    if not adb:
        raise SystemExit("adb executable not found")
    tag = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = PROJECT / "evidence" / "phase-2" / "bootloop-live" / tag
    folder.mkdir(parents=True, exist_ok=False)
    print("CAPTURE " + str(folder), flush=True)

    report = {
        "schema_version": 1,
        "scope": "bootloop_android_bounded_inventory",
        "created": stamp(),
        "serial": args.serial,
        "partition_writes": False,
        "userdata_writes": args.disable_modules,
        "module_state_changes": args.disable_modules,
        "commands": [],
        "device_observations": [],
    }

    initial = run([adb, "-s", args.serial, "shell", "getprop", "ro.twrp.boot"])
    report["commands"].append(retain(folder, 0, "initial-recovery", initial))
    if initial["exit_code"] != 0 or (folder / initial["stdout"]).read_bytes().strip() != b"1":
        report["status"] = "refused_not_in_recovery"
        (folder / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        (folder / "index.json").write_text(json.dumps(make_index(folder), indent=2) + "\n", encoding="utf-8")
        return 2

    reboot = run([adb, "-s", args.serial, "reboot", "system"])
    report["commands"].append(retain(folder, 1, "reboot-system", reboot))
    if reboot["exit_code"] != 0:
        report["status"] = "reboot_command_failed"
        (folder / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        (folder / "index.json").write_text(json.dumps(make_index(folder), indent=2) + "\n", encoding="utf-8")
        return 3

    android_seen = wait_for_mode(adb, args.serial, "android", args.android_timeout,
                                 report["device_observations"])
    report["android_seen"] = android_seen
    query_number = 2
    if android_seen:
        mutation = r'''
echo '===MODULE_DISABLE_TRANSACTION==='
changed=0
for module_dir in /data/adb/modules/*; do
  [ -d "$module_dir" ] || continue
  module_id=${module_dir##*/}
  if [ -e "$module_dir/remove" ]; then
    echo "MODULE_SKIP_REMOVE $module_id"
  elif [ -e "$module_dir/disable" ]; then
    echo "MODULE_ALREADY_DISABLED $module_id"
  else
    : > "$module_dir/disable" || exit 41
    echo "MODULE_DISABLED $module_id"
    changed=$((changed + 1))
  fi
done
sync
echo "MODULE_DISABLE_COUNT $changed"''' if args.disable_modules else ""
        command = r'''set -o pipefail
''' + mutation + r'''
echo '===IDENTITY==='; id; id -Z
echo '===BOOT==='; cat /proc/sys/kernel/random/boot_id; cat /proc/uptime
getprop sys.boot_completed; getprop ro.boot.bootreason; getprop sys.boot.reason
getprop sys.powerctl; uname -a
echo '===KSU_MODULES===' 
module_count=0
active_module_count=0
for module_dir in /data/adb/modules/*; do
  [ -d "$module_dir" ] || continue
  module_count=$((module_count + 1))
  module_id=${module_dir##*/}
  echo "MODULE_BEGIN $module_id"
  if [ -f "$module_dir/module.prop" ]; then cat "$module_dir/module.prop"; fi
  for marker in disable remove update; do
    if [ -e "$module_dir/$marker" ]; then echo "MARKER $module_id $marker"; fi
  done
  if [ ! -e "$module_dir/disable" ] && [ ! -e "$module_dir/remove" ]; then
    active_module_count=$((active_module_count + 1))
    echo "MODULE_STILL_ACTIVE $module_id"
  fi
  find "$module_dir" -maxdepth 2 -type f 2>/dev/null | sort
  echo "MODULE_END $module_id"
done
echo "MODULE_COUNT $module_count"
echo "MODULE_ACTIVE_COUNT $active_module_count"
echo '===KSU_FILES===' 
find /data/adb/ksu -maxdepth 2 -type f 2>/dev/null | sort
echo '===RELEVANT_PROCESSES===' 
ps -A -o USER,PID,PPID,NAME,ARGS 2>/dev/null | grep -E 'ksu|franco|kernel|magisk' || true
echo '===LOADED_MODULES===' 
cat /proc/modules
echo '===RECENT_KSU_DMESG===' 
dmesg | grep -i -E 'KernelSU|TIMA|RKP|VMM|hypervisor' | tail -n 250'''
        remote = "su -c " + shlex.quote(command)
        inventory = run([adb, "-s", args.serial, "exec-out", remote], timeout=12)
        inventory_record = retain(folder, query_number, "android-inventory", inventory)
        report["commands"].append(inventory_record)
        query_number += 1
        report["inventory_succeeded"] = inventory["exit_code"] == 0
        inventory_text = (folder / inventory_record["stdout"]).read_text(
            encoding="utf-8", errors="replace")
        report["module_disable_verified"] = (
            not args.disable_modules
            or (
                "===MODULE_DISABLE_TRANSACTION===" in inventory_text
                and "MODULE_ACTIVE_COUNT 0" in inventory_text
            )
        )
    else:
        report["inventory_succeeded"] = False

    recovery_request = run([adb, "-s", args.serial, "reboot", "recovery"], timeout=8)
    report["commands"].append(retain(folder, query_number, "return-recovery", recovery_request))
    report["recovery_request_succeeded"] = recovery_request["exit_code"] == 0
    recovery_seen = wait_for_mode(adb, args.serial, "recovery", args.recovery_timeout,
                                  report["device_observations"])
    report["recovery_seen"] = recovery_seen
    report["status"] = "passed" if (
        android_seen
        and report["inventory_succeeded"]
        and report.get("module_disable_verified", not args.disable_modules)
        and recovery_seen
    ) else "incomplete"
    report["finished"] = stamp()
    (folder / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (folder / "index.json").write_text(json.dumps(make_index(folder), indent=2) + "\n", encoding="utf-8")
    print("RESULT " + report["status"], flush=True)
    print("REPORT " + str(folder / "report.json"), flush=True)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
