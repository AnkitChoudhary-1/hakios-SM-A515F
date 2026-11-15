#!/usr/bin/env python3
"""Observe one bounded Android boot, retain logs, then return to recovery.

The helper starts only from TWRP.  It performs no partition or userdata
writes.  During the observation window it follows every logcat buffer,
captures rooted dmesg snapshots, and polls boot identity, uptime, power
properties, and KernelSU module-disable markers.  It requests recovery only
after the observation window (or after a spontaneous reboot is detected).
"""

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import time


PROJECT = Path(__file__).resolve().parents[1]


def stamp():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def pin(path):
    data = Path(path).read_bytes()
    return {"bytes": len(data), "sha256": sha256(data)}


def run(argv, timeout=10):
    started = stamp()
    try:
        proc = subprocess.run(argv, capture_output=True, timeout=timeout,
                              shell=False)
        return {
            "argv": argv,
            "started": started,
            "finished": stamp(),
            "exit_code": proc.returncode,
            "stdout_bytes": proc.stdout,
            "stderr_bytes": proc.stderr,
            "status": "passed" if proc.returncode == 0 else "failed",
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "argv": argv,
            "started": started,
            "finished": stamp(),
            "exit_code": None,
            "stdout_bytes": exc.stdout or b"",
            "stderr_bytes": exc.stderr or b"",
            "status": "timeout",
        }


def retain(folder, number, name, result):
    stem = f"{number:03d}-{name}"
    stdout_path = folder / (stem + ".stdout")
    stderr_path = folder / (stem + ".stderr")
    stdout_path.write_bytes(result.pop("stdout_bytes"))
    stderr_path.write_bytes(result.pop("stderr_bytes"))
    result["id"] = name
    result["stdout"] = stdout_path.name
    result["stderr"] = stderr_path.name
    result["stdout_pin"] = pin(stdout_path)
    result["stderr_pin"] = pin(stderr_path)
    return result


def adb_mode(adb, serial):
    devices = run([adb, "devices"], timeout=5)
    state = "absent"
    for line in devices["stdout_bytes"].decode("utf-8", errors="replace").splitlines()[1:]:
        fields = line.split()
        if fields and fields[0] == serial:
            state = fields[1] if len(fields) > 1 else "unknown"
            break
    if state == "recovery":
        return state, "recovery"
    if state != "device":
        return state, state
    prop = run([adb, "-s", serial, "shell", "getprop", "ro.twrp.boot"],
               timeout=5)
    if prop["exit_code"] != 0:
        return state, "unknown"
    return state, "recovery" if prop["stdout_bytes"].strip() == b"1" else "android"


def observe_mode(adb, serial, observations, last):
    state, mode = adb_mode(adb, serial)
    current = (state, mode)
    if current != last:
        item = {"at": stamp(), "transport": state, "mode": mode}
        observations.append(item)
        print(f"DEVICE transport={state} mode={mode}", flush=True)
    return current


def wait_for_mode(adb, serial, wanted, timeout, observations):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = observe_mode(adb, serial, observations, last)
        if last[1] == wanted:
            return True
        time.sleep(0.25)
    return False


def start_stream(argv, folder, name):
    stdout_path = folder / f"stream-{name}.stdout"
    stderr_path = folder / f"stream-{name}.stderr"
    stdout_handle = stdout_path.open("wb")
    stderr_handle = stderr_path.open("wb")
    started = stamp()
    proc = subprocess.Popen(argv, stdout=stdout_handle, stderr=stderr_handle,
                            shell=False)
    return {
        "argv": argv,
        "name": name,
        "started": started,
        "proc": proc,
        "stdout_handle": stdout_handle,
        "stderr_handle": stderr_handle,
        "stdout_path": stdout_path,
        "stderr_path": stderr_path,
    }


def stop_stream(stream):
    proc = stream.pop("proc")
    running_before_stop = proc.poll() is None
    if running_before_stop:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    stream.pop("stdout_handle").close()
    stream.pop("stderr_handle").close()
    stdout_path = stream.pop("stdout_path")
    stderr_path = stream.pop("stderr_path")
    stream.update({
        "finished": stamp(),
        "exit_code": proc.returncode,
        "running_before_host_stop": running_before_stop,
        "stdout": stdout_path.name,
        "stderr": stderr_path.name,
        "stdout_pin": pin(stdout_path),
        "stderr_pin": pin(stderr_path),
    })
    return stream


def make_index(folder):
    return {
        path.relative_to(folder).as_posix(): pin(path)
        for path in sorted(folder.rglob("*"))
        if path.is_file() and path.name != "index.json"
    }


def return_to_recovery(adb, serial, timeout, observations, folder, commands,
                       number):
    deadline = time.monotonic() + timeout
    last = None
    last_request = 0.0
    attempt = 0
    while time.monotonic() < deadline:
        last = observe_mode(adb, serial, observations, last)
        if last[1] == "recovery":
            return True, number
        now = time.monotonic()
        if last[1] == "android" and now - last_request >= 5:
            request = run([adb, "-s", serial, "reboot", "recovery"], timeout=8)
            commands.append(retain(folder, number,
                                   f"return-recovery-{attempt}", request))
            number += 1
            attempt += 1
            last_request = now
        time.sleep(0.5)
    return False, number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", default="A51_SERIAL_HERE")
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--observe-seconds", type=int, default=180)
    parser.add_argument("--poll-seconds", type=float, default=3.0)
    parser.add_argument("--android-timeout", type=int, default=120)
    parser.add_argument("--recovery-timeout", type=int, default=180)
    args = parser.parse_args()
    if args.observe_seconds < 30:
        raise SystemExit("--observe-seconds must be at least 30")
    if args.poll_seconds < 1:
        raise SystemExit("--poll-seconds must be at least 1")

    adb = shutil.which(args.adb)
    if not adb:
        raise SystemExit("adb executable not found")

    tag = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = PROJECT / "evidence" / "phase-2" / "bootloop-stability" / tag
    folder.mkdir(parents=True, exist_ok=False)
    print("CAPTURE " + str(folder), flush=True)
    report = {
        "schema_version": 1,
        "scope": "post_module_isolation_android_stability",
        "created": stamp(),
        "serial": args.serial,
        "requested_observation_seconds": args.observe_seconds,
        "poll_seconds": args.poll_seconds,
        "partition_writes": False,
        "userdata_writes": False,
        "host_reboot_during_observation": False,
        "privacy": "stream-logcat.stdout may contain personal application data; do not quote it publicly",
        "commands": [],
        "polls": [],
        "device_observations": [],
    }

    initial = run([adb, "-s", args.serial, "shell", "getprop", "ro.twrp.boot"])
    report["commands"].append(retain(folder, 0, "initial-recovery", initial))
    if initial["exit_code"] != 0 or (folder / initial["stdout"]).read_bytes().strip() != b"1":
        report["status"] = "refused_not_in_recovery"
        report["finished"] = stamp()
        (folder / "report.json").write_text(json.dumps(report, indent=2) + "\n",
                                             encoding="utf-8")
        (folder / "index.json").write_text(json.dumps(make_index(folder), indent=2) + "\n",
                                            encoding="utf-8")
        return 2

    reboot = run([adb, "-s", args.serial, "reboot", "system"])
    report["commands"].append(retain(folder, 1, "reboot-system", reboot))
    if reboot["exit_code"] != 0:
        report["status"] = "reboot_command_failed"
        report["finished"] = stamp()
        (folder / "report.json").write_text(json.dumps(report, indent=2) + "\n",
                                             encoding="utf-8")
        (folder / "index.json").write_text(json.dumps(make_index(folder), indent=2) + "\n",
                                            encoding="utf-8")
        return 3

    android_seen = wait_for_mode(adb, args.serial, "android", args.android_timeout,
                                 report["device_observations"])
    report["android_seen"] = android_seen
    number = 2
    stream = None
    baseline_boot_id = None
    last_boot_id = None
    spontaneous_reboot = False
    completed_window = False
    observation_started = None
    observation_finished = None

    if android_seen:
        stream = start_stream(
            [adb, "-s", args.serial, "logcat", "-b", "all", "-v", "threadtime"],
            folder, "logcat")
        dmesg_start_command = "dmesg"
        dmesg_start = run([
            adb, "-s", args.serial, "exec-out",
            "su -c " + shlex.quote(dmesg_start_command)
        ], timeout=12)
        report["commands"].append(retain(folder, number, "dmesg-start",
                                          dmesg_start))
        number += 1

        poll_command = r'''set -o pipefail
printf 'BOOT_ID '; cat /proc/sys/kernel/random/boot_id
printf 'UPTIME '; cat /proc/uptime
printf 'BOOT_COMPLETED '; getprop sys.boot_completed
printf 'BOOT_REASON '; getprop ro.boot.bootreason
printf 'SYSTEM_BOOT_REASON '; getprop sys.boot.reason
printf 'POWERCTL '; getprop sys.powerctl
for module_dir in /data/adb/modules/*; do
  [ -d "$module_dir" ] || continue
  module_id=${module_dir##*/}
  disabled=0; removed=0
  [ -e "$module_dir/disable" ] && disabled=1
  [ -e "$module_dir/remove" ] && removed=1
  printf 'MODULE %s disable=%s remove=%s\n' "$module_id" "$disabled" "$removed"
done'''
        remote_poll = "su -c " + shlex.quote(poll_command)
        observation_started = stamp()
        started_mono = time.monotonic()
        deadline = started_mono + args.observe_seconds
        while True:
            poll = run([adb, "-s", args.serial, "exec-out", remote_poll],
                       timeout=8)
            poll_record = retain(folder, number, "stability-poll", poll)
            number += 1
            poll_text = (folder / poll_record["stdout"]).read_text(
                encoding="utf-8", errors="replace")
            match = re.search(r"^BOOT_ID ([0-9a-f-]+)$", poll_text,
                              flags=re.MULTILINE)
            boot_id = match.group(1) if match else None
            if boot_id and baseline_boot_id is None:
                baseline_boot_id = boot_id
            if boot_id:
                last_boot_id = boot_id
            if baseline_boot_id and boot_id and boot_id != baseline_boot_id:
                spontaneous_reboot = True
            report["polls"].append({
                **poll_record,
                "elapsed_seconds": round(time.monotonic() - started_mono, 3),
                "boot_id": boot_id,
            })
            if poll_record["exit_code"] != 0:
                state, mode = adb_mode(adb, args.serial)
                if mode != "android":
                    spontaneous_reboot = True
                    report["device_observations"].append({
                        "at": stamp(), "transport": state, "mode": mode,
                        "during_observation": True,
                    })
                    break
            now = time.monotonic()
            if now >= deadline:
                completed_window = True
                break
            time.sleep(min(args.poll_seconds, max(0.0, deadline - now)))
        observation_finished = stamp()

        if not spontaneous_reboot:
            dmesg_end = run([
                adb, "-s", args.serial, "exec-out",
                "su -c " + shlex.quote("dmesg")
            ], timeout=12)
            report["commands"].append(retain(folder, number, "dmesg-end",
                                              dmesg_end))
            number += 1

    if stream is not None:
        report["streams"] = [stop_stream(stream)]

    report.update({
        "observation_started": observation_started,
        "observation_finished": observation_finished,
        "completed_observation_window": completed_window,
        "baseline_boot_id": baseline_boot_id,
        "last_boot_id": last_boot_id,
        "same_boot_id": bool(baseline_boot_id and baseline_boot_id == last_boot_id),
        "spontaneous_reboot_detected": spontaneous_reboot,
    })
    stable = bool(
        android_seen
        and completed_window
        and baseline_boot_id
        and baseline_boot_id == last_boot_id
        and not spontaneous_reboot
        and report.get("streams", [{}])[0].get("running_before_host_stop")
    )
    report["stable_observation"] = stable

    recovery_seen, number = return_to_recovery(
        adb, args.serial, args.recovery_timeout,
        report["device_observations"], folder, report["commands"], number)
    report["recovery_seen"] = recovery_seen
    report["status"] = "passed" if stable and recovery_seen else "incomplete"
    report["finished"] = stamp()
    (folder / "report.json").write_text(json.dumps(report, indent=2) + "\n",
                                         encoding="utf-8")
    (folder / "index.json").write_text(json.dumps(make_index(folder), indent=2) + "\n",
                                        encoding="utf-8")
    print("RESULT " + report["status"], flush=True)
    print("REPORT " + str(folder / "report.json"), flush=True)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
