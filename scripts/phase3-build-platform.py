#!/usr/bin/env python3
"""Build the isolated Phase 3 kernel and timer-verification user program."""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

PROJECT = Path(__file__).resolve().parents[1]


def pin(path):
    raw = path.read_bytes()
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def main():
    workspace = json.loads((PROJECT / "manifests/phase3-workspace.json").read_text())
    root = Path(workspace["root"]).resolve()
    assert root.is_relative_to(Path("/opt/a51-hakios/experimental/phase3-port"))
    adaptation = json.loads((PROJECT / "manifests/phase3-platform-adaptation.json").read_text())
    for change in adaptation["changes"]:
        tree = root / "xnu-src/xnu-8796.121.2" if change["tree"] == "native" else root
        assert pin(tree / change["path"]) == change["after"], change["path"]
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    packet = PROJECT / "evidence/phase-3/platform-build" / stamp
    packet.mkdir(parents=True, exist_ok=False)
    for rel in ("hakios-kernel", "userland/hello", "xnu-build.log", ".config"):
        path = root / rel
        if path.is_file():
            dest = packet / "before" / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
    shutil.copy2(Path(__file__), packet / "source.py")
    env = dict(os.environ, THEOS="/opt/a51-hakios/theos",
               MAKEFLAGS="MAKEJOBS=--jobs=2 SHELL=/bin/bash",
               PATH="/usr/lib/llvm-18/bin:" + os.environ["PATH"])
    result = {"schema_version": 1, "root": str(root), "packet": str(packet.relative_to(PROJECT)),
              "commands": [], "build_verified": False, "device_operations": False,
              "phase_3_device_gate_passed": False}
    try:
        for label, argv in (
            ("kernel", ["bash", "tools/make-kernel.sh", "-j2", "MAKEJOBS=--jobs=2", "SHELL=/bin/bash"]),
            ("hello", ["make", "hello", "SHELL=/bin/bash"]),
            ("artifact-identification", ["file", "hakios-kernel", "userland/hello"]),
        ):
            print("COMMAND " + label + " " + repr(argv), flush=True)
            command = {"label": label, "argv": argv, "started_utc": dt.datetime.now(dt.timezone.utc).isoformat()}
            result["commands"].append(command)
            with (packet / (label + ".log")).open("wb") as log:
                child = subprocess.Popen(argv, cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                for line in iter(child.stdout.readline, b""):
                    log.write(line)
                    log.flush()
                    print(line.decode(errors="replace"), end="", flush=True)
                command["exit_code"] = child.wait()
            command["finished_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
            if command["exit_code"]:
                raise RuntimeError(label + " failed")
        result["artifacts"] = {}
        for rel in ("hakios-kernel", "userland/hello", ".config", "xnu-build.log"):
            path = root / rel
            dest = packet / "artifacts" / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
            result["artifacts"][rel] = pin(dest)
        result["build_verified"] = True
    except Exception as exc:
        result["error"] = str(exc)
    finally:
        (packet / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        (PROJECT / "manifests/phase3-platform-build.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if result["build_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
