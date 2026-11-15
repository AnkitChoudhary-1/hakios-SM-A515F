#!/usr/bin/env python3
"""Retain source changes for accepted-envelope loader builds and gate binding."""
import ast
import json
from pathlib import Path
import shutil
from phase3_support import PROJECT, packet_new, packet_index, update_documents, require


def replace_once(text, old, new):
    require(text.count(old) == 1, "Source replacement not unique: " + old[:70])
    return text.replace(old, new)


def main():
    packet = packet_new("accepted-carrier-preparation", Path(__file__))
    shutil.copy2(PROJECT / "scripts/phase3_carrier.py", packet / "phase3_carrier.py")
    paths = ("scripts/phase3-build-loader.py", "scripts/phase3-device-cycle.py", "scripts/phase3-package-loader.py")
    changes = {rel: (PROJECT / rel).read_text(encoding="utf-8") for rel in paths}
    b = changes[paths[0]]
    b = replace_once(b, "from phase3_support import PROJECT, command, json_write, packet_new, packet_index, pin, require", "from phase3_support import PROJECT, command, json_write, packet_new, packet_index, pin, require\nfrom phase3_carrier import wrap as wrap_carrier")
    b = replace_once(b, 'parser.add_argument("--mode", choices=("hardware", "qemu"), required=True)', 'parser.add_argument("--mode", choices=("hardware", "qemu"), required=True)\n    parser.add_argument("--entry-style", choices=("standalone", "accepted-carrier"), default="standalone")')
    b = replace_once(b, '"work": str(work), "mode": args.mode, "diagnostic": args.diagnostic,', '"work": str(work), "mode": args.mode, "diagnostic": args.diagnostic, "entry_style": args.entry_style,')
    b = replace_once(b, '(work / "loader.Image").write_bytes(image + bytes(IMAGE_BYTES - len(image)))', 'if args.entry_style == "accepted-carrier":\n            emitted, carrier = wrap_carrier(image, symbols)\n            result["carrier"] = carrier\n            shutil.copy2(PROJECT / "scripts/phase3_carrier.py", packet / "phase3_carrier.py")\n        else:\n            emitted = image + bytes(IMAGE_BYTES - len(image))\n        require(len(emitted) == IMAGE_BYTES, "Final Image length differs")\n        (work / "loader.Image").write_bytes(emitted)')
    changes[paths[0]] = b
    d = changes[paths[1]]
    d = replace_once(d, 'require(tested["input_artifacts"] == loader["input_artifacts"], "QEMU tested different kernel/hello bytes")', 'require(tested["input_artifacts"] == loader["input_artifacts"], "QEMU tested different kernel/hello bytes")\n        require(tested.get("entry_style", "standalone") == loader.get("entry_style", "standalone"), "QEMU tested a different entry envelope")\n        if loader.get("entry_style") == "accepted-carrier":\n            require(tested["carrier"] == loader["carrier"] and pin(PROJECT / "scripts/phase3_carrier.py") == loader["carrier"]["helper_pin"], "Carrier envelope/helper changed")')
    changes[paths[1]] = d
    p = changes[paths[2]]
    p = replace_once(p, '"nonce": selected["nonce"], "diagnostic": selected["diagnostic"], "checkpoint": selected["checkpoint"],', '"nonce": selected["nonce"], "diagnostic": selected["diagnostic"], "checkpoint": selected["checkpoint"],\n              "entry_style": selected.get("entry_style", "standalone"),')
    changes[paths[2]] = p
    for text in changes.values():
        ast.parse(text)
    log = (PROJECT / "docs/IMPLEMENTATION-LOG.md").read_text(encoding="utf-8")
    log += "\n\n### P3-026 — Preserve accepted Samsung entry envelope for bounded loader builds\n\nPurpose/files: scripts/phase3_carrier.py, scripts/phase3-prepare-carrier.py, scripts/phase3-build-loader.py, scripts/phase3-device-cycle.py, scripts/phase3-package-loader.py and this log. The accepted-Image diagnostic creates expected-size pstore records and continues Android, while prior standalone resets produce no attributable record. A new optional accepted-carrier build retains all 64 original Samsung header bytes and the original stext location; only the bounded loader body and stext's first branch change. The loader redirects to XNU/reset/recovery; overwritten Linux code never executes. This tests an envelope difference without declaring its cause proved. Immutable original Image/result pins, helper pin and exact patch extents are retained. No original upstream Image/source is changed.\n\nVerification: all changed Python sources parsed. New builds, all five complete-loader QEMU cases at observed placement and a fresh phone reset diagnostic are required. The device gate rejects different carrier helpers/envelopes or kernel/hello bytes between QEMU and hardware. No phone operation occurs in this preparation.\n\nLimitations/rollback: an accepted historical header cannot prove current firmware entry, reset, watchdog or XNU execution. Restore indexed before scripts to remove the option; rebuild only into new isolated directories. Preserve every original packet, failed hardware nonce and pinned baseline/recovery/DTBO input. Phase 3 remains 0/3; Phase 4 is authorized after its gate.\n"
    changes["docs/IMPLEMENTATION-LOG.md"] = log
    update_documents(packet, changes)
    packet_index(packet)
    print(packet.relative_to(PROJECT), flush=True)


if __name__ == "__main__":
    main()
