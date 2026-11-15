#!/usr/bin/env python3
"""Retain the failed capture and correct direct exec-out argument quoting."""
import ast
import json
from pathlib import Path
from phase3_support import PROJECT, packet_new, packet_index, update_documents, require, command
from phase3_entry_probe import decode


def main():
    packet = packet_new("entry-capture-correction", Path(__file__))
    path = PROJECT / "scripts/phase3-device-entry-probe.py"
    old = path.read_text(encoding="utf-8")
    needle = 'argv = ["exec-out", "sh", "-c", shlex.quote(text)] if recovery else ["exec-out", "su", "-c", shlex.quote(text)]'
    require(old.count(needle) == 1, "Capture source differs")
    new = old.replace(needle, 'argv = ["exec-out", "sh", "-c", text] if recovery else ["exec-out", "su", "-c", text]')
    ast.parse(new)
    records = []
    for bank in ("console", "pmsg"):
        proc = command(packet, records, "current-original-" + bank, ["adb", "-s", "A51_SERIAL_HERE", "exec-out", "su", "-c", "cat /sys/fs/pstore/" + bank + "-ramoops-0"], check=False)
        try:
            fields = decode(proc.stdout, "0928d6002b6b47d79c235f949acbeaec")
            (packet / (bank + "-decoded.json")).write_text(json.dumps(fields, indent=2), encoding="utf-8")
            print(bank + " retained current probe record", flush=True)
        except ValueError as exc:
            print(bank + " no longer contains the probe: " + str(exc), flush=True)
    log = (PROJECT / "docs/IMPLEMENTATION-LOG.md").read_text(encoding="utf-8")
    log += "\n\n### P3-025 — Correct direct binary pstore capture arguments\n\nPurpose/files: scripts/phase3-fix-entry-capture.py, scripts/phase3-device-entry-probe.py and this log. The accepted-Image diagnostic reached fresh completed Android in 42.922 seconds and its original filesystem listing reports both 160-byte records. The capture incorrectly supplied shell quoting to exec-out's direct argument array; Android treated the entire expression as a command name, returned an error string with status zero, and no register record was captured. The failure and verified baseline restoration remain retained in evidence/phase-3/entry-probe-device/20261114T045243323110Z; nonce 0928d6002b6b47d79c235f949acbeaec is retired.\n\nVerification: corrected Python syntax parsed, original current pstore reads retained in this correction packet. Shell-based adb shell commands retain necessary quoting; exec-out passes its single command argument directly. Fresh probe build, both QEMU placements and new hardware capture are required. No partition write or reboot occurs in this correction.\n\nLimitations/rollback: the filesystem sizes suggest execution/persistence but do not substitute for nonce/CRC validation. Restore the indexed before runner, rebuild with a fresh nonce, and preserve all failed packets. Phase 3 remains 0/3; Phase 4 remains authorized.\n"
    update_documents(packet, {"scripts/phase3-device-entry-probe.py": new, "docs/IMPLEMENTATION-LOG.md": log})
    packet_index(packet)
    print(packet.relative_to(PROJECT), flush=True)


if __name__ == "__main__":
    main()
