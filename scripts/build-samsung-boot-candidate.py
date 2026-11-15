#!/usr/bin/env python3
"""Build the exact P2-018 early-entry Android boot candidate for P2-020."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path

from samsung_boot_dry_run import DryRunError, reconstruct_in_memory


PROJECT = Path(__file__).resolve().parents[1]
WORKSPACE = PROJECT.parent
TEMPLATE = WORKSPACE / "everline-ksu/artifacts/A51-PixelOS-Everline-KernelSU-Next-boot.img"
KERNEL = PROJECT / "evidence/phase-2/early-entry-kernel/20261111T163522918342Z/Image"
ORIGINAL_BOOT = WORKSPACE / "everline-ksu/backups/a51-pixelos-original-boot.img"
RECOVERY = WORKSPACE / "everline-ksu/backups/a51-twrp-original-recovery.img"
DTBO = WORKSPACE / "everline-ksu/backups/a51-pixelos-original-dtbo.img"
EXPECTED = {
    "template": (61_865_984, "eb30609a62999e3282ac81e0a5e56411ef12ec1a39c107171bf3e01209c7cb67"),
    "kernel": (36_334_080, "87c0401361d4503afb0b266b15ff0caf1e64f505d61d53be700e8b6c6d8e9cf6"),
    "candidate": (61_865_984, "73d88c699dda238238b7b2b1105caea248b9ef3aef282a3f01b566f0fd894a58"),
    "original_boot": (61_865_984, "89600eb7f3bb73a26d6d8b38aa46c7cb27a5b942da84e0a3c77626ea21642e52"),
    "recovery": (71_106_560, "12412e2008d950260cda627ac7a6b8eac954b49ef9db5573a297f67e4fc85999"),
    "dtbo": (8_388_608, "41662c61ff3158448935025477a4e29d445823dab2cddafb18ea649c8ea925d6"),
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pinned(path: Path, role: str) -> bytes:
    data = path.read_bytes()
    size, sha256 = EXPECTED[role]
    if len(data) != size or digest(data) != sha256:
        raise DryRunError(f"{role} differs from its retained pin")
    return data


def write_exclusive(path: Path, data: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def main() -> int:
    try:
        template = pinned(TEMPLATE, "template")
        kernel = pinned(KERNEL, "kernel")
        original_boot = pinned(ORIGINAL_BOOT, "original_boot")
        recovery = pinned(RECOVERY, "recovery")
        dtbo = pinned(DTBO, "dtbo")
        candidate, reconstruction = reconstruct_in_memory(template, kernel)
        if (len(candidate), digest(candidate)) != EXPECTED["candidate"]:
            raise DryRunError("candidate identity differs from P2-019")
        names = [item["name"] for item in reconstruction["changed_regions"]]
        if names != ["header.kernel_size", "header.id", "kernel.slot", "avb.boot_digest"]:
            raise DryRunError("candidate changed-region contract differs")

        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        folder = PROJECT / "artifacts/phase-2/samsung-boot-candidate" / stamp
        folder.mkdir(parents=True, exist_ok=False)
        image = folder / "A51-HakiOS-P2-018-Early-Entry-boot.img"
        write_exclusive(image, candidate)
        if image.stat().st_size != EXPECTED["candidate"][0] or digest(image.read_bytes()) != EXPECTED["candidate"][1]:
            raise DryRunError("written candidate failed immediate readback")

        sources = {}
        for name in ("samsung_boot_dry_run.py", "build-samsung-boot-candidate.py"):
            source = PROJECT / "scripts" / name
            raw = source.read_bytes()
            sources[name] = {"bytes": len(raw), "sha256": digest(raw)}
        manifest = {
            "schema_version": 1,
            "milestone": "P2-020",
            "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "status": "built_host_only_not_installed",
            "candidate": {
                "path": image.relative_to(PROJECT).as_posix(),
                "bytes": len(candidate),
                "sha256": digest(candidate),
                "changed_regions": reconstruction["changed_regions"],
                "android_boot_id_sha1": reconstruction["candidate"]["android_boot_id_sha1"],
            },
            "inputs": {
                "template": {"path": TEMPLATE.relative_to(WORKSPACE).as_posix(), "bytes": len(template), "sha256": digest(template)},
                "kernel": {"path": KERNEL.relative_to(PROJECT).as_posix(), "bytes": len(kernel), "sha256": digest(kernel)},
            },
            "rollback": {
                "current_kernel_boot": {"path": TEMPLATE.relative_to(WORKSPACE).as_posix(), "bytes": len(template), "sha256": digest(template)},
                "original_pixelos_boot": {"path": ORIGINAL_BOOT.relative_to(WORKSPACE).as_posix(), "bytes": len(original_boot), "sha256": digest(original_boot)},
                "twrp_recovery": {"path": RECOVERY.relative_to(WORKSPACE).as_posix(), "bytes": len(recovery), "sha256": digest(recovery)},
                "original_dtbo": {"path": DTBO.relative_to(WORKSPACE).as_posix(), "bytes": len(dtbo), "sha256": digest(dtbo)},
            },
            "sources": sources,
            "operations": {"phone_queries": False, "phone_writes": False, "reboot": False, "flashing": False, "repartitioning": False},
            "gates": {"samsung_acceptance_verified": False, "a51_payload_execution_verified": False, "retrievable_logs_verified": False, "a51_return_verified": False, "phase_2_device_gate_passed": False},
            "limitations": [
                "Host-built raw boot-partition candidate only; no Odin archive.",
                "The candidate has not been installed, accepted or executed by Samsung firmware.",
                "Rollback inputs are pinned host files; recovery access must be demonstrated separately.",
            ],
        }
        manifest_path = folder / "manifest.json"
        write_exclusive(manifest_path, (json.dumps(manifest, indent=2) + "\n").encode("utf-8"))
        print(json.dumps({"status": "passed", "folder": folder.relative_to(PROJECT).as_posix(),
                          "image": image.relative_to(PROJECT).as_posix(),
                          "bytes": len(candidate), "sha256": digest(candidate),
                          "phone_writes": False, "phase_2_device_gate_passed": False}, sort_keys=True))
        return 0
    except Exception as exc:
        print("SAMSUNG_BOOT_CANDIDATE_BUILD_REJECTED: " + str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
