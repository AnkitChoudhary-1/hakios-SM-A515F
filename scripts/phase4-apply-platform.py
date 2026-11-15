#!/usr/bin/env python3
"""Retain and apply guarded diagnostics/SPI support only to the Phase 4 copy."""
from __future__ import annotations
import difflib
import json
import os
from pathlib import Path
import shutil
import subprocess
from phase4_support import PROJECT, require, pin, new_packet, command, documents, write_json, index_packet

def main():
    if os.name == "nt":
        source = "/mnt/c" + str(Path(__file__).resolve()).replace("\\", "/")[2:]
        return subprocess.call(["wsl", "-d", "A51-KernelBuilder", "--", "python3", "-B", source])
    manifest = json.loads((PROJECT / "manifests/phase4-workspace.json").read_text())
    root, parent = Path(manifest["root"]).resolve(), Path(manifest["parent"]).resolve()
    require(root.is_relative_to(Path("/opt/a51-hakios/experimental/phase4-port")), "Wrong Phase 4 root")
    require(root != parent and (root / ".git").is_dir(), "Workspace must be independent")
    require(not (PROJECT / "manifests/phase4-platform-adaptation.json").exists(), "Already applied; use a retained update")
    native = root / "xnu-src/xnu-8796.121.2"
    packet = new_packet("platform-adaptation", __file__)
    records = []
    result = {"root": str(root), "packet": packet.relative_to(PROJECT).as_posix(), "applied": False,
              "build_verified": False, "device_operations": False, "phase_4_gate_passed": False}
    planned, changes = [], []
    def edit(tree, rel, value):
        path = tree / rel
        old = path.read_bytes() if path.exists() else b""
        new = value(old.decode()).encode() if callable(value) else value
        require(old != new, "No change: " + rel)
        planned.append(("native" if tree == native else "common", rel, path, old, new))
    try:
        for label, tree in (("common", root), ("native", native)):
            expected = (PROJECT / manifest["packet"] / (label + "-head.stdout.bin")).read_text().strip()
            actual = command(packet, records, label + "-head", ["git", "-C", str(tree), "rev-parse", "HEAD"]).stdout.decode().strip()
            require(actual == expected, "Changed source commit: " + label)
        instructions = command(packet, records, "local-instructions",
            ["rg", "--files", "--hidden", "-g", "AGENTS.md", "-g", "!**/.git/**", "-g", "!**/BUILD/**", "-g", "!xnu-deps/**", str(root)],
            check=False)
        require(instructions.returncode == 1 and not instructions.stdout and not instructions.stderr,
                "Read local upstream instructions before editing")
        for tree in (root, native):
            for ancestor in (tree, *tree.parents):
                require(not (ancestor / "AGENTS.md").exists(), "Unread ancestor instructions: " + str(ancestor))
        for rel, expected in manifest["preserved"].items():
            require(pin(root / rel) == expected and pin(parent / rel) == expected, "Preserved input drift: " + rel)
        for rel in ("osfmk/arm64/gic_v2_irq.c", "bsd/dev/hakios.platform.c"):
            require(pin(native / rel) == pin(parent / "xnu-src/xnu-8796.121.2" / rel), "Native copy drift: " + rel)
        source_pins = {}
        for name in ("gic_v2_irq.c", "hakios.a51.c", "hakios.a51.h", "hello.c"):
            source = PROJECT / "prototype/phase4-platform" / name
            dest = packet / "sources" / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
            source_pins[name] = pin(dest)
        result["source_pins"] = source_pins
        edit(native, "osfmk/arm64/gic_v2_irq.c", (packet / "sources/gic_v2_irq.c").read_bytes())
        for name in ("hakios.a51.c", "hakios.a51.h"):
            edit(root, "drivers/core/" + name, (packet / "sources" / name).read_bytes())
            edit(native, "bsd/dev/" + name, (packet / "sources" / name).read_bytes())
        edit(root, "userland/src/hello.c", (packet / "sources/hello.c").read_bytes())
        edit(root, "userland/src/hakios.a51.h", (packet / "sources/hakios.a51.h").read_bytes())
        edit(root, "drivers/core/conf", lambda s: s +
            "\ndriver A51\n\tfile    bsd/dev/hakios.a51.c\n\thelp    Explicitly guarded A51 MMIO diagnostics; no peripheral initialization\n")
        edit(root, "drivers/map", lambda s: s + "\ncore    bsd/dev/hakios.a51.c\ncore    bsd/dev/hakios.a51.h\n")
        edit(root, "devices/a51/configs/a51_defconfig", lambda s: s +
            "\n# Phase 4 guarded diagnostics; inactive unless explicitly selected in bootargs.\nCONFIG_HAKIOS_A51=y\n")
        # Every transform is computed before any upstream mutation.
        patch = []
        for tree, rel, path, old, new in planned:
            for label, raw in (("before", old), ("after", new)):
                dest = packet / label / tree / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(raw)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(new)
            changes.append({"tree": tree, "path": rel, "before_exists": bool(old),
                            "before": pin(packet / "before" / tree / rel), "after": pin(path)})
            patch.append("".join(difflib.unified_diff(old.decode().splitlines(True), new.decode().splitlines(True),
                fromfile="a/" + tree + "/" + rel, tofile="b/" + tree + "/" + rel)))
        (packet / "adaptations.patch").write_text("".join(patch))
        shutil.copy2(root / ".config", packet / "config-before")
        command(packet, records, "generate-config", ["python3", "tools/hakios-config.py", "defconfig", "devices/a51/configs/a51_defconfig"], cwd=root)
        require("CONFIG_HAKIOS_A51=y" in (root / ".config").read_text(), "A51 driver is not enabled")
        require("# CONFIG_HAKIOS_UFS is not set" in (root / ".config").read_text(), "Writable foreign UFS driver must remain disabled")
        command(packet, records, "generate-kernel-config", ["python3", "tools/hakios-config.py", "kernel", "--tree", str(native)], cwd=root)
        shutil.copy2(root / ".config", packet / "config-after")
        changes.append({"tree": "common", "path": ".config", "before_exists": True,
                        "before": pin(packet / "config-before"), "after": pin(root / ".config")})
        result["changes"], result["applied"] = changes, True
        result["parent_unchanged"] = all(pin(parent / rel) == expected for rel, expected in manifest["preserved"].items())
        require(result["parent_unchanged"], "Phase 3 parent changed")
    except Exception as exc:
        result["error"] = str(exc)
        result["changes"] = changes
    finally:
        write_json(packet / "result.json", result)
        write_json(PROJECT / "manifests/phase4-platform-adaptation.json", result)
        state = json.loads((PROJECT / "state.json").read_text())
        state["phase_4_diagnostics"] = {"status": "applied_not_built" if result["applied"] else "adaptation_failed",
            "result": (packet / "result.json").relative_to(PROJECT).as_posix(), "error": result.get("error")}
        state["next_action"] = "build_and_execute_qemu_phase4_diagnostics_then_bounded_a51_cycle"
        note = f"\n\n## Latest Phase 4 platform adaptation ({packet.name})\n\n"
        note += f"Guarded controller snapshot, static Darwin reporting and peripheral GICv2 support: applied={result['applied']}; build and execution pending. Evidence: `{result['packet']}/result.json`. Phase 4 remains incomplete.\n"
        log = f"\n\n## P4-006 — Retain and integrate genuine controller diagnostics and SPI support\n\n"
        log += f"Purpose/files: prototype/phase4-platform/{{gic_v2_irq.c,hakios.a51.c,hakios.a51.h,hello.c}}, scripts/phase4-apply-platform.py, isolated native/common files listed in `{result['packet']}/result.json`, the adaptation manifest, state and this log. The previously unlogged GIC template is now retained. Bounded 64-slot single-core SPI registration uses the banked target mask, handles interrupts, masks/detaches sources and preserves timer PPI 27. Its pending-SPI integration diagnostic is restricted to QEMU by physical-base and bootarg guards. The read-only register allowlists are corrected against the retained cal_9610, SysMMU and UFSHCI sources; FIFO, flush and clear command ports are excluded. DECON window stride/shadow offsets are now correct. Darwin PID 1 checks guards/ABI and emits actual register values.\n\n"
        log += f"Verification: applied={result['applied']}, error={result.get('error')}; exact source commit checks, local-instruction search, before/after bytes, patch, configuration command outputs and parent pins are retained in `{result['packet']}`. Applied does not mean compiled or executed. No phone operation occurred. No new dependency downloaded. Build, QEMU SPI delivery, real controller clock/power state and all display/input/storage hardware gates remain pending.\n\n"
        log += "Rollback/rebuild: restore only the indexed before native/common bytes (remove files whose before_exists is false), restore config-before and regenerate the kernel configuration; or ignore this isolated Phase 4 copy and select untouched Phase 3. Preserve all packets, baseline images and false-completion correction.\n"
        documents(packet, {"state.json": json.dumps(state, indent=2) + "\n",
            "docs/STATE.md": (PROJECT / "docs/STATE.md").read_text() + note,
            "docs/IMPLEMENTATION-LOG.md": (PROJECT / "docs/IMPLEMENTATION-LOG.md").read_text() + log})
        index_packet(packet)
    print(json.dumps(result, indent=2), flush=True)
    return 0 if result["applied"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
