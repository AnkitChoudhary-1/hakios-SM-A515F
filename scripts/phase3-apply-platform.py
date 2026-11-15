#!/usr/bin/env python3
"""Apply a retained single-core GICv2/Cortex-A53 port to the isolated tree."""
import datetime as dt
import difflib
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

PROJECT = Path(__file__).resolve().parents[1]


def pin(path):
    raw = path.read_bytes()
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def main():
    manifest = json.loads((PROJECT / "manifests/phase3-workspace.json").read_text())
    root = Path(manifest["root"]).resolve()
    assert root.is_relative_to(Path("/opt/a51-hakios/experimental/phase3-port"))
    native = root / "xnu-src/xnu-8796.121.2"
    assert subprocess.check_output(["git", "-C", str(native), "rev-parse", "HEAD"], text=True).strip() == manifest["trees"]["native"]["head"]
    assert not (native / "osfmk/arm64/gic_v2_irq.c").exists(), "Already applied; preserve and inspect instead of reapplying"
    assert not list(native.rglob("AGENTS.md")), "Read local upstream instructions before editing"
    assert not list(root.glob("userland/**/AGENTS.md")), "Read local userland instructions before editing"
    assert (PROJECT / "prototype/a51-platform/hello.c").is_file()
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    packet = PROJECT / "evidence/phase-3/platform-adaptation" / stamp
    packet.mkdir(parents=True)
    changes = []

    planned = []

    def edit(tree, relative, transform):
        target = tree / relative
        raw = target.read_bytes() if target.exists() else b""
        old = raw.decode()
        new = transform(old)
        assert old != new, relative
        planned.append((tree, relative, target, raw, new.encode()))

    def apply(tree, relative, target, raw, new):
        for label, value in (("before", raw), ("after", new)):
            copy = packet / label / ("native" if tree == native else "common") / relative
            copy.parent.mkdir(parents=True, exist_ok=True)
            copy.write_bytes(value)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(new)
        diff = "".join(difflib.unified_diff(raw.decode().splitlines(True), new.decode().splitlines(True), fromfile="a/" + relative, tofile="b/" + relative))
        changes.append({"tree": "native" if tree == native else "common", "path": relative, "after": pin(target)})
        with (packet / "adaptations.patch").open("a") as out:
            out.write(diff)

    def replace(text, old, new):
        assert old in text, old
        return text.replace(old, new)

    def board(text):
        text = replace(text, "#define GENERIC_GIC_V3_IRQ                 1 /* interrupts via GICv3 Group 1, see osfmk/arm64/gic_v3_irq.c */", "#define GENERIC_GIC_V2_IRQ                 1 /* A51 MMIO interrupt controller, single-core bring-up */")
        start = text.index("/*\n * The cores this kernel really runs on")
        end = text.index("#define __ARM_ARCH__", start)
        return text[:start] + "/* Cortex-A53/A73 are ARMv8.0; PAN instructions are unavailable. */\n\n" + text[end:]

    edit(native, "pexpert/pexpert/arm64/BCM2837.h", board)
    for path in ("pexpert/arm/pe_fiq.c", "osfmk/arm64/loader_return.c"):
        edit(native, path, lambda text: replace(text, "defined(GENERIC_GIC_V3_IRQ)", "(defined(GENERIC_GIC_V3_IRQ) || defined(GENERIC_GIC_V2_IRQ))"))
    edit(native, "osfmk/conf/files.arm64", lambda text: replace(text, "osfmk/arm64/gic_v3_irq.c\toptional nos_arm_asm", "osfmk/arm64/gic_v3_irq.c\toptional nos_arm_asm\nosfmk/arm64/gic_v2_irq.c\toptional nos_arm_asm"))
    edit(native, "osfmk/arm64/gic_v2_irq.c", lambda _: (PROJECT / "prototype/a51-platform/gic_v2_irq.c").read_text())
    edit(native, "makedefs/MakeInc.def", lambda text: replace(text,
        "MACHINE_FLAGS_ARM64_BCM2837 = -DARM64_BOARD_CONFIG_BCM2837 -Xclang -target-feature -Xclang +pan",
        "MACHINE_FLAGS_ARM64_BCM2837 = -DARM64_BOARD_CONFIG_BCM2837 -mcpu=cortex-a53"))
    edit(root, "userland/src/hello.c", lambda _: (PROJECT / "prototype/a51-platform/hello.c").read_text())
    # Compute every transformation before mutating any source. Retain original bytes.
    for change in planned:
        apply(*change)
    shutil.copy2(Path(__file__), packet / "source.py")
    result = {"schema_version": 1, "scope": "isolated_single_core_a51_platform_adaptation",
              "root": str(root), "changes": changes, "build_verified": False,
              "device_operations": False, "phase_3_device_gate_passed": False}
    (packet / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    (PROJECT / "manifests/phase3-platform-adaptation.json").write_text(json.dumps({"packet": str(packet.relative_to(PROJECT)), **result}, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
