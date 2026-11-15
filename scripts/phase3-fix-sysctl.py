#!/usr/bin/env python3
"""Retain and apply the BSD/osfmk sysctl-boundary correction in the isolated port."""
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
    native = root / "xnu-src/xnu-8796.121.2"
    manifest_path = PROJECT / "manifests/phase3-platform-adaptation.json"
    manifest = json.loads(manifest_path.read_text())
    for item in manifest["changes"]:
        tree = native if item["tree"] == "native" else root
        assert pin((tree / item["path"]).read_bytes()) == item["after"], item["path"]
    assert not list(native.rglob("AGENTS.md"))
    assert not list((root / "drivers/core").rglob("AGENTS.md"))
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    packet = PROJECT / "evidence/phase-3/platform-corrections" / stamp
    packet.mkdir(parents=True, exist_ok=False)
    shutil.copy2(Path(__file__), packet / "source.py")
    planned = []

    def change(tree, relative, new):
        target = {"native": native, "common": root, "project": PROJECT}[tree] / relative
        old = target.read_bytes()
        new = new.encode()
        assert old != new, relative
        planned.append((tree, relative, target, old, new))

    gic = (PROJECT / "prototype/a51-platform/gic_v2_irq.c").read_text()
    assert "#include <sys/sysctl.h>\n" in gic
    gic = gic.replace("#include <sys/sysctl.h>\n", "")
    gic = gic.replace("static int gic_version = 2;\nstatic uint64_t timer_irqs, boot_midr;",
                      "/* BSD registers these read-only counters in hakios.platform.c. */\n"
                      "int hakios_gic_version = 2;\nuint64_t hakios_timer_irqs, hakios_boot_midr;")
    start = gic.index("SYSCTL_DECL(_kern_hakios);")
    end = gic.index("void gic_v3_irq_cpu_init(void);", start)
    gic = gic[:start] + gic[end:]
    gic = gic.replace("&timer_irqs", "&hakios_timer_irqs")
    gic = gic.replace("boot_midr =", "hakios_boot_midr =").replace("cpu_number(), boot_midr,", "cpu_number(), hakios_boot_midr,")
    change("project", "prototype/a51-platform/gic_v2_irq.c", gic)
    change("native", "osfmk/arm64/gic_v2_irq.c", gic)

    common_path = "drivers/core/hakios.platform.c"
    platform = (root / common_path).read_text()
    assert "#include <pexpert/arm64/board_config.h>" not in platform
    platform = platform.replace('#include "hakios.drivers.h"',
        '#include "hakios.drivers.h"\n#if defined(__arm64__)\n#include <pexpert/arm64/board_config.h>\n#endif')
    platform += """
/* A51 bring-up statistics belong to BSD, not osfmk's private type universe. */
#if defined(GENERIC_GIC_V2_IRQ)
extern int hakios_gic_version;
extern uint64_t hakios_timer_irqs, hakios_boot_midr;
SYSCTL_INT(_kern_hakios, OID_AUTO, gic_version, CTLFLAG_RD | CTLFLAG_LOCKED,
    &hakios_gic_version, 0, "Interrupt controller backend version");
SYSCTL_QUAD(_kern_hakios, OID_AUTO, timer_irqs, CTLFLAG_RD | CTLFLAG_LOCKED,
    &hakios_timer_irqs, "Virtual timer interrupts handled by XNU");
SYSCTL_QUAD(_kern_hakios, OID_AUTO, boot_midr, CTLFLAG_RD | CTLFLAG_LOCKED,
    &hakios_boot_midr, "MIDR of the executing boot core");
#endif
"""
    change("common", common_path, platform)
    change("native", "bsd/dev/hakios.platform.c", platform)
    # All transformations and original-pin checks precede the source mutations.
    changes = []
    patch = []
    for tree, relative, target, old, new in planned:
        for label, raw in (("before", old), ("after", new)):
            copy = packet / label / tree / relative
            copy.parent.mkdir(parents=True, exist_ok=True)
            copy.write_bytes(raw)
        target.write_bytes(new)
        changes.append({"tree": tree, "path": relative, "before": pin(old), "after": pin(new)})
        patch.append("".join(difflib.unified_diff(old.decode().splitlines(True), new.decode().splitlines(True),
                     fromfile=f"a/{tree}/{relative}", tofile=f"b/{tree}/{relative}")))
    (packet / "adaptations.patch").write_text("".join(patch))
    shutil.copy2(manifest_path, packet / "before-manifest.json")
    for item in changes:
        if item["tree"] == "project":
            continue
        prior = [p for p in manifest["changes"] if (p["tree"], p["path"]) == (item["tree"], item["path"])]
        if prior:
            prior[0]["after"] = item["after"]
        else:
            manifest["changes"].append({k: item[k] for k in ("tree", "path", "after")})
    manifest.setdefault("correction_packets", []).append(str(packet.relative_to(PROJECT)))
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    log = PROJECT / "docs/IMPLEMENTATION-LOG.md"
    shutil.copy2(log, packet / "before-IMPLEMENTATION-LOG.md")
    with log.open("a") as out:
        out.write(f"""

### P3-009 correction — Separate BSD sysctl registration from osfmk

Date: 14 November 2026, Asia/Calcutta. Status: correction implemented; rebuild and execution pending.

The original Cortex-A53/GICv2 build `20261114T020548727641Z-phase3-build-single-core-gicv2` failed (exit 1): including BSD sys/sysctl.h from osfmk caused incompatible daddr_t, dev_t and clock_t typedef redefinitions. Its failed output and result remain preserved. The kern.hakios namespace is defined in the existing BSD platform driver, which is generated from drivers/core/hakios.platform.c. This correction exports single-core 64-bit counters from osfmk and registers them in that BSD driver, updating both its common source and generated copy. No header-guard workaround is used. Files: prototype/a51-platform/gic_v2_irq.c, isolated native osfmk/arm64/gic_v2_irq.c and bsd/dev/hakios.platform.c, isolated common drivers/core/hakios.platform.c, the adaptation manifest and scripts/phase3-fix-sysctl.py.

Verification: original adaptation pins and absence of local upstream instructions checked before all edits. Exact before/after copies and the patch are retained in `{packet.relative_to(PROJECT).as_posix()}`. Two WSL regex-string inspections accidentally exposed pipe characters to the WSL shell (`20261114T021434591061Z` and `20261114T021435067699Z`, exit 127); successful replacements use separate rg -e arguments. Build, complete GICv2/A53 QEMU execution, A51 logs/timers, bounded return and three consecutive phone runs remain pending. No device operation occurred.

Rollback: restore only indexed before source files and before-manifest.json from this correction packet, or recreate the isolated trees from preserved sources and reapply the prior adaptation. Retain both build failures and successful future runs; preserve original trees and Android baseline images.
""")
    result = {"schema_version": 1, "packet": str(packet.relative_to(PROJECT)), "changes": changes,
              "source_verified": True, "build_verified": False, "device_operations": False,
              "phase_3_device_gate_passed": False}
    (packet / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
