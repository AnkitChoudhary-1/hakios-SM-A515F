"""Acquire original recovery pstore records without device actions on import."""
from __future__ import annotations

import re
from phase4_envelope import CAPACITY, decode
from phase4_support import pin, require, write_json

# fs/pstore/ram.c appends persistent_ram_ecc_string() after the old log.
# fs/pstore/ram_core.c:247-262 defines precisely these two optional notices.
# Never scan for an envelope, strip arbitrary text, or accept bad ECC blocks.
ECC_NOTICE = re.compile(
    rb"\n(?:No errors detected|([0-9]{1,10}) Corrected bytes, ([0-9]{1,10}) unrecoverable blocks)\n\Z"
)
EXPORT_LIMIT = CAPACITY + 96


def decode_export(raw: bytes, nonce: str) -> dict:
    require(isinstance(raw, bytes) and 0 < len(raw) <= EXPORT_LIMIT,
            "Pstore export is empty or exceeds its bound")
    require(raw.startswith(b"HAKIOS_P4_ENVELOPE_V1 "),
            "Pstore does not begin with the original Phase 4 envelope")
    notice = ECC_NOTICE.search(raw)
    envelope = raw
    ecc = {"present": False}
    if notice:
        corrected = int(notice[1] or b"0")
        bad = int(notice[2] or b"0")
        require(corrected <= 0x7fffffff and bad == 0,
                "Pstore ECC reports invalid counts or unrecoverable blocks")
        envelope = raw[:notice.start()]
        ecc = {"present": True, "corrected_bytes": corrected,
               "unrecoverable_blocks": bad, "original_notice": notice[0].decode("ascii")}
    parsed = decode(envelope, nonce)
    parsed["ecc"] = ecc
    return parsed


def acquire(device, packet, nonce: str, result: dict) -> dict:
    """One checked, framed acquisition per bank; conflicting valid banks fail."""
    selected = None
    result["capture_banks"] = {}
    for bank in ("console", "pmsg"):
        name = "capture-original-" + bank
        original = packet / (bank + ".original")
        try:
            raw = device.root(name,
                "test -r /sys/fs/pstore/" + bank + "-ramoops-0 && cat /sys/fs/pstore/" + bank + "-ramoops-0",
                recovery=True, limit=EXPORT_LIMIT, timeout=15)
            original.write_bytes(raw)
            decoded = decode_export(raw, nonce)
        except Exception as exc:
            # Device saves transport output even on a failed remote exit.
            saved = packet / (name + ".stdout.bin")
            if not original.exists() and saved.is_file():
                original.write_bytes(saved.read_bytes())
            result["capture_banks"][bank] = {"valid": False, "error": str(exc),
                "original": pin(original) if original.is_file() else None}
            continue
        result["capture_banks"][bank] = {"valid": True, "original": pin(original),
            "envelope": decoded["envelope_pin"], "ecc": decoded["ecc"]}
        write_json(packet / "pstore-acquisition.json", result["capture_banks"])
        # Deliberately outside the invalid-bank handler: disagreement between
        # independently valid records must never become a missing-bank warning.
        if selected is not None:
            require(selected["envelope_pin"] == decoded["envelope_pin"] and
                    selected["fields"] == decoded["fields"] and
                    selected["log"] == decoded["log"] and
                    selected["diagnostic"] == decoded["diagnostic"],
                    "Conflicting valid console and pmsg envelopes")
        else:
            selected = decoded
            result["capture_bank"] = bank
    write_json(packet / "pstore-acquisition.json", result["capture_banks"])
    require(selected is not None, "No valid attributable pstore bank: " +
            "; ".join(bank + ": " + row.get("error", "") for bank, row in result["capture_banks"].items()))
    (packet / "kernel-user.log").write_bytes(selected["log"])
    (packet / "fault-diagnostic.log").write_bytes(selected["diagnostic"])
    result["envelope"] = selected["fields"]
    result["original_log"] = selected["log_pin"]
    return selected
