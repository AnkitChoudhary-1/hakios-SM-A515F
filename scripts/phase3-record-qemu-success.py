#!/usr/bin/env python3
"""Select original complete QEMU evidence without changing any A51 gate."""
from __future__ import annotations

import datetime as dt
import difflib
import hashlib
import json
from pathlib import Path
import shutil

PROJECT = Path(__file__).resolve().parents[1]
QEMU = "evidence/phase-3/platform-qemu/20261114T024808085318Z"
INVENTORY = "evidence/phase-3/continuation-inventory/20261114T024941032676Z/result.json"


def pin(path: Path) -> dict:
    raw = path.read_bytes()
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def main() -> None:
    selected = json.loads((PROJECT / "manifests/phase3-platform-qemu.json").read_text(encoding="utf-8"))
    result_path = PROJECT / QEMU / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert selected["packet"] == QEMU and selected["passed"] is True
    assert result["passed"] is True and all(result["checks"].values())
    assert len(result["checks"]) == 12 and len(result["timer_samples"]) == 3
    assert not result["device_operations"] and not result["phase_3_device_gate_passed"]
    assert pin(PROJECT / QEMU / "kernel-user.log") == result["log"]
    raw_log = (PROJECT / QEMU / "kernel-user.log").read_bytes()
    assert ("HAKIOS_RUN_NONCE=" + result["nonce"]).encode() in raw_log
    assert b"HAKIOS_TIMER_PASS samples=3" in raw_log
    assert b"HAKIOS_USER_EXIT outcome=0 timer_verified=1" in raw_log
    state = json.loads((PROJECT / "state.json").read_text(encoding="utf-8"))
    assert state["phase_3_status"] == "in_progress" and not state["phase_3_device_gate_passed"]
    relative_files = ["README.md", "docs/STATE.md", "docs/PHASE-3-PLATFORM.md", "docs/IMPLEMENTATION-LOG.md", "state.json"]
    texts = {relative: (PROJECT / relative).read_text(encoding="utf-8") for relative in relative_files}
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    packet = PROJECT / "evidence/phase-3/qemu-success-selection" / stamp
    packet.mkdir(parents=True, exist_ok=False)
    packet_rel = packet.relative_to(PROJECT).as_posix()
    shutil.copy2(__file__, packet / "source.py")
    changes, patches = [], []

    def update(relative: str, text: str) -> None:
        target = PROJECT / relative
        old, new = target.read_bytes(), text.encode("utf-8")
        assert old != new, relative
        for name, data in (("before", old), ("after", new)):
            copy = packet / name / relative
            copy.parent.mkdir(parents=True, exist_ok=True)
            copy.write_bytes(data)
        target.write_bytes(new)
        changes.append({"path": relative, "before": pin(packet / "before" / relative), "after": pin(target)})
        patches.append("".join(difflib.unified_diff(old.decode("utf-8").splitlines(True), text.splitlines(True), fromfile="a/" + relative, tofile="b/" + relative)))

    continuation = state["phase_3_continuation"]
    continuation.update({
        "full_qemu_result": QEMU + "/result.json",
        "full_qemu_result_pin": pin(result_path),
        "full_qemu_passed": True,
        "full_qemu_scope": result["scope"],
        "full_qemu_original_log": QEMU + "/kernel-user.log",
        "full_qemu_original_log_pin": result["log"],
        "qemu_security_correction_execution": "passed_pid1_three_timer_samples_physical_return",
        "latest_inventory_result": INVENTORY,
        "latest_inventory_pin": pin(PROJECT / INVENTORY),
        "qemu_success_selection_packet": packet_rel,
        "qualifying_a51_runs": 0,
        "new_hardware_loader_built": False,
        "device_gate_passed": False,
    })
    state["next_action"] = "repair_bounded_hardware_loader_capture_and_reset_then_validate_and_run_three_a51_cycles"
    update("state.json", json.dumps(state, indent=2) + "\n")
    summary = (f"P3-011 full QEMU execution **PASSED** in `{QEMU}`: original PID 1 log, three measured one-second sleeps with increasing IRQ counts, and physical loader return; all 12 checks passed in 12.724 seconds. This is Cortex-A53/GICv2 QEMU evidence only. A51 user-program/timer execution, attributable per-run capture, reset/return and three consecutive qualifying runs remain unverified (0/3). Latest read-only inventory `{INVENTORY}` reconfirms the unchanged baseline boot/root. Hardware loader memory placement, bounded copies, exception capture and return/reset are being repaired before a new candidate launch.")
    doc = texts["docs/STATE.md"]
    start = doc.index("P3-010 host progress:")
    end = doc.index("\n\nUpdated 14 November", start)
    update("docs/STATE.md", doc[:start] + summary + doc[end:])
    readme = texts["README.md"]
    marker = "Phase 4 remains planned."
    assert marker in readme
    update("README.md", readme.replace(marker, "Full Cortex-A53/GICv2 QEMU execution now passes PID 1, measured timer sleeps and physical return; this remains host evidence. " + marker, 1))
    guide = texts["docs/PHASE-3-PLATFORM.md"]
    old = "Corrected execution remains pending."
    assert old in guide
    guide = guide.replace(old, f"Corrected full execution **PASSED** in `{QEMU}` (run `20261114T024758584731Z-phase3-full-nonsecure-a53-gicv2-qemu`): all 12 checks, PID 1, three measured sleeps, increasing timer IRQ counts and physical return, in 12.724 seconds.")
    marker = "## Rebuild and validation"
    guide = guide.replace(marker, f"Original `kernel-user.log` is 22,485 bytes, SHA-256 `{result['log']['sha256']}`. Fresh nonce `{result['nonce']}` identifies this host run; the return record reports reason 0/code 0, Cortex-A53 MIDR `0x410fd034` and 62.5 MHz QEMU counter. The sleeps measured 1,007,124; 1,005,575; and 1,005,598 microseconds with IRQ counts 125→183, 191→250 and 261→317. The expected PID 1 zero-exit panic returned to the physical loader stub. None of these observations is an A51 run.\n\n" + marker, 1)
    update("docs/PHASE-3-PLATFORM.md", guide)
    update("docs/IMPLEMENTATION-LOG.md", texts["docs/IMPLEMENTATION-LOG.md"] + f"""

### P3-011 — Select full QEMU PID 1/timer/return success and refresh hardware baseline

Date: 14 November 2026, Asia/Calcutta. Status: host execution verified; Phase 3 IN PROGRESS, A51 gate UNPASSED, qualifying device runs 0/3.

Purpose: record the executed outcome of P3-010's corrected nonsecure EL1 harness and direct remaining work to the hardware loader. Files: scripts/phase3-record-qemu-success.py, README.md, docs/STATE.md, docs/PHASE-3-PLATFORM.md, state.json and this log. Exact before/after bytes and a unified patch are retained in `{packet_rel}`; historical failure/pending entries remain intact.

Verification: `20261114T024758584731Z-phase3-full-nonsecure-a53-gicv2-qemu`, exit 0, selected result `{QEMU}/result.json`: all 12 runtime predicates pass, PID 1 prints fresh nonce `{result['nonce']}`, three timer samples measure 1,007,124/1,005,575/1,005,598 us with increasing timer IRQ counts, timer/pass/zero-exit markers exist in the original 22,485-byte log, and physical return record reports reason 0/code 0. Log SHA-256 `{result['log']['sha256']}`. The checker completed in 12.724 seconds and left every A51 gate false. This selector rechecks the selected result, original log pin/markers and unchanged A51 gate before updating documents.

Read-only inventory run `20261114T024939782928Z-phase3-refresh-baseline-before-loader-work`, exit 0, result `{INVENTORY}`, verifies SM-A515F/root/boot completion, unchanged Android boot ID `0c73e96a-851c-45d9-838e-b38e54071ad2`, boot partition size 61,865,984 bytes and baseline SHA-256 `eb30609a62999e3282ac81e0a5e56411ef12ec1a39c107171bf3e01209c7cb67`. Battery is 100 percent, USB powered and 28.4 C. Existing pstore files are observed, not attributable XNU logs. No new boot write/reboot/flash occurred.

Retained invocation failure: `20261114T025340232658Z-phase3-record-full-qemu-success` used a redundant hakios-a51 prefix for the child script; run.py already sets that directory as its working directory. Python exited 2 without running this selector or mutating documents. The corrected invocation uses scripts/phase3-record-qemu-success.py.

Remaining contracts: replace overlapping GNSS/DSS record writes, bound TOC/log/UART operations, preserve exceptions, dynamically place hello/bootargs/device tree above the actual current kernel extent, and establish source-backed reset/pstore behavior. The previous fixed payload addresses overlap the current kernel's end near 0x84208490 and cannot be reused. Verify the actual repaired loader in host/QEMU, package a pinned candidate with rollback artifacts, then execute three qualifying A51 cycles. Single-core host success does not establish any working A51 XNU core, multicore, no-flash launch or peripheral support.

Recovery/rollback: restore only this packet's indexed document/state before copies for bookkeeping rollback; preserve this entry and every successful/failed source/build/runtime packet. Rebuild from the pinned isolated tree and platform adaptations using the commands in PHASE-3-PLATFORM.md. The phone remains on its verified baseline; no device rollback is required by this documentation update.
""")
    (packet / "adaptations.patch").write_text("".join(patches), encoding="utf-8")
    selection = {"schema_version": 1, "packet": packet_rel, "changes": changes,
                 "qemu_result": QEMU + "/result.json", "qemu_result_pin": pin(result_path),
                 "inventory_result": INVENTORY, "inventory_pin": pin(PROJECT / INVENTORY),
                 "full_qemu_passed": True, "device_operations": False, "phase_3_device_gate_passed": False}
    (packet / "result.json").write_text(json.dumps(selection, indent=2) + "\n", encoding="utf-8")
    index = [{"path": path.relative_to(packet).as_posix(), **pin(path)} for path in sorted(packet.rglob("*")) if path.is_file()]
    (packet / "index.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: selection[key] for key in ("packet", "full_qemu_passed", "device_operations", "phase_3_device_gate_passed")}, indent=2))


if __name__ == "__main__":
    main()
