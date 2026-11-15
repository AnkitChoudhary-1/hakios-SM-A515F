"""Strict decoder for the fixed-bank Phase 4 capture. No device operations."""
from __future__ import annotations
import hashlib
import struct
from phase4_support import require

BANKS = ((0xfb000000, 0x1e0, 65536), (0xf9000040, 0x100, 400), (0x8f000000, 0x140, 65536))
RECORD_MAGIC, LOG_MAGIC = 0x32454c5241494b48, 0x3150474c344b4848
CAPTURE_BYTES = 64 + sum(64 + 256 + 32 + cap for _, _, cap in BANKS)


def decode(raw, nonce):
    require(len(nonce) == 32 and all(c in "0123456789abcdef" for c in nonce), "Invalid expected nonce")
    require(len(raw) == CAPTURE_BYTES and raw[:8] == b"HK4CAP01", "Capture length/magic mismatch")
    meta = struct.unpack_from("<8Q", raw)
    hi, lo = int(nonce[:16], 16), int(nonce[16:], 16)
    require(meta[1:7] == (1, 64, len(raw), hi, lo, 3) and meta[7] <= 7, "Capture metadata mismatch")
    offset, banks, valid_mask = 64, [], 0
    for i, (pa, header_offset, cap) in enumerate(BANKS):
        desc = struct.unpack_from("<8Q", raw, offset)
        block_bytes = 64 + 256 + 32 + cap
        require(desc[:2] == (pa, cap) and desc[4:] == (256, 32, block_bytes, header_offset), "Capture bank is outside whitelist")
        flags, copied = desc[2:4]
        require(flags in (0, 4, 5, 7) and copied <= cap, "Invalid bank flags/length")
        record_raw = raw[offset + 64:offset + 320]
        record = struct.unpack("<32Q", record_raw)
        header = struct.unpack_from("<4Q", raw, offset + 320)
        data = raw[offset + 352:offset + block_bytes]
        current = record[:3] == (RECORD_MAGIC, 1, 256) and record[3] <= 8 and record[17:19] == (hi, lo)
        require(not flags & 1 or current, "Reader accepted an unattributable record")
        if flags & 1:
            valid_mask |= 1 << i
        if flags == 7:
            require(header[0] == LOG_MAGIC and 4 <= record[3] <= 7 and header[3] == record[3] and
                    header[2] == record[7] and copied == header[1] <= min(header[2], cap), "Uncommitted/invalid log accepted")
            if copied:
                require(0x83000000 <= record[6] < 0x847f0000 and record[7] <= 0x847f0000 - record[6], "Log source metadata is outside arena")
        else:
            require(copied == 0, "Reader copied a stale/uncommitted log")
        require(data[copied:] == bytes(cap - copied), "Reader disclosed uncopied bank bytes")
        log = data[:copied]
        banks.append({"pa": hex(pa), "current": bool(flags & 1), "committed": flags == 7,
            "stable": bool(flags & 4), "record": list(record), "header": list(header), "copied": copied,
            "log": log, "log_pin": {"bytes": len(log), "sha256": hashlib.sha256(log).hexdigest()}})
        offset += block_bytes
    require(valid_mask == meta[7], "Capture current-bank mask disagrees")
    current_banks = [b for b in banks if b["current"]]
    require(current_banks, "No stable record matches this run's nonce")
    first = current_banks[0]["record"]
    require(all(b["record"] == first for b in current_banks), "Current record banks disagree")
    committed = [b for b in current_banks if b["committed"]]
    full = max(committed, key=lambda b: b["copied"], default=None)
    if full:
        require(all(full["log"].startswith(b["log"]) for b in committed), "Committed log banks disagree")
    return {"record": first, "banks": banks, "log": full["log"] if full else b"", "committed": bool(full)}
