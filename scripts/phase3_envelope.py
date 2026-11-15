"""Strict decoder for original bounded Phase 3 persistent-console envelopes."""
import hashlib
import re
import struct
import zlib


def decode(raw, nonce):
    if not isinstance(raw, bytes) or len(raw) > 512 * 1024:
        raise ValueError("Console capture exceeds its measured capacity")
    if raw[:4] == b"DBGC":
        if len(raw) < 12:
            raise ValueError("Truncated persistent RAM header")
        start, size = struct.unpack_from("<II", raw, 4)
        if start != size or size > len(raw) - 12:
            raise ValueError("Incomplete/wrapped console header")
        raw = raw[12:12 + size]
    header, separator, body = raw.partition(b"\n")
    if not separator or not header.startswith(b"HAKIOS_P3_ENVELOPE_V1 "):
        raise ValueError("Missing original Phase 3 envelope")
    fields = {}
    for pair in header[len(b"HAKIOS_P3_ENVELOPE_V1 "):].split():
        key, equal, value = pair.partition(b"=")
        key = key.decode("ascii")
        if not equal or key in fields:
            raise ValueError("Invalid/duplicate envelope field")
        fields[key] = value.decode("ascii")
    if not re.fullmatch("[0-9a-f]{32}", nonce) or fields.get("nonce") != nonce:
        raise ValueError("Run nonce mismatch")
    required = ("stage", "error", "reason", "code", "entry_el", "midr", "mpidr", "cntfrq",
                "entry_sctlr", "return_sctlr", "fdt", "wdt_before", "wdt_after",
                "log_valid", "requested", "copied", "crc32")
    for key in required:
        if key not in fields:
            raise ValueError("Missing envelope field: " + key)
        value = fields[key]
        fields[key] = int(value, 16 if key == "crc32" or value.startswith("0x") else 10)
        if not 0 <= fields[key] < 1 << 64:
            raise ValueError("Envelope integer out of bounds")
    copied = fields["copied"]
    if copied > 512 * 1024 - 4096 or fields["requested"] > 1536 * 1024:
        raise ValueError("Unbounded log length")
    prefix, marker, rest = body.partition(b"HAKIOS_P3_LOG_BEGIN\n")
    if not marker or len(rest) < copied:
        raise ValueError("Missing/truncated original log")
    log, footer = rest[:copied], rest[copied:]
    expected = (f"\nHAKIOS_P3_LOG_END nonce={nonce} crc32={fields['crc32']:08x}\n").encode("ascii")
    if footer != expected or zlib.crc32(log) != fields["crc32"]:
        raise ValueError("Log footer/checksum mismatch")
    return {"fields": fields, "log": log, "diagnostic": prefix,
            "log_pin": {"bytes": len(log), "sha256": hashlib.sha256(log).hexdigest()},
            "complete_log": fields["log_valid"] == 1 and fields["requested"] == copied}
