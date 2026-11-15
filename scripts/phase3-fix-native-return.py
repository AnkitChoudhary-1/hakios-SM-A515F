#!/usr/bin/env python3
"""Retain bounded native return/fault capture adaptations in the isolated port."""
from __future__ import annotations
import difflib
import json
from pathlib import Path
import shutil
from phase3_support import PROJECT, command, json_write, packet_new, packet_index, pin, require

EARLY = """Lloader_early_exception:
	// Stackless capture before any argument or scratch register is clobbered.
	msr		TPIDR_EL1, x16
	adrp	x16, EXT(loader_early_fault_frame)@page
	add		x16, x16, EXT(loader_early_fault_frame)@pageoff
	stp		x0, x1, [x16, #8]
	stp		x2, x3, [x16, #24]
	stp		x4, x5, [x16, #40]
	stp		x6, x7, [x16, #56]
	stp		x8, x9, [x16, #72]
	stp		x10, x11, [x16, #88]
	stp		x12, x13, [x16, #104]
	stp		x14, x15, [x16, #120]
	str		x17, [x16, #144]
	mrs		x17, TPIDR_EL1
	str		x17, [x16, #136]
	stp		x18, x19, [x16, #152]
	stp		x20, x21, [x16, #168]
	stp		x22, x23, [x16, #184]
	stp		x24, x25, [x16, #200]
	stp		x26, x27, [x16, #216]
	stp		x28, x29, [x16, #232]
	str		x30, [x16, #248]
	mov		x17, sp
	str		x17, [x16, #256]
	mrs		x17, ESR_EL1
	str		x17, [x16, #264]
	mrs		x17, ELR_EL1
	str		x17, [x16, #272]
	mrs		x17, FAR_EL1
	str		x17, [x16, #280]
	mrs		x17, SCTLR_EL1
	str		x17, [x16, #288]
	mrs		x17, CurrentEL
	str		x17, [x16, #296]
	movz	x17, #0x4e58
	movk	x17, #0x4655, lsl #16
	movk	x17, #0x544c, lsl #32
	movk	x17, #0x2133, lsl #48 // XNUFLT3!
	str		x17, [x16]
	mov		x8, x16
	mov		x9, x16
	add		x10, x16, #320
1:
	dc		cvac, x9
	add		x9, x9, #64
	cmp		x9, x10
	b.lo	1b
	ldr		x6, [x16, #248]
	ldr		x7, [x16, #256]
	ldr		x3, [x16, #264]
	ldr		x4, [x16, #272]
	ldr		x5, [x16, #280]
	adrp	x0, EXT(loader_log)@page
	add		x0, x0, EXT(loader_log)@pageoff
	adrp	x1, EXT(loader_log_len)@page
	add		x1, x1, EXT(loader_log_len)@pageoff
	ldr		w1, [x1]
	// Bound cache operations even when the reported length is corrupt.
	mov		x11, #0x180000
	cmp		x1, x11
	csel	x11, x1, x11, lo
	cbz		x11, 3f
	mov		x9, x0
	add		x10, x0, x11
2:
	dc		cvac, x9
	add		x9, x9, #64
	cmp		x9, x10
	b.lo	2b
3:
	dsb		sy
	mov		x2, #1
	adr		x9, Lloader_stub_slot
	ldr		x9, [x9, #8]
	cbz		x9, .
	br		x9 // loader disables M/C/I after preserving all arguments
"""


def replace_once(text, old, new):
    require(text.count(old) == 1, "Unexpected source shape: " + old[:90])
    return text.replace(old, new, 1)


def main():
    workspace = json.loads((PROJECT / "manifests/phase3-workspace.json").read_text())
    root = Path(workspace["root"])
    native = root / "xnu-src/xnu-8796.121.2"
    require(root.is_relative_to("/opt/a51-hakios/experimental/phase3-port"), "Wrong isolated root")
    for base in (root, root / "xnu-src", native, native / "osfmk", native / "osfmk/arm64",
                 native / "pexpert", native / "pexpert/pexpert", native / "pexpert/pexpert/arm64"):
        require(not (base / "AGENTS.md").exists(), "Read applicable upstream AGENTS.md: " + str(base))
    manifest_path = PROJECT / "manifests/phase3-platform-adaptation.json"
    manifest = json.loads(manifest_path.read_text())
    for item in manifest["changes"]:
        base = native if item["tree"] == "native" else root
        require(pin(base / item["path"]) == item["after"], "Adaptation bytes changed: " + item["path"])
    packet = packet_new("native-return-correction", Path(__file__))
    records = []
    head = command(packet, records, "native-head", ["git", "-C", str(native), "rev-parse", "HEAD"]).stdout.decode().strip()
    require(head == workspace["trees"]["native"]["head"], "Native HEAD changed")
    planned = {}
    board = native / "pexpert/pexpert/arm64/BCM2837.h"
    planned[board] = replace_once(board.read_text(), "#define GENERIC_GIC_V2_IRQ", "#define HAKIOS_A51_PORT                    1 /* bounded read-only A51 bring-up */\n#define GENERIC_GIC_V2_IRQ")
    start = native / "osfmk/arm64/start.s"
    old_start = start.read_text()
    begin = old_start.index("Lloader_early_exception:\n")
    end = old_start.index("\t.align\t3\n\t.globl EXT(loader_stub_slot)", begin)
    planned[start] = old_start[:begin] + EARLY + old_start[end:]
    ret = native / "osfmk/arm64/loader_return.c"
    text = replace_once(ret.read_text(), "char     loader_log[LOADER_LOG_SIZE];",
        "uint64_t loader_early_fault_frame[40] __attribute__((aligned(64)));\nchar     loader_log[LOADER_LOG_SIZE];")
    text = replace_once(text,
        "for (uintptr_t p = (uintptr_t)loader_log & ~63UL; p < (uintptr_t)loader_log + loader_log_len; p += 64)",
        "uint32_t clean_log_len = loader_log_len < LOADER_LOG_SIZE ? loader_log_len : LOADER_LOG_SIZE;\n\tfor (uintptr_t p = (uintptr_t)loader_log & ~63UL; p < (uintptr_t)loader_log + clean_log_len; p += 64)")
    text = replace_once(text, "\t/* ... and a screen recording, and the note of where it is */",
        "\t/* Clean the bounded return translation tables before changing TTBR0. */\n\tfor (uintptr_t p = (uintptr_t)loader_l1; p < (uintptr_t)loader_l1 + sizeof(loader_l1); p += 64) {\n\t\t__asm__ volatile (\"dc cvac, %0\" : : \"r\" (p));\n\t}\n\tfor (uintptr_t p = (uintptr_t)loader_l2; p < (uintptr_t)loader_l2 + sizeof(loader_l2); p += 64) {\n\t\t__asm__ volatile (\"dc cvac, %0\" : : \"r\" (p));\n\t}\n#if !defined(HAKIOS_A51_PORT)\n\t/* ... and a screen recording, and the note of where it is */")
    text = replace_once(text, '\t__asm__ volatile ("dc cvac, %0" : : "r" ((uintptr_t)loader_sound + 16));',
        '\t__asm__ volatile ("dc cvac, %0" : : "r" ((uintptr_t)loader_sound + 16));\n#endif /* no screen/sound capture during bounded A51 bring-up */')
    # The A51's state stays in RAM; orderly/timed return cannot save a volume.
    require(text.count("\t\thakios_var_save_on_return();") == 2, "Unexpected save-on-return calls")
    text = text.replace("\t\thakios_var_save_on_return();",
        "#if !defined(HAKIOS_A51_PORT)\n\t\thakios_var_save_on_return();\n#endif\n\t\t/* A51 bring-up does not write a persistent volume. */")
    text = replace_once(text,
        "mb->msg_size <= 0 || mb->msg_bufx < 0", "mb->msg_size <= 0 || mb->msg_size > 256 * 1024 || mb->msg_bufx < 0")
    planned[ret] = text
    changes, patch = [], []
    shutil.copy2(manifest_path, packet / "before-manifest.json")
    for target, new in planned.items():
        rel = target.relative_to(native).as_posix()
        old = target.read_bytes()
        for label, raw in (("before", old), ("after", new.encode())):
            path = packet / label / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        target.write_bytes(new.encode())
        patch.append("".join(difflib.unified_diff(old.decode().splitlines(True), new.splitlines(True),
                       fromfile="a/" + rel, tofile="b/" + rel)))
        changes.append({"tree": "native", "path": rel, "before": pin(packet / "before" / rel), "after": pin(target)})
        item = next((x for x in manifest["changes"] if x["tree"] == "native" and x["path"] == rel), None)
        if item is None:
            manifest["changes"].append({"tree": "native", "path": rel, "after": pin(target)})
        else:
            item["after"] = pin(target)
    (packet / "adaptations.patch").write_text("".join(patch))
    manifest.setdefault("correction_packets", []).append(packet.relative_to(PROJECT).as_posix())
    json_write(manifest_path, manifest)
    log = PROJECT / "docs/IMPLEMENTATION-LOG.md"
    shutil.copy2(log, packet / "before-IMPLEMENTATION-LOG.md")
    with log.open("a", encoding="utf-8") as out:
        out.write(f"""

### P3-015 — Bound native fault/return operations and retain loader test failures

Date: 14 November 2026, Asia/Calcutta. Status: source adaptations implemented; rebuilt execution pending. Hardware gate UNPASSED, qualifying runs 0/3.

Purpose/files: scripts/phase3-fix-native-return.py and selected isolated native osfmk/arm64/{{start.s,loader_return.c}}, pexpert/pexpert/arm64/BCM2837.h; manifests/phase3-platform-adaptation.json and this log. Original indexed adaptations and native HEAD were checked first, and applicable ancestor AGENTS.md files were absent (a separate scoped search also found none). Exact before/after sources and patch: {packet.relative_to(PROJECT).as_posix()}. Stackless early exceptions now retain original x0-x30/SP/ESR/ELR/FAR/SCTLR/EL in a 320-byte frame, clean its bounded extent and pass its PA in x8. Both early and normal return cache operations cap at the 1536 KiB log capacity while preserving an oversized reported length for loader rejection. Normal return cleans bounded translation tables. HAKIOS_A51_PORT disables recording/sound cache walks and persistent volume saves during return; message-buffer collection caps at 256 KiB.

Loader corrections/test sources: prototype/phase3-loader/entry.S (separate M/C bit tests because #5 is not a legal AArch64 logical immediate), fdt_guard.c (permit legal zero address cells on unrelated buses), fdt_test.c and scripts/phase3-test-loader-fdt.py (real FDT, exact allocation truncations, header/reservation cases and diagnostic rejection line). Retained first strict build failure: runs/20261114T034346227494Z, assembler rejected tst x21,#5. Corrected strict build passed in evidence/phase-3/loader-build/20261114T034537486607Z; this is compilation only. First real-FDT sanitizer test evidence/phase-3/loader-fdt-tests/20261114T034537292256Z compiled successfully but rejected the actual FDT; investigate without weakening reservation guards. No candidate/device write or reboot occurred in these host operations.

Verification pending: rebuild the pinned kernel/hello, repeat real-FDT sanitizer checks and run the actual new loader in QEMU before hardware reset/watchdog/log diagnostics and three qualifying A51 cycles. Frame mapping/physical persistence and standalone watchdog/reset remain unverified. Rollback: restore only this packet's three before sources and before-manifest.json, then rebuild; keep all patches, original build pins and failed tests. Baseline Android and original upstream trees remain preserved. Phase 4 continuation is already authorized after Phase 3 passes.
""")
    result = {"packet": packet.relative_to(PROJECT).as_posix(), "implemented": True, "changes": changes,
              "build_verified": False, "device_operations": False, "phase_3_device_gate_passed": False}
    json_write(packet / "result.json", result)
    packet_index(packet)
    print(json.dumps({"packet": result["packet"], "implemented": True}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
