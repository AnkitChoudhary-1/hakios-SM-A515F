#!/usr/bin/env python3
"""Retain corrections to UP GIC routing, QEMU firmware groups and reporting."""
from __future__ import annotations
import difflib
import json
import os
from pathlib import Path
import shutil
import subprocess
from phase4_support import PROJECT, require, pin, new_packet, documents, write_json, index_packet


def replace_once(text, old, new):
    require(text.count(old) == 1, "Unknown source or correction already applied: " + old[:80])
    return text.replace(old, new)


def main():
    if os.name == "nt":
        source = "/mnt/c" + str(Path(__file__).resolve()).replace("\\", "/")[2:]
        return subprocess.call(["wsl", "-d", "A51-KernelBuilder", "--", "python3", "-B", source])
    workspace = json.loads((PROJECT / "manifests/phase4-workspace.json").read_text())
    adaptation = json.loads((PROJECT / "manifests/phase4-platform-adaptation.json").read_text())
    root, parent = Path(workspace["root"]).resolve(), Path(workspace["parent"]).resolve()
    require(root.is_relative_to(Path("/opt/a51-hakios/experimental/phase4-port")), "Wrong root")
    require(adaptation["applied"] and adaptation["root"] == str(root), "No matching adaptation")
    native = root / "xnu-src/xnu-8796.121.2"
    for item in adaptation["changes"]:
        tree = native if item["tree"] == "native" else root
        require(pin(tree / item["path"]) == item["after"], "Unretained adaptation drift")
    templates = PROJECT / "prototype/phase4-platform"
    revised = {}
    for name in ("gic_v2_irq.c", "hakios.a51.c", "hello.c"):
        require(pin(templates / name) == adaptation["source_pins"][name], "Template drift")
        revised[name] = (templates / name).read_text()
    revised["gic_v2_irq.c"] = replace_once(revised["gic_v2_irq.c"],
        "gic_lines = ((read32(gicd, GICD_TYPER) & 31) + 1) * 32;",
        "uint32_t typer = read32(gicd, GICD_TYPER);\n\tgic_lines = ((typer & 31) + 1) * 32;")
    revised["gic_v2_irq.c"] = replace_once(revised["gic_v2_irq.c"],
        "cpu_target = read32(gicd, GICD_ITARGETSR(0)) & 0xff;",
        "/* Banked SGI/PPI target fields identify this CPU on an MP GIC.\n"
        "\t * A uniprocessor implementation can expose these as RAZ/WI;\n"
        "\t * its sole target is implicit. Never infer an MP bit from MPIDR. */\n"
        "\tcpu_target = 0;\n"
        "\tfor (unsigned i = 0; i < 32; i += 4) {\n"
        "\t\tuint32_t targets = read32(gicd, GICD_ITARGETSR(i));\n"
        "\t\ttargets |= targets >> 16;\n\t\ttargets |= targets >> 8;\n"
        "\t\tcpu_target |= (uint8_t)targets;\n\t}\n"
        "\tif (!cpu_target && !((typer >> 5) & 7)) { cpu_target = 1; }")
    revised["gic_v2_irq.c"] = replace_once(revised["gic_v2_irq.c"],
        "if (gic_v3_spi_attach(id, true, test_irq, (void *)&observed) != KERN_SUCCESS) { return KERN_FAILURE; }",
        "kern_return_t attach = gic_v3_spi_attach(id, true, test_irq, (void *)&observed);\n"
        "\tif (attach != KERN_SUCCESS) {\n"
        "\t\tkprintf(\"HAKIOS_QEMU_SPI_ATTACH rc=%d flags=0x%x target=0x%x\\n\", attach, *flags, cpu_target);\n"
        "\t\treturn KERN_FAILURE;\n\t}")
    revised["hakios.a51.c"] = replace_once(revised["hakios.a51.c"],
        "if (hakios_gicv2_qemu_test(&flags) != KERN_SUCCESS) { return EIO; }\n    return SYSCTL_OUT(req, &flags, sizeof(flags));",
        "kern_return_t test = hakios_gicv2_qemu_test(&flags);\n"
        "    /* Retain partial flags even when the test fails. */\n"
        "    int output = SYSCTL_OUT(req, &flags, sizeof(flags));\n"
        "    return output ? output : (test == KERN_SUCCESS ? 0 : EIO);")
    revised["hello.c"] = replace_once(revised["hello.c"],
        "\t\tif (!nonce_ok || gic_rc || core_rc || midr_rc || gic != 2 || cores != 1 || !midr || wait < 3) {\n\t\t\tfailed = 1; put(fd, \"HAKIOS_TIMER_FAIL platform_or_nonce\\n\");\n\t\t}",
        "\t\tint timer_failed = !nonce_ok || gic_rc || core_rc || midr_rc || gic != 2 || cores != 1 || !midr || wait < 3;\n"
        "\t\tif (timer_failed) { put(fd, \"HAKIOS_TIMER_FAIL platform_or_nonce\\n\"); }")
    revised["hello.c"] = replace_once(revised["hello.c"],
        "if (!ok) { failed = 1; }", "if (!ok) { timer_failed = 1; }")
    revised["hello.c"] = replace_once(revised["hello.c"],
        "timer_verified = !failed;\n\t\tput(fd, failed ? \"HAKIOS_TIMER_FAIL samples=\" : \"HAKIOS_TIMER_PASS samples=\");",
        "timer_verified = !timer_failed;\n\t\tfailed |= timer_failed;\n"
        "\t\tput(fd, timer_failed ? \"HAKIOS_TIMER_FAIL samples=\" : \"HAKIOS_TIMER_PASS samples=\");")
    entry = (PROJECT / "prototype/a51-platform/qemu_entry.S").read_text()
    entry = replace_once(entry,
        "    mov w11, #0xffffffff\n    str w11, [x10, #0x80]\n    mov w11, #2",
        "    /* Assign every implemented interrupt to NS Group 1 in the\n"
        "     * emulated EL3 firmware. EL1 cannot alter secure Group 0 SPIs. */\n"
        "    ldr w12, [x10, #4]\n    and w12, w12, #31\n    add w12, w12, #1\n"
        "    add x13, x10, #0x80\n    mov w11, #0xffffffff\n"
        "9:  str w11, [x13], #4\n    subs w12, w12, #1\n    b.ne 9b\n    mov w11, #2")
    require(not (templates / "qemu_entry.S").exists(), "Entry correction already exists")
    qemu_path = PROJECT / "scripts/phase4-qemu-platform.py"
    qemu = qemu_path.read_text()
    qemu = replace_once(qemu,
        '    end = log.find(footer, begin)\n    text = log[begin:end + len(footer)] if begin >= 0 and end > begin else ""',
        '    ending = re.search(r"HAKIOS_USER_EXIT outcome=[01] timer_verified=[01]", log[begin:]) if begin >= 0 else None\n'
        '    text = log[begin:begin + ending.end()] if ending else ""')
    qemu = replace_once(qemu,
        '"no_test_failure": "HAKIOS_TIMER_FAIL" not in log and "HAKIOS_USER_FAIL" not in log,',
        '"no_test_failure": all(marker not in log for marker in ("HAKIOS_TIMER_FAIL", "HAKIOS_USER_FAIL", "HAKIOS_A51_DIAG_FAIL")),')
    qemu = qemu.replace('prototype/a51-platform/qemu_entry.S', 'prototype/phase4-platform/qemu_entry.S')
    packet = new_packet("spi-correction", __file__)
    shutil.copy2(PROJECT / "prototype/a51-platform/qemu_entry.S", packet / "original-qemu_entry.S")
    changes, patches = [], []
    destinations = {
        "gic_v2_irq.c": [("native", "osfmk/arm64/gic_v2_irq.c")],
        "hakios.a51.c": [("common", "drivers/core/hakios.a51.c"), ("native", "bsd/dev/hakios.a51.c")],
        "hello.c": [("common", "userland/src/hello.c")],
    }
    for name, places in destinations.items():
        old, new = (templates / name).read_bytes(), revised[name].encode()
        for tree, rel in places:
            path = (native if tree == "native" else root) / rel
            require(path.read_bytes() == old, "Copies differ: " + rel)
            for label, data in (("before", old), ("after", new)):
                dest = packet / label / tree / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
            path.write_bytes(new)
            changes.append({"tree": tree, "path": rel, "before": pin(packet / "before" / tree / rel), "after": pin(path)})
            patches.append("".join(difflib.unified_diff(old.decode().splitlines(True), revised[name].splitlines(True),
                fromfile="a/" + tree + "/" + rel, tofile="b/" + tree + "/" + rel)))
            next(c for c in adaptation["changes"] if c["tree"] == tree and c["path"] == rel)["after"] = pin(path)
        adaptation["source_pins"][name] = {"bytes": len(new), "sha256": __import__("hashlib").sha256(new).hexdigest()}
    (packet / "adaptations.patch").write_text("".join(patches))
    adaptation.setdefault("revision_packets", []).append(packet.relative_to(PROJECT).as_posix())
    require(all(pin(parent / rel) == expected for rel, expected in workspace["preserved"].items()), "Parent drift")
    result = {"applied": True, "root": str(root), "changes": changes, "parent_unchanged": True,
        "device_operations": False, "phase_4_gate_passed": False}
    write_json(packet / "result.json", result)
    state = json.loads((PROJECT / "state.json").read_text())
    state["phase_4_diagnostics"] = {"status": "spi_corrections_applied_execution_pending",
        "result": (packet / "result.json").relative_to(PROJECT).as_posix()}
    state["next_action"] = "rebuild_phase4_spi_corrections_then_qemu"
    note = f"\n\n## Latest Phase 4 interrupt correction ({packet.name})\n\nThe original QEMU log reports SPI target 0x0 and three passing timer samples. UP target fields can be RAZ/WI; only a GIC reporting one interface gets an implicit target. QEMU's EL3 entry now assigns implemented SPIs to NS Group 1; it formerly assigned only SGIs/PPIs. Partial failure flags and timer results are retained independently. Evidence: `{packet.relative_to(PROJECT).as_posix()}/result.json`. Rebuild/execution are pending; Phase 4 remains incomplete.\n"
    log = f"\n\n## P4-010 — Correct interrupt target/group configuration and diagnostic reporting\n\nPurpose/files: scripts/phase4-fix-spi.py, prototype/phase4-platform/{{gic_v2_irq.c,hakios.a51.c,hello.c,qemu_entry.S}}, isolated native/common copies, scripts/phase4-qemu-platform.py, adaptation manifest, state and this log. The failed log proves QEMU has a zero target mask. Read all banked target bytes; allow an implicit sole target only when GICD_TYPER reports a UP implementation. The Phase 4-specific EL3 emulator entry assigns all implemented interrupts to NS Group 1; the unchanged Phase 3 entry assigned only register 0, leaving SPI 47 secure. Kernel test failures now copy out partial flags and log attach errors. PID 1 reports timer results separately from peripheral failures, and the validator extracts both successful and failed user frames.\n\nVerification: retained exact before/after bytes, patches, source pins and parent invariance in `{packet.relative_to(PROJECT).as_posix()}`. Source inspection establishes these defects; corrected runtime verification is pending. No phone operation or new dependency. The fallback does not supply guessed target bits for the A51's MP GIC.\n\nRollback/rebuild: restore this packet's before native/common/template/scripts and adaptation manifest; select the untouched Phase 3 tree as needed. Rebuild with phase4-build-platform.py and rerun phase4-qemu-platform.py through scripts/run.py. Preserve the failed original log and all hardware evidence.\n"
    replacements = {"prototype/phase4-platform/" + name: value for name, value in revised.items()}
    replacements.update({"prototype/phase4-platform/qemu_entry.S": entry, "scripts/phase4-qemu-platform.py": qemu,
        "manifests/phase4-platform-adaptation.json": json.dumps(adaptation, indent=2) + "\n",
        "state.json": json.dumps(state, indent=2) + "\n",
        "docs/STATE.md": (PROJECT / "docs/STATE.md").read_text() + note,
        "docs/IMPLEMENTATION-LOG.md": (PROJECT / "docs/IMPLEMENTATION-LOG.md").read_text() + log})
    documents(packet, replacements)
    index_packet(packet)
    print(json.dumps({"packet": packet.relative_to(PROJECT).as_posix(), "applied": True, "parent_unchanged": True}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
