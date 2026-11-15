#!/usr/bin/env python3
"""Restore baseline KernelSU boot image and clean up temporary files."""
from pathlib import Path
import subprocess
import sys

PROJECT = Path(__file__).resolve().parents[1]
WORKSPACE = PROJECT.parent
ROLLBACK_IMAGE = WORKSPACE / "everline-ksu/artifacts/A51-PixelOS-Everline-KernelSU-Next-boot.img"
EXPECTED_SHA = "eb30609a62999e3282ac81e0a5e56411ef12ec1a39c107171bf3e01209c7cb67"
BOOT_DEV = "/dev/block/sda12"

def get_adb_state() -> str:
    res = subprocess.run(["adb", "get-state"], capture_output=True, text=True)
    return res.stdout.strip()

def adb_root(cmd: str) -> subprocess.CompletedProcess[str]:
    state = get_adb_state()
    if state == "recovery":
        return subprocess.run(["adb", "shell", cmd], capture_output=True, text=True)
    else:
        return subprocess.run(["adb", "shell", "su", "-c", cmd], capture_output=True, text=True)

def main():
    print("Verifying host rollback image...")
    data = ROLLBACK_IMAGE.read_bytes()
    assert len(data) == 61_865_984
    import hashlib
    assert hashlib.sha256(data).hexdigest() == EXPECTED_SHA
    print("Host rollback image verified.")

    stage_path = "/tmp/rollback-boot.img" if get_adb_state() == "recovery" else "/data/local/tmp/rollback-boot.img"
    print(f"Pushing rollback image to device ({stage_path})...")
    subprocess.run(["adb", "push", str(ROLLBACK_IMAGE), stage_path], check=True)

    print("Flashing rollback image to boot partition...")
    res = adb_root(f"dd if={stage_path} of={BOOT_DEV} bs=4096 status=none conv=fsync")
    assert res.returncode == 0, f"Flash failed: {res.stderr}"

    print("Verifying flashed boot partition SHA-256 on device...")
    res = adb_root(f"sha256sum {BOOT_DEV}")
    assert res.returncode == 0, f"Readback failed: {res.stderr}"
    device_sha = res.stdout.split()[0].lower()
    print("Device boot partition SHA-256:", device_sha)
    assert device_sha == EXPECTED_SHA, f"Mismatch: {device_sha} != {EXPECTED_SHA}"

    print("Cleaning up /data/local/tmp staging files...")
    adb_root("rm -f /data/local/tmp/rollback-boot.img /data/local/tmp/hakios-candidate-boot.img /data/local/tmp/known-good-rollback-boot.img /data/local/tmp/early_probe.ko")

    print("RESTORATION COMPLETE: Boot partition successfully restored to baseline.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

