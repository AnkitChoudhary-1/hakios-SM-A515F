#!/usr/bin/env python3
"""Corruption, containment, and resource guards for P2-019 evidence replay."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
from unittest import mock

from samsung_boot_dry_run import DryRunError


PROJECT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = PROJECT / "evidence/phase-2/samsung-boot-dry-run"
VERIFY_PATH = PROJECT / "scripts/verify-samsung-boot-dry-run.py"


def load_verifier():
    spec = importlib.util.spec_from_file_location("p2_019_verify", VERIFY_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load P2-019 verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VERIFY = load_verifier()


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def repin(fixture: Path, role: str) -> None:
    index_path = fixture / "index.json"
    index = load_json(index_path)
    data = fixture.joinpath(*role.split("/")).read_bytes()
    index["files"][role] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    write_json(index_path, index)


def mutate_report(fixture: Path, change) -> None:
    path = fixture / "report.json"
    report = load_json(path)
    change(report)
    write_json(path, report)
    repin(fixture, "report.json")


def rejected(label: str, fixture: Path, expected: str | None = None) -> None:
    try:
        VERIFY.verify_packet(fixture)
    except (DryRunError, OSError, ValueError, KeyError, TypeError) as exc:
        if expected is not None and expected not in str(exc):
            raise AssertionError(f"{label}: wrong rejection: {exc}") from exc
        print("PASS rejected " + label)
        return
    raise AssertionError("accepted corrupted evidence: " + label)


class Fixture:
    def __init__(self, original: Path):
        self.original = original
        self.context = None
        self.path = None

    def __enter__(self) -> Path:
        EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
        self.context = tempfile.TemporaryDirectory(prefix=".p2-019-test-", dir=EVIDENCE_ROOT)
        self.path = Path(self.context.name)
        if self.path.parent.resolve() != EVIDENCE_ROOT.resolve():
            raise RuntimeError("test fixture escaped P2-019 evidence root")
        shutil.copytree(self.original, self.path, dirs_exist_ok=True)
        return self.path

    def __exit__(self, exc_type, exc, traceback):
        self.context.cleanup()


def case(original: Path, label: str, mutator, expected: str | None = None) -> None:
    with Fixture(original) as fixture:
        mutator(fixture)
        rejected(label, fixture, expected)


def main() -> int:
    if len(sys.argv) != 2:
        raise ValueError("usage: test-samsung-boot-dry-run-evidence.py EVIDENCE_FOLDER")
    original = Path(sys.argv[1]).resolve(strict=True)
    valid = VERIFY.verify_packet(original)
    assert valid["status"] == "passed" and valid["indexed_files"] == len(VERIFY.EXPECTED_ROLES)
    print("PASS valid_packet")
    checks = 1

    def run(label, mutator, expected=None):
        nonlocal checks
        case(original, label, mutator, expected)
        checks += 1

    def duplicate_index(folder):
        path = folder / "index.json"
        raw = path.read_bytes().replace(b'"schema_version": 1,',
                                        b'"schema_version": 1,\n  "schema_version": 1,', 1)
        path.write_bytes(raw)
    run("duplicate_index_key", duplicate_index, "duplicate")

    run("nonfinite_index", lambda f: (f / "index.json").write_bytes(b'{"schema_version":NaN}'),
        "non-finite")
    run("floating_index", lambda f: (f / "index.json").write_bytes(b'{"schema_version":1.0}'),
        "floating-point")
    run("invalid_utf8_index", lambda f: (f / "index.json").write_bytes(b"{\xff}"),
        "invalid UTF-8")
    run("oversized_index", lambda f: (f / "index.json").write_bytes(
        b" " * (VERIFY.MAX_INDEX_BYTES + 1)), "read bound")
    run("nested_index", lambda f: (f / "index.json").write_text(
        "[" * (VERIFY.MAX_JSON_DEPTH + 1) + "]" * (VERIFY.MAX_JSON_DEPTH + 1),
        encoding="utf-8"), "nesting")

    def bool_size(folder):
        index = load_json(folder / "index.json")
        index["files"]["report.json"]["bytes"] = True
        write_json(folder / "index.json", index)
    run("boolean_index_size", bool_size, "declared size")

    def traversal_role(folder):
        index = load_json(folder / "index.json")
        pin = index["files"].pop("report.json")
        index["files"]["../report.json"] = pin
        write_json(folder / "index.json", index)
    run("traversal_index_role", traversal_role, "roles differ")

    def absolute_role(folder):
        index = load_json(folder / "index.json")
        pin = index["files"].pop("report.json")
        index["files"][str((folder / "report.json").resolve())] = pin
        write_json(folder / "index.json", index)
    run("absolute_index_role", absolute_role, "roles differ")

    run("extra_unindexed_file", lambda f: (f / "unexpected.bin").write_bytes(b"x"), "file set")
    run("missing_indexed_file", lambda f: (f / "report.json").unlink(), "file set")

    def excess_entries(folder):
        for number in range(VERIFY.MAX_TREE_ENTRIES + 1):
            (folder / f"extra-{number:02d}").mkdir()
    run("tree_entry_limit", excess_entries, "entry limit")

    run("tree_depth_limit", lambda f: (f / "sources/deeper/nested").mkdir(parents=True),
        "depth limit")

    def aggregate(folder):
        index = load_json(folder / "index.json")
        for name in VERIFY.EXPECTED_ROLES:
            index["files"][name]["bytes"] = VERIFY.role_limit(name)
        write_json(folder / "index.json", index)
    run("declared_aggregate_limit", aggregate, "aggregate byte limit")

    def wrong_hash(folder):
        index = load_json(folder / "index.json")
        index["files"]["report.json"]["sha256"] = "0" * 64
        write_json(folder / "index.json", index)
    run("indexed_hash_mismatch", wrong_hash, "pin mismatch")

    def duplicate_report(folder):
        path = folder / "report.json"
        path.write_bytes(path.read_bytes().replace(
            b'"schema_version": 1,', b'"schema_version": 1,\n  "schema_version": 1,', 1))
        repin(folder, "report.json")
    run("duplicate_report_key", duplicate_report, "duplicate")

    def nonfinite_report(folder):
        path = folder / "report.json"
        path.write_bytes(path.read_bytes().replace(b'"schema_version": 1', b'"schema_version": NaN', 1))
        repin(folder, "report.json")
    run("nonfinite_report", nonfinite_report, "non-finite")

    run("boolean_report_integer", lambda f: mutate_report(
        f, lambda r: r["template"].__setitem__("bytes", True)), "typed semantic replay")
    run("extra_report_field", lambda f: mutate_report(
        f, lambda r: r.__setitem__("unexpected", False)), "fields differ")
    run("template_path_traversal", lambda f: mutate_report(
        f, lambda r: r["inputs"]["template"].__setitem__("path", "../outside.img")),
        "input metadata")
    run("template_path_absolute", lambda f: mutate_report(
        f, lambda r: r["inputs"]["template"].__setitem__("path", str((f / "outside.img").resolve()))),
        "input metadata")
    run("kernel_input_size", lambda f: mutate_report(
        f, lambda r: r["inputs"]["kernel"].__setitem__("bytes", 1)), "input metadata")
    run("repack_input_hash", lambda f: mutate_report(
        f, lambda r: r["inputs"]["prior_repack_record"].__setitem__("sha256", "0" * 64)),
        "input metadata")

    def retained_repack(folder):
        path = folder / "references/repack-validation.json"
        path.write_bytes(path.read_bytes().replace(b"Parbindar7", b"Parbindar8", 1))
        repin(folder, "references/repack-validation.json")
    run("retained_repack_drift", retained_repack, "differs from live pinned")

    def source_drift(folder):
        role = "sources/samsung_boot_dry_run.py"
        path = folder.joinpath(*role.split("/"))
        path.write_bytes(path.read_bytes() + b"\n")
        repin(folder, role)
    run("source_snapshot_drift", source_drift, "source snapshot drift")

    def source_role_swap(folder):
        first = folder / "sources/capture-samsung-boot-dry-run.py"
        second = folder / "sources/test-samsung-boot-dry-run.py"
        one, two = first.read_bytes(), second.read_bytes()
        first.write_bytes(two)
        second.write_bytes(one)
        repin(folder, "sources/capture-samsung-boot-dry-run.py")
        repin(folder, "sources/test-samsung-boot-dry-run.py")
    run("source_role_swap", source_role_swap, "source snapshot drift")

    def reparse_file(folder):
        target = (folder / "report.json").absolute()
        original_lstat = VERIFY.os.lstat

        def fake_lstat(path):
            info = original_lstat(path)
            if Path(path).absolute() == target:
                return SimpleNamespace(st_mode=info.st_mode, st_size=info.st_size,
                                       st_mtime_ns=info.st_mtime_ns,
                                       st_file_attributes=getattr(info, "st_file_attributes", 0)
                                       | VERIFY.REPARSE_FLAG)
            return info

        with mock.patch.object(VERIFY.os, "lstat", side_effect=fake_lstat):
            rejected("reparse_file", folder, "reparse")
    with Fixture(original) as fixture:
        reparse_file(fixture)
    checks += 1

    outside = PROJECT / "evidence/phase-2/early-entry-kernel/20261111T163522918342Z"
    rejected("outside_evidence_subtree", outside, "direct P2-019")
    checks += 1

    fake = SimpleNamespace(st_file_attributes=VERIFY.REPARSE_FLAG)
    assert VERIFY._is_reparse(fake) is True
    print("PASS reparse_predicate")
    checks += 1

    print(f"SAMSUNG_BOOT_DRY_RUN_EVIDENCE_TESTS cases={checks} result=PASS "
          "full_image_emitted=0 phone_writes=0 device_gate=0")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, DryRunError, OSError, ValueError, KeyError, TypeError) as exc:
        print("SAMSUNG_BOOT_DRY_RUN_EVIDENCE_TESTS result=FAIL " + str(exc), file=sys.stderr)
        raise SystemExit(1)
