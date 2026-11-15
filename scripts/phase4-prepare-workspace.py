#!/usr/bin/env python3
"""Preserve a separate Phase 4 copy of the known A53/GICv2 source/build tree."""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

PROJECT = Path(__file__).resolve().parents[1]
PARENT = "/opt/a51-hakios/experimental/phase3-port/20261114T013656044425Z"

def pin(path):
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1048576), b""):
            sha.update(chunk)
    return {"bytes": path.stat().st_size, "sha256": sha.hexdigest()}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native", action="store_true")
    args = parser.parse_args()
    if os.name == "nt":
        source = "/mnt/c" + str(Path(__file__).resolve()).replace("\\", "/")[2:]
        return subprocess.call(["wsl", "-d", "A51-KernelBuilder", "--", "python3", source, "--native"])
    assert args.native
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    original = Path(PARENT)
    target = Path("/opt/a51-hakios/experimental/phase4-port") / stamp
    assert original.is_dir() and not target.exists()
    packet = PROJECT / "evidence/phase-4/source-preservation" / stamp
    packet.mkdir(parents=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    commands = []
    def execute(label, argv):
        start = dt.datetime.now(dt.timezone.utc).isoformat()
        proc = subprocess.run(argv, capture_output=True, timeout=240)
        (packet / (label + ".stdout.bin")).write_bytes(proc.stdout)
        (packet / (label + ".stderr.bin")).write_bytes(proc.stderr)
        commands.append({"name": label, "argv": argv, "started_utc": start,
                         "finished_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "exit_code": proc.returncode})
        assert proc.returncode == 0, label
        return proc.stdout
    for rel, label in (("", "common"), ("xnu-src/xnu-8796.121.2", "native")):
        source = original / rel
        for suffix, argv in (("head", ["rev-parse", "HEAD"]), ("origin", ["remote", "get-url", "origin"]),
                             ("status", ["status", "--short"]), ("adaptations", ["diff", "--binary", "HEAD"])):
            execute(label + "-" + suffix, ["git", "-C", str(source), *argv])
    # The preceding rg audit and explicit ancestor check establish no local AGENTS.
    for ancestor in [original, *original.parents, original / "xnu-src", original / "xnu-src/xnu-8796.121.2"]:
        assert not (ancestor / "AGENTS.md").exists(), "Read new local instructions first: " + str(ancestor)
    preserved = {}
    for rel in (".config", "hakios-kernel", "userland/hello", "xnu-env.sh", "drivers/map", "drivers/core/conf",
                "drivers/core/hakios.platform.c", "tools/make-kernel.sh"):
        preserved[rel] = pin(original / rel)
    execute("copy", ["cp", "--reflink=auto", "-a", str(original), str(target)])
    assert all(pin(target / rel) == expected and pin(original / rel) == expected for rel, expected in preserved.items())
    links = []
    for parent, dirs, files in os.walk(target, followlinks=False):
        for name in [*dirs, *files]:
            path = Path(parent) / name
            if path.is_symlink():
                links.append({"path": path.relative_to(target).as_posix(), "target": os.readlink(path)})
    result = {"schema_version": 1, "scope": "isolated_phase4_source_and_dependency_copy", "root": str(target),
              "parent": str(original), "packet": packet.relative_to(PROJECT).as_posix(), "preserved": preserved,
              "dependency_provenance": "Inherited pinned Phase 1 toolchain and Phase 3 source preservation manifest; no downloads.",
              "symlinks": links, "commands": commands, "parent_unchanged": True, "device_operations": False,
              "phase_4_gate_passed": False}
    (packet / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    shutil.copy2(Path(__file__), packet / "source.py")
    (PROJECT / "manifests/phase4-workspace.json").write_text(json.dumps(result, indent=2) + "\n")
    state_path = PROJECT / "state.json"
    state = json.loads(state_path.read_text())
    shutil.copy2(state_path, packet / "state-before.json")
    state["phase_4_workspace"] = {"root": str(target), "preservation_result": (packet / "result.json").relative_to(PROJECT).as_posix()}
    state_path.write_text(json.dumps(state, indent=2) + "\n")
    with (PROJECT / "docs/IMPLEMENTATION-LOG.md").open("a", encoding="utf-8") as stream:
        stream.write(f"\n\n## P4-004 — Preserve isolated XNU Phase 4 workspace\n\n"
                     f"Purpose/files: scripts/phase4-prepare-workspace.py, manifests/phase4-workspace.json, state.json and this log. "
                     f"Copied `{original}` to `{target}` before hardware driver changes. Common/native Git HEADs, origins, binary adaptation diffs, status, symlinks, build/config/driver pins and timed copy command are retained in `{result['packet']}`. "
                     "Verification: selected parent/copy bytes match and parent remains unchanged; no local upstream AGENTS files found. Toolchain/source provenance is inherited, no new dependency was downloaded. "
                     "Limitations: preserved build is still Phase 3; a new driver build/execution is required. Rollback: ignore the new isolated directory and select the untouched Phase 3 tree; restore state-before.json if reverting bookkeeping. No phone operation.\n")
    print(json.dumps({"root": str(target), "packet": str(packet), "parent_unchanged": True, "symlinks": len(links)}), flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
