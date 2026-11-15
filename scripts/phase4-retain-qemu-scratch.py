#!/usr/bin/env python3
"""Retain exact successful QEMU inputs/readbacks before releasing raw scratch."""
from __future__ import annotations
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from phase4_support import PROJECT, new_packet, pin, require, write_json, index_packet, documents

SCRATCH_ROOT = Path("/opt/a51-hakios/experimental/phase4-loader-qemu")
EVIDENCE_ROOT = PROJECT / "evidence/phase-4/complete-loader-qemu"
FILES = (("test.Image", "executed_image"), ("arena-prefill.bin", "prefill"),
         ("arena-after.bin", "destination_readback"))
MIN_FREE = 1024 * 1024 * 1024


def capacity():
    """Check both the sparse WSL filesystem and its actual Windows backing disk."""
    usages = {"evidence": shutil.disk_usage(PROJECT), "scratch": shutil.disk_usage(SCRATCH_ROOT.parent)}
    for name, usage in usages.items():
        require(usage.free >= MIN_FREE, f"Insufficient {name} capacity: {usage.free} bytes free; need {MIN_FREE}")
    return {name: usage._asdict() for name, usage in usages.items()}


def _archive_bytes(path, expected):
    with gzip.open(path, "rb") as stream:
        raw = stream.read(expected["bytes"] + 1)
    require({"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()} == expected,
            "Compressed evidence does not match original pin: " + str(path))
    return raw


def retain_case(packet, result, *, release=True):
    require(os.name != "nt", "Scratch retention must run in A51-KernelBuilder")
    packet = Path(packet)
    require(not packet.is_symlink() and packet.parent.resolve() == EVIDENCE_ROOT.resolve(), "Wrong case evidence root")
    require(result.get("passed") is True and result.get("packet") == packet.relative_to(PROJECT).as_posix(),
            "Only attributable successful cases may release scratch")
    work = Path(result["work"])
    require(SCRATCH_ROOT.resolve() == SCRATCH_ROOT, "Named scratch root must not redirect through a symlink")
    require(not work.is_symlink() and work.parent.resolve() == SCRATCH_ROOT.resolve() and work.name == packet.name,
            "Scratch path must be the exact isolated case directory")
    require(work.is_dir(), "Missing original scratch directory")
    # Never remove a file that a running QEMU could still be loading/using.
    for proc in Path("/proc").glob("[0-9]*/cmdline"):
        try:
            argv = proc.read_bytes().split(b"\0")
        except (OSError, ProcessLookupError):
            continue
        if argv and b"qemu-system-aarch64" in argv[0]:
            require(not any((str(work) + "/").encode() in arg for arg in argv), "Case QEMU is still running")
    rows = []
    for name, key in FILES:
        if key not in result:
            require(name == "arena-after.bin" and result["case"] == "full", "Missing original pin: " + key)
            continue
        expected = result[key]
        require(set(expected) == {"bytes", "sha256"} and 0 < expected["bytes"] <= 48 * 1024 * 1024,
                "Invalid scratch pin")
        rawpath, archive = work / name, packet / (name + ".gz")
        require(not rawpath.is_symlink() and not archive.is_symlink(), "Symlink in retained file path")
        raw = rawpath.read_bytes() if rawpath.exists() else None
        if raw is not None:
            require({"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()} == expected,
                    "Original scratch changed: " + str(rawpath))
        if not archive.exists():
            require(raw is not None, "Neither original nor archive exists: " + name)
            with archive.open("xb") as stream:
                stream.write(gzip.compress(raw, mtime=0))
                stream.flush()
                os.fsync(stream.fileno())
        retained = _archive_bytes(archive, expected)
        require(raw is None or retained == raw, "Archive is not byte-exact")
        with archive.open("rb") as stream:
            os.fsync(stream.fileno())
        rows.append({"raw_path": str(rawpath), "raw_pin": expected,
                     "archive": archive.relative_to(PROJECT).as_posix(), "archive_pin": pin(archive),
                     "exact_decompression_verified": True, "raw_already_absent": raw is None,
                     "raw_released": raw is None})
    receipt = {"schema_version": 1, "case_packet": result["packet"], "work": str(work),
               "release_requested": release, "files": rows, "complete": False,
               "device_operations": False, "phase_4_gate_passed": False}
    previous_path = packet / "scratch-retention.json"
    if previous_path.exists() and release and all(row["raw_already_absent"] for row in rows):
        previous = json.loads(previous_path.read_text(encoding="utf-8"))
        if previous.get("complete") and previous.get("release_requested") and all(
                row.get("raw_released") for row in previous.get("files", [])):
            require([(r["raw_path"], r["raw_pin"], r["archive"], r["archive_pin"]) for r in previous["files"]] ==
                    [(r["raw_path"], r["raw_pin"], r["archive"], r["archive_pin"]) for r in rows],
                    "Existing complete retention receipt changed")
            return previous  # idempotent verification preserves previous receipt pins
    # All archives have passed before any unlink. Interrupted cleanup is recoverable
    # from the archive and original pin; the exact original execution result is kept.
    write_json(packet / "scratch-retention.json", receipt)
    for row in rows:
        rawpath = Path(row["raw_path"])
        if release and rawpath.exists():
            require(rawpath.parent.resolve() == work.resolve() and rawpath.name in {item[0] for item in FILES},
                    "Release escaped explicit scratch file allowlist")
            require(pin(rawpath) == row["raw_pin"], "Scratch changed after archive verification")
            rawpath.unlink()
            row["raw_released"] = True
            write_json(packet / "scratch-retention.json", receipt)
    receipt["complete"] = True
    write_json(packet / "scratch-retention.json", receipt)
    return receipt


def main():
    if os.name == "nt":
        source = "/mnt/c" + str(Path(__file__).resolve()).replace("\\", "/")[2:]
        return subprocess.call(["wsl", "-d", "A51-KernelBuilder", "--exec", "python3", "-B", source, *sys.argv[1:]])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", action="store_true", help="Unlink only successful, byte-verified raw copies")
    args = parser.parse_args()
    packet = new_packet("qemu-scratch-retention", __file__)
    result = {"packet": packet.relative_to(PROJECT).as_posix(), "cases": [], "failures": [], "passed": False,
              "device_operations": False, "phase_4_gate_passed": False}
    try:
        result["capacity_before"] = capacity()
        for original in sorted(EVIDENCE_ROOT.iterdir()):
            if not (original / "result.json").is_file():
                continue
            case = json.loads((original / "result.json").read_text(encoding="utf-8"))
            if case.get("passed") is not True:
                continue  # preserve all failed-case scratch for diagnosis
            before = packet / "before-indexes" / original.name
            before.mkdir(parents=True, exist_ok=False)
            shutil.copy2(original / "index.json", before / "index.json")
            if (original / "scratch-retention.json").exists():
                shutil.copy2(original / "scratch-retention.json", before / "scratch-retention.json")
            original_pin = pin(original / "result.json")
            raw_present_before = {str(Path(case["work"]) / name) for name, key in FILES
                                  if key in case and (Path(case["work"]) / name).exists()}
            try:
                receipt = retain_case(original, case, release=args.release)
            except Exception as exc:
                result["failures"].append({"packet": case["packet"], "error": str(exc),
                                           "mismatched_raw_preserved": True})
                write_json(packet / "progress.json", result)
                continue
            require(pin(original / "result.json") == original_pin, "Historical execution result changed")
            index_packet(original)
            after = packet / "after-receipts" / original.name
            after.mkdir(parents=True, exist_ok=False)
            shutil.copy2(original / "scratch-retention.json", after / "scratch-retention.json")
            result["cases"].append({"packet": case["packet"], "result_pin": original_pin,
                "receipt_pin": pin(original / "scratch-retention.json"),
                "raw_bytes_released": sum(r["raw_pin"]["bytes"] for r in receipt["files"]
                                          if r["raw_released"] and r["raw_path"] in raw_present_before)})
            write_json(packet / "progress.json", result)
        result["capacity_after"] = capacity()
        result["passed"] = not result["failures"]
        if result["failures"]:
            result["error"] = "Some historical raw scratch is missing or no longer matches its recorded pin; preserved"
    except Exception as exc:
        result["error"] = str(exc)
    write_json(packet / "result.json", result)
    note = f"\n\n## P4-019 — Retain exact QEMU evidence and release redundant scratch ({packet.name})\n\nPurpose/files: scripts/phase4-retain-qemu-scratch.py and scripts/phase4-qemu-device-path.py. Preserve test.Image, full-arena prefill and destination readback as deterministic gzip archives, check decompressed bytes/length/SHA against original execution pins, then unlink only the explicit redundant raw filenames after QEMU has exited. Failed cases keep all scratch. Both Windows-backed evidence and WSL capacity are checked before cases. Historical result bytes/pins remain unchanged; previous indexes and cleanup receipts are retained in `{result['packet']}`.\n\nVerification: passed={result['passed']}; successful case packets processed={len(result['cases'])}; preserved integrity failures={len(result['failures'])}; error={result.get('error')}. The earlier all-case run stopped on case 20 with EROFS after C: ran out of space. Its first 19 result packets report execution success, but post-exhaustion raw-file integrity queries found truncated/absent scratch from later cases; these old raw files are preserved and a fresh complete suite is required. Lossless NTFS compression recovered host space without changing evidence/artifact content; retained watchdog bytes were rechecked in run 20261114T173623970029Z. WSL write access recovered without remount/termination. Compression attempts and capacity/mount/error queries remain in the original run logs. No device action occurred.\n\nLimitations/rollback: archives preserve exact inputs/readbacks, not peripheral hardware evidence. Reconstruct each raw file by gzip-decompressing its archive into the receipt's exact isolated path and verify raw_pin; retain failures and old indexes. Revert the harness/source from the loader-correction packet to undo the retention policy. Phase 4 remains incomplete.\n"
    documents(packet, {"docs/IMPLEMENTATION-LOG.md": (PROJECT / "docs/IMPLEMENTATION-LOG.md").read_text(encoding="utf-8") + note})
    index_packet(packet)
    print(json.dumps({"packet": result["packet"], "passed": result["passed"], "cases": len(result["cases"]),
                      "released_bytes": sum(r["raw_bytes_released"] for r in result["cases"]),
                      "error": result.get("error")}), flush=True)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
