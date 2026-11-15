#!/usr/bin/env python3
"""Retain the current, partly unrecorded revision before a guarded replacement.

Use --capture first. --apply requires the captured WSL files to remain exact;
new Windows templates are copied only after every planned file is retained.
The old manifest and every original packet remain historical evidence.
"""
from __future__ import annotations
import argparse
import difflib
import json
import os
from pathlib import Path
import shutil
import subprocess
from phase4_support import PROJECT, command, documents, index_packet, new_packet, pin, require, write_json

SELECTION = PROJECT / "manifests/phase4-readonly-revision.json"
TEMPLATES = ("hakios.a51.c", "hakios.a51.h", "hello.c", "gic_v2_irq.c")
REFERENCES = (
    "drivers/scsi/ufs/ufshci.h", "drivers/scsi/ufs/ufshcd.h", "drivers/scsi/ufs/ufshcd.c",
    "drivers/scsi/ufs/ufs.h", "drivers/scsi/ufs/ufs-exynos.c", "drivers/scsi/ufs/ufs-exynos.h",
    "drivers/scsi/ufs/ufs-exynos-fmp.c", "drivers/i2c/busses/i2c-s3c2410.c",
    "drivers/input/touchscreen/melfas/mss100/melfas_mss100.c",
    "drivers/input/touchscreen/melfas/mss100/melfas_mss100_mod.c",
    "drivers/input/touchscreen/melfas/mss100/melfas_mss100_reg.h",
    "drivers/video/fbdev/exynos/dpu20/cal_9610/regs-decon.h",
    "drivers/video/fbdev/exynos/dpu20/cal_9610/regs-dsim.h",
    "drivers/video/fbdev/exynos/dpu20/panels/s6e3fa9_a51_lcd_ctrl.c",
    "drivers/video/fbdev/exynos/dpu20/panels/s6e3fa9_a51_param.h",
    "arch/arm64/boot/dts/samsung/exynos9611-a51_common.dtsi",
)

def destinations(root):
    native = root / "xnu-src/xnu-8796.121.2"
    rows = [("common", "userland/src/hello.c", "hello.c"),
            ("common", "userland/src/hakios.a51.h", "hakios.a51.h"),
            ("native", "osfmk/arm64/gic_v2_irq.c", "gic_v2_irq.c")]
    for name in ("hakios.a51.c", "hakios.a51.h", "a51_ufs_readonly.h", "a51_input.h"):
        rows += [("common", "drivers/core/" + name, name), ("native", "bsd/dev/" + name, name)]
    rows += [("common", "userland/src/a51_input.h", "a51_input.h")]
    return [(tree, rel, (native if tree == "native" else root) / rel, name) for tree, rel, name in rows]

def record(packet, heading, text, extra=None):
    state = json.loads((PROJECT / "state.json").read_text())
    state["phase_4_readonly_revision"] = {"result": packet.relative_to(PROJECT).as_posix() + "/result.json", **(extra or {})}
    state["phase_4"] = "in_progress"
    state["next_action"] = "verify_corrected_readonly_protocol_then_build_and_qemu_before_device_execution"
    documents(packet, {"state.json": json.dumps(state, indent=2) + "\n",
        "docs/IMPLEMENTATION-LOG.md": (PROJECT / "docs/IMPLEMENTATION-LOG.md").read_text() +
        f"\n\n## {heading}\n\n{text}\n\n"})

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    require(args.capture != args.apply, "Choose --capture or --apply")
    if os.name == "nt":
        script = "/mnt/c" + str(Path(__file__).resolve()).replace("\\", "/")[2:]
        return subprocess.call(["wsl", "-d", "A51-KernelBuilder", "--", "python3", "-B", script,
                                "--capture" if args.capture else "--apply"])
    workspace = json.loads((PROJECT / "manifests/phase4-workspace.json").read_text())
    root = Path(workspace["root"]).resolve()
    native = root / "xnu-src/xnu-8796.121.2"
    require(root.is_relative_to(Path("/opt/a51-hakios/experimental/phase4-port")), "Wrong source root")
    if args.capture:
        require(not SELECTION.exists(), "A retained revision already exists")
        packet = new_packet("readonly-source-capture", __file__)
        records = []
        result = {"packet": packet.relative_to(PROJECT).as_posix(), "root": str(root),
                  "captured": False, "device_operations": False, "phase_4_gate_passed": False}
        try:
            scan = command(packet, records, "local-instructions", ["rg", "--files", "--hidden", "-g", "AGENTS.md",
                "-g", "!**/.git/**", "-g", "!**/BUILD/**", "-g", "!xnu-deps/**", str(root)], check=False)
            require(scan.returncode == 1 and not scan.stdout and not scan.stderr, "Read upstream AGENTS.md before edits")
            for tree in (root, native):
                for ancestor in (tree, *tree.parents):
                    require(not (ancestor / "AGENTS.md").exists(), "Unread ancestor AGENTS.md")
            result["heads"] = {}
            for label, tree in (("common", root), ("native", native)):
                result["heads"][label] = command(packet, records, label + "-head", ["git", "-C", str(tree), "rev-parse", "HEAD"]).stdout.decode().strip()
                command(packet, records, label + "-diff", ["git", "-C", str(tree), "diff", "--binary", "HEAD"])
            result["destinations"] = []
            for tree, rel, path, name in destinations(root):
                saved = packet / "before" / tree / rel
                saved.parent.mkdir(parents=True, exist_ok=True)
                if path.exists():
                    shutil.copy2(path, saved)
                else:
                    saved.write_bytes(b"")
                result["destinations"].append({"tree": tree, "path": rel, "template": name,
                    "exists": path.exists(), "pin": pin(saved)})
            result["templates"] = {}
            for name in TEMPLATES:
                saved = packet / "before/templates" / name
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(PROJECT / "prototype/phase4-platform" / name, saved)
                result["templates"][name] = pin(saved)
            for rel in ("manifests/phase4-platform-adaptation.json", "manifests/phase4-platform-build.json",
                        "manifests/phase4-platform-qemu.json", "scripts/phase4-device-gate.py",
                        "scripts/phase4-device-cycle.py", "scripts/phase4-build-platform.py",
                        "scripts/phase4-qemu-platform.py", "scripts/phase4-build-device-path.py"):
                saved = packet / "before/project" / rel
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(PROJECT / rel, saved)
            old = json.loads((PROJECT / "manifests/phase4-platform-adaptation.json").read_text())
            result["unrecorded_source_drift"] = []
            for row in old["changes"]:
                path = (native if row["tree"] == "native" else root) / row["path"]
                if not path.exists() or pin(path) != row["after"]:
                    result["unrecorded_source_drift"].append({"tree": row["tree"], "path": row["path"],
                        "old_manifest_pin": row["after"], "observed": pin(path) if path.exists() else None})
            result["references"] = {}
            for rel in REFERENCES:
                source = Path("/opt/a51-everline/src") / rel
                require(source.is_file(), "Reference missing: " + rel)
                saved = packet / "references" / rel
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, saved)
                result["references"][rel] = pin(saved)
            result["parent_unchanged"] = all(pin(Path(workspace["parent"]) / rel) == expected
                for rel, expected in workspace["preserved"].items())
            require(result["parent_unchanged"], "Phase 3 parent changed")
            result["captured"] = True
        except Exception as exc:
            result["error"] = str(exc)
        write_json(packet / "result.json", result)
        if result["captured"]:
            write_json(SELECTION, result)
        record(packet, "P4-028 — Capture current driver bytes and missing revision history",
            f"Purpose/files: scripts/phase4-revise-platform.py and its indexed packet `{result['packet']}`; "
            "retain current common/native/template sources, Git heads/diffs, selected manifests/harnesses and 16 matching Android references before changes. "
            f"Verification: captured={result['captured']}; unrecorded adapted-file changes={len(result.get('unrecorded_source_drift', []))}; error={result.get('error')}. "
            "Previously rewritten platform-build artifact pins are retained as a provenance gap, not attributed to the old adaptation. "
            "No upstream mutation, build, phone query/write/reboot occurred. Limitation: source references are hypotheses until execution. "
            "Rollback: ignore the new selection and continue with retained historical packets; no phone restoration is needed.",
            {"captured": result["captured"], "applied": False})
        index_packet(packet)
        print(json.dumps({k: result[k] for k in ("packet", "captured", "unrecorded_source_drift") if k in result}, indent=2), flush=True)
        return 0 if result["captured"] else 1
    captured = json.loads(SELECTION.read_text())
    require(captured["captured"] and captured["root"] == str(root), "No matching capture")
    packet = new_packet("readonly-platform-revision", __file__)
    records, planned, changes = [], [], []
    result = {"packet": packet.relative_to(PROJECT).as_posix(), "root": str(root),
              "captured_packet": captured["packet"], "applied": False,
              "build_verified": False, "device_operations": False, "phase_4_gate_passed": False}
    try:
        old_manifest = json.loads((PROJECT / "manifests/phase4-platform-adaptation.json").read_text())
        source_packet = PROJECT / captured["packet"]
        require(pin(PROJECT / "manifests/phase4-platform-adaptation.json") ==
                pin(source_packet / "before/project/manifests/phase4-platform-adaptation.json"), "Manifest changed during work")
        for label, tree in (("common", root), ("native", native)):
            actual = command(packet, records, label + "-head", ["git", "-C", str(tree), "rev-parse", "HEAD"]).stdout.decode().strip()
            require(actual == captured["heads"][label], "Git HEAD changed")
        source_pins = {}
        for row, (tree, rel, path, name) in zip(captured["destinations"], destinations(root), strict=True):
            require(row["tree"] == tree and row["path"] == rel and path.exists() == row["exists"], "Target identity changed")
            old = path.read_bytes() if path.exists() else b""
            require(pin(source_packet / "before" / tree / rel) == row["pin"], "Capture modified")
            require(old == (source_packet / "before" / tree / rel).read_bytes(), "Concurrent source edit: " + rel)
            template = PROJECT / "prototype/phase4-platform" / name
            new = template.read_bytes()
            source_pins[name] = pin(template)
            if old != new:
                planned.append((tree, rel, path, old, new, row["exists"]))
        patches = []
        for tree, rel, path, old, new, existed in planned:
            for label, raw in (("before", old), ("after", new)):
                saved = packet / label / tree / rel
                saved.parent.mkdir(parents=True, exist_ok=True)
                saved.write_bytes(raw)
            patches.append("".join(difflib.unified_diff(old.decode().splitlines(True), new.decode().splitlines(True),
                fromfile="a/" + tree + "/" + rel, tofile="b/" + tree + "/" + rel)))
        for name in source_pins:
            saved = packet / "sources" / name
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(PROJECT / "prototype/phase4-platform" / name, saved)
            require(pin(saved) == source_pins[name], "Template changed during retention")
        # Verify every target again immediately before the first mutation.
        for tree, rel, path, old, new, existed in planned:
            require(path.exists() == existed and (path.read_bytes() if existed else b"") == old, "Concurrent edit before apply: " + rel)
        for tree, rel, path, old, new, existed in planned:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(new)
            changes.append({"tree": tree, "path": rel, "before_exists": existed,
                            "before": pin(packet / "before" / tree / rel), "after": pin(path)})
        (packet / "adaptations.patch").write_text("".join(patches))
        adaptation = dict(old_manifest)
        for row in adaptation["changes"]:
            path = (native if row["tree"] == "native" else root) / row["path"]
            require(path.is_file(), "Adapted source missing: " + row["path"])
            row["after"] = pin(path)
        known = {(row["tree"], row["path"]) for row in adaptation["changes"]}
        adaptation["changes"] += [row for row in changes if (row["tree"], row["path"]) not in known]
        adaptation["source_pins"] = source_pins
        adaptation["revision_packets"] = old_manifest.get("revision_packets", []) + [result["packet"]]
        adaptation["captured_unrecorded_revision"] = {"packet": captured["packet"],
            "result_pin": pin(source_packet / "result.json"), "historical_artifacts_not_revalidated": True}
        documents(packet, {"manifests/phase4-platform-adaptation.json": json.dumps(adaptation, indent=2) + "\n"})
        result.update(applied=True, changes=changes, source_pins=source_pins)
        result["parent_unchanged"] = all(pin(Path(workspace["parent"]) / rel) == expected
            for rel, expected in workspace["preserved"].items())
        require(result["parent_unchanged"], "Phase 3 parent changed")
    except Exception as exc:
        result.update(error=str(exc), changes=changes)
    write_json(packet / "result.json", result)
    write_json(SELECTION, {**captured, "applied_result": result})
    # Avoid overwriting the adaptation document patch recorded above.
    record_packet = new_packet("readonly-revision-documentation", __file__)
    write_json(record_packet / "result.json", {"revision_result": result["packet"] + "/result.json", "applied": result["applied"]})
    record(record_packet, "P4-029 — Apply bounded read-only driver and measured diagnostics",
        f"Purpose/files: retained before/after native/common files and template pins in `{result['packet']}`; adaptation manifest retains the prior revisions and explicitly identifies the source-history gap. "
        "The replacement prohibits writes before descriptor/MMIO access; uses kernel-owned contiguous DMA memory; rejects active inherited doorbells, incorrect descriptor configuration, nonzero OCS and invalid UPIU; bounds waits and retains each lifecycle state. "
        "The snapshot no longer writes framebuffer/DSIM. Display/input labels must be observations, and storage hashes are emitted only for validated transfers. "
        f"Verification: applied={result['applied']}; error={result.get('error')}. Build/native/QEMU/hardware execution remain separate pending checks. "
        "Rollback: restore only this packet's indexed before files, remove newly added files whose before_exists=false, and restore the before adaptation manifest. Preserve all failed historical packets and the Phase 3 parent. No phone operation occurred.",
        {"applied": result["applied"], "build_verified": False})
    index_packet(packet)
    index_packet(record_packet)
    print(json.dumps({k: v for k, v in result.items() if k not in ("changes", "source_pins")}, indent=2), flush=True)
    return 0 if result["applied"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
