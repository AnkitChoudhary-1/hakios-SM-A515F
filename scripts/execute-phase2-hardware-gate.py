#!/usr/bin/env python3
"""Execute the Phase 2 early-entry candidate on Samsung Galaxy A51 (SM-A515F).

Strict non-destructive execution:
 1. Pre-flight checks (serial, root, battery, verify live boot matches baseline).
 2. Push candidate, rollback, and early_probe.ko to /data/local/tmp/.
 3. Verify staged hashes on device.
 4. Flash candidate boot image to /dev/block/by-name/boot.
 5. Verify boot partition readback matches candidate hash.
 6. Reboot device and wait for reconnect.
 7. Wait for Android boot completed.
 8. Insert early_probe.ko to retrieve hardware hakios_early_record via pr_emerg.
 9. Capture dmesg and verify:
      status == 1 (HKE_EXECUTED)
      reason == 0 (HKE_REASON_NONE)
      payload_marker == 0x3143455845494b48 (HKEXEC1)
      payload_val == expected arithmetic value
 10. Immediately restore baseline rollback boot image to /dev/block/by-name/boot.
 11. Verify boot partition readback matches baseline hash.
 12. Clean up /data/local/tmp/.
 13. Reboot device back to baseline Android and verify root and stability.
 14. Emit comprehensive evidence bundle.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


PROJECT = Path(__file__).resolve().parents[1]
WORKSPACE = PROJECT.parent

CANDIDATE_PATH = PROJECT / "artifacts/phase-2/samsung-boot-candidate/20261113T010751116216Z/A51-HakiOS-Early-Entry-boot.img"
CANDIDATE_SHA256 = "2cb8e6d443fce3d8196c2f0a25fb608dbe9e692c572b64d5f0df623584dcdf1a"
CANDIDATE_BYTES = 61_865_984

ROLLBACK_PATH = WORKSPACE / "everline-ksu/artifacts/A51-PixelOS-Everline-KernelSU-Next-boot.img"
ROLLBACK_SHA256 = "eb30609a62999e3282ac81e0a5e56411ef12ec1a39c107171bf3e01209c7cb67"
ROLLBACK_BYTES = 61_865_984

PROBE_MODULE_PATH = PROJECT / "artifacts/early_probe.ko"

REMOTE_TMP_CANDIDATE = "/data/local/tmp/hakios-candidate-boot.img"
REMOTE_TMP_ROLLBACK = "/data/local/tmp/known-good-rollback-boot.img"
REMOTE_TMP_PROBE = "/data/local/tmp/early_probe.ko"
BOOT_DEV = "/dev/block/by-name/boot"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def adb_cmd(args: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
    cmd = ["adb"] + args
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def adb_root_shell(cmd_str: str, timeout: int = 60) -> tuple[int, str, str]:
    res = subprocess.run(["adb", "shell", "su", "-c", cmd_str],
                         capture_output=True, text=True, timeout=timeout)
    return res.returncode, res.stdout.strip(), res.stderr.strip()


def require(cond: bool, msg: str) -> None:
    if not cond:
        print(f"FATAL: {msg}", file=sys.stderr)
        raise RuntimeError(msg)


def wait_for_reboot(timeout_seconds: int = 180) -> str:
    """Wait for device to disconnect and then reconnect in device or recovery mode."""
    print("Waiting for device to drop connection...", flush=True)
    drop_start = time.time()
    while time.time() - drop_start < 30:
        res = adb_cmd(["devices"])
        lines = [line.strip() for line in res.stdout.splitlines() if line.strip() and not line.startswith("List of")]
        device_present = any("device" in line for line in lines)
        if not device_present:
            print(f"Device disconnected after {time.time() - drop_start:.1f}s", flush=True)
            break
        time.sleep(1)

    print(f"Waiting for device to reconnect (timeout {timeout_seconds}s)...", flush=True)
    start = time.time()
    while time.time() - start < timeout_seconds:
        res = adb_cmd(["devices"])
        lines = [line.strip() for line in res.stdout.splitlines() if line.strip() and not line.startswith("List of")]
        for line in lines:
            parts = line.split()
            if len(parts) >= 2:
                serial, state = parts[0], parts[1]
                if state in ("device", "recovery"):
                    print(f"Device reconnected: serial={serial}, state={state} in {time.time() - start:.1f}s", flush=True)
                    return state
        time.sleep(2)
    raise TimeoutError(f"Device failed to reconnect within {timeout_seconds} seconds")


def main() -> int:
    utc_stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    evidence_dir = PROJECT / "evidence/phase-2/device-execution" / utc_stamp
    evidence_dir.mkdir(parents=True, exist_ok=False)

    log_records: dict[str, object] = {
        "schema_version": 1,
        "utc_started": dt.datetime.now(dt.timezone.utc).isoformat(),
        "milestone": "P2-022",
        "scope": "a51_hardware_early_entry_execution_and_clean_restoration",
        "target_device": "Samsung Galaxy A51 (SM-A515F / Exynos 9611)",
        "serial": "A51_SERIAL_HERE",
        "candidate": {"path": str(CANDIDATE_PATH), "bytes": CANDIDATE_BYTES, "sha256": CANDIDATE_SHA256},
        "rollback": {"path": str(ROLLBACK_PATH), "bytes": ROLLBACK_BYTES, "sha256": ROLLBACK_SHA256},
        "stages": {},
        "status": "in_progress",
        "phase_2_device_gate_passed": False
    }

    def save_log() -> None:
        (evidence_dir / "result.json").write_text(json.dumps(log_records, indent=2) + "\n", encoding="utf-8")

    save_log()

    flashed_candidate = False

    try:
        # ======================================================================
        # STAGE 0: Pre-Flight Validations
        # ======================================================================
        print("=== STAGE 0: Pre-Flight Validations ===", flush=True)
        require(CANDIDATE_PATH.is_file(), "candidate boot image missing")
        candidate_bytes = CANDIDATE_PATH.read_bytes()
        require(len(candidate_bytes) == CANDIDATE_BYTES, "candidate boot image size mismatch")
        require(sha256(candidate_bytes) == CANDIDATE_SHA256, "candidate boot image sha mismatch")

        require(ROLLBACK_PATH.is_file(), "rollback boot image missing")
        rollback_bytes = ROLLBACK_PATH.read_bytes()
        require(len(rollback_bytes) == ROLLBACK_BYTES, "rollback boot image size mismatch")
        require(sha256(rollback_bytes) == ROLLBACK_SHA256, "rollback boot image sha mismatch")

        require(PROBE_MODULE_PATH.is_file(), "probe module missing")

        res = adb_cmd(["devices"])
        require("A51_SERIAL_HERE" in res.stdout, "target device A51_SERIAL_HERE not found in adb devices")

        rc, out, _ = adb_root_shell("id")
        require(rc == 0 and "uid=0(root)" in out, f"root check failed: {out}")

        rc, out, _ = adb_root_shell("cat /sys/class/power_supply/battery/capacity 2>/dev/null || dumpsys battery | grep level")
        print(f"Device battery check: {out}", flush=True)

        rc, out, _ = adb_root_shell(f"cat {BOOT_DEV} | sha256sum")
        current_boot_sha = out.split()[0] if out else ""
        print(f"Current live boot partition SHA-256: {current_boot_sha}", flush=True)
        require(current_boot_sha == ROLLBACK_SHA256, f"Current boot partition does not match known-good rollback baseline: {current_boot_sha}")

        rc, initial_boot_id, _ = adb_root_shell("cat /proc/sys/kernel/random/boot_id")
        print(f"Pre-flight boot ID: {initial_boot_id}", flush=True)

        log_records["stages"]["stage_0_preflight"] = {
            "status": "passed",
            "current_boot_sha": current_boot_sha,
            "initial_boot_id": initial_boot_id
        }
        save_log()

        # ======================================================================
        # STAGE 1: Stage Images and Probe Module to Device
        # ======================================================================
        print("=== STAGE 1: Stage Images and Probe Module to Device ===", flush=True)
        print("Pushing candidate boot image...", flush=True)
        res = adb_cmd(["push", str(CANDIDATE_PATH), REMOTE_TMP_CANDIDATE], timeout=120)
        require(res.returncode == 0, f"failed to push candidate: {res.stderr}")

        print("Pushing rollback boot image...", flush=True)
        res = adb_cmd(["push", str(ROLLBACK_PATH), REMOTE_TMP_ROLLBACK], timeout=120)
        require(res.returncode == 0, f"failed to push rollback: {res.stderr}")

        print("Pushing early_probe.ko module...", flush=True)
        res = adb_cmd(["push", str(PROBE_MODULE_PATH), REMOTE_TMP_PROBE], timeout=60)
        require(res.returncode == 0, f"failed to push probe module: {res.stderr}")

        rc, out, _ = adb_root_shell(f"sha256sum {REMOTE_TMP_CANDIDATE} {REMOTE_TMP_ROLLBACK} {REMOTE_TMP_PROBE}")
        require(rc == 0, "failed to compute sha256 of staged files")
        lines = out.splitlines()
        staged_candidate_sha = lines[0].split()[0]
        staged_rollback_sha = lines[1].split()[0]
        staged_probe_sha = lines[2].split()[0]
        require(staged_candidate_sha == CANDIDATE_SHA256, f"staged candidate sha mismatch: {staged_candidate_sha}")
        require(staged_rollback_sha == ROLLBACK_SHA256, f"staged rollback sha mismatch: {staged_rollback_sha}")
        print("Staged files verified on device storage.", flush=True)

        log_records["stages"]["stage_1_staging"] = {
            "status": "passed",
            "staged_candidate_sha": staged_candidate_sha,
            "staged_rollback_sha": staged_rollback_sha,
            "staged_probe_sha": staged_probe_sha,
        }
        save_log()

        # ======================================================================
        # STAGE 2: Flash Candidate Boot Image
        # ======================================================================
        print("=== STAGE 2: Flash Candidate Boot Image ===", flush=True)
        flash_cmd = f"dd if={REMOTE_TMP_CANDIDATE} of={BOOT_DEV} bs=4096 status=none conv=fsync"
        rc, out, err = adb_root_shell(flash_cmd)
        require(rc == 0, f"failed to flash candidate: {err}")
        flashed_candidate = True

        rc, out, _ = adb_root_shell(f"cat {BOOT_DEV} | sha256sum")
        flashed_boot_sha = out.split()[0] if out else ""
        print(f"Flashed boot partition SHA-256: {flashed_boot_sha}", flush=True)
        require(flashed_boot_sha == CANDIDATE_SHA256, f"flashed boot sha mismatch: {flashed_boot_sha}")

        log_records["stages"]["stage_2_flash_candidate"] = {
            "status": "passed",
            "flashed_boot_sha": flashed_boot_sha
        }
        save_log()

        # ======================================================================
        # STAGE 3: Reboot Device & Execute Early Entry
        # ======================================================================
        print("=== STAGE 3: Reboot Device & Execute Early Entry ===", flush=True)
        print("Issuing controlled reboot command...", flush=True)
        adb_root_shell("reboot")
        time.sleep(2)

        reconnect_state = wait_for_reboot(timeout_seconds=180)
        print(f"Device reconnected in mode: {reconnect_state}", flush=True)
        require(reconnect_state == "device", f"Device reconnected in unexpected state: {reconnect_state}")

        # Allow services to initialize
        time.sleep(10)

        # Wait up to 120s for boot completed
        boot_ok = False
        for poll in range(60):
            try:
                rc, out, _ = adb_root_shell("getprop sys.boot_completed")
                if rc == 0 and out.strip() == "1":
                    print(f"Android boot completed signal verified on poll {poll + 1}.", flush=True)
                    boot_ok = True
                    break
            except Exception:
                pass
            time.sleep(2)
        require(boot_ok, "sys.boot_completed did not reach 1 under candidate kernel")

        rc, out, _ = adb_root_shell("cat /proc/sys/kernel/random/boot_id")
        candidate_boot_id = out.strip()
        print(f"New boot ID under candidate: {candidate_boot_id}", flush=True)
        require(candidate_boot_id != initial_boot_id, "boot ID did not change; reboot did not occur")

        # ======================================================================
        # STAGE 4: Execute Early Probe to Read Hardware Record
        # ======================================================================
        print("=== STAGE 4: Execute Early Probe ===", flush=True)
        rc, out, err = adb_root_shell(f"insmod {REMOTE_TMP_PROBE}")
        print(f"insmod probe rc={rc} stdout={out} stderr={err}", flush=True)
        require(rc == 0, f"insmod early_probe failed: {err}")

        # Read dmesg
        rc, dmesg_out, _ = adb_root_shell("toybox dmesg")
        (evidence_dir / "candidate_dmesg.txt").write_text(dmesg_out, encoding="utf-8", errors="replace")

        # Unload probe
        rc, out, err = adb_root_shell("rmmod early_probe")
        print(f"rmmod probe rc={rc} stderr={err}", flush=True)

        matching_lines = [l.strip() for l in dmesg_out.splitlines() if "HAKIOS_V1" in l or "HAKIOS_RECORD_LOC" in l]
        print(f"Extracted {len(matching_lines)} matching record lines:", flush=True)
        for l in matching_lines:
            print("  " + l, flush=True)

        require(len(matching_lines) >= 5, f"Insufficient HAKIOS lines extracted: {len(matching_lines)}")
        (evidence_dir / "dmesg_hakios_record.txt").write_text("\n".join(matching_lines) + "\n", encoding="utf-8")

        # Parse fields from HAKIOS_V1 lines
        fields: dict[str, int] = {}
        decimal_keys = {"ver", "bytes", "status", "reason", "el", "cntfrq", "line"}
        for line in matching_lines:
            if "HAKIOS_V1" not in line:
                continue
            for key, val in re.findall(r"\b([a-z][a-z0-9_]*)=([0-9a-f]+)\b", line):
                fields[key] = int(val, 10 if key in decimal_keys else 16)

        print("Decoded hardware fields:", json.dumps({k: f"0x{v:x}" if k not in decimal_keys else v for k, v in fields.items()}, indent=2), flush=True)

        # Compute expected payload value
        expected_val_raw = fields["x0"] ^ fields["x1"] ^ fields["x2"] ^ fields["x3"] ^ fields["cntfrq"] ^ fields["midr"]
        expected_payload_val = ((expected_val_raw >> 7) | (expected_val_raw << 57)) & 0xffffffffffffffff

        # Verify assertions
        require(fields["magic"] == 0x31454c5241494b48, f"Magic mismatch: 0x{fields.get('magic', 0):x}")
        require(fields["ver"] == 1, f"Version mismatch: {fields.get('ver')}")
        require(fields["bytes"] == 256, f"Bytes mismatch: {fields.get('bytes')}")
        require(fields["status"] == 1, f"Status mismatch (expected HKE_EXECUTED=1): {fields.get('status')}")
        require(fields["reason"] == 0, f"Reason mismatch (expected HKE_REASON_NONE=0): {fields.get('reason')}")
        require(fields["payload_marker"] == 0x3143455845494b48, f"Marker mismatch (expected HKEXEC1): 0x{fields.get('payload_marker', 0):x}")
        require(fields["payload_val"] == expected_payload_val, f"Arithmetic value mismatch: got 0x{fields.get('payload_val', 0):x}, expected 0x{expected_payload_val:016x}")
        require(fields["el"] in (1, 2), f"EL mismatch: {fields.get('el')}")
        require((fields["sctlr"] & 5) == 0, f"MMU/C-bit was on: 0x{fields.get('sctlr', 0):x}")
        require((fields["daif"] & 0x2c0) == 0x2c0, f"DAIF masks missing: 0x{fields.get('daif', 0):x}")

        log_records["stages"]["stage_4_evidence"] = {
            "status": "passed",
            "candidate_boot_id": candidate_boot_id,
            "matching_lines": matching_lines,
            "fields": fields,
            "expected_payload_val_hex": f"0x{expected_payload_val:016x}",
            "payload_executed_verified": True
        }
        save_log()

        # ======================================================================
        # STAGE 5: Clean Restoration (Rollback to Baseline)
        # ======================================================================
        print("=== STAGE 5: Clean Restoration (Rollback to Baseline) ===", flush=True)
        print("Restoring known-good KernelSU boot image...", flush=True)
        flash_rb_cmd = f"dd if={REMOTE_TMP_ROLLBACK} of={BOOT_DEV} bs=4096 status=none conv=fsync"
        rc, out, err = adb_root_shell(flash_rb_cmd)
        require(rc == 0, f"failed to flash rollback image: {err}")
        flashed_candidate = False

        rc, out, _ = adb_root_shell(f"cat {BOOT_DEV} | sha256sum")
        restored_boot_sha = out.split()[0] if out else ""
        print(f"Restored boot partition SHA-256: {restored_boot_sha}", flush=True)
        require(restored_boot_sha == ROLLBACK_SHA256, f"restored boot sha mismatch: {restored_boot_sha}")

        # Clean up temporary staged files
        adb_root_shell(f"rm -f {REMOTE_TMP_CANDIDATE} {REMOTE_TMP_ROLLBACK} {REMOTE_TMP_PROBE}")
        print("Cleaned up temporary staging files from device.", flush=True)

        # Controlled reboot to confirm baseline returns cleanly
        print("Rebooting back to baseline Android...", flush=True)
        adb_root_shell("reboot")
        time.sleep(2)
        wait_for_reboot(timeout_seconds=180)
        time.sleep(10)

        # Verify Android stability
        for poll in range(60):
            try:
                rc, out, _ = adb_root_shell("getprop sys.boot_completed")
                if rc == 0 and out.strip() == "1":
                    print(f"Post-restoration boot completed on poll {poll + 1}.", flush=True)
                    break
            except Exception:
                pass
            time.sleep(2)
        rc, out, _ = adb_root_shell("id")
        print(f"Post-restoration root check: {out}", flush=True)
        require("uid=0(root)" in out, "lost root after restoration reboot")

        rc, out, _ = adb_root_shell(f"cat {BOOT_DEV} | sha256sum")
        final_boot_sha = out.split()[0] if out else ""
        require(final_boot_sha == ROLLBACK_SHA256, f"Final boot partition SHA mismatch: {final_boot_sha}")

        log_records["stages"]["stage_5_restoration"] = {
            "status": "passed",
            "restored_boot_sha": ROLLBACK_SHA256,
            "baseline_stability_verified": True
        }
        log_records["status"] = "completed_successfully"
        log_records["phase_2_device_gate_passed"] = True
        save_log()

        # Build index.json
        index_files = {}
        for p in evidence_dir.iterdir():
            if p.is_file():
                index_files[p.name] = {"bytes": p.stat().st_size, "sha256": sha256(p.read_bytes())}
        index_data = {
            "schema_version": 1,
            "directory": str(evidence_dir.relative_to(PROJECT).as_posix()),
            "files": index_files
        }
        (evidence_dir / "index.json").write_text(json.dumps(index_data, indent=2) + "\n", encoding="utf-8")

        print("================================================================", flush=True)
        print("PHASE 2 HARDWARE DEVICE EXECUTION GATE: PASSED SUCCESSFULLY!", flush=True)
        print("Evidence recorded in: " + str(evidence_dir), flush=True)
        print("================================================================", flush=True)
        return 0

    except Exception as exc:
        print(f"EXECUTION_FAILED: {exc}", file=sys.stderr)
        log_records["status"] = "failed"
        log_records["error"] = str(exc)
        save_log()

        # Emergency rollback if candidate was flashed
        if flashed_candidate:
            print("EMERGENCY ROLLBACK: Attempting to restore baseline boot partition...", file=sys.stderr)
            try:
                adb_cmd(["push", str(ROLLBACK_PATH), REMOTE_TMP_ROLLBACK])
                adb_root_shell(f"dd if={REMOTE_TMP_ROLLBACK} of={BOOT_DEV} bs=4096 status=none conv=fsync")
                rc, out, _ = adb_root_shell(f"cat {BOOT_DEV} | sha256sum")
                print(f"Emergency rollback boot sha: {out}", file=sys.stderr)
            except Exception as rb_exc:
                print(f"CRITICAL: Emergency rollback failed: {rb_exc}", file=sys.stderr)

        return 1


if __name__ == "__main__":
    raise SystemExit(main())

