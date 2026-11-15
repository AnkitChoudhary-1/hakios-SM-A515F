#!/usr/bin/env python3
"""Derive isolated, bounded Phase 4 sources from the proven standalone loader."""
from __future__ import annotations
import json
from pathlib import Path
import shutil
from phase4_support import PROJECT, new_packet, pin, require, documents, write_json, index_packet


VALIDATE_TOC = r'''
    /* Validate every TOC source and destination before performing any copy. */
    mov x26, x20
    adrp x27, _payload_toc_end
    add x27, x27, :lo12:_payload_toc_end
    adrp x18, _payload_end
    add x18, x18, :lo12:_payload_end
    sub x18, x18, x19
.Lphase4_validate_toc:
    add x6, x26, #32
    cmp x6, x27
    b.hi .Lphase4_bad_toc
    ldp x21, x22, [x26]
    ldp x23, x24, [x26, #16]
    add x26, x26, #32
    cmn x21, #1
    b.eq .Lphase4_toc_sentinel
    cmp x21, x18
    b.hi .Lphase4_bad_toc
    sub x6, x18, x21
    cmp x23, x6
    b.hi .Lphase4_bad_toc
    adds x6, x23, x24
    b.cs .Lphase4_bad_toc
    cbz x6, .Lphase4_bad_toc
    ldr x7, =0x83000000
    cmp x22, x7
    b.lo .Lphase4_bad_toc
    adds x7, x22, x6
    b.cs .Lphase4_bad_toc
    ldr x8, =0x847f0000
    cmp x7, x8
    b.hi .Lphase4_bad_toc
    /* Reject pairwise destination overlap, including zero-fill extents. */
    mov x9, x20
1:  sub x8, x26, #32
    cmp x9, x8
    b.hs .Lphase4_validate_toc
    ldp x6, x8, [x9, #8]
    ldr x11, [x9, #24]
    add x8, x8, x11
    add x8, x8, x6
    cmp x7, x6
    b.ls 2f
    cmp x8, x22
    b.hi .Lphase4_bad_toc
2:  add x9, x9, #32
    b 1b
.Lphase4_toc_sentinel:
    cmp x26, x27
    b.ne .Lphase4_bad_toc
    orr x6, x22, x23
    orr x6, x6, x24
    cbnz x6, .Lphase4_bad_toc
    adrp x10, xnu_boot_record
    add x10, x10, :lo12:xnu_boot_record
    b .Ltoc_loop
.Lphase4_bad_toc:
    mov x0, #0
    mov x1, #0
    mov x2, #4
    mov x3, #0x101
    b xnu_loader_return_stub
'''


def main():
    packet = new_packet("device-path-preparation", __file__)
    original = PROJECT / "prototype/xnu-loader"
    target = PROJECT / "prototype/phase4-loader"
    before_pins = {p.name: pin(p) for p in original.iterdir() if p.is_file()}
    for name in ("a51_loader.ld", "xnu_trampoline.h"):
        require(not (target / name).exists(), "Refusing to replace existing Phase 4 source: " + name)
        shutil.copy2(original / name, target / name)
    loader = (original / "a51_loader.S").read_text(encoding="utf-8")
    start = loader.index("    // Initialize persistent RAM bank")
    end = loader.index("    // Iterate over Table of Contents", start)
    loader = loader[:start] + "    bl phase4_publish_record\n\n" + loader[end:]
    for beginning, ending in (("    // Mirror early banner", "    // Record incoming silicon state"),
                              ("    // Mirror jump message", "    // Memory barriers")):
        start = loader.index(beginning)
        end = loader.index(ending, start)
        loader = loader[:start] + "#ifndef PHASE4_LOADER_QEMU\n" + loader[start:end] + "#endif\n\n" + loader[end:]
    anchor = "    mov     sp, x9\n"
    require(loader.count(anchor) == 1, "Stack anchor changed")
    loader = loader.replace(anchor, anchor + "\n    adrp x6, phase4_vectors\n    add x6, x6, :lo12:phase4_vectors\n    msr vbar_el1, x6\n    isb\n    bl phase4_arm_watchdog\n")
    anchor = ".Ltoc_loop:\n"
    loader = loader.replace(anchor, VALIDATE_TOC + "\n" + anchor, 1)
    start = loader.index(".Ltoc_done:")
    end = loader.index("    // Mirror jump message", start)
    loader = loader[:start] + r'''.Ltoc_done:
    mov x4, #XNU_BOOT_STATUS_PAYLOAD_LOADED
    str x4, [x10, #XBR_O_STATUS]
    bl phase4_publish_record
    adrp x6, xnu_trampoline_config
    add x6, x6, :lo12:xnu_trampoline_config
    ldr x7, [x6, #48]
    cbz x7, 1f
    /* Dedicated watchdog-expiry candidate, never enters XNU. */
    mov x7, #8
    str x7, [x10, #XBR_O_STATUS]
    mov x7, #2
    str x7, [x10, #184]
    bl phase4_publish_record
2:  wfe
    b 2b
1:

''' + loader[end:]
    start = loader.index("    // If xnu_trampoline_entry returns:")
    end = loader.index("    .section .rodata", start)
    loader = loader[:start] + "    mov x0, #0\n    mov x1, #0\n    mov x2, #4\n    mov x3, #0x102\n    b xnu_loader_return_stub\n\n" + loader[end:]
    loader = loader.replace('#include "xnu_trampoline.S"', '#include "xnu_trampoline.S"\n#include "recovery.S"\n#include "return.S"')
    trampoline = (original / "xnu_trampoline.S").read_text(encoding="utf-8")
    trampoline = trampoline[:trampoline.index("/*\n * Return stub called by XNU")]
    # Use the same non-overlapping publisher at every entry milestone.
    import re
    trampoline, count = re.subn(r"#ifdef XNU_CONFIG_EXTERNAL\n.*?#endif", "    bl phase4_publish_record", trampoline, flags=re.S)
    require(count == 3, "Expected exactly three external-record mirrors")
    replacements = {
        "prototype/phase4-loader/a51_loader.S": loader,
        "prototype/phase4-loader/xnu_trampoline.S": trampoline,
    }
    inventory_rel = "evidence/phase-4/live-inventory/20261114T162645749263Z/result.json"
    inventory = json.loads((PROJECT / inventory_rel).read_text(encoding="utf-8"))
    require(inventory["inventory_valid"] and all(inventory["checks"].values()), "Fresh inventory failed")
    state = json.loads((PROJECT / "state.json").read_text(encoding="utf-8"))
    state["phase_4_inventory"] = {"result": inventory_rel, **pin(PROJECT / inventory_rel)}
    state["next_action"] = "build_verify_phase4_bounded_loader_and_binary_reader_then_watchdog_hardware_test"
    log = (PROJECT / "docs/IMPLEMENTATION-LOG.md").read_text(encoding="utf-8") + f"""

## P4-012 — Prepare bounded standalone Phase 4 recovery and capture

Purpose/files: scripts/phase4-prepare-device-path.py, prototype/phase4-loader/
(derived assembly/linker/header plus new recovery.S and return.S), state.json,
docs/STATE.md and this log. Preserve the proven Phase 3 loader unchanged. The
isolated derivative validates all TOC spans and overlaps before copying, adds
early exception vectors, arms the source-backed cluster-0 watchdog, records
countdown and an exact nonce, and provides a dedicated expiry test. Return log
sources are range checked; copies are capped at 64 KiB (400 bytes for DSS).
Each DSS bank has one record; copied and declared lengths are distinct.
The recovery-target mask uses an encodable register OR; original UART/ramoops
writes are excluded from the QEMU variant, and all trampoline record mirrors
use the single bounded publisher.

Verification: preparation packet `{packet.relative_to(PROJECT).as_posix()}`
retains parent pins and exact before/after changes. Fresh connected inventory
`{inventory_rel}` is now selected; all required Android checks pass. Assembly,
runtime bounds, actual watchdog expiry and controller execution are pending.
This preparation makes no device change. Existing Android inputs are preserved.
Rollback: select the original prototype/xnu-loader and preserved Phase 3 tree;
restore this packet's before documents. Preserve source and failed-test evidence.
"""
    current = (PROJECT / "docs/STATE.md").read_text(encoding="utf-8") + f"\n\n## Phase 4 recovery preparation ({packet.name})\n\nFresh inventory `{inventory_rel}` passed and is selected. Isolated loader bounds, non-overlapping capture and watchdog code are prepared; build/execution remain pending. Phase 4 is incomplete.\n"
    replacements.update({"state.json": json.dumps(state, indent=2) + "\n", "docs/STATE.md": current, "docs/IMPLEMENTATION-LOG.md": log})
    documents(packet, replacements)
    after_pins = {p.name: pin(p) for p in original.iterdir() if p.is_file()}
    require(before_pins == after_pins, "Original loader changed")
    for folder in ("prototype/phase4-loader",):
        shutil.copytree(PROJECT / folder, packet / "sources" / folder)
    write_json(packet / "result.json", {"prepared": True, "original_loader_unchanged": True,
        "original_pins": before_pins, "fresh_inventory": inventory_rel,
        "device_operations": False, "phase_4_gate_passed": False})
    index_packet(packet)
    print(packet.relative_to(PROJECT).as_posix(), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
