#!/usr/bin/env python3
"""Strictly replay one retained P2-019 host-only evidence packet."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any

from samsung_boot_dry_run import DryRunError, generate_report


PROJECT = Path(__file__).resolve().parents[1]
WORKSPACE = PROJECT.parent
EVIDENCE_ROOT = PROJECT / "evidence/phase-2/samsung-boot-dry-run"

TEMPLATE_REL = "everline-ksu/artifacts/A51-PixelOS-Everline-KernelSU-Next-boot.img"
KERNEL_REL = "evidence/phase-2/early-entry-kernel/20261111T163522918342Z/Image"
REPACK_REL = "everline-ksu/artifacts/repack-validation.json"
INPUT_PINS = {
    "template": {"path": TEMPLATE_REL, "bytes": 61_865_984,
                 "sha256": "eb30609a62999e3282ac81e0a5e56411ef12ec1a39c107171bf3e01209c7cb67"},
    "kernel": {"path": KERNEL_REL, "bytes": 36_334_080,
               "sha256": "87c0401361d4503afb0b266b15ff0caf1e64f505d61d53be700e8b6c6d8e9cf6"},
    "prior_repack_record": {"path": REPACK_REL, "bytes": 1_911,
                            "sha256": "2ced1959920eb5a1daf1343c89b36c40caf1a3d7d419a73957385597c8e8712b"},
}
EXPECTED_CANDIDATE_SHA256 = "73d88c699dda238238b7b2b1105caea248b9ef3aef282a3f01b566f0fd894a58"
EXPECTED_CHANGED_REGIONS = [
    "header.kernel_size", "header.id", "kernel.slot", "avb.boot_digest",
]
SOURCE_NAMES = (
    "samsung_boot_dry_run.py",
    "capture-samsung-boot-dry-run.py",
    "test-samsung-boot-dry-run.py",
    "test-samsung-boot-dry-run-evidence.py",
    "verify-samsung-boot-dry-run.py",
)
EXPECTED_ROLES = frozenset(
    {"report.json", "references/repack-validation.json"}
    | {"sources/" + name for name in SOURCE_NAMES}
)
EXPECTED_DIRECTORIES = frozenset({"references", "sources"})

MAX_INDEX_BYTES = 128 * 1024
MAX_JSON_BYTES = 128 * 1024
MAX_SOURCE_BYTES = 256 * 1024
MAX_REFERENCE_BYTES = 16 * 1024
MAX_INDEXED_BYTES = 1024 * 1024
MAX_TREE_ENTRIES = 16
MAX_TREE_DEPTH = 2
MAX_JSON_DEPTH = 64
REPARSE_FLAG = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def require(ok: bool, message: str) -> None:
    if not ok:
        raise DryRunError(message)


def exact(value: Any, fields: set[str] | frozenset[str], where: str) -> dict[str, Any]:
    require(type(value) is dict, where + ": object required")
    actual = set(value)
    require(actual == set(fields),
            f"{where}: fields differ (missing={sorted(set(fields) - actual)}, "
            f"extra={sorted(actual - set(fields))})")
    return value


def typed_equal(first: Any, second: Any) -> bool:
    if type(first) is not type(second):
        return False
    if type(first) is dict:
        return (set(first) == set(second)
                and all(type(key) is str and typed_equal(first[key], second[key]) for key in first))
    if type(first) is list:
        return len(first) == len(second) and all(
            typed_equal(left, right) for left, right in zip(first, second))
    return first == second


def _is_reparse(info: os.stat_result) -> bool:
    return bool(getattr(info, "st_file_attributes", 0) & REPARSE_FLAG)


def regular_info(path: Path, maximum: int, where: str) -> os.stat_result:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise DryRunError(where + ": missing or unreadable") from exc
    require(stat.S_ISREG(info.st_mode), where + ": regular file required")
    require(not _is_reparse(info) and not path.is_symlink(), where + ": reparse/symlink rejected")
    require(0 <= info.st_size <= maximum, where + ": file exceeds read bound")
    return info


def bounded_read(path: Path, maximum: int, where: str) -> bytes:
    before = regular_info(path, maximum, where)
    try:
        with path.open("rb") as stream:
            data = stream.read(maximum + 1)
    except OSError as exc:
        raise DryRunError(where + ": read failed") from exc
    require(len(data) <= maximum and len(data) == before.st_size,
            where + ": oversized, short, or concurrently changed read")
    after = regular_info(path, maximum, where)
    require(after.st_size == before.st_size and after.st_mtime_ns == before.st_mtime_ns,
            where + ": file changed during read")
    return data


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        require(type(key) is str and key not in result, "duplicate or non-text JSON key")
        result[key] = value
    return result


def _constant(value: str) -> Any:
    raise DryRunError("non-finite JSON value rejected: " + value)


def _floating(value: str) -> Any:
    raise DryRunError("JSON floating-point value rejected: " + value)


def _check_json_depth(text: str, where: str) -> None:
    depth = 0
    quoted = False
    escaped = False
    for character in text:
        if quoted:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
        elif character == '"':
            quoted = True
        elif character in "[{":
            depth += 1
            require(depth <= MAX_JSON_DEPTH, where + ": JSON nesting exceeds limit")
        elif character in "]}":
            depth -= 1
            require(depth >= 0, where + ": invalid JSON nesting")


def json_bytes(data: bytes, where: str) -> Any:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DryRunError(where + ": invalid UTF-8 JSON") from exc
    _check_json_depth(text, where)
    try:
        return json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant,
                          parse_float=_floating)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise DryRunError(where + ": invalid or excessively nested JSON") from exc


def read_json(path: Path, maximum: int, where: str) -> Any:
    return json_bytes(bounded_read(path, maximum, where), where)


def digest_text(value: Any, where: str) -> str:
    require(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
            where + ": lowercase SHA-256 required")
    return value


def role_limit(name: str) -> int:
    if name == "report.json":
        return MAX_JSON_BYTES
    if name == "references/repack-validation.json":
        return MAX_REFERENCE_BYTES
    if name.startswith("sources/"):
        return MAX_SOURCE_BYTES
    raise DryRunError("unexpected evidence role: " + name)


def canonical_folder(argument: str | Path) -> Path:
    root = Path(os.path.abspath(EVIDENCE_ROOT))
    raw = Path(argument)
    lexical = Path(os.path.abspath(raw if raw.is_absolute() else Path.cwd() / raw))
    require(lexical.parent == root, "evidence folder must be a direct P2-019 packet")
    current = root
    for part in lexical.relative_to(root).parts:
        current /= part
        try:
            info = os.lstat(current)
        except OSError as exc:
            raise DryRunError("evidence folder missing or unreadable") from exc
        require(stat.S_ISDIR(info.st_mode), "evidence path component is not a directory")
        require(not _is_reparse(info) and not current.is_symlink(),
                "evidence path contains a reparse point or symlink")
    try:
        resolved = lexical.resolve(strict=True)
        resolved_root = root.resolve(strict=True)
    except OSError as exc:
        raise DryRunError("evidence folder cannot be resolved") from exc
    require(resolved.parent == resolved_root and resolved == lexical,
            "evidence folder escapes or aliases the P2-019 evidence root")
    return resolved


def enumerate_packet(folder: Path) -> tuple[set[str], set[str]]:
    files: set[str] = set()
    directories: set[str] = set()
    stack = [(folder, 0)]
    entries = 0
    while stack:
        parent, depth = stack.pop()
        try:
            children = list(os.scandir(parent))
        except OSError as exc:
            raise DryRunError("evidence directory enumeration failed") from exc
        for entry in children:
            entries += 1
            require(entries <= MAX_TREE_ENTRIES, "evidence tree entry limit exceeded")
            path = Path(entry.path)
            relative = path.relative_to(folder).as_posix()
            child_depth = len(Path(relative).parts)
            require(child_depth <= MAX_TREE_DEPTH, "evidence tree depth limit exceeded")
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise DryRunError("evidence entry cannot be inspected: " + relative) from exc
            require(not entry.is_symlink() and not _is_reparse(info),
                    "evidence reparse/symlink entry rejected: " + relative)
            if stat.S_ISDIR(info.st_mode):
                directories.add(relative)
                stack.append((path, depth + 1))
            elif stat.S_ISREG(info.st_mode):
                files.add(relative)
            else:
                raise DryRunError("non-regular evidence entry rejected: " + relative)
    require(directories == EXPECTED_DIRECTORIES, "evidence directory set differs")
    require(files == EXPECTED_ROLES | {"index.json"}, "evidence file set differs")
    require(not any(name.lower().endswith(".img") for name in files),
            "evidence unexpectedly contains an image")
    return files, directories


def check_created(value: Any) -> None:
    require(type(value) is str and len(value) <= 40, "index.created_utc: timestamp text required")
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError as exc:
        raise DryRunError("index.created_utc: invalid timestamp") from exc
    require(parsed.tzinfo is not None and parsed.utcoffset() == dt.timedelta(0),
            "index.created_utc: UTC offset required")


def validate_index(folder: Path) -> tuple[dict[str, Any], dict[str, bytes]]:
    index = read_json(folder / "index.json", MAX_INDEX_BYTES, "index")
    exact(index, {"schema_version", "created_utc", "files", "full_image_emitted",
                  "candidate_bytes_retained", "phone_writes", "phase_2_device_gate_passed"},
          "index")
    require(type(index["schema_version"]) is int and index["schema_version"] == 1,
            "index.schema_version mismatch")
    check_created(index["created_utc"])
    for field in ("full_image_emitted", "candidate_bytes_retained", "phone_writes",
                  "phase_2_device_gate_passed"):
        require(type(index[field]) is bool and index[field] is False,
                "index scope/gate mismatch: " + field)
    files = index["files"]
    require(type(files) is dict and len(files) == len(EXPECTED_ROLES)
            and set(files) == EXPECTED_ROLES, "index evidence roles differ")
    declared_total = 0
    for name in sorted(EXPECTED_ROLES):
        pin = exact(files[name], {"bytes", "sha256"}, "index.files[" + name + "]")
        limit = role_limit(name)
        require(type(pin["bytes"]) is int and 0 <= pin["bytes"] <= limit,
                "index declared size outside role bound: " + name)
        digest_text(pin["sha256"], "index.files[" + name + "].sha256")
        declared_total += pin["bytes"]
        require(declared_total <= MAX_INDEXED_BYTES, "index aggregate byte limit exceeded")

    enumerate_packet(folder)
    retained: dict[str, bytes] = {}
    actual_total = 0
    for name in sorted(EXPECTED_ROLES):
        data = bounded_read(folder.joinpath(*name.split("/")), role_limit(name), name)
        pin = files[name]
        require(len(data) == pin["bytes"] and sha(data) == pin["sha256"],
                "evidence pin mismatch: " + name)
        actual_total += len(data)
        require(actual_total <= MAX_INDEXED_BYTES, "evidence aggregate byte limit exceeded")
        retained[name] = data
    require(actual_total == declared_total, "index/evidence aggregate byte mismatch")
    return index, retained


def pinned_input(path: Path, pin: dict[str, Any], where: str) -> bytes:
    data = bounded_read(path, pin["bytes"], where)
    require(len(data) == pin["bytes"] and sha(data) == pin["sha256"],
            where + ": selected input pin mismatch")
    return data


def validate_repack(data: bytes, where: str) -> dict[str, Any]:
    value = json_bytes(data, where)
    require(type(value) is dict, where + ": object required")
    required = {
        "new_boot_sha256": INPUT_PINS["template"]["sha256"],
        "new_boot_bytes": INPUT_PINS["template"]["bytes"],
        "kernel_file_bytes": 36_333_584,
        "device_boot_tested": True,
        "installed_boot_readback_verified": True,
    }
    for key, expected in required.items():
        require(key in value and type(value[key]) is type(expected) and value[key] == expected,
                where + ": retained Android association mismatch: " + key)
    return value


def validate_report(report_data: bytes, template: bytes, kernel: bytes) -> dict[str, Any]:
    report = json_bytes(report_data, "report")
    replay = generate_report(template, kernel)
    exact(report, set(replay) | {"milestone", "inputs"}, "report")
    require(type(report["milestone"]) is str and report["milestone"] == "P2-019",
            "report milestone mismatch")
    expected_inputs = {
        "template": dict(INPUT_PINS["template"]),
        "kernel": dict(INPUT_PINS["kernel"]),
        "prior_repack_record": dict(INPUT_PINS["prior_repack_record"],
                                    device_boot_tested_applies_only_to_prior_android_kernel=True),
    }
    require(typed_equal(report["inputs"], expected_inputs), "report input metadata mismatch")
    for key, expected in replay.items():
        require(typed_equal(report[key], expected), "typed semantic replay mismatch: " + key)
    require(replay["candidate"]["sha256"] == EXPECTED_CANDIDATE_SHA256,
            "candidate digest differs from selected P2-019 result")
    require([item["name"] for item in replay["changed_regions"]] == EXPECTED_CHANGED_REGIONS,
            "changed-region contract differs")
    return replay


def verify_packet(argument: str | Path) -> dict[str, Any]:
    folder = canonical_folder(argument)
    index, retained = validate_index(folder)

    template_path = WORKSPACE.joinpath(*TEMPLATE_REL.split("/"))
    kernel_path = PROJECT.joinpath(*KERNEL_REL.split("/"))
    repack_path = WORKSPACE.joinpath(*REPACK_REL.split("/"))
    template = pinned_input(template_path, INPUT_PINS["template"], "template input")
    kernel = pinned_input(kernel_path, INPUT_PINS["kernel"], "kernel input")
    live_repack = pinned_input(repack_path, INPUT_PINS["prior_repack_record"], "live repack record")
    retained_repack = retained["references/repack-validation.json"]
    require(retained_repack == live_repack, "retained repack reference differs from live pinned record")
    validate_repack(live_repack, "live repack record")
    validate_repack(retained_repack, "retained repack reference")

    replay = validate_report(retained["report.json"], template, kernel)
    for name in SOURCE_NAMES:
        current = bounded_read(PROJECT / "scripts" / name, MAX_SOURCE_BYTES,
                               "current source " + name)
        require(retained["sources/" + name] == current,
                "source snapshot drift or role mismatch: " + name)

    indexed_bytes = sum(index["files"][name]["bytes"] for name in EXPECTED_ROLES)
    return {
        "status": "passed",
        "evidence": folder.relative_to(PROJECT).as_posix(),
        "indexed_files": len(EXPECTED_ROLES),
        "indexed_bytes": indexed_bytes,
        "candidate_sha256": replay["candidate"]["sha256"],
        "changed_regions": len(replay["changed_regions"]),
        "full_image_emitted": False,
        "candidate_bytes_retained": False,
        "phone_writes": False,
        "phase_2_device_gate_passed": False,
    }


def main() -> int:
    try:
        require(len(sys.argv) == 2, "usage: verify-samsung-boot-dry-run.py EVIDENCE_FOLDER")
        print(json.dumps(verify_packet(sys.argv[1]), sort_keys=True))
        return 0
    except (DryRunError, OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print("SAMSUNG_BOOT_DRY_RUN_EVIDENCE_REJECTED: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
