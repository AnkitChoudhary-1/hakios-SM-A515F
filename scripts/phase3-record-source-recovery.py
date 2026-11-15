#!/usr/bin/env python3
"""Record the retained Phase 3 preservation and byte-exact historical capture."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import shutil

PROJECT = Path(__file__).resolve().parents[1]


def pin(path):
    raw = path.read_bytes()
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def main():
    workspace = json.loads((PROJECT / "manifests/phase3-workspace.json").read_text())
    capture_path = "evidence/phase-3/historical-raw-capture/20261114T014844776405Z/result.json"
    capture = json.loads((PROJECT / capture_path).read_text())
    assert capture["checks_passed"] and capture["same_android_boot"] and capture["cleaned_up"]
    assert capture["validated_old_log_bytes"] == 0
    assert pin(PROJECT / Path(capture_path).parent / "snapshot.bin") == capture["raw_snapshot_pin"]
    assert not workspace["native_build_output_copied"]
    assert all(t["source_bytes_verified"] and t["original_unchanged"] for t in workspace["trees"].values())
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    packet = PROJECT / "evidence/phase-3/progress-documentation" / stamp
    before = packet / "before"
    before.mkdir(parents=True)
    files = ["state.json", "docs/STATE.md", "docs/IMPLEMENTATION-LOG.md"]
    for name in files:
        dest = before / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PROJECT / name, dest)
    state_path = PROJECT / "state.json"
    state = json.loads(state_path.read_text())
    state["phase_3_continuation"] = {
        "status": "implementation_active",
        "isolated_root": workspace["root"],
        "source_preservation_packet": workspace["packet"],
        "historical_capture_result": capture_path,
        "historical_capture_pin": pin(PROJECT / capture_path),
        "historical_log_bytes_recovered": 0,
        "temporary_capture_module_loaded_and_removed": True,
        "android_boot_id": capture["boot_id"],
        "baseline_unchanged_at_capture": True,
        "new_xnu_candidate_built": False,
        "new_xnu_candidate_launched": False,
        "device_gate_passed": False,
    }
    state["active_task"] = "phase_3_gicv2_timer_and_attributable_log_implementation"
    state["next_action"] = "implement_and_validate_isolated_a51_gicv2_cortex_a53_full_boot"
    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    doc = PROJECT / "docs/STATE.md"
    text = doc.read_text(encoding="utf-8")
    old = "No device write/reboot/flash occurred in this continuation so far."
    text = text.replace(old, "A temporary read-only capture module was loaded/unloaded and its staging files removed; no boot-partition write, reboot or flash has occurred in this continuation so far.")
    marker = "The physical target is still on the baseline kernel; none of the missing Phase 3 execution gates has changed."
    text = text.replace(marker, marker + "\n\nThe isolated continuation checkout is `" + workspace["root"] + "`; source/dependency byte preservation passed without copying native XNU build output. Byte-exact historical capture `" + capture_path + "` retained 66,400 bytes but recovered zero validated XNU log bytes. GNSS contents were overwritten by Android, so that bank cannot supply the missing historical execution proof. Current work is A51 Cortex-A53/GICv2 timer support and bounded, attributable per-run logging.")
    doc.write_text(text, encoding="utf-8")
    entry = """

### P3-008 continuation — Preserve adapted inputs and recover raw historical RAM

Date: 14 November 2026, Asia/Calcutta. Status: implementation active; Phase 3 IN PROGRESS, device gate UNPASSED.

Purpose: retain every adapted source/dependency before changing the isolated A51 port, and recover original historical log bytes without binary terminal translation. Added `scripts/phase3-build-log-reader.py`, `scripts/phase3-capture-historical.py` and the out-of-tree matching-ABI read-only capture module retained with its build packet. The source preservation implementation is in `scripts/phase3-workspace.py`. This documentation update uses `scripts/phase3-record-source-recovery.py` and retains immediate before copies.

Source preservation: `evidence/phase-3/source-preservation/20261114T013656044425Z/` retains common/native archives, tracked adaptations, source inventories and dependency pins. `manifests/phase3-workspace.json` selects `/opt/a51-hakios/experimental/phase3-port/20261114T013656044425Z`, common HEAD `63fc2b4633bac3af8e57dadab9f5a8d4cb940438` and native XNU HEAD `c54f35ca767986246321eb901baf8f5ff7923f6a`. All 866 common files, 5,188 native files and 14,088 dependency files were preserved/verified; originals remain unchanged and native BUILD output was not copied.

Capture changes: use a uniquely named root-created device snapshot file and `adb pull` for byte-exact proc output, then unload the module and remove both staging files. Capture exceptions are recorded as failed results. KernelSU's shell wrapper translated LF to CRLF, expanding the expected 66,400 bytes to 66,811. A subsequent `exec-out` quoting attempt returned a 71-byte command error despite ADB exit 0. No translated or error output is accepted as raw evidence.

Verification: failed runs `20261114T014440784818Z-phase3-recover-historical-raw-log` (wrong child path), `20261114T014454610153Z-phase3-recover-historical-raw-log-corrected` (binary translation), and `20261114T014735222215Z-phase3-recover-historical-binary-log` (quoting) remain retained. Successful run `20261114T014844083173Z-phase3-recover-historical-file-log` exited 0; packet `evidence/phase-3/historical-raw-capture/20261114T014844776405Z/` retains a 66,400-byte original snapshot, bounded bank extracts, raw strings and exact commands. Same Android boot/root/baseline hash were verified, the module unloaded and both staging files removed. Validated historical XNU log bytes: **zero**. The overwritten GNSS header and GNSS strings cannot prove previous XNU user execution or timers.

Limitations: loading the temporary module and writing its staging files are device operations, but there was no boot write, reboot, flash or new XNU execution. Reserved-bank labels do not establish ownership/persistence. Cortex-A53 ISA compatibility, GICv2 timer delivery, loader return/logging, bounded reset and three qualifying hardware cycles remain pending. The current completion gate stays false.

Rollback/rebuild: originals and Phase 1 evidence remain preserved. Recreate the isolated trees from the recorded commits, archived source adaptations and pinned dependency inventory; do not reuse original build output. Rebuild the capture module through its recorded script and manifest. Restore only the immediate documentation before copies from this progress packet for bookkeeping rollback, retaining this entry and all failed/successful runs. The Android baseline boot is unchanged.
"""
    with (PROJECT / "docs/IMPLEMENTATION-LOG.md").open("a", encoding="utf-8") as log:
        log.write(entry)
    shutil.copy2(Path(__file__), packet / "source.py")
    index = [{"path": str(p.relative_to(packet)), **pin(p)} for p in sorted(packet.rglob("*")) if p.is_file()]
    (packet / "index.json").write_text(json.dumps(index, indent=2) + "\n")
    print(json.dumps({"packet": str(packet.relative_to(PROJECT)), "historical_xnu_log_bytes": 0,
                      "phase_3_device_gate_passed": False}, indent=2))


if __name__ == "__main__":
    main()
