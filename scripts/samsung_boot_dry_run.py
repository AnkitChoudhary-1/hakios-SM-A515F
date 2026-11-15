#!/usr/bin/env python3
"""Strict, non-emitting reconstruction of the retained A51 boot image.

The candidate exists only as an in-process byte array.  This module has no
file-writing or device interface and deliberately supports only the exact
Android boot v2 / unsigned AVB shape retained for this A51.
"""
from __future__ import annotations

import hashlib
import struct
from typing import Any

from boot_formats import FormatError, aligned, parse_arm64_image, parse_boot


class DryRunError(ValueError):
    """The retained input or proposed reconstruction violates the contract."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise DryRunError(message)


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def _span(data: bytes | bytearray, offset: int, size: int, label: str) -> bytes:
    require(type(offset) is int and type(size) is int and offset >= 0 and size >= 0,
            label + ": invalid span")
    require(offset + size <= len(data), label + ": outside input bounds")
    return bytes(data[offset:offset + size])


def _text(raw: bytes, label: str) -> str:
    try:
        return raw.rstrip(b"\0").decode("ascii")
    except UnicodeDecodeError as exc:
        raise DryRunError(label + ": non-ASCII text") from exc


def parse_avb(image: bytes | bytearray) -> dict[str, Any]:
    require(len(image) >= 320, "AVB: image is too small")
    footer_offset = len(image) - 64
    footer = _span(image, footer_offset, 64, "AVB footer")
    require(footer[:4] == b"AVBf", "AVB: missing footer magic")
    major, minor, original_size, vbmeta_offset, vbmeta_size = struct.unpack_from(
        ">IIQQQ", footer, 4)
    require(major == 1 and minor == 0, "AVB: unsupported footer version")
    require(0 < original_size <= vbmeta_offset < vbmeta_offset + vbmeta_size <= footer_offset,
            "AVB: invalid original-image/vbmeta bounds")
    vbmeta = _span(image, vbmeta_offset, vbmeta_size, "AVB vbmeta")
    require(vbmeta[:4] == b"AVB0" and len(vbmeta) >= 256,
            "AVB: missing or truncated vbmeta header")
    required_major, required_minor = struct.unpack_from(">II", vbmeta, 4)
    auth_size, auxiliary_size = struct.unpack_from(">QQ", vbmeta, 12)
    algorithm_type = struct.unpack_from(">I", vbmeta, 28)[0]
    descriptors_offset, descriptors_size = struct.unpack_from(">QQ", vbmeta, 96)
    flags = struct.unpack_from(">I", vbmeta, 120)[0]
    require(256 + auth_size + auxiliary_size == len(vbmeta),
            "AVB: authentication/auxiliary sizes do not cover vbmeta")
    require(descriptors_offset + descriptors_size <= auxiliary_size,
            "AVB: descriptor block exceeds auxiliary data")
    descriptors_start = 256 + auth_size + descriptors_offset
    descriptors_end = descriptors_start + descriptors_size
    require(descriptors_end <= len(vbmeta), "AVB: descriptor block is truncated")
    position = descriptors_start
    hashes: list[dict[str, Any]] = []
    descriptor_count = 0
    while position < descriptors_end:
        require(position + 16 <= descriptors_end, "AVB: truncated descriptor header")
        tag, following = struct.unpack_from(">QQ", vbmeta, position)
        total = 16 + following
        require(following % 8 == 0 and position + total <= descriptors_end,
                "AVB: invalid descriptor extent")
        descriptor_count += 1
        if tag == 2:
            require(total >= 132, "AVB: truncated hash descriptor")
            image_size = struct.unpack_from(">Q", vbmeta, position + 16)[0]
            algorithm = _text(vbmeta[position + 24:position + 56], "AVB hash algorithm")
            name_size, salt_size, digest_size, descriptor_flags = struct.unpack_from(
                ">IIII", vbmeta, position + 56)
            content = position + 132
            end = content + name_size + salt_size + digest_size
            require(end <= position + total, "AVB: hash descriptor payload is truncated")
            name = _text(vbmeta[content:content + name_size], "AVB partition name")
            salt_start = content + name_size
            digest_start = salt_start + salt_size
            hashes.append({
                "name": name,
                "algorithm": algorithm,
                "image_size": image_size,
                "flags": descriptor_flags,
                "salt": bytes(vbmeta[salt_start:digest_start]),
                "digest": bytes(vbmeta[digest_start:digest_start + digest_size]),
                "image_size_offset": vbmeta_offset + position + 16,
                "digest_offset": vbmeta_offset + digest_start,
                "digest_size": digest_size,
            })
        position += total
    require(position == descriptors_end and descriptor_count > 0,
            "AVB: descriptor walk did not end exactly")
    boot = [item for item in hashes if item["name"] == "boot"]
    require(len(boot) == 1, "AVB: exactly one boot hash descriptor is required")
    descriptor = boot[0]
    require(descriptor["image_size"] == original_size,
            "AVB: boot hash size differs from footer original image size")
    require(descriptor["algorithm"] in hashlib.algorithms_available,
            "AVB: unsupported hash algorithm")
    expected = hashlib.new(descriptor["algorithm"],
                           descriptor["salt"] + bytes(image[:original_size])).digest()
    require(len(expected) == descriptor["digest_size"], "AVB: digest length mismatch")
    return {
        "footer_offset": footer_offset,
        "footer_version": [major, minor],
        "required_libavb_version": [required_major, required_minor],
        "original_image_size": original_size,
        "vbmeta_offset": vbmeta_offset,
        "vbmeta_size": vbmeta_size,
        "authentication_data_bytes": auth_size,
        "auxiliary_data_bytes": auxiliary_size,
        "algorithm_type": algorithm_type,
        "flags": flags,
        "descriptor_count": descriptor_count,
        "boot_descriptor": descriptor,
        "boot_hash_matches": expected == descriptor["digest"],
    }


def android_boot_id(image: bytes | bytearray, boot: dict[str, Any] | None = None) -> bytes:
    """Return the Android v2 legacy SHA-1 identifier for retained sections."""
    boot = parse_boot(bytes(image)) if boot is None else boot
    digest = hashlib.sha1()
    # AOSP's v2 identifier includes the zero-length second/recovery sections
    # as four-byte length words.  The retained image pins this exact formula.
    names = ["kernel", "ramdisk", "second"]
    if boot["header_version"] >= 1:
        names.append("recovery_dtbo")
    if boot["header_version"] >= 2:
        names.append("dtb")
    for name in names:
        section = boot["sections"][name]
        digest.update(_span(image, section["offset"], section["size"], name))
        digest.update(struct.pack("<I", section["size"]))
    return digest.digest()


def _region(image: bytes | bytearray, name: str, offset: int, size: int) -> dict[str, Any]:
    return {"name": name, "offset": offset, "bytes": size,
            "sha256": sha256(_span(image, offset, size, name))}


def _assert_only_regions_changed(before: bytes, after: bytes,
                                 regions: list[tuple[str, int, int]]) -> None:
    require(len(before) == len(after), "reconstruction changed partition byte length")
    ordered = sorted(regions, key=lambda item: item[1])
    cursor = 0
    for name, offset, size in ordered:
        require(offset >= cursor and size > 0 and offset + size <= len(before),
                "invalid or overlapping allowed region: " + name)
        require(before[cursor:offset] == after[cursor:offset],
                "bytes changed outside allowed region before " + name)
        cursor = offset + size
    require(before[cursor:] == after[cursor:], "bytes changed after final allowed region")


def reconstruct_in_memory(template: bytes, kernel: bytes) -> tuple[bytes, dict[str, Any]]:
    """Reconstruct and return bytes for tests; callers must not persist them."""
    require(type(template) is bytes and type(kernel) is bytes,
            "template and kernel must be immutable bytes")
    try:
        boot = parse_boot(template)
        arm64 = parse_arm64_image(kernel)
    except FormatError as exc:
        raise DryRunError(str(exc)) from exc
    avb = parse_avb(template)
    require(avb["boot_hash_matches"], "template AVB boot hash is stale")
    require(avb["authentication_data_bytes"] == 0 and avb["algorithm_type"] == 0,
            "signed/authenticated AVB is unsupported without its signing key")
    require(avb["flags"] == 0, "AVB verification-disabled flags are not accepted")
    require(boot["payload_end"] == avb["original_image_size"],
            "boot payload end differs from AVB original image size")
    require(template[576:596] == android_boot_id(template, boot)
            and template[596:608] == b"\0" * 12,
            "template Android boot identifier is stale or malformed")
    require(arm64["endianness"] == "little" and arm64["page_size"] == 4096,
            "candidate ARM64 Image flags differ from the retained kernel contract")
    require(len(kernel) <= arm64["image_size"],
            "candidate stored Image exceeds its declared runtime extent")

    old_kernel = boot["sections"]["kernel"]
    old_aligned = old_kernel["padded_end"] - old_kernel["offset"]
    new_aligned = aligned(len(kernel), boot["page_size"])
    require(new_aligned == old_aligned,
            "candidate crosses the retained kernel slot; moving later sections is forbidden")
    old_padding = template[old_kernel["offset"] + old_kernel["size"]:old_kernel["padded_end"]]
    require(old_padding == b"\0" * len(old_padding), "template kernel padding is not zero")

    candidate = bytearray(template)
    struct.pack_into("<I", candidate, 8, len(kernel))
    candidate[old_kernel["offset"]:old_kernel["padded_end"]] = b"\0" * old_aligned
    candidate[old_kernel["offset"]:old_kernel["offset"] + len(kernel)] = kernel
    try:
        candidate_boot = parse_boot(bytes(candidate))
    except FormatError as exc:
        raise DryRunError(str(exc)) from exc
    require(candidate_boot["payload_end"] == boot["payload_end"],
            "candidate moves the AVB boundary")
    for name in ("ramdisk", "second", "recovery_dtbo", "dtb"):
        require(candidate_boot["sections"][name] == boot["sections"][name],
                "candidate moves or changes the " + name + " section")

    candidate[576:608] = android_boot_id(candidate, candidate_boot) + b"\0" * 12
    stale_avb = parse_avb(candidate)
    descriptor = stale_avb["boot_descriptor"]
    require(descriptor["algorithm"] == "sha256" and descriptor["digest_size"] == 32,
            "only the retained SHA-256 AVB boot descriptor is supported")
    digest = hashlib.sha256(descriptor["salt"] +
                            bytes(candidate[:stale_avb["original_image_size"]])).digest()
    digest_offset = descriptor["digest_offset"]
    candidate[digest_offset:digest_offset + len(digest)] = digest
    final_avb = parse_avb(candidate)
    require(final_avb["boot_hash_matches"], "rebuilt in-memory AVB hash does not verify")

    allowed = [
        ("header.kernel_size", 8, 4),
        ("header.id", 576, 32),
        ("kernel.slot", old_kernel["offset"], old_aligned),
        ("avb.boot_digest", digest_offset, len(digest)),
    ]
    _assert_only_regions_changed(template, bytes(candidate), allowed)
    changes = []
    for name, offset, size in allowed:
        before = _region(template, name, offset, size)
        after = _region(candidate, name, offset, size)
        if before["sha256"] != after["sha256"]:
            changes.append({"name": name, "offset": offset, "bytes": size,
                            "before_sha256": before["sha256"], "after_sha256": after["sha256"]})

    report = {
        "schema_version": 1,
        "status": "verified_host_only",
        "scope": "retained_a51_android_v2_unsigned_avb_in_memory_reconstruction",
        "template": {"bytes": len(template), "sha256": sha256(template)},
        "kernel": {"bytes": len(kernel), "sha256": sha256(kernel),
                   "runtime_bytes": arm64["image_size"], "header": arm64},
        "layout": {
            "page_size": boot["page_size"],
            "kernel_offset": old_kernel["offset"],
            "old_kernel_bytes": old_kernel["size"],
            "new_kernel_bytes": len(kernel),
            "kernel_slot_bytes": old_aligned,
            "old_kernel_padding_bytes": old_aligned - old_kernel["size"],
            "new_kernel_padding_bytes": old_aligned - len(kernel),
            "ramdisk_offset": boot["sections"]["ramdisk"]["offset"],
            "dtb_offset": boot["sections"]["dtb"]["offset"],
            "payload_end": boot["payload_end"],
            "partition_bytes": len(template),
            "later_section_offsets_unchanged": True,
        },
        "avb": {
            "footer_version": final_avb["footer_version"],
            "required_libavb_version": final_avb["required_libavb_version"],
            "original_image_size": final_avb["original_image_size"],
            "vbmeta_offset": final_avb["vbmeta_offset"],
            "vbmeta_size": final_avb["vbmeta_size"],
            "algorithm_type": final_avb["algorithm_type"],
            "flags": final_avb["flags"],
            "authentication_data_bytes": final_avb["authentication_data_bytes"],
            "hash_algorithm": final_avb["boot_descriptor"]["algorithm"],
            "boot_hash_matches": final_avb["boot_hash_matches"],
        },
        "candidate": {"bytes": len(candidate), "sha256": sha256(candidate),
                      "android_boot_id_sha1": bytes(candidate[576:596]).hex()},
        "changed_regions": changes,
        "invariants": {
            "ramdisk_sha256": candidate_boot["sections"]["ramdisk"]["sha256"],
            "second_sha256": candidate_boot["sections"]["second"]["sha256"],
            "recovery_dtbo_sha256": candidate_boot["sections"]["recovery_dtbo"]["sha256"],
            "dtb_sha256": candidate_boot["sections"]["dtb"]["sha256"],
            "full_partition_length_unchanged": True,
            "bytes_outside_declared_regions_unchanged": True,
        },
        "outputs": {"full_image_emitted": False, "candidate_bytes_retained": False,
                    "installable_image_created": False},
        "operations": {"phone_queries": False, "phone_writes": False,
                       "flashing": False, "repartitioning": False, "reboot": False},
        "gates": {"a51_payload_execution_verified": False,
                  "standalone_execution_verified": False,
                  "persistent_fault_logging_verified": False,
                  "a51_return_verified": False,
                  "phase_2_device_gate_passed": False},
        "limits": [
            "The reconstruction is an in-memory host calculation; no boot image is emitted.",
            "The retained AVB metadata is unsigned (algorithm type 0); this does not establish the phone's complete verified-boot policy.",
            "This validates retained boot-partition byte layout, not Odin packaging, Samsung firmware entry, phone execution, fault recovery, or return.",
        ],
    }
    return bytes(candidate), report


def generate_report(template: bytes, kernel: bytes) -> dict[str, Any]:
    """Generate a report while ensuring candidate bytes are not returned."""
    _candidate, report = reconstruct_in_memory(template, kernel)
    del _candidate
    return report
