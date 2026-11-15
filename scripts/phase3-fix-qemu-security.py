#!/usr/bin/env python3
"""Preserve and correct the host harness's GICv2 security-state contract."""
import datetime as dt
import difflib
import hashlib
import json
from pathlib import Path
import shutil

PROJECT = Path(__file__).resolve().parents[1]


def pin(path):
    raw = path.read_bytes()
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def main():
    build = json.loads((PROJECT / "manifests/phase3-platform-build.json").read_text(encoding="utf-8"))
    qemu = json.loads((PROJECT / "manifests/phase3-platform-qemu.json").read_text(encoding="utf-8"))
    diag_rel = "evidence/phase-3/qemu-diagnostics/20261114T024440077269Z"
    diag = json.loads((PROJECT / diag_rel / "result.json").read_text(encoding="utf-8"))
    # Preflight documentation decoding before any source/document mutations.
    prior_log = (PROJECT / "docs/IMPLEMENTATION-LOG.md").read_text(encoding="utf-8")
    assert build["build_verified"] and not qemu["passed"]
    assert pin(PROJECT / build["packet"] / "artifacts/hakios-kernel") == build["artifacts"]["hakios-kernel"]
    assert len(diag["snapshots"]) == 2
    for snap in diag["snapshots"]:
        assert snap["globals"]["_hakios_timer_irqs"] == 0
        assert snap["system_registers"]["CNTV_CTL_EL0"] == "0x5"
        assert snap["gic_mmio"]["GICD_ISPENDR0"] == "0x8000000"
        assert snap["gic_mmio"]["GICC_HPPIR"] == "0x3fe"
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    packet = PROJECT / "evidence/phase-3/qemu-security-correction" / stamp
    packet.mkdir(parents=True, exist_ok=False)
    shutil.copy2(Path(__file__), packet / "source.py")
    changes = []
    patch = []

    def update(relative, text):
        target = PROJECT / relative
        old = target.read_bytes() if target.exists() else b""
        new = text.encode("utf-8")
        assert old != new, relative
        for label, raw in (("before", old), ("after", new)):
            copy = packet / label / relative
            copy.parent.mkdir(parents=True, exist_ok=True)
            copy.write_bytes(raw)
        target.write_bytes(new)
        changes.append({"path": relative, "before": {"bytes": len(old), "sha256": hashlib.sha256(old).hexdigest()}, "after": pin(target)})
        patch.append("".join(difflib.unified_diff(old.decode().splitlines(True), text.splitlines(True), fromfile="a/" + relative, tofile="b/" + relative)))

    relative = "prototype/a51-platform/qemu_entry.S"
    entry = (PROJECT / relative).read_text(encoding="utf-8")
    assert entry.count("    cmp x9, #8\n") == 1
    entry = entry.replace("/* Host-only direct EL1 entry", "/* Host-only nonsecure EL1 entry")
    entry = entry.replace("    cmp x9, #8\n", """    cmp x9, #12
    b.ne 0f
    /* Model firmware that assigned the virtual timer to nonsecure Group 1.
     * These secure GIC registers cannot be configured later by EL1 NS. */
    ldr x10, =0x08000000
    mov w11, #0xffffffff
    str w11, [x10, #0x80]
    mov w11, #2
    str w11, [x10]
    ldr x10, =0x08010000
    str w11, [x10]
    mov w11, #0xff
    str w11, [x10, #4]
    dsb sy
    mov x9, #0x501 /* SCR_EL3: NS, HCE, AArch64 lower levels */
    msr SCR_EL3, x9
    mov x9, #0x80000000
    msr HCR_EL2, x9
    mov x9, #3
    msr CNTHCTL_EL2, x9
    msr CNTVOFF_EL2, xzr
    adr x9, 1f
    msr ELR_EL3, x9
    mov x9, #0x3c5 /* EL1h, DAIF masked */
    msr SPSR_EL3, x9
    eret
0:
    cmp x9, #8
""")
    relative_qemu = "scripts/phase3-qemu-platform.py"
    checker = (PROJECT / relative_qemu).read_text(encoding="utf-8")
    assert checker.count('"virt,gic-version=2"') == 1
    checker = checker.replace('"virt,gic-version=2"', '"virt,gic-version=2,secure=on,virtualization=on"')
    checker = checker.replace("QEMU virt TCG Cortex-A53 GICv2 only", "QEMU virt TCG Cortex-A53 GICv2, EL3 to nonsecure EL1 only")
    update(relative, entry)
    update(relative_qemu, checker)
    # The diagnostic before bytes are already retained by its failed packet.
    diagnostic = "scripts/phase3-qemu-diagnose.py"
    before_diag = PROJECT / "evidence/phase-3/qemu-diagnostics/20261114T024202843329Z/source.py"
    copy = packet / "before" / diagnostic
    copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(before_diag, copy)
    copy = packet / "after" / diagnostic
    copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(PROJECT / diagnostic, copy)
    changes.append({"path": diagnostic, "before": pin(before_diag), "after": pin(PROJECT / diagnostic)})
    patch.append("".join(difflib.unified_diff(before_diag.read_text(encoding="utf-8").splitlines(True), (PROJECT / diagnostic).read_text(encoding="utf-8").splitlines(True), fromfile="a/" + diagnostic, tofile="b/" + diagnostic)))

    state = json.loads((PROJECT / "state.json").read_text(encoding="utf-8"))
    assert state["phase_3_status"] == "in_progress" and not state["phase_3_device_gate_passed"]
    state["phase_3_continuation"].update({
        "new_xnu_candidate_built": True,
        "new_xnu_candidate_launched": False,
        "platform_build_result": build["packet"] + "/result.json",
        "platform_build_artifacts": build["artifacts"],
        "full_qemu_result": qemu["packet"] + "/result.json",
        "full_qemu_passed": False,
        "timer_diagnostic_result": diag_rel + "/result.json",
        "timer_diagnostic_scope": "replayed QEMU payload only; zero serviced IRQs; timer pending in disabled Group 1",
        "qemu_security_correction": str(packet.relative_to(PROJECT)),
        "qemu_security_correction_execution": "pending",
        "device_gate_passed": False,
    })
    state["next_action"] = "validate_nonsecure_el1_qemu_timer_delivery_then_repair_hardware_capture_and_return"
    update("state.json", json.dumps(state, indent=2) + "\n")

    summary = f"""P3-010 host progress: the Cortex-A53/GICv2 kernel and static PID 1 build passed in `{build['packet']}` (15,183,248-byte kernel; 16,584-byte hello). The first full QEMU boot timed out without user-program or return evidence. Diagnostic `{diag_rel}` observes CNTV_CTL=5 (enabled, expired, unmasked), timer PPI 27 pending, zero serviced timer IRQs and GICC_HPPIR=1022. The original harness enabled Group 0 while placing the timer in Group 1. The host harness now models firmware entry through EL3 to **nonsecure EL1**, including secure timer-group assignment. Its corrected execution is pending; no new phone operation occurred. See `docs/PHASE-3-PLATFORM.md`."""
    doc = (PROJECT / "docs/STATE.md").read_text(encoding="utf-8")
    marker = "Updated 14 November 2026, Asia/Calcutta."
    assert marker in doc
    update("docs/STATE.md", doc.replace(marker, summary + "\n\n" + marker, 1))
    guide = f"""# Phase 3 single-core platform continuation

Phase 3 remains **IN PROGRESS**, device gate **UNPASSED**. Three qualifying A51 runs remain required. No phone operation occurred during these build and QEMU diagnostics.

## Implemented and build-verified

Selected isolated tree: `/opt/a51-hakios/experimental/phase3-port/20261114T013656044425Z`. Original common/native sources and dependencies remain preserved by `manifests/phase3-workspace.json`.

The Cortex-A53 ARMv8.0 configuration, GICv2 MMIO backend, boot-core/timer sysctls and static Darwin PID 1 are implemented. PID 1 requires a fresh 128-bit nonce, one CPU, matching MIDR and three measured one-second sleeps with increasing interrupt counts. Build `{build['packet']}` passes kernel and hello commands. Kernel SHA-256 `{build['artifacts']['hakios-kernel']['sha256']}`; hello SHA-256 `{build['artifacts']['userland/hello']['sha256']}`. Build success establishes compilation only.

## Execution failures and diagnostic findings

Full boot `evidence/phase-3/platform-qemu/20261114T022820401480Z` reached VM/IOKit setup but timed out at 120 seconds without a physical return record. Serial ends after the unavailable boot framebuffer message. Initial diagnostic `evidence/phase-3/qemu-diagnostics/20261114T023720235624Z` reached `_processor_idle`/`_ml_get_timebase`; timer IRQ and loader log counts were zero.

Expanded diagnostic `evidence/phase-3/qemu-diagnostics/20261114T024202843329Z` failed because QEMU's target XML uses undeclared `xi:include`. `scripts/phase3-qemu-diagnose.py` now adds the missing namespace only to parser input, retains original XML and reads advertised registers over the local GDB socket. Corrected run `{diag_rel}` captured two snapshots: virtual timer enabled/expired/unmasked; PPI 27 pending; timer IRQ count zero; Group 1 selected; distributor and CPU control 1; HPPIR 1022. No GIC interrupt acknowledgement/deactivation registers were read by the diagnostic.

The original security-disabled QEMU entry exposes a Group 0/Group 1 view inconsistent with the backend's nonsecure EL1 contract. `prototype/a51-platform/qemu_entry.S` now initializes the timer group from EL3 before entering nonsecure EL1, and `scripts/phase3-qemu-platform.py` enables QEMU security and virtualization. This is a host firmware model, not an A51 firmware observation. Corrected execution remains pending. The historical nonce is reused only by diagnostics and cannot qualify as a new gate run.

## Rebuild and validation

From the Windows workspace, use `python hakios-a51/scripts/run.py --label phase3-platform-build -- wsl.exe -d A51-KernelBuilder --cd /opt/a51-hakios -- python3 /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/phase3-build-platform.py`.

Execute the complete host test with the same wrapper and `scripts/phase3-qemu-platform.py --seconds 120`. It generates a fresh nonce and checks original PID 1/timer logs plus a physical return record. Its result always leaves the A51 gate false. Replays with `scripts/phase3-qemu-diagnose.py --packet <retained-platform-qemu-packet> --seconds 20` retain their diagnostic scope explicitly.

## Remaining hardware contracts and recovery

Repair the existing hardware loader's overlapping/unbounded GNSS copies, stale-register magic write, unbounded UART/log copies and exception-state loss before launching a candidate. Reserved memory labels do not establish exclusive ownership or log persistence. Prior raw RAM capture recovered zero validated XNU log bytes. Establish a bounded attributable per-run capture and return/reset mechanism, then perform three real A51 runs reaching PID 1 with timers and restore/verify the baseline boot/root state. Single boot-core support does not establish multicore support.

Rollback only the indexed host harness/document before copies in `{packet.relative_to(PROJECT).as_posix()}`; preserve all failed/successful evidence. Kernel source rollback uses the indexed platform adaptation/correction packets or a new isolated tree from the source-preservation inputs. Android boot remains the last verified baseline hash `eb30609a62999e3282ac81e0a5e56411ef12ec1a39c107171bf3e01209c7cb67`.
"""
    update("docs/PHASE-3-PLATFORM.md", guide)
    index = (PROJECT / "docs/INDEX.md").read_text(encoding="utf-8")
    marker = "## Guides by task"
    update("docs/INDEX.md", index.replace(marker, "Current Phase 3 platform build, timer diagnostics and rebuild/recovery guide: [PHASE-3-PLATFORM.md](C:/Users/Ankit/Desktop/A51/hakios-a51/docs/PHASE-3-PLATFORM.md).\n\n" + marker, 1))
    log = prior_log
    update("docs/IMPLEMENTATION-LOG.md", log + f"""

### P3-010 — Retain full-build results, inspect pending timer and correct QEMU security entry

Date: 14 November 2026, Asia/Calcutta. Status: kernel/hello build verified; full boot unpassed; corrected host entry execution pending. Phase 3 IN PROGRESS, A51 gate UNPASSED.

Purpose: finish P3-009's evidence recording and investigate the full-boot stall before another hardware attempt. Files: scripts/phase3-qemu-diagnose.py, scripts/phase3-qemu-platform.py, prototype/a51-platform/qemu_entry.S, scripts/phase3-fix-qemu-security.py, docs/PHASE-3-PLATFORM.md, docs/INDEX.md, docs/STATE.md, state.json and this log. Before/after bytes and changes are retained in `{packet.relative_to(PROJECT).as_posix()}`.

Verification: build run 20261114T022738964712Z passed kernel and static hello; result `{build['packet']}/result.json`. Full QEMU run 20261114T022819179908Z failed its 120-second physical-return deadline. Diagnostic 20261114T023709972906Z retained idle-loop snapshots with zero timer/log counts; 20261114T024153975496Z failed XML parsing. Namespace-corrected diagnostic run 20261114T024430179956Z passed and retained two original register/MMIO snapshots in `{diag_rel}`. Timer is enabled/expired/unmasked; PPI 27 is pending; Group 1 is selected but only Group 0 is enabled in the original QEMU model. The host entry now assigns nonsecure timer ownership from EL3 and enters EL1 NS with security/virtualization enabled. Runtime validation of the correction remains pending. Exact consequential commands, exit statuses, output and times are retained by scripts/run.py. Source inspection attempts with guessed nonexistent directories remain retained; successful inspections establish their corrected locations. First correction run 20261114T024658997348Z failed when Windows cp1252 could not decode the implementation log after partial updates; its retained before/after files were used to restore those updates before rerunning. The helper now preflights UTF-8 documentation decoding before mutations.

Limitations: these are QEMU diagnostics with a reused historical nonce, not A51 runs. No new phone query/write/reboot/flash occurred in this segment; no user/timer/return hardware gate changed. Group-assignment diagnosis does not yet prove all startup failures are resolved. Hardware loader ownership, bounded logs/fault/reset and three consecutive A51 cycles remain pending.

Rollback: restore only the indexed host source/document before copies or rebuild an isolated tree from preserved pinned inputs. Retain failed build/QEMU/XML attempts and all original source/dependency and Phase 1 packets. Baseline Android artifacts and boot partition were unchanged.
""")
    (packet / "adaptations.patch").write_text("".join(patch))
    result = {"schema_version": 1, "packet": str(packet.relative_to(PROJECT)), "changes": changes,
              "build_result": build["packet"] + "/result.json", "diagnostic_result": diag_rel + "/result.json",
              "correction_executed": False, "device_operations": False, "phase_3_device_gate_passed": False}
    (packet / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    inventory = [{"path": str(p.relative_to(packet)), **pin(p)} for p in sorted(packet.rglob("*")) if p.is_file()]
    (packet / "index.json").write_text(json.dumps(inventory, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ("packet", "correction_executed", "device_operations", "phase_3_device_gate_passed")}, indent=2))


if __name__ == "__main__":
    main()
