#!/usr/bin/env python3
"""Check cumulative patches, finalize publication metadata, or audit staged blobs.

All patch application happens in temporary directories. No phone operations,
downloads, pushes, or changes to the original upstream checkouts occur here.
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
REPOSITORY = "https://github.com/AnkitChoudhary-1/hakios-SM-A515F"
EDITORIAL_FILES = {"README.md", "docs/IMPLEMENTATION-LOG.md", "docs/PUBLICATION.md", "docs/PUBLIC-STATUS.md", "patches/README.md"}
VALIDATION_FILES = {"validation/public-smoke.json", "validation/patch-checks.json"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def stamp():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def helpers():
    spec = importlib.util.spec_from_file_location("publication_export", PROJECT / "scripts/prepare-publication.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(root, *args):
    command = ["git", "-c", "safe.directory=" + str(root), "-C", str(root), *args]
    proc = subprocess.run(command, capture_output=True)
    if proc.returncode:
        raise RuntimeError(proc.stderr.decode("utf-8", errors="replace"))
    return proc.stdout


def safe_relative(name):
    path = Path(name)
    require(not path.is_absolute() and ".." not in path.parts and ".git" not in path.parts,
            "Unsafe publication path: " + name)
    return path


def public_files(root):
    files = set()
    for path in root.rglob("*"):
        rel = path.relative_to(root)
        if ".git" in rel.parts or "__pycache__" in rel.parts or rel.parts[:2] == ("validation", "local"):
            continue
        if path.is_file():
            require(not path.is_symlink(), "Symlink in publication: " + str(rel))
            files.add(rel.as_posix())
    return files


def check_patches(destination, report, baseline, util):
    native_baseline = baseline / "xnu-src/xnu-8796.121.2"
    require(run(baseline, "rev-parse", "HEAD").decode().strip() == util.COMMON_COMMIT, "Wrong common baseline")
    require(run(native_baseline, "rev-parse", "HEAD").decode().strip() == util.XNU_COMMIT, "Wrong native baseline")
    results, commands, patch_hashes = {}, [], {}
    for name, patch_record in report["patches"].items():
        native = name.endswith("-xnu.patch")
        patch_path = destination / safe_relative(name)
        patch_hashes[name] = util.pin(patch_path.read_bytes())
        with tempfile.TemporaryDirectory(prefix="a51-public-patch-") as temp:
            work = Path(temp)
            run(work, "init", "--quiet")
            for row in patch_record["files"]:
                relative = safe_relative(row["path"])
                if not row["before_exists"]:
                    if native:
                        require(not (native_baseline / relative).exists(), "New native file exists in baseline: " + str(relative))
                    continue
                before = (native_baseline / relative).read_bytes() if native else run(baseline, "show", util.COMMON_COMMIT + ":" + row["path"])
                require(util.pin(before) == row["before"], "Baseline hash differs: " + row["path"])
                target = work / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(before)
            for action in (("apply", "--check", "--whitespace=nowarn", str(patch_path)),
                           ("apply", "--whitespace=nowarn", str(patch_path))):
                commands.append({"cwd": str(work), "arguments": ["git", *action]})
                run(work, *action)
            for row in patch_record["files"]:
                after_path = work / row["path"]
                if row["after_exists"]:
                    require(after_path.is_file() and util.pin(after_path.read_bytes()) == row["after"],
                            "Patched result hash differs: " + row["path"])
                else:
                    require(not after_path.exists(), "Deleted patch file remains: " + row["path"])
            results[name] = {"application_check_passed": True, "result_hashes_matched": True,
                             "files_checked": len(patch_record["files"])}
    result = {"passed": True, "checked_utc": stamp(), "patches": results, "patch_hashes": patch_hashes,
              "common_commit": util.COMMON_COMMIT, "xnu_commit": util.XNU_COMMIT,
              "native_baseline": "pinned common checkout after upstream xnu/apply.sh",
              "commands": commands, "device_operations": False,
              "scope": "application and exact result hashes for all changed files in temporary baseline trees"}
    target = destination / "validation/patch-checks.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "commands"}, indent=2))


def finalize(destination, report, util):
    local_results = sorted((destination / "validation/local").glob("*/result.json"))
    require(bool(local_results), "Run the portable smoke checks first")
    smoke = json.loads(local_results[-1].read_text(encoding="utf-8"))
    require(smoke.get("passed") is True and smoke.get("device_operations") is False, "Invalid smoke result")
    require(all(row.get("passed") is True for row in smoke["suites"].values()), "Native model failed")
    for name, expected in smoke["sources"].items():
        require(util.pin((destination / name).read_bytes()) == expected, "Smoke source changed: " + name)
    (destination / "validation/public-smoke.json").write_text(json.dumps(smoke, indent=2) + "\n", encoding="utf-8")
    patches = json.loads((destination / "validation/patch-checks.json").read_text(encoding="utf-8"))
    require(patches.get("passed") is True and patches.get("device_operations") is False, "Invalid patch check result")
    require(set(patches["patches"]) == set(report["patches"]), "Incomplete patch checks")
    for name, expected in patches["patch_hashes"].items():
        require(util.pin((destination / name).read_bytes()) == expected, "Patch changed since validation: " + name)
    rows = {row["path"]: row for row in report["files"]}
    actual_files = public_files(destination) - {"PUBLICATION-MANIFEST.json"}
    require(not (set(rows) - actual_files), "An exported file is missing")
    require(not (actual_files - set(rows) - VALIDATION_FILES), "Unexpected files in publication")
    for name in sorted(actual_files):
        raw = (destination / name).read_bytes()
        current_pin = util.pin(raw)
        if name not in rows:
            rows[name] = {"path": name, **current_pin, "origin": "publication-validation"}
        elif any(rows[name][key] != current_pin[key] for key in ("bytes", "sha256")):
            require(name in EDITORIAL_FILES, "Export changed after capture: " + name)
            rows[name].update(current_pin, transformed=True, post_export_editorial_update=True)
    report.update(files=[rows[name] for name in sorted(rows)], finalized_utc=stamp(),
                  validation={"portable_host_checks": "validation/public-smoke.json", "patch_application_checks": "validation/patch-checks.json"})
    manifest = destination / "PUBLICATION-MANIFEST.json"
    manifest.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    report["scan"] = util.scan_tree(destination)
    require(report["scan"]["passed"], "Publication text/identifier scan failed")
    manifest.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    require(util.scan_tree(destination) == report["scan"], "Publication changed during final scan")
    print(json.dumps({"finalized": True, "files": len(rows) + 1, "scan": report["scan"]}, indent=2))


def staged(destination, report, util):
    require("finalized_utc" in report, "Finalize the publication manifest before staging")
    require(run(destination, "symbolic-ref", "--short", "HEAD").decode().strip() == "main", "Wrong publication branch")
    require(run(destination, "remote", "get-url", "origin").decode().strip() == REPOSITORY + ".git", "Wrong publication remote")
    entries = {}
    for entry in run(destination, "ls-files", "--stage", "-z").split(b"\0"):
        if not entry:
            continue
        metadata, name = entry.split(b"\t", 1)
        mode, object_id, stage = metadata.decode().split()
        path = name.decode("utf-8")
        safe_relative(path)
        require(mode in ("100644", "100755") and stage == "0", "Unexpected index entry: " + path)
        entries[path] = object_id
    expected = {row["path"]: {key: row[key] for key in ("bytes", "sha256")} for row in report["files"]}
    expected["PUBLICATION-MANIFEST.json"] = util.pin((destination / "PUBLICATION-MANIFEST.json").read_bytes())
    require(set(entries) == set(expected), "Staged paths do not exactly match the reviewed manifest")
    proc = subprocess.run(["git", "-c", "safe.directory=" + str(destination), "-C", str(destination), "cat-file", "--batch"],
                          input=("\n".join(entries.values()) + "\n").encode(), capture_output=True, check=True)
    payload, offset = proc.stdout, 0
    for name, object_id in entries.items():
        end = payload.index(b"\n", offset)
        observed_id, kind, size_text = payload[offset:end].decode().split()
        require(observed_id == object_id and kind == "blob", "Unexpected Git object: " + name)
        size = int(size_text)
        raw = payload[end + 1:end + 1 + size]
        offset = end + 1 + size + 1
        require(util.pin(raw) == expected[name], "Staged blob hash differs: " + name)
        content = raw.decode("utf-8")
        require("\0" not in content and not util.SERIAL_PATTERN.search(content) and not util.MAC_PATTERN.search(content),
                "Non-text or personal identifier staged: " + name)
        for label, pattern in util.SECRET_PATTERNS.items():
            require(not pattern.search(content), "Credential pattern staged: " + name + " (" + label + ")")
        if name.endswith(".json"):
            json.loads(content)
    require(offset == len(payload), "Unexpected extra Git object output")
    print(json.dumps({"staged_tree_verified": True, "files": len(entries), "blob_hashes_match_manifest": True,
                      "text_and_identifier_scan_passed": True, "remote": REPOSITORY, "branch": "main", "device_operations": False}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("patches", "finalize", "staged"))
    parser.add_argument("--destination", default=str(PROJECT))
    parser.add_argument("--baseline", default="/opt/a51-hakios/src/hakios-xnu-kernel")
    args = parser.parse_args()
    destination = Path(args.destination).resolve()
    require((destination / ".git").is_dir(), "Destination must be a publication clone")
    report = json.loads((destination / "PUBLICATION-MANIFEST.json").read_text(encoding="utf-8"))
    require(report.get("repository") == REPOSITORY and report.get("phase4_hardware_gate_passed") is False, "Wrong publication manifest")
    util = helpers()
    if args.mode == "patches":
        check_patches(destination, report, Path(args.baseline).resolve(), util)
    elif args.mode == "finalize":
        finalize(destination, report, util)
    else:
        staged(destination, report, util)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
