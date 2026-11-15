#!/usr/bin/env python3
"""Reconcile retained Phase 3 execution and the byte-exact Phase 4 inventory."""
from __future__ import annotations
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

PROJECT = Path(__file__).resolve().parents[1]

def pin(path):
    raw = path.read_bytes()
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}

def main():
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    packet = PROJECT / "evidence/phase-4/evidence-reconciliation" / stamp
    packet.mkdir(parents=True)
    for rel in ("state.json", "docs/STATE.md", "docs/IMPLEMENTATION-LOG.md"):
        dst = packet / "before" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PROJECT / rel, dst)
    summary_path = PROJECT / "evidence/phase-3/repeatability/20261114T132905926137Z/consecutive_runs_summary.json"
    summary = json.loads(summary_path.read_text())
    assert summary["cycles_completed"] == 3 and summary["all_cycles_passed"]
    cycles = []
    seen = set()
    for number, audit in enumerate(summary["results"], 1):
        directory = summary_path.parent / f"cycle-{number}_{audit['stamp']}"
        source = directory / "early_probe.log"
        raw = source.read_text()
        lines = [line.split("HAKIOS_OUT: ", 1)[1] for line in raw.splitlines() if "HAKIOS_OUT: " in line]
        text = "\n".join(lines) + "\n"
        begin = text.index("HAKIOS_USER_BEGIN pid=1 uid=0 console=0\n")
        finish = text.index("HAKIOS_USER_EXIT outcome=0 timer_verified=1\n", begin)
        frame = text[begin:finish + len("HAKIOS_USER_EXIT outcome=0 timer_verified=1\n")]
        nonce = audit["nonce"]
        assert re.fullmatch("[0-9a-f]{32}", nonce) and nonce not in seen
        seen.add(nonce)
        assert frame.count(f"HAKIOS_RUN_NONCE={nonce}\n") == 1
        assert "HAKIOS_PLATFORM gic=2 cores=1 midr=0x410fd034\n" in frame
        samples = re.findall(r"^HAKIOS_TIMER_SAMPLE index=(\d+) select_rc=(-?\d+) elapsed_us=(\d+) irq_before=(\d+) irq_after=(\d+) read_rc=(-?\d+) pass=([01])$", frame, re.M)
        assert len(samples) == 3
        previous = 0
        for index, sample in enumerate(samples, 1):
            n, rc, elapsed, before, after, read_rc, passed = map(int, sample)
            assert n == index and rc == read_rc == 0 and 900000 <= elapsed <= 3000000
            assert before >= previous and after > before and passed == 1
            previous = after
        assert audit["baseline_verified_pre_flash"] and audit["baseline_verified_post_boot"]
        assert audit["candidate_verified_on_silicon"] and audit["qualifying_cycle_passed"]
        assert "HAKIOS_8F magic=32454c5241494b48 ver=1 bytes=256 status=6" in raw
        assert "HAKIOS_8F reason=0 code=0" in raw
        cycles.append({"cycle": number, "nonce": nonce, "samples": samples, "original_log": source.relative_to(PROJECT).as_posix(), "pin": pin(source), "user_frame_sha256": hashlib.sha256(frame.encode()).hexdigest()})
    inventory_path = PROJECT / "evidence/phase-4/live-inventory/20261114T145624626688Z/result.json"
    inventory = json.loads(inventory_path.read_text())
    assert inventory["inventory_valid"] and all(inventory["checks"].values())
    assert not inventory["operations"]["device_writes"] and not inventory["operations"]["reboot"]
    data = (inventory_path.parent / "known-boot-first-1m.stdout.bin").read_bytes()
    assert len(data) == 1048576 and hashlib.sha256(data).hexdigest() == inventory["known_image"]["first_1m_sha256"]
    assert inventory["known_image"]["ufs_boot_lba"] == 27792
    command = [sys.executable, str(PROJECT / "scripts/phase4-device-gate.py")]
    proc = subprocess.run(command, capture_output=True, timeout=10)
    (packet / "disabled-gate.stdout.bin").write_bytes(proc.stdout)
    (packet / "disabled-gate.stderr.bin").write_bytes(proc.stderr)
    assert proc.returncode == 2
    result = {"schema_version": 1, "scope": "retained_evidence_replay_no_phone_operations", "phase_3_gate_passed": True,
              "phase_3_summary": {"path": summary_path.relative_to(PROJECT).as_posix(), **pin(summary_path)},
              "cycles": cycles, "inventory": {"path": inventory_path.relative_to(PROJECT).as_posix(), **pin(inventory_path)},
              "disabled_gate_command": command, "disabled_gate_exit_code": proc.returncode,
              "phase_4_gate_passed": False, "limitations": "Phase 3 original text capture predates byte-exact collector; this replays retained attributable user frames and restoration records, not a new hardware run."}
    (packet / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    shutil.copy2(Path(__file__), packet / "source.py")
    state = json.loads((PROJECT / "state.json").read_text(encoding="utf-8"))
    state["phase_3_device_gate_passed"] = True
    state["phase_3_evidence_selection"]["current_gate_review_result"] = (packet / "result.json").relative_to(PROJECT).as_posix()
    state["phase_3_completion_review"]["superseded_by"] = (packet / "result.json").relative_to(PROJECT).as_posix()
    state["phase_3_continuation"]["qualifying_a51_runs"] = 3
    state["phase_3_continuation"]["device_gate_passed"] = True
    state["phase_3_continuation"]["status"] = "gate_passed_retained_three_attributable_user_timer_return_runs"
    state["phase_4_criteria"]["hardware_inventory"] = "verified_original_fdt_and_independent_1m_boot_bytes_android_only"
    state["phase_4_inventory"] = {"result": inventory_path.relative_to(PROJECT).as_posix(), **pin(inventory_path)}
    state["phase_4_device_gate_passed"] = False
    (PROJECT / "state.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    note = (f"\n## Latest Phase 4 prerequisites ({stamp})\n\n"
            f"Original FDT/image inventory passed: `{inventory_path.relative_to(PROJECT).as_posix()}`. "
            "Android remained in the same boot; boot hash matched the pinned baseline, and 1 MiB matched the independent host image. "
            "UFS LUN 0 uses 4096-byte blocks; boot begins at absolute LBA 27792. GPIO debugfs is unavailable. "
            "These are Android observations, not XNU driver validation. The superseded Phase 4 gate exits 2 before device actions. "
            f"Phase 3's gate flag is reconciled against three distinct original PID 1/nonce/timer frames and retained baseline-return records: `{(packet / 'result.json').relative_to(PROJECT).as_posix()}`. "
            "Phase 4 remains in progress.\n\n")
    path = PROJECT / "docs/STATE.md"
    text = path.read_text(encoding="utf-8")
    marker = "## Verified build baseline"
    path.write_text(text.replace(marker, note + marker, 1), encoding="utf-8")
    with (PROJECT / "docs/IMPLEMENTATION-LOG.md").open("a", encoding="utf-8") as stream:
        stream.write(f"\n\n## P4-003 — Verify original inventory and reconcile retained Phase 3 gate\n\n"
                     f"Purpose/files: scripts/phase4-reconcile-evidence.py, state.json, docs/STATE.md and this log. "
                     f"Successful P4-002 collector run `20261114T145624153228Z-phase4-original-inventory-framed-binary` retained a valid 224,774-byte FDT, exact 1 MiB boot bytes, unchanged boot identity and baseline SHA-256. "
                     "Known bytes begin ANDROID!, with 4096-byte logical blocks and absolute LBA 27792. "
                     "The disabled old gate returned 2. Three Phase 3 user frames were replayed with distinct exact nonces, three bounded increasing IRQ/timer samples each, PID 1/uid 0, exit 0, status 6/reason 0 and baseline readbacks. "
                     f"Verification/rollback: `{(packet / 'result.json').relative_to(PROJECT).as_posix()}` retains checks, pins, gate stdout/stderr and before documents. "
                     "No new phone operation occurred. Old Phase 3/4 reviews and failed captures are preserved; historical Phase 3 text transport lacks the newer byte-exact framing. Phase 4 hardware drivers and execution remain pending.\n")
    print(json.dumps({"packet": str(packet), "phase_3_gate_passed": True, "phase_4_gate_passed": False}))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
