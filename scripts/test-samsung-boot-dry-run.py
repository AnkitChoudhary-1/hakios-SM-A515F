#!/usr/bin/env python3
"""Focused positive and corruption tests for the P2-019 dry run."""
from __future__ import annotations

import hashlib
from pathlib import Path
import struct
import sys

from samsung_boot_dry_run import DryRunError, generate_report, reconstruct_in_memory


PROJECT = Path(__file__).resolve().parents[1]
WORKSPACE = PROJECT.parent
TEMPLATE_PATH = WORKSPACE / "everline-ksu/artifacts/A51-PixelOS-Everline-KernelSU-Next-boot.img"
KERNEL_PATH = PROJECT / "evidence/phase-2/early-entry-kernel/20261111T163522918342Z/Image"


def reject(label: str, template: bytes, kernel: bytes) -> None:
    try:
        generate_report(template, kernel)
    except DryRunError:
        print("PASS rejected " + label)
        return
    raise AssertionError("accepted corruption: " + label)


def main() -> int:
    template = TEMPLATE_PATH.read_bytes()
    kernel = KERNEL_PATH.read_bytes()
    candidate, report = reconstruct_in_memory(template, kernel)
    assert report["template"]["sha256"] == hashlib.sha256(template).hexdigest()
    assert report["kernel"]["sha256"] == hashlib.sha256(kernel).hexdigest()
    assert report["layout"]["old_kernel_bytes"] == 36_333_584
    assert report["layout"]["new_kernel_bytes"] == 36_334_080
    assert report["layout"]["kernel_slot_bytes"] == 36_335_616
    assert report["layout"]["payload_end"] == 37_797_888
    assert report["layout"]["later_section_offsets_unchanged"] is True
    assert report["avb"]["boot_hash_matches"] is True
    assert len(candidate) == len(template) == 61_865_984
    assert hashlib.sha256(candidate).hexdigest() == report["candidate"]["sha256"]
    assert report["outputs"] == {"full_image_emitted": False,
                                  "candidate_bytes_retained": False,
                                  "installable_image_created": False}
    assert all(value is False for value in report["gates"].values())
    print("PASS retained_candidate")

    identity, identity_report = reconstruct_in_memory(template, template[2048:2048 + 36_333_584])
    assert identity == template
    assert identity_report["candidate"]["sha256"] == report["template"]["sha256"]
    print("PASS identity_reconstruction")

    corrupted = bytearray(template); corrupted[0] ^= 1
    reject("boot_magic", bytes(corrupted), kernel)
    corrupted = bytearray(template); struct.pack_into("<I", corrupted, 40, 1)
    reject("header_version", bytes(corrupted), kernel)
    corrupted = bytearray(template); corrupted[576] ^= 1
    reject("legacy_boot_id", bytes(corrupted), kernel)
    corrupted = bytearray(template); corrupted[-64] ^= 1
    reject("avb_footer", bytes(corrupted), kernel)
    corrupted = bytearray(template); corrupted[37_797_888 + 28:37_797_888 + 32] = (1).to_bytes(4, "big")
    reject("signed_avb_algorithm", bytes(corrupted), kernel)
    corrupted = bytearray(template); corrupted[37_797_888 + 120:37_797_888 + 124] = (2).to_bytes(4, "big")
    reject("verification_disabled", bytes(corrupted), kernel)
    corrupted = bytearray(template); corrupted[37_797_888 - 1] ^= 1
    reject("stale_avb_hash", bytes(corrupted), kernel)
    corrupted_kernel = bytearray(kernel); corrupted_kernel[56] ^= 1
    reject("arm64_magic", template, bytes(corrupted_kernel))
    reject("kernel_slot_growth", template, kernel + b"\0" * 2_048)

    print("SAMSUNG_BOOT_DRY_RUN_TESTS cases=11 result=PASS full_image_emitted=0 phone_writes=0 device_gate=0")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, OSError, ValueError, KeyError, TypeError) as exc:
        print("SAMSUNG_BOOT_DRY_RUN_TESTS result=FAIL " + str(exc), file=sys.stderr)
        raise SystemExit(1)
