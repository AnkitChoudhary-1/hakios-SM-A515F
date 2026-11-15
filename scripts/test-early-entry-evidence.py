#!/usr/bin/env python3
"""Focused corruption tests for early_entry_evidence.py.

The selected packets are copied to an OS temporary directory.  No retained
evidence is modified and no compiler, emulator, WSL command, ADB command, or
phone interface is used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

import early_entry_evidence as evidence


def dump(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def digest(path: Path) -> dict[str, object]:
    data = path.read_bytes()
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def reindex(kernel: Path) -> None:
    index = json.loads((kernel / "index.json").read_text(encoding="utf-8"))
    for relative in list(index["files"]):
        path = kernel / relative
        if path.is_file():
            index["files"][relative] = digest(path)
    dump(kernel / "index.json", index)


def rejected(name: str, action) -> None:
    try:
        action()
    except evidence.EvidenceError:
        print("PASS corruption_rejected " + name, flush=True)
        return
    raise RuntimeError("corruption was accepted: " + name)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", type=Path, default=evidence.PROJECT / evidence.SELECTED["host"])
    parser.add_argument("--prepare", type=Path, default=evidence.PROJECT / evidence.SELECTED["prepare"])
    parser.add_argument("--kernel", type=Path, default=evidence.PROJECT / evidence.SELECTED["kernel"])
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="hakios-early-entry-corruption-") as temporary:
        root = Path(temporary)
        host = root / "host" / args.host.name
        prepare = root / "prepare" / args.prepare.name
        kernel = root / "kernel" / args.kernel.name
        shutil.copytree(args.host, host)
        shutil.copytree(args.prepare, prepare)
        shutil.copytree(args.kernel, kernel)
        evidence.verify_all(host, prepare, kernel, enforce_selection=False)
        print("PASS copied_baseline", flush=True)

        host_result = host / "result.json"
        host_original = host_result.read_bytes()
        value = json.loads(host_original)
        value["cases"][0]["harness_checks"] += 1
        dump(host_result, value)
        rejected("host_check_count", lambda: evidence.verify_host(host, False))
        host_result.write_bytes(host_original)

        duplicate = host_original.replace(b'"schema_version": 1,', b'"schema_version": 1,\n  "schema_version": 1,', 1)
        host_result.write_bytes(duplicate)
        rejected("duplicate_json_key", lambda: evidence.verify_host(host, False))
        host_result.write_bytes(host_original)

        nonfinite = host_original.replace(b'"schema_version": 1,', b'"schema_version": NaN,', 1)
        host_result.write_bytes(nonfinite)
        rejected("nonfinite_json", lambda: evidence.verify_host(host, False))
        host_result.write_bytes(host_original)

        patch = prepare / "early-entry.patch"
        patch_original = patch.read_bytes()
        patch.write_bytes(patch_original + b"\nforged\n")
        rejected("preparation_patch", lambda: evidence.verify_prepare(prepare, kernel / "prototype", False))
        patch.write_bytes(patch_original)

        kernel_result, kernel_index = kernel / "result.json", kernel / "index.json"
        result_original, index_original = kernel_result.read_bytes(), kernel_index.read_bytes()
        value = json.loads(result_original)
        value["phase_2_device_gate_passed"] = True
        dump(kernel_result, value)
        reindex(kernel)
        rejected("forged_device_gate", lambda: evidence.verify_kernel(kernel, host, prepare, False))
        kernel_result.write_bytes(result_original)
        kernel_index.write_bytes(index_original)

        value = json.loads(result_original)
        value["symbols"]["stext"] = True
        dump(kernel_result, value)
        reindex(kernel)
        rejected("bool_for_integer_symbol", lambda: evidence.verify_kernel(kernel, host, prepare, False))
        kernel_result.write_bytes(result_original)
        kernel_index.write_bytes(index_original)

        value = json.loads(result_original)
        image = kernel / "Image"
        record_offset = value["symbols"]["hakios_early_record"] - value["symbols"]["_text"]
        with image.open("r+b") as stream:
            stream.seek(record_offset + 24)
            original_byte = stream.read(1)
            stream.seek(record_offset + 24)
            stream.write(bytes([original_byte[0] ^ 1]))
        value["image"] = digest(image)
        dump(kernel_result, value)
        reindex(kernel)
        rejected("reindexed_initialized_record", lambda: evidence.verify_kernel(kernel, host, prepare, False))
        with image.open("r+b") as stream:
            stream.seek(record_offset + 24)
            stream.write(original_byte)
        kernel_result.write_bytes(result_original)
        kernel_index.write_bytes(index_original)

        forged = kernel / "forged.txt"
        forged.write_text("forged\n", encoding="utf-8")
        index = json.loads(index_original)
        index["files"]["forged.txt"] = digest(forged)
        dump(kernel_index, index)
        rejected("extra_reindexed_role", lambda: evidence.verify_kernel(kernel, host, prepare, False))
        forged.unlink()
        kernel_index.write_bytes(index_original)

        index = json.loads(index_original)
        index["files"]["../escape"] = {"bytes": 0, "sha256": "0" * 64}
        dump(kernel_index, index)
        rejected("index_traversal", lambda: evidence.verify_kernel(kernel, host, prepare, False))
        kernel_index.write_bytes(index_original)

        evidence.verify_all(host, prepare, kernel, enforce_selection=False)
        print("PASS restored_baseline", flush=True)
    print(json.dumps({"schema_version": 1, "status": "passed", "corruptions_rejected": 9,
                      "retained_evidence_modified": False, "phone_queries": False,
                      "phone_writes": False, "phase_2_device_gate_passed": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
