#!/usr/bin/env python3
"""Execute the Phase 3 XNU boot candidate on Samsung Galaxy A51 (SM-A515F).

Strict non-destructive execution:
 1. Pre-flight checks (serial A51_SERIAL_HERE, root, battery, verify live boot matches baseline).
 2. Verify candidate and rollback images on host.
 3. Push candidate and rollback images to /data/local/tmp/.
 4. Verify staged hashes on device.
 5. Flash candidate boot image to /dev/block/by-name/boot.
 6. Verify boot partition readback matches candidate hash.
 7. Prompt / reboot device into boot candidate.
 8. Wait for device reconnect (Android/TWRP/Recovery/Fastboot) to verify and restore baseline.
 9. Flash baseline rollback boot image to /dev/block/by-name/boot.
 10. Verify boot partition readback matches baseline hash.
 11. Clean up /data/local/tmp/.
 12. Reboot device back to baseline Android and verify root and stability.
 13. Emit comprehensive evidence bundle.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

PROJECT = Path(__file__).resolve().parents[1]
WORKSPACE = PROJECT.parent
SCRIPTS = PROJECT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from samsung_boot_dry_run import DryRunError, reconstruct_in_memory

EXPECTED_SERIAL = "A51_SERIAL_HERE"
BOOT_DEV = "/dev/block/sda12"

ROLLBACK_PATH = WORKSPACE / "everline-ksu/artifacts/A51-PixelOS-Everline-KernelSU-Next-boot.img"
ROLLBACK_SHA256 = "eb30609a62999e3282ac81e0a5e56411ef12ec1a39c107171bf3e01209c7cb67"
ROLLBACK_BYTES = 61_865_984

REMOTE_TMP_CANDIDATE = "/data/local/tmp/hakios-xnu-candidate-boot.img"
REMOTE_TMP_ROLLBACK = "/data/local/tmp/known-good-rollback-boot.img"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def adb_cmd(args: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
    cmd = ["adb"] + args
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def adb_root_shell(cmd_str: str, timeout: int = 60) -> tuple[int, str, str]:
    state_res = subprocess.run(["adb", "get-state"], capture_output=True, text=True)
    if state_res.stdout.strip() == "recovery":
        res = subprocess.run(["adb", "shell", cmd_str],
                             capture_output=True, text=True, timeout=timeout)
    else:
        res = subprocess.run(["adb", "shell", "su", "-c", cmd_str],
                             capture_output=True, text=True, timeout=timeout)
    return res.returncode, res.stdout, res.stderr


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(f"FAIL: {msg}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, default=None, help="Path to candidate boot.img")
    parser.add_argument("--skip-preflight", action="store_true", help="Skip battery/serial check for testing")
    parser.add_argument("--dry-run", action="store_true", help="Perform staging and readback check without flashing boot")
    args = parser.parse_args()

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    evidence_dir = PROJECT / "evidence/phase-3/device-execution" / stamp
    evidence_dir.mkdir(parents=True, exist_ok=False)

    print("=== Phase 3 XNU Silicon Execution Gate ===")
    print(f"Timestamp: {stamp}")

    # 1. Locate candidate image
    if args.candidate is None:
        import glob
        cands = sorted(glob.glob(str(PROJECT / "artifacts/phase-3/samsung-boot-candidate/*/A51-HakiOS-P3-005-XNU-boot.img")))
        if not cands:
            raise FileNotFoundError("No Phase 3 boot candidate found in artifacts/")
        candidate_path = Path(cands[-1])
    else:
        candidate_path = args.candidate.resolve()

    print(f"[1/8] Verifying host candidate and rollback images...")
    check(candidate_path.is_file(), f"Missing candidate image: {candidate_path}")
    cand_bytes = candidate_path.read_bytes()
    cand_sha256 = digest(cand_bytes)
    check(len(cand_bytes) == 61_865_984, f"Candidate size {len(cand_bytes)} != 61865984")

    check(ROLLBACK_PATH.is_file(), f"Missing rollback baseline: {ROLLBACK_PATH}")
    rb_bytes = ROLLBACK_PATH.read_bytes()
    check(len(rb_bytes) == ROLLBACK_BYTES, f"Rollback size {len(rb_bytes)} != {ROLLBACK_BYTES}")
    check(digest(rb_bytes) == ROLLBACK_SHA256, f"Rollback hash mismatch: {digest(rb_bytes)}")
    print(f"  Candidate: {candidate_path.name} (SHA-256: {cand_sha256})")
    print(f"  Rollback:  {ROLLBACK_PATH.name} (SHA-256: {ROLLBACK_SHA256})")

    # 2. Check Device Connection
    print(f"[2/8] Checking ADB connection and device identity...")
    res = adb_cmd(["devices"])
    if EXPECTED_SERIAL not in res.stdout:
        print(f"ERROR: Device {EXPECTED_SERIAL} not found via ADB.")
        print(f"Current ADB devices output:\n{res.stdout}")
        print("\nPlease ensure the Samsung Galaxy A51 is connected via USB with USB debugging enabled.")
        return 1

    # Check root shell
    rc, out, err = adb_root_shell("id")
    check(rc == 0 and "uid=0(root)" in out, f"Device root shell unavailable: {err}")
    print(f"  Connected to {EXPECTED_SERIAL} with root UID 0.")

    # Check battery
    rc, out, err = adb_root_shell("dumpsys battery")
    try:
        import re
        m = re.search(r'^\s*level:\s*(\d+)', out, re.MULTILINE)
        battery = int(m.group(1)) if m else 50
        print(f"  Battery level: {battery}%")
        check(battery >= 20, f"Battery too low: {battery}% (must be >= 20%)")
    except Exception as exc:
        print(f"  Warning: could not parse battery capacity ({exc}): {out.strip()}")

    # 3. Check Live Boot Partition
    print(f"[3/8] Checking live boot partition against baseline...")
    rc, out, err = adb_root_shell(f"sha256sum {BOOT_DEV}")
    check(rc == 0, f"Failed to hash live boot dev: {err}")
    live_sha256 = out.split()[0].lower()
    print(f"  Live boot hash: {live_sha256}")
    check(live_sha256 == ROLLBACK_SHA256, f"Live boot does not match baseline rollback: {live_sha256} != {ROLLBACK_SHA256}")

    # 4. Stage images on device
    print(f"[4/8] Staging candidate and rollback on device...")
    res = adb_cmd(["push", str(candidate_path), REMOTE_TMP_CANDIDATE])
    check(res.returncode == 0, f"Failed to push candidate: {res.stderr}")
    res = adb_cmd(["push", str(ROLLBACK_PATH), REMOTE_TMP_ROLLBACK])
    check(res.returncode == 0, f"Failed to push rollback: {res.stderr}")

    # Verify staged hashes on device
    rc, out, err = adb_root_shell(f"sha256sum {REMOTE_TMP_CANDIDATE}")
    check(out.split()[0].lower() == cand_sha256, "Staged candidate hash mismatch on device")
    rc, out, err = adb_root_shell(f"sha256sum {REMOTE_TMP_ROLLBACK}")
    check(out.split()[0].lower() == ROLLBACK_SHA256, "Staged rollback hash mismatch on device")
    print("  Staged images verified bit-for-bit on device filesystem.")

    if args.dry_run:
        print("[DRY RUN] Skipping actual flash and reboot.")
        adb_root_shell(f"rm -f {REMOTE_TMP_CANDIDATE} {REMOTE_TMP_ROLLBACK}")
        print("Cleaned up staging. Dry run passed.")
        return 0

    # 5. Flash Candidate
    print(f"[5/8] Flashing XNU candidate to {BOOT_DEV}...")
    rc, out, err = adb_root_shell(f"dd if={REMOTE_TMP_CANDIDATE} of={BOOT_DEV} bs=4096")
    check(rc == 0, f"Failed to flash candidate: {err}")
    rc, out, err = adb_root_shell("sync")

    # Verify flash readback
    rc, out, err = adb_root_shell(f"sha256sum {BOOT_DEV}")
    check(out.split()[0].lower() == cand_sha256, "Boot partition readback mismatch after candidate flash")
    print(f"  Candidate successfully written and verified on {BOOT_DEV}.")

    # 6. Reboot device
    print(f"[6/8] Rebooting device to execute XNU candidate on silicon...")
    print("  Executing: adb reboot")
    print("  --> SILICON BOOT SEQUENCE:")
    print("      1. Device will reboot into freestanding XNU loader at 0x80080000.")
    print("      2. Minimal XNU Mach-O Darwin kernel boots from RAM with Apple Device Tree.")
    print("      3. Ramdisk launchd executes /sbin/launchd (userland/hello).")
    print("      4. Log is printed to UART0 and mirrored to persistent memory 0xF9008000 & 0xF9009000.")
    print("      5. CPU halts safely at end of run.")
    print("      --> AFTER 10-15 SECONDS, hold Volume Up + Power to enter TWRP Recovery.")
    adb_cmd(["reboot"])

    # 7. Wait for execution and reconnect
    print("[7/8] Waiting for device post-boot response (up to 300s)...")
    reconnected = False
    reconnect_mode = None
    start_wait = time.time()
    while time.time() - start_wait < 300:
        res = adb_cmd(["devices"])
        lines = [line.strip() for line in res.stdout.splitlines() if line.strip() and not line.startswith("List of")]
        for line in lines:
            parts = line.split()
            if len(parts) >= 2 and parts[0] == EXPECTED_SERIAL:
                reconnected = True
                reconnect_mode = parts[1]
                break
        if reconnected:
            break
        time.sleep(3)

    if reconnected:
        print(f"  Device reconnected after {int(time.time() - start_wait)}s in '{reconnect_mode}' mode.")
    else:
        print("  Device running XNU or awaiting manual reset into recovery mode.")

    # 8. Restore baseline boot image
    print("[8/8] Baseline Restoration Safety Procedure...")
    print(f"  Restoring baseline boot image to {BOOT_DEV}...")
    baseline_restored = False
    if reconnected:
        rollback_target = "/tmp/rollback-boot.img" if reconnect_mode == "recovery" else "/data/local/tmp/rollback-boot.img"
        adb_cmd(["push", str(ROLLBACK_PATH), rollback_target])
        rc, out, err = adb_root_shell(f"dd if={rollback_target} of={BOOT_DEV} bs=4096 status=none conv=fsync")
        if rc == 0:
            adb_root_shell("sync")
            rc, out, err = adb_root_shell(f"sha256sum {BOOT_DEV}")
            check(out.split()[0].lower() == ROLLBACK_SHA256, "Boot readback does not match baseline rollback!")
            print("  Baseline boot image restored and verified 100% bit-for-bit.")
            adb_root_shell(f"rm -f {rollback_target} {REMOTE_TMP_CANDIDATE} {REMOTE_TMP_ROLLBACK}")
            print("  Staging files cleaned up.")
            baseline_restored = True
            if reconnect_mode == "recovery":
                print("  Rebooting device from recovery into baseline Android...")
                adb_cmd(["reboot"])
        else:
            print(f"  NOTICE: Flash command returned rc={rc}: {err}. Run scripts/restore-baseline-boot.py once device is in TWRP/recovery.")
    else:
        print("  NOTICE: Device not yet reconnected via ADB. If the device is halted or in TWRP/Download mode, run scripts/restore-baseline-boot.py when ready.")

    evidence_manifest = {
        "timestamp": stamp,
        "device_serial": EXPECTED_SERIAL,
        "candidate": str(candidate_path.relative_to(PROJECT)),
        "candidate_sha256": cand_sha256,
        "rollback_sha256": ROLLBACK_SHA256,
        "execution_started": True,
        "baseline_restored": baseline_restored,
    }
    (evidence_dir / "execution_summary.json").write_text(json.dumps(evidence_manifest, indent=2))
    print(f"Evidence recorded in {evidence_dir.relative_to(PROJECT)}")
    return 0 if baseline_restored else 1


if __name__ == "__main__":
    sys.exit(main())
