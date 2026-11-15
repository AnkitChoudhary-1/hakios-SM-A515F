#!/usr/bin/env python3
"""Check each existing WSL tool with argv, without shell pipelines.

Use scripts/run.py. This does not install tools or contact a phone.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

TOOLS = ("clang-18", "ld.lld-18", "llvm-objcopy-18", "llvm-nm-18",
         "llvm-objdump-18", "llvm-readelf-18", "qemu-system-aarch64")


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def check_tools() -> dict:
    result = {"schema_version": 1, "scope": "host_tool_availability_only",
              "started_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
              "cwd": str(Path.cwd()), "tools": [], "status": "passed",
              "phone_queries": False, "phone_writes": False,
              "phase_2_device_gate_passed": False}
    if os.name != "posix":
        result["status"] = "failed"
        result["error"] = "Run inside A51-KernelBuilder WSL."
        return result
    for name in TOOLS:
        found = shutil.which(name)
        entry = {"name": name, "path": found, "argv": [name, "--version"]}
        try:
            if found is None:
                raise FileNotFoundError(name)
            path = Path(found).resolve(strict=True)
            entry.update(resolved_path=str(path), sha256=digest(path), bytes=path.stat().st_size)
            proc = subprocess.run(entry["argv"], stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, timeout=10, check=False)
            entry.update(exit_code=proc.returncode,
                         version=proc.stdout.decode("utf-8", errors="replace").strip())
            if proc.returncode != 0 or not proc.stdout.strip():
                raise ValueError("nonzero exit or empty version")
            entry["status"] = "passed"
        except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
            entry.update(status="failed", error=str(exc))
            result["status"] = "failed"
        result["tools"].append(entry)
    result["finished_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
    return result


if __name__ == "__main__":
    report = check_tools()
    print(json.dumps(report, indent=2, sort_keys=True))
    raise SystemExit(0 if report["status"] == "passed" else 1)
