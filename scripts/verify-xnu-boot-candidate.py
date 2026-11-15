#!/usr/bin/env python3
"""Strict verification suite for the Phase 3 Samsung XNU boot candidate."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import tarfile

PROJECT = Path(__file__).resolve().parents[1]
WORKSPACE = PROJECT.parent
SCRIPTS = PROJECT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from boot_formats import parse_arm64_image, parse_boot
from samsung_boot_dry_run import android_boot_id, parse_avb

EXPECTED_PINS = {
    "template": (61_865_984, "eb30609a62999e3282ac81e0a5e56411ef12ec1a39c107171bf3e01209c7cb67"),
    "original_boot": (61_865_984, "89600eb7f3bb73a26d6d8b38aa46c7cb27a5b942da84e0a3c77626ea21642e52"),
    "recovery": (71_106_560, "12412e2008d950260cda627ac7a6b8eac954b49ef9db5573a297f67e4fc85999"),
    "dtbo": (8_388_608, "41662c61ff3158448935025477a4e29d445823dab2cddafb18ea649c8ea925d6"),
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(f"FAIL: {msg}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=None, help="Path to manifest.json (defaults to latest)")
    args = parser.parse_args()

    if args.manifest is None:
        import glob
        manifests = sorted(glob.glob(str(PROJECT / "evidence/phase-3/boot-candidate/*/manifest.json")))
        if not manifests:
            raise FileNotFoundError("No boot candidate manifest found")
        manifest_path = Path(manifests[-1])
    else:
        manifest_path = args.manifest.resolve()

    print(f"Loading manifest: {manifest_path.relative_to(PROJECT)}")
    manifest = json.loads(manifest_path.read_text())

    # 1. Rollback Pins
    print("[1/5] Checking 4 rollback baseline pins...")
    template_path = WORKSPACE / manifest["rollback_pins"]["template"]["path"]
    orig_boot_path = WORKSPACE / manifest["rollback_pins"]["original_pixelos_boot"]["path"]
    recovery_path = WORKSPACE / manifest["rollback_pins"]["twrp_recovery"]["path"]
    dtbo_path = WORKSPACE / manifest["rollback_pins"]["original_dtbo"]["path"]

    check(digest(template_path.read_bytes()) == EXPECTED_PINS["template"][1], "template pin mismatch")
    check(digest(orig_boot_path.read_bytes()) == EXPECTED_PINS["original_boot"][1], "original boot pin mismatch")
    check(digest(recovery_path.read_bytes()) == EXPECTED_PINS["recovery"][1], "recovery pin mismatch")
    check(digest(dtbo_path.read_bytes()) == EXPECTED_PINS["dtbo"][1], "dtbo pin mismatch")
    print("  All 4 baseline rollback images match pinned identities.")

    # 2. Candidate Boot Image Check
    print("[2/5] Checking candidate boot.img structure and geometry...")
    cand_info = manifest["candidate_image"]
    cand_path = PROJECT / cand_info["path"]
    check(cand_path.is_file(), f"Candidate image not found: {cand_path}")

    cand_bytes = cand_path.read_bytes()
    check(len(cand_bytes) == cand_info["bytes"] == 61_865_984, "Candidate length != 61865984")
    check(digest(cand_bytes) == cand_info["sha256"], "Candidate sha256 mismatch")

    boot = parse_boot(cand_bytes)
    check(boot["header_version"] == 2, "Android header version != 2")
    check(boot["page_size"] == 2048, "Page size != 2048")
    check(boot["kernel_size"] == 36_334_080, "Kernel size != 36334080")
    check(boot["kernel_addr"] == 0x10008000, "Kernel load addr != 0x10008000")
    check(cand_bytes[576:596] == android_boot_id(cand_bytes, boot), "Android boot ID mismatch")
    print(f"  Valid Android boot v2 header: kernel_size={boot['kernel_size']}, page_size={boot['page_size']}")

    # 3. Embedded Kernel / Trampoline Image Check
    print("[3/5] Checking embedded ARM64 Image header and trampoline...")
    kernel_slot = boot["sections"]["kernel"]
    kernel_bytes = cand_bytes[kernel_slot["offset"] : kernel_slot["offset"] + boot["kernel_size"]]
    arm64 = parse_arm64_image(kernel_bytes)
    check(arm64["endianness"] == "little", "ARM64 endianness != little")
    check(arm64["page_size"] == 4096, "ARM64 page_size != 4096")
    check(arm64["text_offset"] == 524288, "ARM64 text_offset != 524288")
    check(arm64["code0"] == "0x14000011", "Entry branch instruction != 0x14000011")
    print(f"  Valid ARM64 Image header: text_offset={arm64['text_offset']}, page_size={arm64['page_size']}")

    # 4. AVB Integrity Check
    print("[4/5] Checking AVB footer and vbmeta boot descriptor...")
    avb = parse_avb(cand_bytes)
    check(avb["boot_hash_matches"], "AVB boot hash does not match candidate kernel slot")
    check(avb["flags"] == 0, "AVB flags != 0")
    check(avb["algorithm_type"] == 0, "AVB algorithm_type != 0")
    check(boot["payload_end"] == avb["original_image_size"], "AVB original_image_size mismatch")
    print("  AVB signature descriptor matches recomputed boot hash.")

    # 5. Odin Archive Integrity
    print("[5/5] Checking Odin .tar archive structure...")
    tar_info = manifest["odin_archive"]
    tar_path = PROJECT / tar_info["path"]
    check(tar_path.is_file(), f"Tar archive not found: {tar_path}")

    tar_bytes = tar_path.read_bytes()
    check(len(tar_bytes) == tar_info["bytes"] == 61_870_080, "Tar archive size != 61870080")
    check(digest(tar_bytes) == tar_info["sha256"], "Tar archive sha256 mismatch")

    with tarfile.open(tar_path, "r") as tar:
        members = tar.getmembers()
        check(len(members) == 1, f"Tar archive has {len(members)} members, expected 1")
        check(members[0].name == "boot.img", f"Tar member is {members[0].name}, expected boot.img")
        check(members[0].size == 61_865_984, f"Tar member size {members[0].size} != 61865984")
        extracted = tar.extractfile(members[0]).read()
        check(extracted == cand_bytes, "Extracted boot.img from tar differs from standalone .img")
    print(f"  Valid Odin tar archive containing byte-identical boot.img ({len(cand_bytes)} bytes)")

    print("\n[PASS] All Phase 3 XNU Boot Candidate Verification Checks Passed 100%.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
