#!/usr/bin/env python3
"""Build and package Samsung boot candidate from a specified kernel image."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import tarfile

from samsung_boot_dry_run import DryRunError, reconstruct_in_memory


PROJECT = Path(__file__).resolve().parents[1]
WORKSPACE = PROJECT.parent
TEMPLATE = WORKSPACE / "everline-ksu/artifacts/A51-PixelOS-Everline-KernelSU-Next-boot.img"
ORIGINAL_BOOT = WORKSPACE / "everline-ksu/backups/a51-pixelos-original-boot.img"
RECOVERY = WORKSPACE / "everline-ksu/backups/a51-twrp-original-recovery.img"
DTBO = WORKSPACE / "everline-ksu/backups/a51-pixelos-original-dtbo.img"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_exclusive(path: Path, data: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def main() -> int:
    parser = argparse.ArgumentParser(description="Package Samsung boot candidate")
    parser.add_argument("--kernel", type=Path, required=True, help="Path to built kernel Image")
    args = parser.parse_args()

    kernel_path = args.kernel.resolve()
    if not kernel_path.is_file():
        raise FileNotFoundError(f"Kernel Image not found: {kernel_path}")

    template_bytes = TEMPLATE.read_bytes()
    kernel_bytes = kernel_path.read_bytes()
    original_boot_bytes = ORIGINAL_BOOT.read_bytes()
    recovery_bytes = RECOVERY.read_bytes()
    dtbo_bytes = DTBO.read_bytes()

    candidate, reconstruction = reconstruct_in_memory(template_bytes, kernel_bytes)
    names = [item["name"] for item in reconstruction["changed_regions"]]
    if names != ["header.kernel_size", "header.id", "kernel.slot", "avb.boot_digest"]:
        raise DryRunError(f"Unexpected changed regions: {names}")

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = PROJECT / "artifacts/phase-2/samsung-boot-candidate" / stamp
    folder.mkdir(parents=True, exist_ok=False)

    image_name = "A51-HakiOS-Early-Entry-boot.img"
    image_path = folder / image_name
    write_exclusive(image_path, candidate)

    # Also build Odin-flashable tarball containing boot.img
    tar_name = "boot.tar"
    tar_path = folder / tar_name
    with tarfile.open(tar_path, "w") as tar:
        ti = tarfile.TarInfo("boot.img")
        ti.size = len(candidate)
        ti.mtime = int(dt.datetime.now(dt.timezone.utc).timestamp())
        import io
        tar.addfile(ti, io.BytesIO(candidate))

    tar_bytes = tar_path.read_bytes()

    sources = {}
    for name in ("samsung_boot_dry_run.py", "package-boot-candidate.py"):
        source = PROJECT / "scripts" / name
        raw = source.read_bytes()
        sources[name] = {"bytes": len(raw), "sha256": digest(raw)}

    manifest = {
        "schema_version": 1,
        "milestone": "P2-022-COMPLETION",
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "status": "built_host_only_not_installed",
        "candidate": {
            "path": image_path.relative_to(PROJECT).as_posix(),
            "bytes": len(candidate),
            "sha256": digest(candidate),
            "changed_regions": reconstruction["changed_regions"],
            "android_boot_id_sha1": reconstruction["candidate"]["android_boot_id_sha1"],
        },
        "tar": {
            "path": tar_path.relative_to(PROJECT).as_posix(),
            "bytes": len(tar_bytes),
            "sha256": digest(tar_bytes),
        },
        "inputs": {
            "template": {"path": TEMPLATE.relative_to(WORKSPACE).as_posix(), "bytes": len(template_bytes), "sha256": digest(template_bytes)},
            "kernel": {"path": kernel_path.relative_to(PROJECT).as_posix(), "bytes": len(kernel_bytes), "sha256": digest(kernel_bytes)},
        },
        "rollback": {
            "current_kernel_boot": {"path": TEMPLATE.relative_to(WORKSPACE).as_posix(), "bytes": len(template_bytes), "sha256": digest(template_bytes)},
            "original_pixelos_boot": {"path": ORIGINAL_BOOT.relative_to(WORKSPACE).as_posix(), "bytes": len(original_boot_bytes), "sha256": digest(original_boot_bytes)},
            "twrp_recovery": {"path": RECOVERY.relative_to(WORKSPACE).as_posix(), "bytes": len(recovery_bytes), "sha256": digest(recovery_bytes)},
            "original_dtbo": {"path": DTBO.relative_to(WORKSPACE).as_posix(), "bytes": len(dtbo_bytes), "sha256": digest(dtbo_bytes)},
        },
        "sources": sources,
        "operations": {"phone_queries": False, "phone_writes": False, "reboot": False, "flashing": False, "repartitioning": False},
        "gates": {"phase_2_device_gate_passed": False},
    }

    manifest_path = folder / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "status": "success",
        "folder": folder.relative_to(PROJECT).as_posix(),
        "candidate_img": image_path.relative_to(PROJECT).as_posix(),
        "bytes": len(candidate),
        "sha256": digest(candidate),
        "tar_bytes": len(tar_bytes),
        "tar_sha256": digest(tar_bytes),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

