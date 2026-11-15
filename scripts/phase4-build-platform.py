#!/usr/bin/env python3
"""Build and retain only the isolated Phase 4 kernel and static Darwin probe."""
from __future__ import annotations
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
    workspace = json.loads((PROJECT / "manifests/phase4-workspace.json").read_text())
    adaptation = json.loads((PROJECT / "manifests/phase4-platform-adaptation.json").read_text())
    root = Path(workspace["root"]).resolve()
    require(adaptation["applied"] and adaptation["root"] == str(root), "No matching adaptation")
    require(root.is_relative_to(Path("/opt/a51-hakios/experimental/phase4-port")), "Wrong root")
    for change in adaptation["changes"]:
        tree = root / "xnu-src/xnu-8796.121.2" if change["tree"] == "native" else root
        require(pin(tree / change["path"]) == change["after"], "Adapted source drift: " + change["path"])
    packet = new_packet("platform-build", __file__)
    result = {"root": str(root), "packet": packet.relative_to(PROJECT).as_posix(), "build_verified": False,
        "adaptation_packet": adaptation["packet"], "device_operations": False, "phase_4_gate_passed": False}
    records = []
    for rel in ("hakios-kernel", "userland/hello", ".config", "xnu-build.log"):
        path = root / rel
        if path.is_file():
            dest = packet / "before" / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
    env = dict(os.environ, THEOS="/opt/a51-hakios/theos",
               MAKEFLAGS="MAKEJOBS=--jobs=2 SHELL=/bin/bash",
               PATH="/usr/lib/llvm-18/bin:" + os.environ["PATH"])
    try:
        print("Building isolated Phase 4 kernel; complete stdout/stderr will be retained in " + str(packet), flush=True)
        command(packet, records, "kernel", ["bash", "tools/make-kernel.sh", "-j2", "MAKEJOBS=--jobs=2", "SHELL=/bin/bash"],
                timeout=1800, cwd=root, env=env)
        command(packet, records, "hello", ["make", "hello", "SHELL=/bin/bash"], timeout=120, cwd=root, env=env)
        identification = command(packet, records, "artifact-identification", ["file", "hakios-kernel", "userland/hello"], cwd=root)
        print(identification.stdout.decode(), flush=True)
        symbols = command(packet, records, "driver-symbols", ["llvm-nm", "hakios-kernel"], cwd=root, env=env).stdout
        require(b"_sysctl_a51_snapshot" in symbols and b"_hakios_gicv2_qemu_test" in symbols, "New driver/test not linked")
        result["artifacts"] = {}
        for rel in ("hakios-kernel", "userland/hello", ".config", "xnu-build.log"):
            dest = packet / "artifacts" / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / rel, dest)
            result["artifacts"][rel] = pin(dest)
        result["parent_unchanged"] = all(pin(Path(workspace["parent"]) / rel) == expected
            for rel, expected in workspace["preserved"].items())
        require(result["parent_unchanged"], "Phase 3 parent changed")
        result["build_verified"] = True
    except Exception as exc:
        result["error"] = str(exc)
        for name in ("kernel.stdout", "kernel.stderr", "hello.stdout", "hello.stderr"):
            path = packet / name
            if path.is_file():
                for line in path.read_text(errors="replace").splitlines():
                    if "error:" in line or "make-kernel:" in line or "fatal error" in line:
                        print(line[:300], flush=True)
    finally:
        write_json(packet / "result.json", result)
        write_json(PROJECT / "manifests/phase4-platform-build.json", result)
        state = json.loads((PROJECT / "state.json").read_text())
        state["phase_4_build"] = {"result": result["packet"] + "/result.json", "verified": result["build_verified"], "error": result.get("error")}
        state["next_action"] = "qemu_phase4_spi_guard_test_then_device_snapshot" if result["build_verified"] else "resolve_phase4_build_failure"
        log = f"\n\n## P4-007 — Build isolated Phase 4 diagnostics\n\nPurpose/files: scripts/phase4-build-platform.py, isolated build outputs, build manifest, state and this log. Verification: build_verified={result['build_verified']}; error={result.get('error')}; exact commands/output/exit/times, previous outputs and new artifacts are retained in `{result['packet']}`. A51 snapshot and SPI test symbols must be linked; the writable foreign UFS driver remains disabled. The initial P4-006 wrapper attempt used a nested relative path and exited 2 before actions; its corrected absolute-path run passed. No phone operation occurred. QEMU and A51 execution remain pending and Phase 4 remains incomplete. Rollback/rebuild: select this packet's before outputs or the untouched Phase 3 tree; reproduce the retained source adaptation and execute this builder through scripts/run.py. Preserve failure output and all baseline/evidence pins.\n"
        documents(packet, {"state.json": json.dumps(state, indent=2) + "\n",
            "docs/IMPLEMENTATION-LOG.md": (PROJECT / "docs/IMPLEMENTATION-LOG.md").read_text() + log})
        index_packet(packet)
    print(json.dumps({k: v for k, v in result.items() if k != "artifacts"}, indent=2), flush=True)
    return 0 if result["build_verified"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
