#!/usr/bin/env python3
"""Snapshot the resumed Phase 4 work and check the A51 without changing it."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
import shutil

from phase4_device import BASELINE_SHA256, Device, SERIAL
from phase4_support import PROJECT, documents, index_packet, new_packet, pin, require, write_json


def main():
    packet = new_packet("resume-audit", __file__)
    files = ["README.md", "docs/STATE.md", "docs/IMPLEMENTATION-LOG.md", "docs/INDEX.md",
             "docs/PHASE-4-COMPLETION-REVIEW.md", "docs/PHASE-4-DEVICE-PATH.md", "state.json"]
    files += [p.relative_to(PROJECT).as_posix() for base in ("prototype/phase4-platform", "prototype/phase4-loader", "scripts", "manifests")
              for p in (PROJECT / base).iterdir() if p.is_file()]
    before = {}
    for rel in dict.fromkeys(files):
        path = PROJECT / rel
        target = packet / "initial" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        before[rel] = pin(path)
    write_json(packet / "initial-pins.json", before)
    dev = Device(packet)
    report = {"schema_version": 1, "packet": packet.relative_to(PROJECT).as_posix(),
              "date_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "serial": SERIAL,
              "device_operations": "read_only", "phase_4_gate_passed": False,
              "passed": False, "source_pins": before}
    try:
        require(dev.mode("device-mode") == "device", "Expected authorized Android ADB connection")
        # exec-out passes this command to su directly in the observed ADB build.
        # Shell-quoting the whole argument makes su execute a literal filename.
        # Use && rather than set -e so failures still reach the remote-exit frame.
        command = " && ".join((
            "id", "getprop ro.product.model", "getprop ro.product.device",
            "getprop sys.boot_completed", "cat /proc/sys/kernel/random/boot_id",
            "readlink -f /dev/block/by-name/boot",
            "sha256sum /dev/block/sda12 /dev/block/by-name/recovery /dev/block/by-name/dtbo",
            "blockdev --getsize64 /dev/block/sda12",
            "cat /proc/sys/kernel/random/boot_id"))
        raw = dev.root("android-baseline", command, timeout=60, limit=16384)
        text = raw.decode("utf-8", "replace")
        (packet / "android-baseline.txt").write_text(text, encoding="utf-8")
        require("uid=0(root)" in text and "SM-A515F" in text and "a51" in text, "Unexpected identity/root")
        expected = {"boot": BASELINE_SHA256,
                    "recovery": "12412e2008d950260cda627ac7a6b8eac954b49ef9db5573a297f67e4fc85999",
                    "dtbo": "41662c61ff3158448935025477a4e29d445823dab2cddafb18ea649c8ea925d6"}
        require(all(value in text for value in expected.values()), "Live recovery/baseline pin changed")
        lines = text.splitlines()
        boot_ids = [line for line in lines if len(line) == 36 and line.count("-") == 4]
        require(len(boot_ids) == 2 and boot_ids[0] == boot_ids[1], "Android rebooted during baseline audit")
        require("1" in lines and "/dev/block/sda12" in lines and "61865984" in lines,
                "Android boot or boot partition identity/size mismatch")
        rollback = PROJECT.parent / "everline-ksu/artifacts/A51-PixelOS-Everline-KernelSU-Next-boot.img"
        require(pin(rollback) == {"bytes": 61865984, "sha256": BASELINE_SHA256}, "Host rollback changed")
        report.update(passed=True, baseline_pins=expected, host_rollback=pin(rollback),
                      android_boot_id=boot_ids[0],
                      capacity_bytes=shutil.disk_usage(PROJECT).free)
    except Exception as exc:
        report["error"] = str(exc)
    # Refuse to overwrite concurrent source/state edits while the inventory ran.
    require(all(pin(PROJECT / rel) == expected for rel, expected in before.items()),
            "Source/document edits detected during audit; initial snapshot retained")
    write_json(packet / "result.json", report)
    state = json.loads((PROJECT / "state.json").read_text(encoding="utf-8"))
    state.update(phase_4_status="in_progress", active_phase="phase_4",
                 active_task="Validate genuine Phase 4 display/input/UFS execution after resuming",
                 updated_date_local="2026-11-15", phase_4_device_gate_passed=False,
                 next_action="Reconcile build provenance; finish matching loader validation; implement real display/input and read-only UFS checks",
                 phone_queries_this_continuation=True)
    state["phase_4_criteria"].update(
        display_scanout_and_dimensions="unverified_fixed_success_marker_and_assumed_framebuffer",
        dsim_repeatable_brightness="unverified_one_command_attempt_no_repeatable_visible_evidence",
        physical_touch_events_and_coordinates="unverified_controller_register_snapshot_no_events",
        physical_power_volume_key_events="unverified_gpio_snapshot_no_press_release_events",
        storage_writes_disabled="implemented_local_rejection_hardware_submission_audit_pending",
        ufs_read_known_image="unpassed_ocs7_zero_hashes_fmp_and_slot_hypotheses_unverified",
        larger_image_loading="unpassed_64k_ufs_transfer_zero_hash",
        status="in_progress_resumed_by_user")
    state["phase_4_resume_audit"] = {"result": report["packet"] + "/result.json", "passed": report["passed"]}
    state["user_authorized_continuation"] = "User instructed 'then start'; resumes Phase 4 work after the historical pause"
    state["blockers"] = [
        "Actual display geometry/scanout and repeated brightness have no qualifying evidence",
        "Physical touch coordinates and key press/release events are not implemented/verified",
        "4 KiB and 64 KiB UFS reads failed with OCS 7; FMP/slot explanation remains a hypothesis",
        "Corrected loader needs its complete matching QEMU suite and attributable hardware execution",
        "Current direct-build sources have drifted from the platform adaptation manifest"]
    if not report["passed"]:
        state["blockers"].append("Resume baseline audit failed: " + report["error"])
    intro = f"""# Current state

## Phase 4 — IN PROGRESS (resumed 15 November 2026)

The user instructed **“then start”**, resuming Phase 4. Phases 1–3 retain their selected completion evidence. Phase 4 is **not complete** and has no justified overall completion percentage.

The previous **8 of 9 verified** claim is superseded by this source review. `hello.c` still printed fixed display, brightness, touch and key success labels. A register snapshot, framebuffer write attempt and DSIM command attempt do not establish visible scanout, repeated brightness, touch coordinates or physical key events. The touch controller base in the retained source is `0x13870000`; the earlier `0x118B0000` documentation was incorrect.

The latest silicon trial (`evidence/phase-4/silicon-execution/20261115T102436837863Z`) completed one of three requested cycles and failed both storage reads: `s_rc=-4 s_ocs=7 m_rc=-4 m_ocs=7`, with zero hashes. UFS/FMP descriptor and firmware-slot explanations are hypotheses; the latest patch has not run on hardware. Timers, the original per-run nonce and rollback have retained evidence, but they do not satisfy the display/input/storage gate.

Resume audit: `{report['packet']}/result.json`, passed `{report['passed']}`. This audit used read-only Android queries and retained the initial sources, manifests and documentation. No source build, phone write or reboot occurred in the audit. Baseline, recovery and DTBO must be rechecked before any later experiment.

Remaining work: reconcile source/build provenance; complete matching corrected-loader checks; implement and demonstrate real display/brightness and input; verify independent 4 KiB/64 KiB image hashes through a bounded read-only UFS path; then repeat all qualifying hardware checks with verified restoration.

## Historical state (superseded where it conflicts with the review above)

"""
    old_state = (PROJECT / "docs/STATE.md").read_text(encoding="utf-8")
    # Replace our current resume summary; originals remain in indexed packets.
    historical_marker = "## Historical state (superseded where it conflicts with the review above)\n\n"
    while old_state.startswith("# Current state\n\n## Phase 4 — IN PROGRESS (resumed 15 November 2026)") and historical_marker in old_state:
        old_state = old_state.split(historical_marker, 1)[1]
    old_review = (PROJECT / "docs/PHASE-4-COMPLETION-REVIEW.md").read_text(encoding="utf-8")
    review_marker = "## Superseded review (retained as history)\n\n"
    while old_review.startswith("# Phase 4 completion review — resumed 15 November 2026") and review_marker in old_review:
        old_review = old_review.split(review_marker, 1)[1]
    review = f"""# Phase 4 completion review — resumed 15 November 2026

**Decision: IN PROGRESS; hardware completion gate unpassed.**

The roadmap requires actual framebuffer/input demonstration, repeatable brightness and key behavior, read data matching known image contents, and a driver that does not enable storage writes. The historical “8 of 9 gates verified” decision below is rejected by source inspection: fixed success strings remain in PID 1, and touch/key data are controller/GPIO snapshots without events.

| Requirement | Current evidence | Status |
|---|---|---|
| Display dimensions and visible scanout | Assumed `0xCA000000`; pattern-write attempt, fixed geometry marker | Unverified |
| Repeatable brightness | Single DSIM attempt, fixed brightness marker | Unverified |
| Physical touch and coordinates | I2C4 status snapshot; no events | Unverified |
| Power/volume press and release | GPIO snapshots; no events | Unverified |
| Read-only UFS/image access | Real transfer attempts, both reads fail with OCS 7 and zero hashes | Unpassed |
| Storage write prohibition | Local `-30` return; audit the only submission path and unchanged doorbell | Implemented, qualification pending |
| Timers, nonce, restoration | Retained physical trial logs/readbacks | Retained supporting evidence |
| Matching corrected loader | Incomplete 63-case suite; corrected hardware path has no attributable envelope | Unpassed |

Sources and earlier claims are preserved in `{report['packet']}/initial/`. The S-Boot/FMP explanation is an untested hypothesis, including the meaning of OCS 7 and vendor PRDT sizing. An interrupt alone does not prove a valid command or read. Touch I2C4 is `0x13870000` in the retained source.

## Superseded review (retained as history)

""" + old_review
    note = f"""

## P4-027 — Resume Phase 4 and correct unsupported completion claims ({packet.name})

Purpose/files: maintain `scripts/phase4-resume-audit.py`; snapshot current platform/loader/scripts/manifests/docs; update STATE, completion review and state.json to reflect the user's resume and genuine evidence. The prior display/brightness/touch/key markers remain fixed; UFS/FMP cause is a hypothesis, not a demonstrated diagnosis. Preserve all historical claims and original failed trials. Two failed attempts retained heredoc/framing and literal shell-quote errors. The successful transport diagnosis is in runs/20261115T113415222581Z-phase4-root-transport-diagnosis: pass the unquoted exec-out su argument through Device.root, use && so errors are framed, and check matching Android UUIDs before/after. Replace this utility's repeated current summaries; the indexed before packets preserve their exact bytes.

Verification: resume read-only ADB baseline audit passed={report['passed']}; error={report.get('error')}. Identity/root/Android boot ID, boot/recovery/DTBO hashes, host rollback pin and initial source hashes are retained in `{report['packet']}`. Earlier Windows/WSL capacity/process inventory is in runs/20261115T112318881811Z-phase4-resume-wsl-state and runs/20261115T112319181366Z-phase4-resume-adb. No payload build/write/reboot in this audit.

Limitations: no display/input/storage gate is established by this audit. Active source pins differ from the old adaptation; corrected loader validation remains incomplete. Rollback: restore this packet's before document copies and initial source snapshot if needed, retaining the packet and all original device evidence; do not reinstate superseded completion claims as current fact.
"""
    documents(packet, {"docs/STATE.md": intro + old_state,
                       "docs/PHASE-4-COMPLETION-REVIEW.md": review,
                       "state.json": json.dumps(state, indent=2) + "\n",
                       "docs/IMPLEMENTATION-LOG.md": (PROJECT / "docs/IMPLEMENTATION-LOG.md").read_text(encoding="utf-8") + note})
    index_packet(packet)
    print(json.dumps({k: report.get(k) for k in ("packet", "passed", "error", "android_boot_id", "baseline_pins", "capacity_bytes")}), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
