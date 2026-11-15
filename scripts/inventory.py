#!/usr/bin/env python3
"""Capture host, retained inputs and a strictly read-only ADB inventory."""
import datetime as dt
import hashlib
import json
import platform
import shutil
import subprocess
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
WORKSPACE = PROJECT.parent


def command(argv, timeout=20):
    try:
        result = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                timeout=timeout, check=False)
        return {"argv": argv, "exit_code": result.returncode,
                "output": result.stdout.decode("utf-8", errors="replace").replace("\x00", "")}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"argv": argv, "error": str(exc)}


def file_record(path):
    data = {"path": str(path), "exists": path.is_file()}
    if path.is_file():
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        data.update(size=path.stat().st_size, sha256=digest.hexdigest())
    return data


def main():
    manifest = {"schema_version": 1, "captured_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                "host": {"platform": platform.platform(), "python": platform.python_version(),
                         "tools": {name: shutil.which(name) for name in ("git", "python", "adb", "wsl", "curl")}},
                "phone_writes": False, "retained_inputs": [], "source_repositories": []}
    for name in ("everline-ksu/artifacts/kernel.config", "everline-ksu/artifacts/repack-validation.json",
                 "everline-ksu/backups/a51-pixelos-original-boot.img",
                 "everline-ksu/backups/a51-pixelos-original-dtbo.img",
                 "everline-ksu/backups/a51-twrp-original-recovery.img",
                 "everline-ksu/artifacts/A51-PixelOS-Everline-KernelSU-Next-boot.img",
                 "hakios-assessment/ROADMAP.md"):
        manifest["retained_inputs"].append(file_record(WORKSPACE / name))
    for tree_file in sorted((WORKSPACE / "hakios-assessment/sources").glob("*-tree.json")):
        tree = json.loads(tree_file.read_text(encoding="utf-8-sig"))
        manifest["source_repositories"].append({"tree_file": tree_file.name, "commit": tree["sha"],
                                                 "truncated": tree.get("truncated"),
                                                 "tree_listing": file_record(tree_file)})
    adb = shutil.which("adb")
    manifest["device_connectivity"] = command([adb, "devices", "-l"]) if adb else {"error": "adb missing"}
    devices = []
    for line in manifest["device_connectivity"].get("output", "").splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[1] == "device":
            devices.append(fields[0])
    manifest["connected_devices"] = devices
    manifest["device_queries"] = []
    if len(devices) == 1:
        prefix = [adb, "-s", devices[0], "shell"]
        queries = [["getprop", key] for key in
                   ("ro.product.model", "ro.product.device", "ro.hardware", "ro.bootloader",
                    "ro.build.display.id", "ro.build.version.release", "ro.build.version.sdk",
                    "ro.boot.slot_suffix", "ro.boot.flash.locked", "ro.boot.hardware.revision",
                    "ro.boot.revision", "ro.boot.verifiedbootstate", "ro.boot.vbmeta.device_state",
                    "gsm.version.baseband")]
        queries += [["uname", "-a"], ["cat", "/proc/meminfo"], ["wm", "size"],
                    ["dumpsys", "battery"], ["ls", "-l", "/dev/block/by-name"]]
        manifest["device_queries"] = [command(prefix + query) for query in queries]
    else:
        manifest["live_inventory_status"] = "pending: exactly one authorized connected device required"
    destination = PROJECT / "manifests/device-and-inputs.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        previous = json.loads(destination.read_text(encoding="utf-8"))
        old_stamp = dt.datetime.fromisoformat(previous["captured_utc"]).strftime("%Y%m%dT%H%M%S%fZ")
        historical = destination.parent / "inventory-snapshots" / (old_stamp + ".json")
        historical.parent.mkdir(parents=True, exist_ok=True)
        if not historical.exists():
            historical.write_bytes(destination.read_bytes())
    serialized = json.dumps(manifest, indent=2) + "\n"
    current_stamp = dt.datetime.fromisoformat(manifest["captured_utc"]).strftime("%Y%m%dT%H%M%S%fZ")
    historical = destination.parent / "inventory-snapshots" / (current_stamp + ".json")
    historical.parent.mkdir(parents=True, exist_ok=True)
    historical.write_text(serialized, encoding="utf-8")
    destination.write_text(serialized, encoding="utf-8")
    print("Wrote " + str(destination))
    print("Authorized connected devices: " + str(len(devices)))
    print("Retained input hashes: " + str(len(manifest["retained_inputs"])))
    print("Phone writes: false")


if __name__ == "__main__":
    main()
