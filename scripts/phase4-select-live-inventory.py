#!/usr/bin/env python3
"""Select the original current inventory and remove a leftover capture module."""
from __future__ import annotations
import json
from pathlib import Path
import shutil
from phase4_support import PROJECT, new_packet, pin, require, write_json, documents, index_packet
from phase4_device import Device, BASELINE_SHA256, BOOT


def main():
    rel = "evidence/phase-4/live-inventory/20261114T160910754391Z/result.json"
    inventory = json.loads((PROJECT / rel).read_text(encoding="utf-8"))
    require(inventory["inventory_valid"] and all(inventory["checks"].values()), "Inventory did not pass")
    packet = new_packet("inventory-selection-cleanup", Path(__file__))
    shutil.copy2(PROJECT / "scripts/phase4_device.py", packet / "phase4_device.py")
    write_json(packet / "selected-inventory.json", inventory)
    dev = Device(packet)
    result = {"packet": packet.relative_to(PROJECT).as_posix(), "inventory": rel,
        "passed": False, "phase_4_gate_passed": False, "partition_writes": False,
        "reboot": False, "leftover_module_removed": False}
    try:
        require(dev.mode("state") == "device", "Android unavailable")
        require(dev.text("model", "getprop ro.product.model") == "SM-A515F", "Wrong model")
        require(dev.text("root", "id").startswith("uid=0(root)"), "Root unavailable")
        before = dev.text("boot-id-before", "cat /proc/sys/kernel/random/boot_id")
        modules = dev.text("modules-before", "cat /proc/modules")
        dev.root("capture-log-before-cleanup", "dmesg", limit=8388608)
        if any(line.startswith("early_probe ") for line in modules.splitlines()):
            dev.root("remove-leftover-reader", "rmmod early_probe")
            result["leftover_module_removed"] = True
        dev.root("reader-absent", "test ! -e /sys/module/early_probe")
        dev.root("modules-after", "cat /proc/modules")
        require(dev.text("baseline-after", "sha256sum " + BOOT).split()[0] == BASELINE_SHA256,
            "Baseline mismatch")
        require(dev.text("boot-id-after", "cat /proc/sys/kernel/random/boot_id") == before,
            "Android rebooted during cleanup")
        result.update(passed=True, same_android_boot=True, android_boot_id=before)
    except Exception as exc:
        result["error"] = str(exc)
    write_json(packet / "result.json", result)
    state = json.loads((PROJECT / "state.json").read_text(encoding="utf-8"))
    if result["passed"]:
        state["phase_4_inventory"] = {"result": rel, **pin(PROJECT / rel)}
        state["phase_4_inventory_cleanup"] = {"result": result["packet"] + "/result.json", **pin(packet / "result.json")}
        state["phase_4_diagnostics"]["status"] = "built_qemu_verified_silicon_pending"
    log = (PROJECT / "docs/IMPLEMENTATION-LOG.md").read_text(encoding="utf-8")
    log += ("\n\n## P4-011 — Select reconnected inventory and clean up the historical reader\n\n"
        "Purpose/files: scripts/phase4_device.py and scripts/phase4-select-live-inventory.py, state.json, "
        "docs/STATE.md and this log. Retain byte-exact commands with mandatory remote status and strict "
        "bounds, select the user's reconnected-device inventory, and unload the leftover early_probe "
        "capture module after retaining the Android log. No partition writes or reboot.\n\n"
        f"Verification: passed={result['passed']}; module_removed={result['leftover_module_removed']}; "
        f"packet={result['packet']}; error={result.get('error')}. "
        "The original inventory and failed missing-device attempt remain unchanged. "
        "The first cleanup run, 20261114T161416749361Z, completed the device cleanup and "
        "saved result.json, then failed during documentation decoding under Windows cp1252. "
        "Explicit UTF-8 reads fix the bookkeeping; the original failed run/source/result are retained. "
        "The 19 corrected QEMU checks are verified; A51 peripheral execution remains pending.\n\n"
        "Limitations/rollback: this is Android inventory/cleanup only. The module removal is reversible "
        "with its retained source/binary; it need not remain loaded. Before/after documents and helper "
        "bytes are retained in the packet. Restore before documents to undo selection; preserve all evidence.\n")
    current = (PROJECT / "docs/STATE.md").read_text(encoding="utf-8")
    current += (f"\n\n## Reconnected Phase 4 inventory and cleanup ({packet.name})\n\n"
        f"Inventory: `{rel}`. Cleanup: `{result['packet']}/result.json`; passed={result['passed']}. "
        f"Leftover early_probe removed={result['leftover_module_removed']}. "
        "Corrected SPI/guard QEMU integration passed all 19 checks. "
        "The next action is a bounded standalone controller snapshot with baseline restoration; "
        "Phase 4 remains incomplete.\n")
    documents(packet, {"state.json": json.dumps(state, indent=2) + "\n",
        "docs/STATE.md": current, "docs/IMPLEMENTATION-LOG.md": log})
    index_packet(packet)
    print(json.dumps(result, indent=2), flush=True)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
