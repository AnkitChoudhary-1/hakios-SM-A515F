#!/usr/bin/env python3
"""Test envelope attribution, lengths and both CRCs with retained fixtures."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import struct
import zlib
from phase4_envelope import decode, CAPACITY, COPY_LIMIT, MAX_LOG, DECIMAL, HEX
from phase4_support import require, write_json, pin

NONCE = "0123456789abcdef0123456789abcdef"


def fixture(log=b"kernel\nHAKIOS_P4_LOG_BEGIN\nuser\n", **updates):
    fields = {key: 0 for key in DECIMAL | HEX}
    fields.update(stage=5, entry_el=4, runtime_base=0x80278000, cntfrq=26000000,
                  validated=1, log_valid=1, requested=len(log), copied=len(log),
                  copy_entries=11, copied_bytes=15200000, zeroed_bytes=2000000)
    fields.update(updates)
    parts = [f"nonce={NONCE}"]
    for key, value in fields.items():
        parts.append(f"{key}={value}" if key in DECIMAL else f"{key}=0x{value:016x}")
    crc = zlib.crc32(log)
    header = ("HAKIOS_P4_ENVELOPE_V1 " + " ".join(parts) + f" crc32={crc:08x}\n").encode("ascii")
    raw = header + b"HAKIOS_P4_LOG_BEGIN\n" + log + (f"\nHAKIOS_P4_LOG_END nonce={NONCE} crc32={crc:08x}\n").encode("ascii")
    return sign(raw)


def sign(raw):
    return raw + (f"HAKIOS_P4_ENVELOPE_CRC32={zlib.crc32(raw):08x}\n").encode("ascii")


def persistent(raw):
    return b"DBGC" + struct.pack("<II", len(raw), len(raw)) + raw + bytes(CAPACITY - 12 - len(raw))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, required=True)
    args = parser.parse_args()
    folder = args.packet / "envelope-fixtures"
    folder.mkdir(parents=True, exist_ok=False)
    checks = {}

    def accepted(name, raw, complete):
        (folder / (name + ".bin")).write_bytes(raw)
        result = decode(raw, NONCE)
        require(result["complete_log"] == complete, name + ": completeness decision differs")
        checks[name] = True

    def rejected(name, raw, nonce=NONCE):
        (folder / (name + ".bin")).write_bytes(raw)
        try:
            decode(raw, nonce)
        except ValueError:
            checks[name] = True
            return
        raise ValueError(name + ": corruption was accepted")

    valid = fixture()
    accepted("complete-text", valid, True)
    accepted("complete-persistent", persistent(valid), True)
    accepted("bounded-partial", fixture(b"z" * COPY_LIMIT, requested=MAX_LOG), False)
    accepted("invalid-source-bounded-empty", fixture(b"", log_valid=0, requested=(1 << 64) - 1), False)
    accepted("prevalidation-empty", fixture(b"", stage=1, reason=5, validated=0, log_valid=0,
             copy_entries=0, copied_bytes=0, zeroed_bytes=0), False)
    rejected("wrong-nonce", valid, "f" * 32)
    rejected("invalid-expected-nonce", valid, "z" * 32)
    rejected("empty", b"")
    rejected("oversize-bank", bytes(CAPACITY + 1))
    rejected("truncated-header", b"DBGC\0\0")
    rejected("wrapped-persistent", b"DBGC" + struct.pack("<II", 1, len(valid)) + valid)
    rejected("excess-persistent-length", b"DBGC" + struct.pack("<II", len(valid) + 1, len(valid) + 1) + valid)
    rejected("uncommitted-persistent", bytes(12) + valid)
    rejected("stale-version", valid.replace(b"ENVELOPE_V1", b"ENVELOPE_V0", 1))
    rejected("header-checksum", valid.replace(b"stage=5", b"stage=4", 1))
    rejected("payload-checksum", valid.replace(b"kernel\n", b"Kernel\n", 1))
    rejected("truncated-trailer", valid[:-1])
    rejected("appended-trailer-data", valid + b"x")
    for name, raw in {
        "unknown-field": valid.replace(b" stage=5", b" unknown=0 stage=5", 1),
        "duplicate-field": valid.replace(b" stage=5", b" stage=5 stage=5", 1),
        "missing-field": valid.replace(b" stage=5", b"", 1),
        "negative-integer": valid.replace(b" stage=5", b" stage=-1", 1),
        "overflow-integer": valid.replace(b" stage=5", b" stage=18446744073709551616", 1),
        "nonascii-field": valid.replace(b" stage=5", b" stage=\xff", 1),
        "wrong-footer-nonce": valid.replace(b"LOG_END nonce=" + NONCE.encode(), b"LOG_END nonce=" + b"f" * 32, 1),
    }.items():
        raw = raw[:raw.rfind(b"HAKIOS_P4_ENVELOPE_CRC32=")]
        rejected(name, sign(raw))
    for name, raw in {
        "copied-exceeds-request": fixture(b"123", requested=2),
        "copied-with-invalid-source": fixture(b"123", log_valid=0),
        "accepted-source-without-validation": fixture(b"", validated=0),
        "accepted-source-exceeds-limit": fixture(b"", requested=MAX_LOG + 1),
        "invalid-stage": fixture(stage=6),
        "invalid-reason": fixture(reason=8),
        "invalid-error": fixture(error=10),
        "invalid-boolean": fixture(validated=2),
        "copy-before-validation": fixture(b"", validated=0, log_valid=0),
        "excess-copy-count": fixture(copy_entries=65),
        "excess-copy-bytes": fixture(copied_bytes=0x1800000),
        "excess-zero-bytes": fixture(zeroed_bytes=0x1800000),
    }.items():
        rejected(name, raw)
    # Every retained byte corruption must be rejected, including the fields
    # whose values are not used in the PID 1 acceptance decision.
    for i in range(0, len(valid), 11):
        raw = bytearray(valid); raw[i] ^= 1
        rejected(f"bit-flip-{i}", bytes(raw))
    write_json(args.packet / "envelope-tests.json", {"passed": True, "checks": checks,
               "fixture_pins": {p.name: pin(p) for p in sorted(folder.glob("*.bin"))},
               "scope": "Contract fixtures only; no device/peripheral evidence"})
    print(json.dumps({"PHASE4_ENVELOPE_PASS": True, "checks": len(checks)}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
