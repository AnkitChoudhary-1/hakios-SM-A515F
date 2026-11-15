#!/usr/bin/env python3
"""Execute Phase 4 Silicon Driver Validation on Samsung Galaxy A51 (SM-A515F).

Verifies Phase 4 hardware drivers and execution gate:
  1. Preserved Samsung bootloader framebuffer (1080x2400 @ 32 bpp at 0xCA000000).
  2. Melfas MMS449 I2C touch controller interface & coordinate bounds.
  3. GPIO hardware keys (Power=116, Vol+=115, Vol-=114).
  4. Read-Only UFS 2.1 flash storage interface (Reads allowed, all writes strictly prohibited).
  5. Darwin XNU monotonic timers measured on silicon.
  6. Per-run attributable cryptographic nonce verified bit-for-bit.
  7. 100% bit-for-bit baseline rollback safety preserved and verified across all cycles.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

PROJECT = Path(__file__).resolve().parents[1]
WORKSPACE = PROJECT.parent
SCRIPTS = PROJECT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

EXPECTED_SERIAL = "A51_SERIAL_HERE"
BOOT_DEV = "/dev/block/sda12"

ROLLBACK_PATH = WORKSPACE / "everline-ksu/artifacts/A51-PixelOS-Everline-KernelSU-Next-boot.img"
ROLLBACK_SHA256 = "eb30609a62999e3282ac81e0a5e56411ef12ec1a39c107171bf3e01209c7cb67"
ROLLBACK_BYTES = 61_865_984

REMOTE_TMP_CANDIDATE = "/data/local/tmp/hakios-candidate-boot.img"
REMOTE_TMP_ROLLBACK = "/data/local/tmp/known-good-rollback-boot.img"

def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def extract_sha256(text: str) -> str:
    m = re.search(r'[0-9a-fA-F]{64}', text)
    return m.group(0).lower() if m else ""

def adb_cmd(args: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
    cmd = ["adb"] + args
    return subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=timeout)

def adb_root_shell(cmd_str: str, timeout: int = 60) -> tuple[int, str, str]:
    state_res = subprocess.run(["adb", "get-state"], capture_output=True, text=True, errors="replace")
    if state_res.stdout.strip() == "recovery":
        res = subprocess.run(["adb", "shell", cmd_str],
                             capture_output=True, text=True, errors="replace", timeout=timeout)
    else:
        # Wrap via ksud debug su -g for full root capabilities
        ksu_cmd = f"/data/adb/ksu/bin/ksud debug su -g << 'EOF'\n{cmd_str}\nEOF\n"
        res = subprocess.run(["adb", "shell", "su", "-c", ksu_cmd],
                             capture_output=True, text=True, errors="replace", timeout=timeout)
        if res.returncode != 0 and "ksud" in res.stderr:
            res = subprocess.run(["adb", "shell", "su", "-c", cmd_str],
                                 capture_output=True, text=True, errors="replace", timeout=timeout)
    return res.returncode, res.stdout, res.stderr

def check(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(f"FAIL: {msg}")

def wait_for_disconnect(timeout: int = 30) -> None:
    start = time.time()
    while time.time() - start < timeout:
        res = adb_cmd(["devices"])
        connected = any(line.startswith(EXPECTED_SERIAL) for line in res.stdout.splitlines())
        if not connected:
            return
        time.sleep(1)

def wait_for_device(target_state: str = None, timeout: int = 300) -> str:
    start = time.time()
    while time.time() - start < timeout:
        res = adb_cmd(["devices"])
        for line in res.stdout.splitlines():
            parts = line.strip().split()
            if len(parts) >= 2 and parts[0] == EXPECTED_SERIAL:
                mode = parts[1]
                if target_state is None or mode == target_state:
                    return mode
        time.sleep(2)
    raise TimeoutError(f"Device {EXPECTED_SERIAL} did not appear within {timeout}s (target: {target_state})")

def run_phase4_cycle(cycle_num: int, total_cycles: int, output_base: Path) -> dict:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    nonce = uuid.uuid4().hex
    cycle_dir = output_base / f"cycle-{cycle_num}_{stamp}"
    cycle_dir.mkdir(parents=True, exist_ok=False)

    print(f"\n==================================================================")
    print(f"=== PHASE 4 QUALIFYING CYCLE {cycle_num}/{total_cycles}: NONCE {nonce} ===")
    print(f"==================================================================")

    # 1. Host pins verification
    print("[1/9] Verifying baseline rollback pin...")
    check(ROLLBACK_PATH.is_file(), f"Rollback file missing: {ROLLBACK_PATH}")
    rb_data = ROLLBACK_PATH.read_bytes()
    check(len(rb_data) == ROLLBACK_BYTES, "Rollback byte size mismatch")
    check(digest(rb_data) == ROLLBACK_SHA256, "Rollback SHA-256 mismatch")
    print(f"  Verified baseline hash: {ROLLBACK_SHA256}")

    # 2. Check Device Connection & Baseline
    print("[2/9] Checking physical device connection and live boot hash...")
    current_mode = wait_for_device(timeout=30)
    print(f"  Device connected in '{current_mode}' mode.")

    rc, out, err = adb_root_shell(f"sha256sum {BOOT_DEV}")
    check(rc == 0, f"Failed to read live boot partition: {err}")
    live_sha256 = extract_sha256(out)
    print(f"  Live boot hash: {live_sha256}")
    pre_verified = (live_sha256 == ROLLBACK_SHA256)
    if not pre_verified:
        print(f"  Partition does not match baseline. Restoring known-good baseline...")
        stage_rb_pre = "/tmp/rb.img" if current_mode == "recovery" else REMOTE_TMP_ROLLBACK
        adb_cmd(["push", str(ROLLBACK_PATH), stage_rb_pre])
        adb_root_shell(f"dd if={stage_rb_pre} of={BOOT_DEV} bs=4096 conv=fsync")
        rc, out, err = adb_root_shell(f"sha256sum {BOOT_DEV}")
        check(rc == 0 and extract_sha256(out) == ROLLBACK_SHA256, "Failed to restore baseline before test")
        print("  Baseline restored successfully.")

    # 3. Build Userland & Phase 4 Boot Candidate
    print(f"[3/9] Building Phase 4 Drivers & packaging candidate with nonce={nonce}...")
    cmdline = f"rd=md0 -v cpus=1 serial=3 debug=0x104008 hello_wait=3 loader_return_after=20 hakios_run_nonce={nonce} hakios_kver=p4-a53-drivers hakios_a51_diag=1 hakios_a51_mmio=1 hakios_a51_probe=31"
    cmd_pack = [
        "wsl", "-d", "A51-KernelBuilder",
        "python3", "/mnt/c/Users/Ankit/Desktop/A51/hakios-a51/prototype/xnu-loader/pack_a51_payload.py",
        "--kernel", "/opt/a51-hakios/experimental/phase4-port/20261114T150320411427Z/hakios-kernel",
        "--hello", "/opt/a51-hakios/experimental/phase4-port/20261114T150320411427Z/userland/hello",
        "--output", "/opt/a51-hakios/experimental/a51-xnu-loader/a51_xnu_loader.bin",
        "--checkpoint", "0",
        "--cmdline", cmdline,
        "--pad-to", "36334080"
    ]
    res = subprocess.run(cmd_pack, capture_output=True, text=True)
    check(res.returncode == 0, f"pack_a51_payload.py failed: {res.stderr}")

    # Reconstruct Samsung boot candidate image
    from samsung_boot_dry_run import reconstruct_in_memory

    raw_loader = Path("//wsl.localhost/A51-KernelBuilder/opt/a51-hakios/experimental/a51-xnu-loader/a51_xnu_loader.bin").read_bytes()
    candidate_bytes, _ = reconstruct_in_memory(rb_data, raw_loader)
    candidate_sha256 = digest(candidate_bytes)
    expected_single_sha = digest(candidate_bytes[:4096])
    expected_multi_sha = digest(candidate_bytes[:65536])
    print(f"  Emitted Phase 4 candidate image: {len(candidate_bytes)} bytes, SHA-256: {candidate_sha256}")
    print(f"  Expected single-block hash: {expected_single_sha}")
    print(f"  Expected multi-block hash:  {expected_multi_sha}")

    candidate_file = cycle_dir / "candidate-boot.img"
    candidate_file.write_bytes(candidate_bytes)

    # 4. Push Candidate and Pre-stage Rollback
    print("[4/9] Pre-staging rollback image and uploading Phase 4 candidate...")
    stage_cand = "/tmp/cand.img" if current_mode == "recovery" else REMOTE_TMP_CANDIDATE
    stage_rb = "/tmp/rb.img" if current_mode == "recovery" else REMOTE_TMP_ROLLBACK

    adb_cmd(["push", str(ROLLBACK_PATH), stage_rb], timeout=120)
    adb_cmd(["push", str(candidate_file), stage_cand], timeout=120)

    # Verify remote staging
    rc, out, _ = adb_root_shell(f"sha256sum {stage_cand} {stage_rb}")
    staged_hashes = re.findall(r'[0-9a-fA-F]{64}', out)
    check(len(staged_hashes) >= 2, "Failed to hash staged remote images")
    check(staged_hashes[0].lower() == candidate_sha256, "Uploaded candidate hash mismatch")
    check(staged_hashes[1].lower() == ROLLBACK_SHA256, "Uploaded rollback hash mismatch")
    print("  Both images verified in device RAM.")

    # 5. Flash Candidate to Physical Silicon
    print(f"[5/9] Flashing Phase 4 candidate to {BOOT_DEV}...")
    rc, out, err = adb_root_shell(f"dd if={stage_cand} of={BOOT_DEV} bs=4096 conv=fsync")
    check(rc == 0, f"Failed to flash candidate: {err}")
    rc, out, err = adb_root_shell(f"sha256sum {BOOT_DEV}")
    check(rc == 0 and extract_sha256(out) == candidate_sha256, "Flash readback hash mismatch")
    print("  Candidate verified bit-for-bit on physical boot partition.")

    # 6. Reboot Silicon into Darwin XNU
    print("[6/9] Rebooting physical silicon into Darwin XNU...")
    boot_start_time = time.time()
    try:
        adb_root_shell("reboot")
    except Exception:
        pass

    wait_for_disconnect(timeout=30)
    print("  Physical device reboot initiated. Waiting for XNU execution and automated return...")

    # Wait for device reconnection in TWRP recovery or Android OS
    reconnected_mode = wait_for_device(timeout=360)
    boot_duration = time.time() - boot_start_time
    print(f"  Device reconnected after {boot_duration:.2f}s in '{reconnected_mode}' mode.")

    time.sleep(3)

    # 7. Restore Baseline Boot Partition
    print("[7/9] Restoring known-good baseline boot image...")
    rb_stage_post = "/tmp/rb.img" if reconnected_mode == "recovery" else REMOTE_TMP_ROLLBACK
    adb_cmd(["push", str(ROLLBACK_PATH), rb_stage_post], timeout=120)
    rc, out, err = adb_root_shell(f"dd if={rb_stage_post} of={BOOT_DEV} bs=4096 conv=fsync")
    check(rc == 0, f"Failed to restore baseline rollback image: {err}")

    rc, out, err = adb_root_shell(f"sha256sum {BOOT_DEV}")
    post_verified = (rc == 0 and extract_sha256(out) == ROLLBACK_SHA256)
    check(post_verified, f"Post-boot baseline rollback verification FAILED! Hash: {out}")
    print(f"  [SAFETY VERIFIED] Boot partition restored bit-for-bit to baseline: {ROLLBACK_SHA256}")

    # If reconnected in recovery, reboot into Android OS for module loading
    if reconnected_mode == "recovery":
        print("  Rebooting from recovery into Android OS for diagnostic extraction...")
        adb_cmd(["reboot"])
        wait_for_disconnect(timeout=30)
        wait_for_device(target_state="device", timeout=360)
        for _ in range(60):
            rc, out, err = adb_root_shell("getprop sys.boot_completed")
            if out.strip() == "1":
                break
            time.sleep(2)
        print("  Android booted cleanly.")
        time.sleep(3)

    # 8. Extract Silicon Execution Logs & Hardware Records via early_probe.ko
    print("[8/9] Extracting XNU DRAM record and execution log via early_probe.ko...")
    probe_ko = PROJECT / "artifacts/early_probe.ko"
    adb_cmd(["push", str(probe_ko), "/data/local/tmp/early_probe.ko"], timeout=30)
    adb_root_shell("setenforce 0 2>/dev/null || true")
    adb_root_shell("rmmod early_probe 2>/dev/null || true")
    rc, out, err = adb_root_shell("insmod /data/local/tmp/early_probe.ko")
    time.sleep(1)

    rc, dmesg_out, _ = adb_root_shell("dmesg")
    dmesg_file = cycle_dir / "dmesg.txt"
    dmesg_file.write_text(dmesg_out, encoding="utf-8")

    # Also capture console-ramoops if available
    rc_pstore, pstore_out, _ = adb_root_shell("cat /sys/fs/pstore/console-ramoops-0 2>/dev/null || true")
    if pstore_out:
        (cycle_dir / "console-ramoops.log").write_text(pstore_out, encoding="utf-8")

    all_evidence = (dmesg_out or "") + "\n" + (pstore_out or "")
    hakios_lines = [line for line in all_evidence.splitlines() if "HAKIOS" in line]
    hakios_file = cycle_dir / "hakios_extracted_records.txt"
    hakios_file.write_text("\n".join(hakios_lines), encoding="utf-8")
    print(f"  Extracted {len(hakios_lines)} HakiOS silicon log lines.")

    # 9. Verify Phase 4 Gate Criteria
    print("[9/9] Verifying Phase 4 hardware driver criteria...")
    full_log_str = all_evidence

    nonce_matched = (f"HAKIOS_RUN_NONCE={nonce}" in full_log_str) or (f"hakios_run_nonce={nonce}" in full_log_str) or (nonce in full_log_str)
    display_verified = ("HAKIOS_DISPLAY_VERIFIED" in full_log_str) and ("1080" in full_log_str) and ("2400" in full_log_str)
    touch_verified = ("HAKIOS_TOUCH_VERIFIED" in full_log_str) and ("controller=mms_ts" in full_log_str)
    keys_verified = ("HAKIOS_KEYS_VERIFIED" in full_log_str) and ("power=116" in full_log_str)
    storage_verified = ("HAKIOS_STORAGE_VERIFIED" in full_log_str) and ("write_rc=-30" in full_log_str) and ("ro_lock=1" in full_log_str) and (f"HAKIOS_STORAGE_MATCH sha256={expected_single_sha}" in full_log_str)
    image_verified = ("HAKIOS_IMAGE_LOAD_VERIFIED" in full_log_str) and (f"HAKIOS_IMAGE_LOAD_VERIFIED bytes=65536 sha256={expected_multi_sha}" in full_log_str)
    timers_verified = ("HAKIOS_TIMER_PASS" in full_log_str)
    phase4_pass = ("HAKIOS_PHASE4_PASS display=1 touch=1 keys=1 storage=1 image=1" in full_log_str)
    user_exit = ("HAKIOS_USER_EXIT outcome=0" in full_log_str)

    print(f"  - Attributable Nonce:   {'PASS' if nonce_matched else 'FAIL'}")
    print(f"  - Framebuffer/Display:  {'PASS' if display_verified else 'FAIL'}")
    print(f"  - Melfas Touchscreen:   {'PASS' if touch_verified else 'FAIL'}")
    print(f"  - Hardware Keys:        {'PASS' if keys_verified else 'FAIL'}")
    print(f"  - Read-Only Storage:    {'PASS' if storage_verified else 'FAIL'}")
    print(f"  - Larger Image Load:    {'PASS' if image_verified else 'FAIL'}")
    print(f"  - Monotonic Timers:     {'PASS' if timers_verified else 'FAIL'}")
    print(f"  - Userland Exit 0:      {'PASS' if user_exit else 'FAIL'}")
    print(f"  - Baseline Rollback:    {'PASS' if post_verified else 'FAIL'}")

    cycle_passed = (
        nonce_matched and
        display_verified and
        touch_verified and
        keys_verified and
        storage_verified and
        image_verified and
        phase4_pass and
        timers_verified and
        user_exit and
        post_verified
    )

    cycle_result = {
        "cycle": cycle_num,
        "stamp": stamp,
        "nonce": nonce,
        "candidate_sha256": candidate_sha256,
        "rollback_sha256": ROLLBACK_SHA256,
        "baseline_verified_pre_flash": pre_verified,
        "candidate_verified_on_silicon": True,
        "device_reconnected": True,
        "baseline_verified_post_boot": post_verified,
        "reconnect_mode": reconnected_mode,
        "boot_duration_seconds": boot_duration,
        "nonce_matched": nonce_matched,
        "display_verified": display_verified,
        "touch_verified": touch_verified,
        "keys_verified": keys_verified,
        "storage_verified": storage_verified,
        "image_verified": image_verified,
        "timers_verified": timers_verified,
        "user_program_exited": user_exit,
        "qualifying_cycle_passed": cycle_passed,
        "hakios_records": hakios_lines[:150]
    }

    result_file = cycle_dir / "cycle_result.json"
    result_file.write_text(json.dumps(cycle_result, indent=2), encoding="utf-8")

    return cycle_result

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=int, default=1, help="Number of consecutive qualifying cycles (default 1)")
    args = parser.parse_args()

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output_base = PROJECT / "evidence/phase-4/silicon-execution" / stamp
    output_base.mkdir(parents=True, exist_ok=True)

    print(f"==================================================================")
    print(f"=== HAKIOS PHASE 4 SILICON DRIVER GATE EXECUTION ===")
    print(f"=== Target: Samsung Galaxy A51 (SM-A515F / Exynos 9611)       ===")
    print(f"=== Serial: {EXPECTED_SERIAL}                                     ===")
    print(f"=== Cycles requested: {args.cycles}                                      ===")
    print(f"==================================================================")

    results = []
    all_passed = True

    for i in range(1, args.cycles + 1):
        try:
            res = run_phase4_cycle(i, args.cycles, output_base)
            results.append(res)
            if not res["qualifying_cycle_passed"]:
                all_passed = False
                print(f"\n[FAIL] Cycle {i} did not meet all Phase 4 criteria.")
                break
        except Exception as e:
            all_passed = False
            print(f"\n[ERROR] Cycle {i} aborted with exception: {e}")
            import traceback
            traceback.print_exc()
            break
        time.sleep(5)

    summary = {
        "timestamp": stamp,
        "cycles_requested": args.cycles,
        "cycles_completed": len(results),
        "all_cycles_passed": all_passed,
        "phase_4_gate_criteria": {
            "display_verified": all_passed and all(r["display_verified"] for r in results),
            "touch_verified": all_passed and all(r["touch_verified"] for r in results),
            "keys_verified": all_passed and all(r["keys_verified"] for r in results),
            "storage_read_only_verified": all_passed and all(r["storage_verified"] for r in results),
            "larger_image_verified": all_passed and all(r.get("image_verified", False) for r in results),
            "working_xnu_timers": all_passed and all(r["timers_verified"] for r in results),
            "per_run_nonce_attributable": all_passed and all(r["nonce_matched"] for r in results),
            "baseline_rollback_verified": all_passed and all(r["baseline_verified_post_boot"] for r in results),
        },
        "results": results
    }

    summary_file = output_base / "phase4_execution_summary.json"
    summary_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("\n==================================================================")
    print("=== FINAL PHASE 4 GATE EXECUTION SUMMARY ===")
    print(f"Cycles completed: {len(results)}/{args.cycles}")
    print(f"All cycles passed: {all_passed}")
    print(f"Display verified: {summary['phase_4_gate_criteria']['display_verified']}")
    print(f"Touch verified: {summary['phase_4_gate_criteria']['touch_verified']}")
    print(f"Keys verified: {summary['phase_4_gate_criteria']['keys_verified']}")
    print(f"Read-Only Storage verified: {summary['phase_4_gate_criteria']['storage_read_only_verified']}")
    print(f"Summary JSON: {summary_file}")
    print("==================================================================")

    sys.exit(0 if all_passed else 1)

if __name__ == "__main__":
    sys.exit(main())
