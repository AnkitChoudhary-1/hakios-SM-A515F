#!/usr/bin/env python3
"""Retain a non-installable P2-019 Samsung boot reconstruction report."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
import shutil
import sys

from samsung_boot_dry_run import DryRunError, generate_report


PROJECT = Path(__file__).resolve().parents[1]
WORKSPACE = PROJECT.parent
TEMPLATE = WORKSPACE / "everline-ksu/artifacts/A51-PixelOS-Everline-KernelSU-Next-boot.img"
KERNEL = PROJECT / "evidence/phase-2/early-entry-kernel/20261111T163522918342Z/Image"
REPACK = WORKSPACE / "everline-ksu/artifacts/repack-validation.json"
EXPECTED = {
    "template": (61_865_984, "eb30609a62999e3282ac81e0a5e56411ef12ec1a39c107171bf3e01209c7cb67"),
    "kernel": (36_334_080, "87c0401361d4503afb0b266b15ff0caf1e64f505d61d53be700e8b6c6d8e9cf6"),
    "repack": (1_911, "2ced1959920eb5a1daf1343c89b36c40caf1a3d7d419a73957385597c8e8712b"),
}
SOURCE_NAMES = ["samsung_boot_dry_run.py", "capture-samsung-boot-dry-run.py",
                "test-samsung-boot-dry-run.py", "test-samsung-boot-dry-run-evidence.py",
                "verify-samsung-boot-dry-run.py"]


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pinned(path: Path, role: str) -> bytes:
    data = path.read_bytes()
    expected_bytes, expected_hash = EXPECTED[role]
    if len(data) != expected_bytes or sha(data) != expected_hash:
        raise DryRunError(role + " input differs from its selected pin")
    return data


def main() -> int:
    try:
        template = pinned(TEMPLATE, "template")
        kernel = pinned(KERNEL, "kernel")
        repack_data = pinned(REPACK, "repack")
        repack = json.loads(repack_data)
        if (repack.get("new_boot_sha256") != EXPECTED["template"][1]
                or repack.get("new_boot_bytes") != EXPECTED["template"][0]
                or repack.get("kernel_file_bytes") != 36_333_584
                or repack.get("device_boot_tested") is not True
                or repack.get("installed_boot_readback_verified") is not True):
            raise DryRunError("prior Android repack record does not bind the retained template")
        report = generate_report(template, kernel)
        if [item["name"] for item in report["changed_regions"]] != [
                "header.kernel_size", "header.id", "kernel.slot", "avb.boot_digest"]:
            raise DryRunError("candidate did not change exactly the four expected regions")
        report["milestone"] = "P2-019"
        report["inputs"] = {
            "template": {"path": TEMPLATE.relative_to(WORKSPACE).as_posix(),
                         "bytes": len(template), "sha256": sha(template)},
            "kernel": {"path": KERNEL.relative_to(PROJECT).as_posix(),
                       "bytes": len(kernel), "sha256": sha(kernel)},
            "prior_repack_record": {"path": REPACK.relative_to(WORKSPACE).as_posix(),
                                    "bytes": len(repack_data), "sha256": sha(repack_data),
                                    "device_boot_tested_applies_only_to_prior_android_kernel": True},
        }
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        folder = PROJECT / "evidence/phase-2/samsung-boot-dry-run" / stamp
        folder.mkdir(parents=True, exist_ok=False)
        sources = folder / "sources"
        references = folder / "references"
        sources.mkdir()
        references.mkdir()
        for name in SOURCE_NAMES:
            shutil.copy2(PROJECT / "scripts" / name, sources / name)
        shutil.copy2(REPACK, references / "repack-validation.json")
        report_path = folder / "report.json"
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        files = {}
        for path in sorted(item for item in folder.rglob("*") if item.is_file()):
            relative = path.relative_to(folder).as_posix()
            data = path.read_bytes()
            if path.suffix.lower() == ".img":
                raise DryRunError("evidence unexpectedly contains an image file")
            files[relative] = {"bytes": len(data), "sha256": sha(data)}
        index = {"schema_version": 1, "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                 "files": files, "full_image_emitted": False,
                 "candidate_bytes_retained": False, "phone_writes": False,
                 "phase_2_device_gate_passed": False}
        (folder / "index.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": "passed", "evidence": folder.relative_to(PROJECT).as_posix(),
                          "candidate_sha256": report["candidate"]["sha256"],
                          "changed_regions": len(report["changed_regions"]),
                          "full_image_emitted": False, "phone_writes": False,
                          "phase_2_device_gate_passed": False}, sort_keys=True))
        return 0
    except (DryRunError, OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print("SAMSUNG_BOOT_DRY_RUN_REJECTED: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
