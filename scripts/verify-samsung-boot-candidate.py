#!/usr/bin/env python3
"""Read-only verifier for a P2-020 Samsung boot candidate folder."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile

from samsung_boot_dry_run import reconstruct_in_memory


PROJECT = Path(__file__).resolve().parents[1]
WORKSPACE = PROJECT.parent
TEMPLATE = WORKSPACE / "everline-ksu/artifacts/A51-PixelOS-Everline-KernelSU-Next-boot.img"
KERNEL = PROJECT / "evidence/phase-2/early-entry-kernel/20261111T163522918342Z/Image"
EXPECTED_SHA256 = "73d88c699dda238238b7b2b1105caea248b9ef3aef282a3f01b566f0fd894a58"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def main(argv: list[str]) -> int:
    try:
        require(len(argv) == 2, "usage: verify-samsung-boot-candidate.py FOLDER")
        folder = Path(argv[1]).resolve()
        require(folder.is_dir() and folder.parent.name == "samsung-boot-candidate", "unexpected candidate folder")
        manifest_path = folder / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        require(manifest.get("schema_version") == 1 and manifest.get("milestone") in ("P2-020", "P2-021"), "manifest identity differs")
        require(manifest.get("status") == "built_host_only_not_installed", "manifest status differs")
        candidate_record = manifest.get("candidate")
        require(type(candidate_record) is dict, "candidate record missing")
        image = PROJECT / candidate_record["path"]
        require(image.resolve().parent == folder and image.is_file(), "candidate path escapes folder")
        candidate = image.read_bytes()
        expected, reconstruction = reconstruct_in_memory(TEMPLATE.read_bytes(), KERNEL.read_bytes())
        require(candidate == expected, "candidate bytes differ from strict reconstruction")
        require(len(candidate) == 61_865_984 and sha(candidate) == EXPECTED_SHA256, "candidate identity differs")
        require(candidate_record["bytes"] == len(candidate) and candidate_record["sha256"] == sha(candidate), "manifest candidate pin differs")
        require(candidate_record["changed_regions"] == reconstruction["changed_regions"], "changed regions differ")
        
        tar_record = manifest.get("tar")
        if tar_record:
            require(type(tar_record) is dict, "tar record malformed")
            tar_path = PROJECT / tar_record["path"]
            require(tar_path.resolve().parent == folder and tar_path.is_file(), "tar path escapes folder")
            tar_bytes = tar_path.read_bytes()
            require(len(tar_bytes) == tar_record["bytes"] and sha(tar_bytes) == tar_record["sha256"], "tar pin differs")
            with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r") as tar:
                members = tar.getmembers()
                require(len(members) == 1, "tar must contain exactly 1 member")
                require(members[0].name == "boot.img", "tar member must be boot.img")
                extracted = tar.extractfile(members[0]).read()
                require(extracted == candidate, "tar member boot.img does not match candidate bytes")

        rollback = manifest.get("rollback", {})
        require(type(rollback) is dict, "rollback record missing")
        for key in ("current_kernel_boot", "original_pixelos_boot", "twrp_recovery", "original_dtbo"):
            require(key in rollback, f"rollback pin missing: {key}")
            rb_file = WORKSPACE / rollback[key]["path"]
            require(rb_file.is_file(), f"rollback file missing: {rb_file}")
            require(rb_file.stat().st_size == rollback[key]["bytes"], f"rollback size mismatch: {key}")
            require(sha(rb_file.read_bytes()) == rollback[key]["sha256"], f"rollback sha mismatch: {key}")

        require(manifest.get("operations") == {"phone_queries": False, "phone_writes": False, "reboot": False, "flashing": False, "repartitioning": False}, "operation flags differ")
        require(manifest.get("gates", {}).get("phase_2_device_gate_passed") is False, "device gate was promoted")
        result = {"status": "passed", "folder": folder.relative_to(PROJECT).as_posix(),
                  "image": image.relative_to(PROJECT).as_posix(), "bytes": len(candidate),
                  "sha256": sha(candidate), "changed_regions": len(reconstruction["changed_regions"]),
                  "has_tar": bool(tar_record), "rollback_pins_verified": len(rollback),
                  "phone_writes": False, "phase_2_device_gate_passed": False}
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        print("SAMSUNG_BOOT_CANDIDATE_REJECTED: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
