#!/usr/bin/env python3
"""Build and package the complete Phase 3 XNU boot candidate for Samsung Galaxy A51."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import uuid

PROJECT = Path(__file__).resolve().parents[1]
WORKSPACE = PROJECT.parent
SCRIPTS = PROJECT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from samsung_boot_dry_run import DryRunError, reconstruct_in_memory

TEMPLATE = WORKSPACE / "everline-ksu/artifacts/A51-PixelOS-Everline-KernelSU-Next-boot.img"
ORIGINAL_BOOT = WORKSPACE / "everline-ksu/backups/a51-pixelos-original-boot.img"
RECOVERY = WORKSPACE / "everline-ksu/backups/a51-twrp-original-recovery.img"
DTBO = WORKSPACE / "everline-ksu/backups/a51-pixelos-original-dtbo.img"

EXPECTED_PINS = {
    "template": (61_865_984, "eb30609a62999e3282ac81e0a5e56411ef12ec1a39c107171bf3e01209c7cb67"),
    "original_boot": (61_865_984, "89600eb7f3bb73a26d6d8b38aa46c7cb27a5b942da84e0a3c77626ea21642e52"),
    "recovery": (71_106_560, "12412e2008d950260cda627ac7a6b8eac954b49ef9db5573a297f67e4fc85999"),
    "dtbo": (8_388_608, "41662c61ff3158448935025477a4e29d445823dab2cddafb18ea649c8ea925d6"),
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pinned(path: Path, role: str) -> bytes:
    if not path.is_file():
        raise FileNotFoundError(f"Missing required pin: {path}")
    data = path.read_bytes()
    size, sha256 = EXPECTED_PINS[role]
    if len(data) != size or digest(data) != sha256:
        raise DryRunError(f"{role} differs from its retained pin: len={len(data)}, sha256={digest(data)}")
    return data


def write_exclusive(path: Path, data: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=int, default=0, help="XNU boot checkpoint (0 = full boot to userland)")
    parser.add_argument("--cmdline", default=None, help="Kernel command line")
    parser.add_argument("--skip-loader-build", action="store_true", help="Skip building loader bin if already built")
    args = parser.parse_args()

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    nonce = uuid.uuid4().hex
    if args.cmdline is None:
        cmdline = f"rd=md0 -v cpus=1 serial=3 debug=0x8 hello_wait=3 loader_return_after=20 hakios_run_nonce={nonce} hakios_kver=p3-a53-gicv2"
    else:
        cmdline = args.cmdline

    # 1. Verify all 4 rollback pins
    print("[1/5] Verifying baseline rollback image pins...")
    template_bytes = pinned(TEMPLATE, "template")
    original_boot_bytes = pinned(ORIGINAL_BOOT, "original_boot")
    recovery_bytes = pinned(RECOVERY, "recovery")
    dtbo_bytes = pinned(DTBO, "dtbo")
    print("  All 4 rollback pins match verified hashes.")

    # 2. Build or locate a51_xnu_loader.bin
    loader_bin = Path("//wsl.localhost/A51-KernelBuilder/opt/a51-hakios/experimental/a51-xnu-loader/a51_xnu_loader.bin")
    if not args.skip_loader_build or not loader_bin.is_file():
        print(f"[2/5] Building freestanding XNU loader binary (checkpoint={args.checkpoint})...")
        cmd = [
            "wsl", "-d", "A51-KernelBuilder",
            "python3", "/mnt/c/Users/Ankit/Desktop/A51/hakios-a51/prototype/xnu-loader/pack_a51_payload.py",
            "--kernel", "/opt/a51-hakios/experimental/phase3-port/20261114T013656044425Z/hakios-kernel",
            "--hello", "/opt/a51-hakios/experimental/phase3-port/20261114T013656044425Z/userland/hello",
            "--output", "/opt/a51-hakios/experimental/a51-xnu-loader/a51_xnu_loader.bin",
            "--checkpoint", str(args.checkpoint),
            "--cmdline", cmdline,
            "--pad-to", "36334080"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            print("STDERR:", res.stderr)
            raise RuntimeError(f"pack_a51_payload.py failed with exit code {res.returncode}")
        print(" ", res.stdout.strip())

    loader_bytes = loader_bin.read_bytes()
    if len(loader_bytes) != 36_334_080:
        raise ValueError(f"a51_xnu_loader.bin has unexpected size: {len(loader_bytes)} (expected 36334080)")
    loader_sha256 = digest(loader_bytes)
    print(f"  Loader Image: {len(loader_bytes)} bytes, SHA-256: {loader_sha256}")

    # 3. Reconstruct boot candidate in memory
    print("[3/5] Reconstructing Android boot v2 container in memory...")
    candidate_bytes, reconstruction = reconstruct_in_memory(template_bytes, loader_bytes)
    if len(candidate_bytes) != 61_865_984:
        raise DryRunError(f"Candidate size is {len(candidate_bytes)}, expected 61865984")

    names = [item["name"] for item in reconstruction["changed_regions"]]
    expected_names = ["header.kernel_size", "header.id", "kernel.slot", "avb.boot_digest"]
    if names != expected_names:
        raise DryRunError(f"Candidate changed regions mismatch: {names} != {expected_names}")

    candidate_sha256 = digest(candidate_bytes)
    print(f"  Candidate boot image: {len(candidate_bytes)} bytes, SHA-256: {candidate_sha256}")

    # 4. Emit boot image and Odin .tar archive
    print("[4/5] Staging boot candidate and Odin archive...")
    artifacts_dir = PROJECT / "artifacts/phase-3/samsung-boot-candidate" / stamp
    artifacts_dir.mkdir(parents=True, exist_ok=False)

    image_path = artifacts_dir / "A51-HakiOS-P3-005-XNU-boot.img"
    write_exclusive(image_path, candidate_bytes)

    tar_path = artifacts_dir / "A51-HakiOS-P3-005-XNU-boot.tar"
    with tarfile.open(tar_path, "w") as tar:
        ti = tarfile.TarInfo("boot.img")
        ti.size = len(candidate_bytes)
        ti.mtime = int(dt.datetime.now(dt.timezone.utc).timestamp())
        ti.mode = 0o644
        ti.type = tarfile.REGTYPE
        import io
        tar.addfile(ti, io.BytesIO(candidate_bytes))

    tar_bytes = tar_path.read_bytes()
    tar_sha256 = digest(tar_bytes)
    print(f"  Wrote {image_path.name} ({len(candidate_bytes)} bytes)")
    print(f"  Wrote {tar_path.name} ({len(tar_bytes)} bytes, SHA-256: {tar_sha256})")

    # 5. Record evidence and manifest
    print("[5/5] Generating Phase 3 boot candidate manifest and evidence...")
    evidence_dir = PROJECT / "evidence/phase-3/boot-candidate" / stamp
    evidence_dir.mkdir(parents=True, exist_ok=False)

    manifest = {
        "schema_version": 1,
        "phase": 3,
        "milestone": "P3-005",
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "status": "built_host_only_not_installed",
        "checkpoint": args.checkpoint,
        "cmdline": cmdline,
        "nonce": nonce,
        "candidate_image": {
            "file": image_path.name,
            "path": image_path.relative_to(PROJECT).as_posix(),
            "bytes": len(candidate_bytes),
            "sha256": candidate_sha256,
            "android_boot_id_sha1": reconstruction["candidate"]["android_boot_id_sha1"],
            "changed_regions": reconstruction["changed_regions"],
        },
        "odin_archive": {
            "file": tar_path.name,
            "path": tar_path.relative_to(PROJECT).as_posix(),
            "bytes": len(tar_bytes),
            "sha256": tar_sha256,
            "member": "boot.img",
        },
        "loader_kernel": {
            "bytes": len(loader_bytes),
            "sha256": loader_sha256,
            "entry_pa": "0x8341a4a8",
            "boot_args_pa": "0x80200000",
            "device_tree_pa": "0x80210000",
            "ramdisk_pa": "0x841c0000",
            "stub_slot_pa": "0x8341b7f0",
        },
        "rollback_pins": {
            "template": {"path": TEMPLATE.relative_to(WORKSPACE).as_posix(), "bytes": len(template_bytes), "sha256": digest(template_bytes)},
            "original_pixelos_boot": {"path": ORIGINAL_BOOT.relative_to(WORKSPACE).as_posix(), "bytes": len(original_boot_bytes), "sha256": digest(original_boot_bytes)},
            "twrp_recovery": {"path": RECOVERY.relative_to(WORKSPACE).as_posix(), "bytes": len(recovery_bytes), "sha256": digest(recovery_bytes)},
            "original_dtbo": {"path": DTBO.relative_to(WORKSPACE).as_posix(), "bytes": len(dtbo_bytes), "sha256": digest(dtbo_bytes)},
        },
        "safety_checks": {
            "phone_queries": False,
            "phone_writes": False,
            "reboot": False,
            "flashing": False,
            "repartitioning": False,
            "baseline_preserved": True,
        }
    }

    manifest_path = evidence_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"  Wrote evidence manifest to {manifest_path.relative_to(PROJECT)}")
    print(f"\n[PASS] Milestone P3-005 Boot Candidate Generation Complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

