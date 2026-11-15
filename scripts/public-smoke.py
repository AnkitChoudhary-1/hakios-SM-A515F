#!/usr/bin/env python3
"""Portable host validation; no ADB, firmware, source download or device writes."""
from __future__ import annotations

import ast
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

PROJECT = Path(__file__).resolve().parents[1]


def main():
    parser_count = 0
    for folder in ("scripts", "prototype"):
        for path in sorted((PROJECT / folder).rglob("*.py")):
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            parser_count += 1
    shell_count = 0
    for path in sorted((PROJECT / "scripts").glob("*.sh")):
        subprocess.run(["bash", "-n", str(path)], check=True)
        shell_count += 1
    subprocess.run([sys.executable, "-B", str(PROJECT / "scripts/test-boot-formats.py")], check=True)

    compiler = shutil.which("clang-18") or shutil.which("clang")
    if not compiler:
        raise RuntimeError("clang-18 or clang is required for the native protocol models")
    compiler_version = subprocess.run([compiler, "--version"], check=True, capture_output=True, text=True).stdout.splitlines()[:2]
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    work = PROJECT / "validation/local" / stamp
    work.mkdir(parents=True, exist_ok=False)
    sources = PROJECT / "prototype/phase4-platform"
    commands, suites = [], {}
    for suite in ("ufs", "input"):
        binary = work / suite
        compile_args = [compiler, "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
            "-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-fno-omit-frame-pointer",
            "-I", str(sources), str(sources / "tests" / (suite + "_model.c")), "-o", str(binary)]
        commands.append(compile_args)
        subprocess.run(compile_args, check=True, timeout=60)
        commands.append([str(binary)])
        proc = subprocess.run([str(binary)], check=True, capture_output=True, timeout=30,
            env=dict(os.environ, ASAN_OPTIONS="detect_leaks=1:abort_on_error=1", UBSAN_OPTIONS="halt_on_error=1"))
        observed = json.loads(proc.stdout)
        if observed.get("passed") is not True or observed.get("suite") != suite:
            raise RuntimeError("Invalid native model result: " + suite)
        suites[suite] = observed
    source_pins = {}
    for name in ("a51_ufs_readonly.h", "a51_input.h", "tests/ufs_model.c", "tests/input_model.c"):
        raw = (sources / name).read_bytes()
        source_pins["prototype/phase4-platform/" + name] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    result = {"passed": True, "checked_utc": stamp, "python_files_parsed": parser_count, "shell_files_parsed": shell_count,
        "compiler_version": compiler_version, "sources": source_pins,
        "suites": suites, "commands": commands, "device_operations": False,
        "scope": "host syntax, boot parser tests and ASan/UBSan protocol models; no hardware gate"}
    (work / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "commands"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
