#!/usr/bin/env python3
"""Record the already captured Android loader audit without promoting hardware gates."""
import json
from pathlib import Path
from phase3_support import PROJECT, json_write, packet_new, packet_index, packet_verify, pin, require, update_documents


def main():
    manifest = json.loads((PROJECT / "manifests/phase3-loader-contract.json").read_text(encoding="utf-8"))
    audit = PROJECT / manifest["packet"]
    packet_verify(audit)
    result = json.loads((audit / "result.json").read_text(encoding="utf-8"))
    require(all(result["checks"].values()), "Loader audit's required Android checks did not pass")
    require(not result["operations"]["device_writes"] and not result["operations"]["reboot"], "Unexpected audit scope")
    packet = packet_new("loader-contract-selection", Path(__file__))
    rel = packet.relative_to(PROJECT).as_posix()
    audit_rel = audit.relative_to(PROJECT).as_posix()
    state = json.loads((PROJECT / "state.json").read_text(encoding="utf-8"))
    require(state["phase_3_status"] == "in_progress" and not state["phase_3_device_gate_passed"], "Hardware gate drift")
    state["phase_3_continuation"].update({
        "loader_contract_result": audit_rel + "/result.json", "loader_contract_pin": pin(audit / "result.json"),
        "loader_contract_scope": result["scope"], "loader_contract_selection_packet": rel,
        "recovery_log_layout_verified": False, "standalone_reset_verified": False,
        "independent_device_watchdog_verified": False,
    })
    summary = (f"P3-012 retained loader-contract audit `{audit_rel}` verifies Android root and ramoops "
        "base `0xF9D10000`/2 MiB, 512 KiB console at `0xF9D90000`, and ECC disabled. "
        "Live PMU/watchdog device-tree properties agree with the retained source. Watchdog sysfs output "
        "was empty; the filtered attachment dmesg query exited 1 with no matches. Recovery layout, "
        "persistence and standalone watchdog/reset remain unverified. Before-loader sources, raw queries "
        "and checksums are retained; the audit made no device write or reboot. Qualifying A51 runs remain 0/3.")
    doc = (PROJECT / "docs/STATE.md").read_text(encoding="utf-8")
    marker = "\n\nUpdated 14 November"
    require(marker in doc, "STATE insertion marker absent")
    log = (PROJECT / "docs/IMPLEMENTATION-LOG.md").read_text(encoding="utf-8")
    entry = f"""

### P3-012 — Retain Android reset/watchdog/pstore contracts and prepare recovery validation

Date: 14 November 2026, Asia/Calcutta. Status: Android read-only audit verified; recovery/standalone reset unverified. Phase 3 IN PROGRESS, device gate UNPASSED, qualifying runs 0/3.

Purpose: ground the loader repair in retained platform source and the phone's actual Android ramoops parameters. Files: scripts/phase3-audit-loader-contract.py, scripts/phase3_support.py, scripts/phase3-record-loader-contract.py, scripts/phase3-recovery-contract.py, manifests/phase3-loader-contract.json, docs/STATE.md, state.json and this log. The shared helper retains original command bytes/times/status, verifies packet checksums and preserves exact documentation before/after bytes. The recovery script is prepared to verify pinned boot/recovery images, query actual recovery layout and return to unchanged baseline Android without partition writes.

Verification: run `20261114T030511071271Z-phase3-audit-loader-contract-live` passed exit 0; packet `{audit_rel}` preserves 14 selected Android source files, six original loader/packer/package files, exact ADB queries and raw results. All five required checks pass: root UID 0, mem_size=2097152, mem_address=4191223808 (`0xF9D10000`), console_size=524288 and ecc=0. Record/ftrace/pmsg regions are each 512 KiB. PMU DT is `0x11860000`; watchdog cluster 0/1 DT bases are `0x10050000`/`0x10060000`, compatible exynos7-wdt/exynos8-wdt. Watchdog sysfs returned empty output, and filtered pstore/watchdog attachment dmesg exited 1 with no matches; neither establishes a working interface. This selector verifies every indexed retained byte before changing current documentation.

Findings: Linux reset uses ACPM shutdown before PMU SWRESET at offset 0x400 and conditionally clears DFD reset-disable at 0x500. Samsung recovery reason uses INFORM2/INFORM3 at 0x808/0x80c; generic recovery uses SYSIP_DAT0 at 0x810. Standalone ACPM prerequisites and direct-reset success remain unresolved. Watchdog reset/disable bits are 23/24 in PMU offsets 0x408/0x40c; PERI QCH controls are 0x10033068/0x1003306c. Source-backed addresses are not proof of a working standalone watchdog. Ramoops console uses a 12-byte signature/start/size header; publication must follow bounded data/checksum completion. Native XNU orderly return reaches the stub with the MMU ON and dirty data already being cleaned; early return supplies ESR/ELR/FAR/LR/SP but clobbers general registers. Those contracts require explicit loader/native repair.

Limitations: Android runtime only; recovery memory layout and persistence, physical loader memory ownership, bounded return, actual A51 PID 1/timers and three qualifying runs remain pending. No boot write/reboot/flash occurred in the audit or this selector. The upcoming recovery-contract operation contains two controlled reboots but no partition write; its outcome will be recorded separately. Original source assessments remain hypotheses, not hardware validation.

Rollback/recovery: restore only indexed documentation before copies from `{rel}` for bookkeeping rollback, preserving this entry and the audit. Original loader bytes are in the audit before/ tree. The phone's baseline boot remains unchanged. The recovery script verifies and retains the same pinned baseline/recovery images and returns through ADB to Android; preserve failed attempts and report any pending recovery state instead of claiming success.
"""
    update_documents(packet, {"state.json": json.dumps(state, indent=2) + "\n",
        "docs/STATE.md": doc.replace(marker, "\n\n" + summary + marker, 1),
        "docs/IMPLEMENTATION-LOG.md": log + entry})
    json_write(packet / "result.json", {"audit": audit_rel, "audit_pin": pin(audit / "result.json"),
        "packet": rel, "device_operations": False, "device_gate_passed": False})
    packet_index(packet)
    print(json.dumps({"packet": rel, "audit_verified": True, "qualifying_a51_runs": 0}))


if __name__ == "__main__":
    main()
