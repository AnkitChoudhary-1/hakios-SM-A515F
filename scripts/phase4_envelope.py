"""Decode the measured console/pmsg Phase 4 contract; no device actions."""
from __future__ import annotations
import hashlib
import re
import struct
import zlib

CAPACITY = 512 * 1024
MAX_LOG = 1536 * 1024
COPY_LIMIT = CAPACITY - 4096
DECIMAL = {"stage", "error", "reason", "log_valid", "requested", "copied"}
HEX = {"code", "entry_el", "midr", "mpidr", "cntfrq", "entry_sctlr", "return_sctlr",
       "entry_daif", "runtime_base", "fdt", "wdt_before", "wdt_after", "validated",
       "copy_entries", "copied_bytes", "zeroed_bytes"}
FIELDS = DECIMAL | HEX | {"nonce", "crc32"}


def decode(raw: bytes, nonce: str) -> dict:
    if not isinstance(raw, bytes) or not raw or len(raw) > CAPACITY:
        raise ValueError("Console capture exceeds its measured capacity or is empty")
    if not isinstance(nonce, str) or not re.fullmatch(r"[0-9a-f]{32}", nonce):
        raise ValueError("Invalid expected run nonce")
    if raw[:4] == b"DBGC":
        if len(raw) < 12:
            raise ValueError("Truncated persistent RAM header")
        start, size = struct.unpack_from("<II", raw, 4)
        if not size or start != size or size > len(raw) - 12:
            raise ValueError("Incomplete/wrapped console header")
        raw = raw[12:12 + size]
    header, separator, body = raw.partition(b"\n")
    prefix = b"HAKIOS_P4_ENVELOPE_V1 "
    if not separator or not header.startswith(prefix) or len(header) > 2048:
        raise ValueError("Missing original Phase 4 envelope")
    fields = {}
    try:
        for pair in header[len(prefix):].split():
            key, equal, value = pair.partition(b"=")
            key, value = key.decode("ascii"), value.decode("ascii")
            if not equal or key in fields or key not in FIELDS:
                raise ValueError("Invalid/duplicate/unknown envelope field")
            fields[key] = value
    except UnicodeError as exc:
        raise ValueError("Non-ASCII envelope field") from exc
    if set(fields) != FIELDS or fields["nonce"] != nonce:
        raise ValueError("Envelope schema or run nonce mismatch")
    for key in FIELDS - {"nonce"}:
        value = fields[key]
        pattern = r"[0-9]+" if key in DECIMAL else r"[0-9a-f]{8}" if key == "crc32" else r"0x[0-9a-f]{16}"
        if not re.fullmatch(pattern, value):
            raise ValueError("Invalid envelope integer: " + key)
        number = int(value, 10 if key in DECIMAL else 16)
        if not 0 <= number < 1 << 64:
            raise ValueError("Envelope integer out of bounds")
        fields[key] = number
    if fields["stage"] not in range(1, 6) or fields["reason"] not in range(8) or fields["error"] > 9:
        raise ValueError("Unknown loader stage/reason/error")
    if fields["log_valid"] not in (0, 1) or fields["validated"] not in (0, 1):
        raise ValueError("Invalid validation state")
    copied, requested = fields["copied"], fields["requested"]
    if copied > COPY_LIMIT or copied > requested or (not fields["log_valid"] and copied):
        raise ValueError("Unbounded/inconsistent copied log length")
    if fields["log_valid"] and (not fields["validated"] or requested > MAX_LOG):
        raise ValueError("Invalid accepted log source length")
    if fields["copy_entries"] > 64 or fields["copied_bytes"] > 0x17f0000 or fields["zeroed_bytes"] > 0x17f0000:
        raise ValueError("Copy counters exceed destination arena")
    if not fields["validated"] and any(fields[key] for key in ("copy_entries", "copied_bytes", "zeroed_bytes")):
        raise ValueError("Payload copied before validation")
    diagnostic, marker, rest = body.partition(b"HAKIOS_P4_LOG_BEGIN\n")
    if not marker or len(diagnostic) > 2048 or len(rest) < copied:
        raise ValueError("Missing/truncated original log")
    log, footer = rest[:copied], rest[copied:]
    expected = (f"\nHAKIOS_P4_LOG_END nonce={nonce} crc32={fields['crc32']:08x}\n").encode("ascii")
    if not footer.startswith(expected) or zlib.crc32(log) != fields["crc32"]:
        raise ValueError("Log footer/checksum mismatch")
    trailer = footer[len(expected):]
    match = re.fullmatch(rb"HAKIOS_P4_ENVELOPE_CRC32=([0-9a-f]{8})\n", trailer)
    if not match or zlib.crc32(raw[:-len(trailer)]) != int(match.group(1), 16):
        raise ValueError("Envelope checksum/length mismatch")
    return {"fields": fields, "log": log, "diagnostic": diagnostic,
            "log_pin": {"bytes": len(log), "sha256": hashlib.sha256(log).hexdigest()},
            "envelope_pin": {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()},
            "complete_log": fields["log_valid"] == 1 and requested == copied}
