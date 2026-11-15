#!/usr/bin/env python3
"""Retain the precise BSD declaration and SoC-base corrections before rebuilding."""
from __future__ import annotations
import difflib
import json
import os
from pathlib import Path
import shutil
import subprocess
from phase4_support import PROJECT, require, pin, new_packet, documents, write_json, index_packet


def main():
    if os.name == "nt":
        source = "/mnt/c" + str(Path(__file__).resolve()).replace("\\", "/")[2:]
        return subprocess.call(["wsl", "-d", "A51-KernelBuilder", "--", "python3", "-B", source])
    workspace = json.loads((PROJECT / "manifests/phase4-workspace.json").read_text())
    manifest_path = PROJECT / "manifests/phase4-platform-adaptation.json"
    adaptation = json.loads(manifest_path.read_text())
    root, parent = Path(workspace["root"]).resolve(), Path(workspace["parent"]).resolve()
    require(root.is_relative_to(Path("/opt/a51-hakios/experimental/phase4-port")), "Wrong root")
    require(adaptation["applied"] and adaptation["root"] == str(root), "No matching adaptation")
    native = root / "xnu-src/xnu-8796.121.2"
    template = PROJECT / "prototype/phase4-platform/hakios.a51.c"
    require(pin(template) == adaptation["source_pins"]["hakios.a51.c"], "Unretained template drift")
    for change in adaptation["changes"]:
        tree = native if change["tree"] == "native" else root
        require(pin(tree / change["path"]) == change["after"], "Unretained adaptation drift")
    header = native / "osfmk/arm/machine_routines.h"
    header_text = header.read_text()
    declaration = "vm_offset_t ml_io_map(\n\tvm_offset_t phys_addr,\n\tvm_size_t size);"
    require(declaration in header_text and
            "#if     defined(PEXPERT_KERNEL_PRIVATE) || defined(MACH_KERNEL_PRIVATE)" in header_text,
            "Reviewed declaration/visibility changed")
    old = template.read_bytes()
    text = old.decode()
    require(text.count('#include "hakios.a51.h"') == 1 and text.count("!= 0x12300000") == 1,
            "Correction already applied or unknown input")
    text = text.replace('#include "hakios.a51.h"', '#include "hakios.a51.h"\n\n'
        '/* BSD lacks MACH_KERNEL_PRIVATE/PEXPERT_KERNEL_PRIVATE. Match the\n'
        ' * osfmk/arm/machine_routines.h declaration, as existing BSD drivers do. */\n'
        'extern vm_offset_t ml_io_map(vm_offset_t phys_addr, vm_size_t size);')
    text = text.replace("!= 0x12300000", "!= 0x10000000")
    new = text.encode()
    packet = new_packet("probe-build-correction", __file__)
    shutil.copy2(header, packet / "reviewed-machine_routines.h")
    replacements = {"prototype/phase4-platform/hakios.a51.c": text}
    changes, patch = [], []
    for tree, rel in (("common", "drivers/core/hakios.a51.c"), ("native", "bsd/dev/hakios.a51.c")):
        path = (native if tree == "native" else root) / rel
        require(path.read_bytes() == old, "Template and adapted copy differ")
        for label, raw in (("before", old), ("after", new)):
            dest = packet / label / tree / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(raw)
        path.write_bytes(new)
        changes.append({"tree": tree, "path": rel, "before": pin(packet / "before" / tree / rel), "after": pin(path)})
        patch.append("".join(difflib.unified_diff(old.decode().splitlines(True), text.splitlines(True),
            fromfile="a/" + tree + "/" + rel, tofile="b/" + tree + "/" + rel)))
        item = next(c for c in adaptation["changes"] if c["tree"] == tree and c["path"] == rel)
        item["after"] = pin(path)
    (packet / "adaptations.patch").write_text("".join(patch))
    adaptation["source_pins"]["hakios.a51.c"] = pin(native / "bsd/dev/hakios.a51.c")
    adaptation.setdefault("revision_packets", []).append(packet.relative_to(PROJECT).as_posix())
    replacements["manifests/phase4-platform-adaptation.json"] = json.dumps(adaptation, indent=2) + "\n"
    parent_ok = all(pin(parent / rel) == expected for rel, expected in workspace["preserved"].items())
    require(parent_ok, "Phase 3 parent drift")
    result = {"applied": True, "root": str(root), "changes": changes, "parent_unchanged": parent_ok,
        "header_pin": pin(header), "device_operations": False, "phase_4_gate_passed": False}
    write_json(packet / "result.json", result)
    state = json.loads((PROJECT / "state.json").read_text())
    state["phase_4_diagnostics"] = {"status": "corrected_build_execution_pending",
        "result": (packet / "result.json").relative_to(PROJECT).as_posix(), "error": None}
    state["next_action"] = "rebuild_corrected_phase4_platform_then_qemu"
    replacements["state.json"] = json.dumps(state, indent=2) + "\n"
    note = f"\n\n## Latest Phase 4 build correction ({packet.name})\n\nThe failed P4-007 build is retained. The BSD driver now declares the exact private mapping interface and guards the selected Apple tree's 0x10000000 SoC base; QEMU's 0x08000000 must remain rejected. Evidence: `{packet.relative_to(PROJECT).as_posix()}/result.json`. Rebuild and execution are pending; Phase 4 remains incomplete.\n"
    replacements["docs/STATE.md"] = (PROJECT / "docs/STATE.md").read_text() + note
    log = f"\n\n## P4-009 — Correct BSD mapping declaration and A51 physical-base guard\n\nPurpose/files: scripts/phase4-fix-probe-build.py, prototype/phase4-platform/hakios.a51.c, isolated common drivers/core/hakios.a51.c and native bsd/dev/hakios.a51.c, adaptation manifest, state and this log. ml_io_map is declared only for PEXPERT_KERNEL_PRIVATE/MACH_KERNEL_PRIVATE in the reviewed pinned arm header; BSD is built without those flags. The explicit declaration matches that header and existing BSD driver convention. The guard now agrees with the selected Apple tree's 0x10000000 /arm-io base and leaves QEMU 0x08000000 rejected.\n\nVerification: exact prior template/adaptation pins, declaration signature, synchronized revised bytes and preserved Phase 3 pins checked. Original header, before/after source and manifest/document patches are retained in `{packet.relative_to(PROJECT).as_posix()}`. Compilation and QEMU execution still required. No phone operation or new dependency.\n\nLimitations/rollback: declarations and base equality do not establish hardware behavior. Restore this packet's before common/native bytes and before template/manifest, or select the untouched Phase 3 tree. Preserve failed build evidence.\n"
    replacements["docs/IMPLEMENTATION-LOG.md"] = (PROJECT / "docs/IMPLEMENTATION-LOG.md").read_text() + log
    documents(packet, replacements)
    index_packet(packet)
    print(json.dumps({"packet": packet.relative_to(PROJECT).as_posix(), **result}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
