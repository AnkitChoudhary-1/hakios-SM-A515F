#!/usr/bin/env python3
"""Preserve and correct the simulated Phase 4 completion decision."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
import shutil

PROJECT = Path(__file__).resolve().parents[1]
LEGACY = "evidence/phase-4/silicon-execution/20261114T144034703838Z/phase4_execution_summary.json"


def main() -> int:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    packet = PROJECT / "evidence/phase-4/completion-correction" / stamp
    packet.mkdir(parents=True, exist_ok=False)
    paths = ["README.md", "docs/INDEX.md", "docs/STATE.md", "state.json",
             "docs/PHASE-4-COMPLETION-REVIEW.md", "docs/IMPLEMENTATION-LOG.md",
             "scripts/phase4-device-gate.py", "scripts/phase4-probe-hardware.py",
             "scripts/phase4-build-drivers.py", "userland/phase4_interactive_test.c"]
    paths += [str(p.relative_to(PROJECT)).replace("\\", "/")
              for p in sorted((PROJECT / "drivers").rglob("*")) if p.is_file()]
    for relative in paths:
        destination = packet / "before" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PROJECT / relative, destination)
    shutil.copy2(PROJECT / LEGACY, packet / "legacy-summary.json")
    findings = [
        {"subsystem": "display", "source": "userland/phase4_interactive_test.c",
         "finding": "Fills a local 16x16 array; reported physical address/dimensions are assigned constants."},
        {"subsystem": "brightness", "source": "drivers/display/ExynosDSIM.cpp",
         "finding": "Absent MMIO returns success; the user test passes MMIO zero and reports a software field."},
        {"subsystem": "touch", "source": "userland/phase4_interactive_test.c",
         "finding": "synthetic_touch_pkt is supplied by the test, with no I2C controller transaction."},
        {"subsystem": "keys", "source": "userland/phase4_interactive_test.c",
         "finding": "ExynosKey_UpdateRaw injects the three key states in software, with no GPIO read."},
        {"subsystem": "storage", "source": "drivers/storage/ExynosUFSHost.cpp",
         "finding": "Manufactures HAKIOSRO/55AA in the buffer. No hardware read is submitted, and hardware branch is incomplete."},
        {"subsystem": "inventory", "source": "scripts/phase4-probe-hardware.py",
         "finding": "FDT cells decoded in host byte order; UFS address is wrong; failed commands are suppressed."},
        {"subsystem": "gate", "source": "scripts/phase4-device-gate.py",
         "finding": "Substring matches accept fabricated markers; no finally restoration or required larger-image proof."},
    ]
    user = (PROJECT / "userland/phase4_interactive_test.c").read_text(encoding="utf-8")
    ufs = (PROJECT / "drivers/storage/ExynosUFSHost.cpp").read_text(encoding="utf-8")
    if "synthetic_touch_pkt" not in user or "HAKIOSRO" not in ufs:
        raise RuntimeError("Sources changed; review the new bytes before correcting their status")
    result = {"schema_version": 1, "timestamp": stamp,
              "scope": "source_and_original_evidence_review", "phase_4_complete": False,
              "phase_4_device_gate_passed": False, "rejected_evidence": LEGACY,
              "decision": "simulated_components_executed_on_device_do_not_validate_hardware",
              "findings": findings, "phone_operations": False}
    (packet / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    selection = str((packet / "result.json").relative_to(PROJECT)).replace("\\", "/")
    state_path = PROJECT / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update(active_phase=4, active_task="complete_phase_4_real_display_input_read_only_storage",
                 phase_4_status="in_progress", phase_4_device_gate_passed=False)
    state["phase_4_completion_review"] = {"path": selection, "decision": "incomplete",
                                          "legacy_summary_rejected": LEGACY}
    state["phase_4_criteria"] = {
        "hardware_inventory": "legacy_capture_rejected_correct_capture_pending",
        "display_scanout_and_dimensions": "unverified",
        "dsim_repeatable_brightness": "unverified",
        "physical_touch_events_and_coordinates": "unverified",
        "physical_power_volume_key_events": "unverified",
        "ufs_read_known_image": "unimplemented_hardware_path",
        "larger_image_loading": "unimplemented_hardware_path",
        "storage_writes_disabled": "software_rejection_only_real_driver_pending",
        "legacy_simulation": "preserved_not_accepted_as_hardware_evidence"}
    state["blockers"] = ["Phase 4 hardware operations are not established by the legacy simulated test."]
    state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    intro = ("Phase 1 and Phase 2 remain COMPLETE. Phase 3 has three retained A51 PID 1/timer/return runs in "
             "`evidence/phase-3/repeatability/20261114T132905926137Z/consecutive_runs_summary.json`. "
             "Phase 4 is **IN PROGRESS**; its device gate is **UNPASSED**. Phase 5 remains planned.\n\n"
             "The previous Phase 4 completion decision is superseded by a source review: the test used "
             "a local framebuffer, absent DSIM MMIO, synthetic touch/key events and fabricated storage bytes. "
             "Actual display output/brightness, physical input, UFS reads against independent image bytes, "
             "larger-image loading and a read-only hardware submission path still require verification. "
             f"The original files/results are preserved in `{selection.rsplit('/', 1)[0]}/before/`. "
             "See [Phase 4 review](/C:/Users/Ankit/Desktop/A51/hakios-a51/docs/PHASE-4-COMPLETION-REVIEW.md).\n\n")
    state_doc = PROJECT / "docs/STATE.md"
    old = state_doc.read_text(encoding="utf-8")
    historical = old[old.index("## Verified build baseline"):]
    state_doc.write_text("# Current state\n\n" + intro +
                         "- Active phase: Phase 4.\n- Connected target: Samsung Galaxy A51 SM-A515F, serial A51_SERIAL_HERE.\n"
                         "- Current phone baseline/root must be freshly checked before hardware work.\n"
                         "- Preserve Android projects, original sources/images and all previous evidence.\n"
                         "- The older sections below retain their original dates; their phase/next-action statements are historical.\n\n"
                         + historical, encoding="utf-8")
    readme = PROJECT / "README.md"
    old = readme.read_text(encoding="utf-8")
    remainder = old[old.index("Historical milestone sections below"):]
    readme.write_text("# HakiOS on Galaxy A51 — implementation workspace\n\n" + intro +
                      "Start with [current state](/C:/Users/Ankit/Desktop/A51/hakios-a51/docs/STATE.md), "
                      "[file map](/C:/Users/Ankit/Desktop/A51/hakios-a51/docs/INDEX.md), "
                      "[implementation log](/C:/Users/Ankit/Desktop/A51/hakios-a51/docs/IMPLEMENTATION-LOG.md) "
                      "and the [roadmap](/C:/Users/Ankit/Desktop/A51/hakios-assessment/ROADMAP.md).\n\n"
                      + remainder, encoding="utf-8")
    index = PROJECT / "docs/INDEX.md"
    old = index.read_text(encoding="utf-8")
    index.write_text("# Documentation index and reading order\n\n" + intro + old[old.index("1. `README.md`"):], encoding="utf-8")
    review = ("# Phase 4 completion review — 14 November 2026\n\n"
              "**Decision: INCOMPLETE. Phase 4 remains active; its hardware gate is unpassed.**\n\n"
              "The previous three runs show that a Darwin user program executed its simulation on the phone. "
              "They do not prove that the simulated display, input or storage code used hardware. "
              "Nonce attribution, timer advancement and boot restoration do not change that distinction.\n\n"
              f"Source review: `{selection}`. Rejected summary (preserved): `{LEGACY}`.\n\n"
              "| Requirement | Finding | Remaining work |\n|---|---|---|\n"
              "| Display dimensions and output | Local 16x16 array; reported 1080x2400/physical base are constants | Measure actual scanout and demonstrate visible output |\n"
              "| Repeatable brightness | No MMIO access; software field reports 220 | Real DSIM/panel transactions and observed changes |\n"
              "| Touch coordinates | Synthetic six-byte packet; board selects MSS100 16-byte format | Matching I2C driver and physical touch events |\n"
              "| Power/volume behavior | Software-injected states | GPIO sampling, debouncing, press/release events |\n"
              "| Known storage contents | Fabricated HAKIOSRO and 55AA | Real UFS DMA read compared with independent source bytes |\n"
              "| Larger image loading | No hardware-backed image path | Bounded multi-block image loading with digest verification |\n"
              "| Storage writes disabled | Stub rejection only | Whitelisted read-only commands/directions in actual submission path |\n\n"
              "The roadmap does not require three Phase 4 cycles or 60 fps. Host unit checks and QEMU can validate "
              "bounds and software behavior; the hardware gate requires A51 execution and physical interaction.\n\n"
              "Recovery: preserve the pinned baseline boot image and use a bounded candidate cycle with verified "
              "readback/restoration. The old phase4-device-gate.py must not be rerun: it also lacks reliable error handling.\n")
    (PROJECT / "docs/PHASE-4-COMPLETION-REVIEW.md").write_text(review, encoding="utf-8")
    with (PROJECT / "docs/IMPLEMENTATION-LOG.md").open("a", encoding="utf-8") as log:
        log.write("\n\n## P4-001 — Reject simulated hardware completion and resume real Phase 4 work\n\n"
                  "Date: 14 November 2026, Asia/Calcutta. User request: complete Phase 4.\n\n"
                  "Purpose/files: scripts/phase4-begin.py; README.md, docs/{STATE,INDEX,PHASE-4-COMPLETION-REVIEW,IMPLEMENTATION-LOG}.md "
                  "and state.json. Correct false hardware claims after examining the exact test/driver sources. "
                  f"Review and rollback copies: {selection}. Original Phase 4 summaries and binaries are untouched.\n\n"
                  "Verification: source predicates require the original synthetic touch packet and fabricated UFS signature; "
                  "the structured review records each missing hardware operation. No phone operation in this correction. "
                  "Phase 3 summary remains selected; its inconsistent machine-readable gate needs separate reconciliation.\n\n"
                  "Limitations: this review establishes incompleteness, not hardware behavior. Actual display/input/UFS/image "
                  "implementation and execution are pending. Rollback: the packet's before/ paths retain every changed document "
                  "and original test/helper/driver; do not reinstate a completion claim without the roadmap gate.\n")
    (packet / "source.py").write_bytes(Path(__file__).read_bytes())
    records = [{"path": str(p.relative_to(packet)).replace("\\", "/"), "bytes": p.stat().st_size,
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
               for p in sorted(packet.rglob("*")) if p.is_file()]
    (packet / "index.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"packet": str(packet), "phase_4_complete": False, "findings": len(findings)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
