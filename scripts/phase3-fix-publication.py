#!/usr/bin/env python3
"""Retain and correct pstore publication order and conflicting bank handling."""
from __future__ import annotations
import ast
import json
from pathlib import Path
import struct
from types import SimpleNamespace
from phase3_support import PROJECT, packet_new, packet_index, packet_verify, json_write, update_documents, require
from phase3_envelope import decode


def main():
    packet = packet_new("publication-correction", Path(__file__))
    core = (PROJECT / "prototype/phase3-loader/loader.c").read_text(encoding="utf-8")
    old = """    barrier();
    write32(CONSOLE_PA + 4, used);
    write32(CONSOLE_PA + 8, used);
    write32(CONSOLE_PA, 0x43474244u);
    /* The separately measured pmsg region is retained by recovery too.
"""
    require(core.count(old) == 1, "Console publication anchor changed")
    core = core.replace(old, """    barrier();
    /* The separately measured pmsg region is retained by recovery too.
""", 1)
    old = """    write32(0xf9e90000, 0x43474244u);
    barrier();
}"""
    require(core.count(old) == 1, "Pmsg publication anchor changed")
    core = core.replace(old, """    write32(0xf9e90000, 0x43474244u);
    barrier();
    /* Publish console last: observers may stop as soon as it is complete. */
    write32(CONSOLE_PA + 4, used);
    write32(CONSOLE_PA + 8, used);
    write32(CONSOLE_PA, 0x43474244u);
    barrier();
}""", 1)
    cycle = (PROJECT / "scripts/phase3-device-cycle.py").read_text(encoding="utf-8")
    old = """                if decoded is None:
                    decoded = validated
                    result["capture_bank"] = bank
                else:
                    require(decoded["fields"] == validated["fields"] and decoded["log"] == validated["log"], "Pstore copies disagree")
            except (ValueError, RuntimeError) as exc:
                failures.append(str(exc))
"""
    new = """            except (ValueError, RuntimeError) as exc:
                failures.append(str(exc))
                continue
            # A conflict between two valid copies is fatal, outside the
            # missing/invalid-bank handler. Restoration still runs in finally.
            if decoded is None:
                decoded = validated
                result["capture_bank"] = bank
            else:
                require(decoded["fields"] == validated["fields"] and decoded["log"] == validated["log"], "Pstore copies disagree")
"""
    require(cycle.count(old) == 1, "Capture comparison anchor changed")
    cycle = cycle.replace(old, new, 1)
    ast.parse(cycle)

    # Exercise the actual nested capture routine with two original, CRC-valid
    # envelopes. The only changed field remains valid but must cause rejection.
    retained = PROJECT / "evidence/phase-3/loader-qemu/20261114T040127526468Z"
    packet_verify(retained)
    selected = json.loads((retained / "selected-loader.json").read_text(encoding="utf-8"))
    raw = (retained / "console.bin").read_bytes()
    original = raw[12:12 + struct.unpack_from("<I", raw, 8)[0]]
    decode(original, selected["nonce"])
    changed = original.replace(b" code=0x0000000000000000", b" code=0x0000000000000001", 1)
    require(changed != original, "Regression envelope anchor missing")
    decode(changed, selected["nonce"])
    main_node = next(n for n in ast.parse(cycle).body if isinstance(n, ast.FunctionDef) and n.name == "main")
    capture = next(n for n in main_node.body if isinstance(n, ast.FunctionDef) and n.name == "retain_console")
    capture.body = [n for n in capture.body if not isinstance(n, ast.Nonlocal)]
    module = ast.fix_missing_locations(ast.Module(body=[capture], type_ignores=[]))
    env = {"shell": lambda *a, **k: "", "packet": packet, "require": require, "decode": decode,
           "selected": selected, "result": {"checks": {}}, "args": SimpleNamespace(case="reset"), "diag": 1,
           "adb": lambda name, *a, **k: SimpleNamespace(returncode=0, stdout=changed if name.endswith("pmsg") else original)}
    exec(compile(module, str(PROJECT / "scripts/phase3-device-cycle.py"), "exec"), env)
    try:
        env["retain_console"]()
    except ValueError as exc:
        require(str(exc) == "Pstore copies disagree", "Unexpected bank rejection: " + str(exc))
    else:
        raise ValueError("Conflicting valid bank copies were accepted")
    env["result"] = {"checks": {}}
    env["adb"] = lambda *a, **k: SimpleNamespace(returncode=0, stdout=original)
    env["retain_console"]()
    require(env["result"]["capture_diagnostics"] == [], "Identical banks rejected")

    log = (PROJECT / "docs/IMPLEMENTATION-LOG.md").read_text(encoding="utf-8")
    log += """

### P3-020 — Complete both pstore copies before publishing console and reject conflicts

Date: 14 November 2026, Asia/Calcutta. Phase 3 IN PROGRESS, hardware gate 0/3; Phase 4 remains authorized after that gate.

Purpose/files: scripts/phase3-fix-publication.py, prototype/phase3-loader/loader.c, scripts/phase3-device-cycle.py and this log. Publish the complete pmsg header/signature first and the console signature last, so a QEMU observer cannot stop halfway through the mirror. Move valid-bank comparison outside the recoverable missing/invalid-bank exception handler; contradictory original copies now fail the cycle and its finally block still restores baseline. Before/after bytes, patch and the actual capture-routine regression outputs are retained in this publication-correction packet.

Verification: Python syntax parsed; the actual nested retain_console routine accepted identical CRC-valid historical envelopes and rejected two independently valid envelopes whose code fields disagree. Changed loader execution is pending a fresh strict build and five QEMU cases. There are no phone operations in this correction. The earlier persistence script run 20261114T041457205670Z failed on Windows cp1252 decoding before any file mutation; UTF-8 retry 20261114T041535065799Z succeeded and remains retained.

Limitations/rollback: source-order and capture tests do not establish physical entry/reset/persistence. Restore only this packet's indexed before files and rebuild into a fresh isolated directory; retain all earlier packets and retired hardware nonces. Baseline phone restoration remains verified from the prior cycle.
"""
    update_documents(packet, {"prototype/phase3-loader/loader.c": core,
                             "scripts/phase3-device-cycle.py": cycle, "docs/IMPLEMENTATION-LOG.md": log})
    json_write(packet / "result.json", {"syntax_passed": True, "identical_valid_banks_accepted": True,
        "conflicting_valid_banks_rejected": True, "loader_execution_verified": False, "device_operations": False})
    packet_index(packet)
    print(packet.relative_to(PROJECT).as_posix(), flush=True)


if __name__ == "__main__":
    main()
