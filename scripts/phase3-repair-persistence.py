#!/usr/bin/env python3
"""Retain the failed hardware attempt and add bounded pstore diagnostics."""
from pathlib import Path
import json
from phase3_support import PROJECT, packet_new, packet_index, packet_verify, pin, json_write, update_documents, require


def main():
    packet = packet_new("persistence-correction", Path(__file__))
    failed_rel = "evidence/phase-3/loader-device-cycle/20261114T040656901957Z"
    packet_verify(PROJECT / failed_rel)
    failed = json.loads((PROJECT / failed_rel / "result.json").read_text())
    require(failed["baseline_restored"] and not failed["passed"], "Unexpected device result")
    core = (PROJECT / "prototype/phase3-loader/loader.c").read_text()
    core = core.replace("static uint32_t used;", "static volatile unsigned char *const pmsg = (void *)(uintptr_t)(0xf9e90000 + 12);\nstatic uint32_t used;")
    core = core.replace("    barrier();\n}\nstatic void envelope", "    /* The separately measured pmsg region is retained by recovery too.\n     * Mirror only the bounded completed envelope, never GNSS or other RAM. */\n    write32(0xf9e90000, 0);\n    for (uint32_t i = 0; i < used; i++) pmsg[i] = console[i];\n    barrier();\n    write32(0xf9e90004, used);\n    write32(0xf9e90008, used);\n    write32(0xf9e90000, 0x43474244u);\n    barrier();\n}\nstatic void envelope", 1)
    old = "    if (!validate()) fail(1);\n    if (!span(loader_context.fdt, 40, 0x80000000, 0x100000000) ||\n        !phase3_fdt_guard((const void *)(uintptr_t)loader_context.fdt, 2 * 1024 * 1024,\n                         loader_context.fdt, 0x80000000,\n                         payload_config.arena_base, payload_config.arena_limit)) fail(2);\n"
    require(old in core, "Loader validation anchor changed")
    core = core.replace(old, "", 1)
    core = core.replace('    if (payload_config.diagnostic == DIAG_FAULT) __asm__ volatile("brk #0x353");', '    if (payload_config.diagnostic == DIAG_FAULT) __asm__ volatile("brk #0x353");\n    /* Diagnostics touch no payload destination. Full runs still validate\n     * every input before the first copy. */\n' + old.rstrip())
    entry = (PROJECT / "prototype/phase3-loader/entry.S").read_text()
    entry = entry.replace("    bic x9, x21, #2\n    msr SCTLR_EL1, x9\n    isb", "    bic x9, x21, #2\n    bic x9, x9, #0x1000\n    msr SCTLR_EL1, x9\n    isb\n    ic iallu\n    dsb sy\n    isb", 1)
    cycle = (PROJECT / "scripts/phase3-device-cycle.py").read_text()
    start = cycle.index('        captured = adb("capture-original-console"')
    end = cycle.index('        fields = decoded["fields"]', start)
    cycle = cycle[:start] + '''        shell("capture-recovery-attachment", "dmesg | grep -E 'persistent_ram:|ramoops:|pstore:'", recovery=True, check=False)
        decoded = None
        failures = []
        for bank in ("console", "pmsg"):
            captured = adb("capture-original-" + bank, ["exec-out", "sh", "-c",
                "test -r /sys/fs/pstore/" + bank + "-ramoops-0 && cat /sys/fs/pstore/" + bank + "-ramoops-0"], check=False)
            (packet / (bank + ".original")).write_bytes(captured.stdout)
            try:
                require(captured.returncode == 0 and captured.stdout.startswith(b"HAKIOS_P3_ENVELOPE_V1 "), "No original " + bank + " envelope")
                validated = decode(captured.stdout, selected["nonce"])
                if decoded is None:
                    decoded = validated
                    result["capture_bank"] = bank
                else:
                    require(decoded["fields"] == validated["fields"] and decoded["log"] == validated["log"], "Pstore copies disagree")
            except (ValueError, RuntimeError) as exc:
                failures.append(str(exc))
        result["capture_diagnostics"] = failures
        require(decoded is not None, "; ".join(failures))
''' + cycle[end:]
    cycle = cycle.replace('result["checks"]["standalone_recovery_return"] = True', 'result["checks"]["recovery_reconnected"] = True')
    qemu = (PROJECT / "scripts/phase3-qemu-loader.py").read_text()
    qemu = qemu.replace('        context = struct.unpack("<24Q",', '''        qmp.save(0xf9e90000, 512 * 1024, packet / "pmsg.bin")
        mirrored = decode((packet / "pmsg.bin").read_bytes(), selected["nonce"])
        require(mirrored["fields"] == decoded["fields"] and mirrored["log"] == decoded["log"], "Pstore mirror mismatch")
        context = struct.unpack("<24Q",''', 1)
    log = (PROJECT / "docs/IMPLEMENTATION-LOG.md").read_text(encoding="utf-8")
    log += """

### P3-019 — Verify complete-loader cases and diagnose missing hardware pstore

Date: 14 November 2026, Asia/Calcutta. Phase 3 IN PROGRESS; qualifying A51 runs 0/3. Phase 4 continuation remains authorized.

Verification: complete-loader QEMU full/reset/fault/bad-TOC/bad-FDT all passed in packets 20261114T040127526468Z, 20261114T040236406931Z, 20261114T040236406312Z, 20261114T040537375181Z and 20261114T040537373356Z. The original-envelope replay passed raw/pstore forms and rejected 13 corruptions in evidence/phase-3/envelope-integrity/20261114T040832801985Z. Device/packager/decoder syntax passed run 20261114T040527723122Z.

Failed hardware reset run 20261114T040655868985Z is retained in evidence/phase-3/loader-device-cycle/20261114T040656901957Z. Candidate staging and partition readback passed; recovery reconnected after 47.484 seconds. Its console file was absent: the 65-byte capture is cat's error, not loader evidence. Only a historical pmsg file was present. No standalone reset, watchdog, loader-entry or XNU execution is attributable. Baseline boot was restored/read back and fresh Android boot completion/root verified; final boot ID 8d42cc10-a018-4939-bc4b-802905b852d7. The candidate nonce is retired. Read-only inspection run 20261114T041229728972Z observes a normal recovery-console file in restored Android and CONFIG_PSTORE_CONSOLE=y; missing attachment matches are retained.

Purpose/files: scripts/phase3-inspect-return.py, scripts/phase3-repair-persistence.py, prototype/phase3-loader/{loader.c,entry.S}, scripts/phase3-device-cycle.py, scripts/phase3-qemu-loader.py, docs/STATE.md, state.json and this log. The loader disables/invalidate its incoming instruction cache and mirrors completed bounded envelopes to the measured pmsg region at 0xF9E90000, separate from the 0xF9D90000 console. Reset/watchdog/fault diagnostics now precede expensive payload/FDT validation because they copy no payload; full execution retains all validation before copying. The device cycle explicitly tests file existence and original envelope bytes, retains both banks and recovery attachment diagnostics, rejects disagreeing validated copies and labels mere reconnection without attributing reset. QEMU checks both copies. All before/after bytes and patch are retained in this persistence-correction packet.

Verification pending for changed sources: strict fresh loader builds and five QEMU cases, followed by fresh reset/watchdog/fault hardware diagnostics and three qualifying full runs. Source-backed persistence/reset remains unknown. No recovery/DTBO or userdata write occurred in the failed cycle; two boot writes and two reboots restored the baseline.

Rollback: restore only indexed before sources/documents from the persistence-correction packet and rebuild in a new isolated loader directory. Retain the failure, retired nonce, original source/kernel/hello pins, baseline/recovery/DTBO images and all historical evidence. Phone restoration is already verified; do not claim a Phase 3 gate from QEMU or reconnection.
"""
    state = json.loads((PROJECT / "state.json").read_text(encoding="utf-8"))
    continuation = state["phase_3_continuation"]
    continuation.update({"new_hardware_loader_built": True, "new_xnu_candidate_launched": True,
        "qualifying_a51_runs": 0, "complete_loader_qemu_cases_passed": ["full", "reset", "fault", "bad-toc", "bad-fdt"],
        "complete_loader_qemu_scope": "before this persistence source correction; new QEMU validation pending",
        "latest_device_cycle": failed_rel + "/result.json", "latest_device_cycle_pin": pin(PROJECT / failed_rel / "result.json"),
        "latest_device_cycle_passed": False, "baseline_restored": True, "last_verified_android_boot_id": failed["boot_id_after"],
        "standalone_reset_verified": False, "independent_device_watchdog_verified": False,
        "recovery_persistence_verified": False, "last_device_error": failed["error"]})
    state["active_task"] = "phase_3_loader_persistence_and_hardware_diagnostics"
    state["phase_3_device_gate_passed"] = False
    current = (PROJECT / "docs/STATE.md").read_text(encoding="utf-8")
    update = """P3-019: five complete-loader QEMU cases and original-envelope integrity checks PASSED before the current persistence correction. Hardware reset attempt `evidence/phase-3/loader-device-cycle/20261114T040656901957Z` FAILED: recovery reconnected but no original console envelope existed. Baseline boot readback, fresh Android completion and root restoration VERIFIED; boot ID `8d42cc10-a018-4939-bc4b-802905b852d7`. This establishes restoration only. Loader entry, standalone reset/watchdog/log persistence and A51 XNU user/timer execution remain unverified (0/3). Current changes add a bounded pmsg copy and recovery attachment diagnostics; fresh source-bound QEMU/hardware checks are pending. Phase 4 is authorized after the actual Phase 3 gate.

"""
    current = current.replace("Updated 14 November", update + "Updated 14 November", 1)
    update_documents(packet, {"prototype/phase3-loader/loader.c": core, "prototype/phase3-loader/entry.S": entry,
        "scripts/phase3-device-cycle.py": cycle, "scripts/phase3-qemu-loader.py": qemu,
        "docs/IMPLEMENTATION-LOG.md": log, "docs/STATE.md": current, "state.json": json.dumps(state, indent=2) + "\n"})
    json_write(packet / "result.json", {"failed_cycle": failed_rel, "qualifying_runs": 0, "baseline_restored": True,
        "changed_loader_runtime_verified": False, "new_device_operations": False})
    packet_index(packet)
    print(packet.relative_to(PROJECT).as_posix())


if __name__ == "__main__":
    main()
