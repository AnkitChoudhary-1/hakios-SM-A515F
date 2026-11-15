#!/usr/bin/env python3
"""Measure recovery's actual log layout, then return to pinned baseline Android.

Two controlled reboots; no partition, loader, module or pstore write.
Raw output is retained but arbitrary Android/recovery log contents are not printed.
"""
from __future__ import annotations
import json
from pathlib import Path
import shlex
import time
from phase3_support import PROJECT, command, json_write, packet_new, packet_index, require

SERIAL = "A51_SERIAL_HERE"
BOOT_SHA = "eb30609a62999e3282ac81e0a5e56411ef12ec1a39c107171bf3e01209c7cb67"
RECOVERY_SHA = "12412e2008d950260cda627ac7a6b8eac954b49ef9db5573a297f67e4fc85999"


def main():
    packet = packet_new("recovery-contract", Path(__file__))
    records = []
    result = {"schema_version": 1, "packet": packet.relative_to(PROJECT).as_posix(),
        "scope": "Android/recovery read contract and controlled Android return only",
        "operations": {"device_reads": True, "device_writes": False, "reboots": 0},
        "baseline_restored": False, "recovery_layout_verified": False, "checks": {},
        "qualifying_a51_runs": 0}
    recovery_requested = False

    def adb(name, args, **kwargs):
        return command(packet, records, name, ["adb", "-s", SERIAL, *args], **kwargs)

    def shell(name, text, root=False, **kwargs):
        args = ["shell", "su", "-c", shlex.quote(text)] if root else ["shell", text]
        return adb(name, args, **kwargs).stdout.decode("utf-8", errors="replace").strip()

    def wait(mode, deadline=180):
        start = time.monotonic()
        i = 0
        while time.monotonic() - start < deadline:
            i += 1
            output = adb(f"wait-{mode}-{i:03}", ["get-state"], timeout=8, check=False)
            if output.returncode == 0 and output.stdout.strip() == mode.encode():
                return True
            time.sleep(3)
        return False

    try:
        require(shell("android-root", "id", root=True).startswith("uid=0(root)"), "Android root unavailable")
        require(shell("android-model", "getprop ro.product.model") == "SM-A515F", "Unexpected model")
        require(shell("android-completed", "getprop sys.boot_completed") == "1", "Android not booted")
        result["android_boot_id_before"] = shell("android-boot-id", "cat /proc/sys/kernel/random/boot_id", root=True)
        require(shell("boot-device", "readlink -f /dev/block/by-name/boot", root=True) == "/dev/block/sda12", "Unexpected boot target")
        require(shell("android-boot-hash", "sha256sum /dev/block/by-name/boot", root=True).split()[0] == BOOT_SHA, "Baseline mismatch")
        require(shell("android-recovery-hash", "sha256sum /dev/block/by-name/recovery", root=True).split()[0] == RECOVERY_SHA, "Recovery pin mismatch")
        require(shell("android-recovery-size", "blockdev --getsize64 /dev/block/by-name/recovery", root=True) == "71106560", "Recovery size mismatch")
        shell("android-gic-dt", "od -An -tx1 /proc/device-tree/interrupt-controller@12300000/reg", root=True)
        print("Pinned Android/recovery verified; requesting the existing recovery.", flush=True)
        recovery_requested = True
        result["operations"]["reboots"] += 1
        adb("reboot-recovery", ["reboot", "recovery"], timeout=20)
        time.sleep(5)
        require(wait("recovery"), "Recovery did not reconnect within 180 seconds")
        require(shell("recovery-root", "id").startswith("uid=0(root)"), "Recovery root unavailable")
        shell("recovery-kernel", "uname -r")
        shell("recovery-boot-id", "cat /proc/sys/kernel/random/boot_id")
        require(shell("recovery-boot-hash", "sha256sum /dev/block/by-name/boot").split()[0] == BOOT_SHA, "Boot changed in recovery")
        params = shell("recovery-pstore-parameters", 'for p in /sys/module/ramoops/parameters/*; do if test -f "$p"; then printf "%s=" "$p"; cat "$p"; fi; done')
        parsed = dict(line.rsplit("/", 1)[-1].split("=", 1) for line in params.splitlines() if "=" in line)
        result["recovery_ramoops_parameters"] = parsed
        result["checks"] = {"recovery_root": True, "baseline_boot_unchanged": True,
            "pstore_base": parsed.get("mem_address") in ("4191223808", "0xf9d10000"),
            "pstore_2m": parsed.get("mem_size") == "2097152", "console_512k": parsed.get("console_size") == "524288",
            "ecc_disabled": parsed.get("ecc") == "0"}
        shell("recovery-pstore-files", "ls -ln /sys/fs/pstore", check=False)
        shell("recovery-dss-dt", 'for p in /proc/device-tree/reserved-memory/*/log_pstore/reg /proc/device-tree/reserved-memory/*/reg; do if test -f "$p"; then printf "%s=" "$p"; od -An -tx1 "$p"; fi; done', check=False)
        shell("recovery-reset-dt", "od -An -tx1 /proc/device-tree/reboot/pmu_base", check=False)
        shell("recovery-pstore-attach", "dmesg | grep -E 'ramoops: attached|pstore: Registered|watchdog cluster[01] probe|clock rate:'", check=False)
        result["recovery_layout_verified"] = all(result["checks"].values())
    except Exception as exc:
        result["error"] = str(exc)
        print("Recovery-contract operation failed: " + str(exc), flush=True)
    finally:
        if recovery_requested:
            try:
                mode = adb("return-current-mode", ["get-state"], check=False, timeout=8).stdout.strip()
                if mode == b"recovery":
                    print("Recovery measurements retained; returning to baseline Android.", flush=True)
                    result["operations"]["reboots"] += 1
                    adb("reboot-android", ["reboot"], timeout=20)
                    time.sleep(5)
                    require(wait("device"), "Android ADB did not reconnect")
                require(adb("android-final-state", ["get-state"]).stdout.strip() == b"device", "Final state is not Android")
                for i in range(60):
                    if shell(f"android-completed-final-{i:02}", "getprop sys.boot_completed", check=False) == "1":
                        break
                    time.sleep(3)
                else:
                    raise RuntimeError("Android boot completion deadline expired")
                require(shell("android-final-root", "id", root=True).startswith("uid=0(root)"), "Final Android root unavailable")
                require(shell("android-final-boot-hash", "sha256sum /dev/block/by-name/boot", root=True).split()[0] == BOOT_SHA, "Final baseline mismatch")
                result["android_boot_id_after"] = shell("android-final-boot-id", "cat /proc/sys/kernel/random/boot_id", root=True)
                result["baseline_restored"] = True
            except Exception as exc:
                result["return_error"] = str(exc)
                print("Android return remains unverified: " + str(exc), flush=True)
        result["passed"] = result["recovery_layout_verified"] and result["baseline_restored"] and "error" not in result
        json_write(packet / "result.json", result)
        packet_index(packet)
        json_write(PROJECT / "manifests/phase3-recovery-contract.json", {k: result[k] for k in
            ("packet", "passed", "baseline_restored", "recovery_layout_verified", "operations")})
        print(json.dumps({k: result[k] for k in ("packet", "passed", "baseline_restored", "recovery_layout_verified", "operations")}), flush=True)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
