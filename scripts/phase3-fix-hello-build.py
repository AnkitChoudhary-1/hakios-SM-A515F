#!/usr/bin/env python3
"""Retain the static PID 1 link correction and record the QEMU test setup."""
import datetime as dt
import difflib
import hashlib
import json
from pathlib import Path
import shutil

PROJECT = Path(__file__).resolve().parents[1]


def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def main():
    workspace = json.loads((PROJECT / "manifests/phase3-workspace.json").read_text())
    root = Path(workspace["root"]).resolve()
    assert root.is_relative_to(Path("/opt/a51-hakios/experimental/phase3-port"))
    manifest_path = PROJECT / "manifests/phase3-platform-adaptation.json"
    manifest = json.loads(manifest_path.read_text())
    native = root / "xnu-src/xnu-8796.121.2"
    for item in manifest["changes"]:
        tree = native if item["tree"] == "native" else root
        assert pin((tree / item["path"]).read_bytes()) == item["after"], item["path"]
    assert not list(native.rglob("AGENTS.md"))
    assert not list((root / "userland").rglob("AGENTS.md"))
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    packet = PROJECT / "evidence/phase-3/platform-corrections" / stamp
    packet.mkdir(parents=True, exist_ok=False)
    source = PROJECT / "prototype/a51-platform/hello.c"
    old = source.read_bytes()
    assert old == (root / "userland/src/hello.c").read_bytes()
    marker = "typedef unsigned long u64;\n"
    replacement = marker + """

/* Clang emits bzero for aggregate initialization in this static binary. */
void
bzero(void *out, unsigned long size)
{
\tvolatile unsigned char *p = out;
\twhile (size--) { *p++ = 0; }
}
"""
    assert marker in old.decode() and "bzero(" not in old.decode()
    new = old.decode().replace(marker, replacement).encode()
    changes = []
    for tree, rel, target in (
        ("project", "prototype/a51-platform/hello.c", source),
        ("common", "userland/src/hello.c", root / "userland/src/hello.c"),
    ):
        for label, raw in (("before", old), ("after", new)):
            path = packet / label / tree / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        target.write_bytes(new)
        changes.append({"tree": tree, "path": rel, "before": pin(old), "after": pin(new)})
    (packet / "adaptations.patch").write_text("".join(difflib.unified_diff(
        old.decode().splitlines(True), new.decode().splitlines(True),
        fromfile="a/userland/src/hello.c", tofile="b/userland/src/hello.c")))
    shutil.copy2(manifest_path, packet / "before-manifest.json")
    next(item for item in manifest["changes"] if item["tree"] == "common" and item["path"] == "userland/src/hello.c")["after"] = pin(new)
    manifest.setdefault("correction_packets", []).append(str(packet.relative_to(PROJECT)))
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    for rel in ("scripts/phase3-qemu-platform.py", "prototype/a51-platform/qemu_entry.S"):
        path = packet / "qemu-test" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PROJECT / rel, path)
    prior = PROJECT / "runs/20261114T022504693210Z-phase3-read-return-and-build-flags/project-scripts/phase3-qemu-platform.py"
    shutil.copy2(prior, packet / "before-qemu-checker.py")
    shutil.copy2(Path(__file__), packet / "source.py")
    log = PROJECT / "docs/IMPLEMENTATION-LOG.md"
    shutil.copy2(log, packet / "before-IMPLEMENTATION-LOG.md")
    with log.open("a", encoding="utf-8") as out:
        out.write(f"""

### P3-009 correction — Link static PID 1 and finish the full-boot QEMU checker

Date: 14 November 2026, Asia/Calcutta. Status: implemented; build and execution pending.

The corrected GICv2 kernel command in `20261114T021733374976Z-phase3-rebuild-bsd-gicv2` passed exit 0; its subsequent hello link failed exit 2 because Clang emitted an unresolved bzero call for aggregate initialization. Added a freestanding volatile-byte bzero in prototype/a51-platform/hello.c and the selected isolated userland/src/hello.c. The loop cannot optimize into a recursive library call. Original pins were verified, source before/after bytes and a patch retained in `{packet.relative_to(PROJECT).as_posix()}`; the adaptation manifest selects the corrected bytes. Files: those two sources, scripts/phase3-fix-hello-build.py and manifests/phase3-platform-adaptation.json.

Completed the draft scripts/phase3-qemu-platform.py and prototype/a51-platform/qemu_entry.S setup: direct EL1 Cortex-A53/GICv2 QEMU entry, host-bounded execution, QMP physical return/log capture, a fresh 128-bit nonce, exact PID 1 output, three measured one-second select sleeps, increasing IRQ counts, real MIDR correspondence and expected PID 1 zero-exit panic/return. The checker now matches the implemented index/select_rc/read_rc/pass and outcome/timer_verified fields. Prior checker source is retained alongside the final setup. This is QEMU evidence only; none of the A51 gates can be set from it.

Verification pending: repeat the isolated build and execute the full kernel/user program in QEMU. Retain every failed run. No phone operation occurred. Rollback: restore the indexed two before files and before-manifest.json; restore before-qemu-checker.py or remove the host test setup. Preserve original checkouts, failed build packets and Android baseline images.
""")
    result = {"schema_version": 1, "packet": str(packet.relative_to(PROJECT)), "changes": changes,
              "source_verified": True, "build_verified": False, "device_operations": False,
              "phase_3_device_gate_passed": False}
    (packet / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
