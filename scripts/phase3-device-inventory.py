#!/usr/bin/env python3
"""Retain a fresh, read-only A51 inventory before Phase 3 execution work."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

PROJECT = Path(__file__).resolve().parents[1]
SERIAL = "A51_SERIAL_HERE"
BASELINE = "eb30609a62999e3282ac81e0a5e56411ef12ec1a39c107171bf3e01209c7cb67"


def main() -> int:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    packet = PROJECT / "evidence/phase-3/continuation-inventory" / stamp
    packet.mkdir(parents=True)
    queries = [
        ("adb-state", ["get-state"]),
        ("identity", ["shell", "getprop", "ro.product.model"]),
        ("boot-completed", ["shell", "getprop", "sys.boot_completed"]),
        ("kernel", ["shell", "uname", "-r"]),
        ("battery", ["shell", "dumpsys", "battery"]),
    ]
    root_queries = [
        ("root", "id"),
        ("boot-id", "cat /proc/sys/kernel/random/boot_id"),
        ("boot-device", "readlink -f /dev/block/by-name/boot"),
        ("boot-bytes", "blockdev --getsize64 /dev/block/by-name/boot"),
        ("boot-hash", "sha256sum /dev/block/by-name/boot"),
        ("online-cpus", "cat /sys/devices/system/cpu/online"),
        ("memory-map", "cat /proc/iomem"),
        ("module-early-probe", "ls /sys/module/early_probe"),
        ("module-log-reader", "ls /sys/module/hakios_log_reader"),
        ("persistent-devices", "ls -l /sys/fs/pstore"),
    ]
    queries += [(name, ["shell", "su", "-c", shlex.quote(cmd)])
                for name, cmd in root_queries]
    records = []
    for name, args in queries:
        command = ["adb", "-s", SERIAL, *args]
        started = dt.datetime.now(dt.timezone.utc).isoformat()
        try:
            res = subprocess.run(command, capture_output=True, timeout=45)
            out = res.stdout.decode("utf-8", errors="replace")
            err = res.stderr.decode("utf-8", errors="replace")
            rc = res.returncode
        except subprocess.TimeoutExpired as exc:
            out = (exc.stdout or b"").decode("utf-8", errors="replace")
            err = "timeout: " + (exc.stderr or b"").decode("utf-8", errors="replace")
            rc = 124
        (packet / (name + ".stdout")).write_text(out, encoding="utf-8")
        (packet / (name + ".stderr")).write_text(err, encoding="utf-8")
        records.append({"name": name, "command": command, "started": started,
                        "finished": dt.datetime.now(dt.timezone.utc).isoformat(),
                        "exit_code": rc, "stdout": out, "stderr": err})
        print(json.dumps({"query": name, "exit_code": rc, "stdout": out, "stderr": err}), flush=True)
        if name == "adb-state" and (rc or out.strip() != "device"):
            break
    by_name = {r["name"]: r for r in records}
    required = {"adb-state": "device", "identity": "SM-A515F", "boot-completed": "1",
                "boot-device": "/dev/block/sda12", "boot-bytes": "61865984"}
    checks = {name: name in by_name and by_name[name]["exit_code"] == 0
              and by_name[name]["stdout"].strip() == value for name, value in required.items()}
    checks["root"] = "root" in by_name and by_name["root"]["exit_code"] == 0 and "uid=0(root)" in by_name["root"]["stdout"]
    checks["baseline"] = "boot-hash" in by_name and by_name["boot-hash"]["exit_code"] == 0 and by_name["boot-hash"]["stdout"].split()[:1] == [BASELINE]
    result = {"schema_version": 1, "scope": "read_only_android_inventory", "serial": SERIAL,
              "operations": {"device_reads": True, "device_writes": False, "reboot": False},
              "checks": checks, "baseline_ready": all(checks.values()), "queries": records}
    (packet / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    (packet / "source.py").write_bytes(Path(__file__).read_bytes())
    index = [{"path": str(p.relative_to(packet)), "bytes": p.stat().st_size,
              "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
             for p in sorted(packet.iterdir()) if p.is_file()]
    (packet / "index.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"packet": str(packet.relative_to(PROJECT)), "checks": checks,
                      "baseline_ready": result["baseline_ready"]}), flush=True)
    return 0 if result["baseline_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
