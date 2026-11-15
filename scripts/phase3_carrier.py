"""Preserve the accepted Samsung Image envelope around the bounded loader."""
import json
from pathlib import Path
import struct
from phase3_support import PROJECT, pin, require

ORIGINAL = PROJECT / "evidence/phase-2/early-entry-kernel/20261113T004224388744Z/result.json"
ORIGINAL_PIN = {"bytes": 36334080, "sha256": "3054cfe40d06c17963575d6e067ced0c38f8e532bb490e49f828ae66b0e5c420"}


def wrap(loader, symbols):
    build = json.loads(ORIGINAL.read_text(encoding="utf-8"))
    source = Path(build["build_directory"]) / "out/arch/arm64/boot/Image"
    require(pin(source) == ORIGINAL_PIN, "Accepted carrier Image changed")
    raw = bytearray(source.read_bytes())
    stext = build["symbols"]["stext"] - build["symbols"]["_text"]
    entry = symbols["loader_entry"] - symbols["_start"]
    require(entry == 64 and 64 < len(loader) < stext, "Loader overlaps carrier entry")
    raw[64:len(loader)] = loader[64:]
    delta = entry - stext
    require(delta % 4 == 0 and -(1 << 27) <= delta < (1 << 27), "Carrier branch bounds")
    raw[stext:stext + 4] = struct.pack("<I", 0x14000000 | ((delta // 4) & 0x3ffffff))
    require(raw[:64] == source.read_bytes()[:64], "Accepted header changed")
    require(raw[64:len(loader)] == loader[64:], "Carrier loader bytes differ")
    return bytes(raw), {"original_image": ORIGINAL_PIN, "original_result": pin(ORIGINAL), "helper_pin": pin(Path(__file__)),
                        "header_hex": raw[:64].hex(), "stext_offset": stext, "loader_entry_offset": entry,
                        "changed_spans": [[64, len(loader)], [stext, stext + 4]],
                        "scope": "Accepted header/stext envelope; overwritten Linux body never runs; XNU returns via reset/recovery"}
