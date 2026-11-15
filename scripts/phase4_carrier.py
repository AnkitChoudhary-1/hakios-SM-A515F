"""Wrap the Phase 4 C loader in the exactly pinned accepted Samsung carrier."""
import json
from pathlib import Path
import struct
from phase4_support import PROJECT, pin, require

ORIGINAL = PROJECT / "evidence/phase-2/early-entry-kernel/20261113T004224388744Z/result.json"
RESULT_SHA256 = "7d6b8807721a6de14998615c4d9f590da1197c7ede6b6ed960309d422b25c856"
IMAGE_PIN = {"bytes": 36334080, "sha256": "3054cfe40d06c17963575d6e067ced0c38f8e532bb490e49f828ae66b0e5c420"}


def wrap(loader, symbols):
    require(pin(ORIGINAL)["sha256"] == RESULT_SHA256, "Accepted carrier result changed")
    build = json.loads(ORIGINAL.read_text(encoding="utf-8"))
    source = Path(build["build_directory"]) / "out/arch/arm64/boot/Image"
    require(pin(source) == IMAGE_PIN, "Accepted carrier Image changed")
    before = source.read_bytes()
    raw = bytearray(before)
    stext = build["symbols"]["stext"] - build["symbols"]["_text"]
    entry = symbols["loader_entry"] - symbols["_start"]
    require(stext == 20643840 and entry == 64 and 64 < len(loader) < stext, "Carrier/loader entry extent")
    require(loader[56:60] == b"ARM\x64" and loader[8:64] == before[8:64], "Vendor Image header contract")
    raw[64:len(loader)] = loader[64:]
    delta = entry - stext
    require(delta % 4 == 0 and -(1 << 27) <= delta < (1 << 27), "Carrier branch bounds")
    raw[stext:stext+4] = struct.pack("<I", 0x14000000 | ((delta // 4) & 0x3ffffff))
    require(raw[:64] == before[:64] and raw[len(loader):stext] == before[len(loader):stext] and
            raw[stext+4:] == before[stext+4:], "Unintended carrier change")
    return bytes(raw), {"original_image": IMAGE_PIN, "original_result": pin(ORIGINAL),
        "helper_pin": pin(Path(__file__)), "header_hex": raw[:64].hex(),
        "stext_offset": stext, "loader_entry_offset": entry,
        "changed_spans": [[64, len(loader)], [stext, stext+4]],
        "scope": "Accepted Samsung envelope. Embedded C loader still needs full phone execution evidence."}
