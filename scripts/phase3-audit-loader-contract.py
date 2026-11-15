#!/usr/bin/env python3
"""Retain the A51 loader's reset/watchdog/pstore source and live read contract."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess

PROJECT = Path(__file__).resolve().parents[1]
SOURCE = Path("//wsl.localhost/A51-KernelBuilder/opt/a51-everline/src")
SERIAL = "A51_SERIAL_HERE"
FILES = [
    "arch/arm64/boot/dts/exynos/exynos9610.dts",
    "arch/arm64/boot/dts/exynos/exynos9610-rmem.dtsi",
    "drivers/soc/samsung/exynos-reboot.c",
    "drivers/samsung/sec_reboot.c",
    "drivers/watchdog/s3c2410_wdt.c",
    "drivers/soc/samsung/cal-if/exynos9610/cmucal-sfr.c",
    "drivers/soc/samsung/cal-if/exynos9610/cmucal-qch.c",
    "drivers/soc/samsung/cal-if/ra.c",
    "include/linux/sec_debug.h", "include/linux/sec_ext.h",
    "include/dt-bindings/soc/samsung/debug-snapshot-table.h",
    "lib/debug-snapshot-pstore.c", "fs/pstore/ram.c", "fs/pstore/ram_core.c",
]
LOADER_FILES = [
    "prototype/xnu-loader/a51_loader.S", "prototype/xnu-loader/a51_loader.ld",
    "prototype/xnu-loader/xnu_trampoline.S", "prototype/xnu-loader/xnu_trampoline.h",
    "prototype/xnu-loader/pack_a51_payload.py", "scripts/build-xnu-boot-candidate.py",
]


def main():
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    packet = PROJECT / "evidence/phase-3/loader-contract" / stamp
    packet.mkdir(parents=True, exist_ok=False)
    shutil.copy2(__file__, packet / "source.py")
    for rel in FILES:
        target = packet / "android-source" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((SOURCE / rel).read_bytes())
    for rel in LOADER_FILES:
        target = packet / "before" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((PROJECT / rel).read_bytes())
    queries = [
        ("root", "id"),
        ("boot-id", "cat /proc/sys/kernel/random/boot_id"),
        ("pstore-parameters", "for p in /sys/module/ramoops/parameters/*; do printf '%s=' \"$p\"; cat \"$p\"; done"),
        ("reset-dt", "od -An -tx1 /proc/device-tree/reboot/pmu_base"),
        ("watchdog0-dt", "od -An -tx1 /proc/device-tree/watchdog_cl0@10050000/reg; cat /proc/device-tree/watchdog_cl0@10050000/compatible"),
        ("watchdog1-dt", "od -An -tx1 /proc/device-tree/watchdog_cl1@10060000/reg; cat /proc/device-tree/watchdog_cl1@10060000/compatible"),
        ("watchdog-sysfs", "for p in /sys/class/watchdog/watchdog*/{identity,status,timeout,timeleft,bootstatus}; do if test -f \"$p\"; then printf '%s=' \"$p\"; cat \"$p\"; fi; done"),
        ("pstore-attach", "dmesg | /system/bin/grep -E 'ramoops: attached|pstore: Registered|watchdog cluster[01] probe|clock rate:'"),
    ]
    records = []
    for name, shell in queries:
        argv = ["adb", "-s", SERIAL, "shell", "su", "-c", shlex.quote(shell)]
        started = dt.datetime.now(dt.timezone.utc).isoformat()
        try:
            proc = subprocess.run(argv, capture_output=True, timeout=30)
            out, err, rc = proc.stdout, proc.stderr, proc.returncode
        except subprocess.TimeoutExpired as exc:
            out, err, rc = exc.stdout or b"", (exc.stderr or b"") + b"\ntimeout", 124
        (packet / (name + ".stdout")).write_bytes(out)
        (packet / (name + ".stderr")).write_bytes(err)
        record = {"name": name, "argv": argv, "exit_code": rc, "started": started,
                  "finished": dt.datetime.now(dt.timezone.utc).isoformat(),
                  "stdout": out.decode("utf-8", errors="replace"),
                  "stderr": err.decode("utf-8", errors="replace")}
        records.append(record)
        print(json.dumps(record), flush=True)
    parameters = next(r["stdout"] for r in records if r["name"] == "pstore-parameters")
    checks = {
        "root": "uid=0(root)" in records[0]["stdout"] and records[0]["exit_code"] == 0,
        "pstore_2m": "mem_size=2097152" in parameters,
        "pstore_base": "mem_address=4191223808" in parameters or "mem_address=0xf9d10000" in parameters,
        "console_512k": "console_size=524288" in parameters,
        "ecc_disabled": "ecc=0" in parameters,
    }
    result = {"schema_version": 1, "packet": str(packet.relative_to(PROJECT)),
              "scope": "selected Android source and read-only Android runtime; firmware entry and recovery unverified",
              "operations": {"device_reads": True, "device_writes": False, "reboot": False},
              "checks": checks, "queries": records, "qualifying_a51_runs": 0,
              "source_lineage": "retained Android source; not verified Git HEAD"}
    (packet / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    index = [{"path": str(p.relative_to(packet)), "bytes": p.stat().st_size,
              "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
             for p in sorted(packet.rglob("*")) if p.is_file()]
    (packet / "index.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    (PROJECT / "manifests/phase3-loader-contract.json").write_text(
        json.dumps({"packet": result["packet"], "checks": checks}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"packet": result["packet"], "checks": checks}), flush=True)
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
