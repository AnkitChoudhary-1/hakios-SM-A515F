#!/usr/bin/env python3
"""Select the retained fresh inventory and record untested Phase 4 scaffolding."""
import json
import shutil
from pathlib import Path
from phase4_support import PROJECT, require, pin, new_packet, documents, write_json, index_packet

def main():
    inventory = "evidence/phase-4/live-inventory/20261114T151220597502Z/result.json"
    observed = json.loads((PROJECT / inventory).read_text(encoding="utf-8"))
    require(observed["inventory_valid"] and all(observed["checks"].values()), "Inventory did not pass")
    packet = new_packet("diagnostic-scaffold", __file__)
    files = ("prototype/phase4-platform/hakios.a51.c", "prototype/phase4-platform/hakios.a51.h",
             "scripts/phase4_support.py", "scripts/phase4-record-scaffold.py")
    sources = {}
    for rel in files:
        dest = packet / "sources" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PROJECT / rel, dest)
        sources[rel] = pin(dest)
    state = json.loads((PROJECT / "state.json").read_text(encoding="utf-8"))
    state["phase_4_inventory"] = {"result": inventory, **pin(PROJECT / inventory)}
    state["phase_4_diagnostics"] = {"status": "source_templates_only_not_built_or_executed",
        "packet": packet.relative_to(PROJECT).as_posix(), "sources": sources}
    state["next_action"] = "build_guarded_controller_diagnostics_and_gicv2_spi_in_isolated_phase4_tree"
    note = f"""
## Latest Phase 4 diagnostic groundwork ({packet.name})

Fresh retained Android inventory passed all required checks in `{inventory}`: valid original FDT,
independent 1 MiB image equality, matching baseline and unchanged Android boot. GPIO debugfs is unavailable.
The fixed 3,096-byte controller snapshot ABI and guarded read-only MMIO template are implemented source only;
they have not been built, applied to XNU or run. GICv2 peripheral interrupts and real display/input/UFS drivers
remain pending. The obsolete synthetic builder now exits 2 before modifying Phase 3. Phase 4 remains incomplete.
"""
    log = f"""
## P4-005 — Record guarded controller templates and select fresh inventory

Purpose/files: prototype/phase4-platform/{{hakios.a51.c,hakios.a51.h}}, scripts/{{phase4_support.py,
phase4-record-scaffold.py,phase4-build-drivers.py}}, docs/{{STATE,INDEX,IMPLEMENTATION-LOG}}.md and state.json.
The three previously unlogged template/helper files provide a versioned bounded snapshot, fixed controller
groups, explicit A51/bootarg guards, write rejection and original command/document provenance. They perform
no device operations on import and are not hardware drivers. The obsolete builder is disabled before it can
compile synthetic drivers into Phase 3; its original source is retained in this packet's before/ directory.

Verification: fresh read-only inventory run 20261114T151220148749Z-phase4-fresh-read-only-device-inventory
passed exit 0; `{inventory}` reports every required check true. This selector verifies that decision and pins
the original report and source bytes. Build, register-allowlist review and QEMU/hardware execution are pending.
No build, reboot, module or partition operation occurred in the prior template-writing continuation or selector.
Limitations: firmware clock/power state and all Phase 4 execution gates remain unknown/unpassed.
Rollback: restore indexed before/ document/script bytes from `{packet.relative_to(PROJECT).as_posix()}`;
the new templates can be ignored. Preserve inventory, source snapshots and the correction of false completion.
"""
    obsolete = '''#!/usr/bin/env python3
"""Disabled legacy simulated Phase 4 builder; original retained in evidence."""
import sys
if __name__ == "__main__":
    print("Disabled: this builder compiled simulated peripherals into Phase 3. Use the isolated Phase 4 platform build.")
    sys.exit(2)
'''
    documents(packet, {"state.json": json.dumps(state, indent=2) + "\n",
        "docs/STATE.md": (PROJECT / "docs/STATE.md").read_text(encoding="utf-8") + note,
        "docs/IMPLEMENTATION-LOG.md": (PROJECT / "docs/IMPLEMENTATION-LOG.md").read_text(encoding="utf-8") + log,
        "docs/INDEX.md": (PROJECT / "docs/INDEX.md").read_text(encoding="utf-8") +
            "\nPhase 4 groundwork: prototype/phase4-platform/hakios.a51.{c,h} and scripts/phase4_support.py; source only, execution pending.\n",
        "scripts/phase4-build-drivers.py": obsolete})
    result = {"sources": sources, "inventory": inventory, "inventory_pin": pin(PROJECT / inventory),
              "device_operations": False, "phase_4_gate_passed": False}
    write_json(packet / "result.json", result)
    index_packet(packet)
    print(json.dumps({"packet": str(packet), **result}, indent=2))

if __name__ == "__main__":
    main()
