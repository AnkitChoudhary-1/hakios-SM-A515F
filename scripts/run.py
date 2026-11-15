#!/usr/bin/env python3
r"""Capture an exact command, merged output, timestamps and exit code.

PowerShell example:
  python .\scripts\run.py --label inventory -- python .\scripts\inventory.py
Arguments after -- are passed directly to subprocess, without a shell.
"""
import argparse
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
IST = dt.timezone(dt.timedelta(hours=5, minutes=30), "IST")


def stamp():
    now = dt.datetime.now(dt.timezone.utc)
    return {"utc": now.isoformat(), "ist": now.astimezone(IST).isoformat()}


def main():
    # WSL/package output contains Unicode; Windows pipe defaults may be cp1252.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--cwd", default=str(PROJECT))
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("provide a command after --")
    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + re.sub(r"[^a-zA-Z0-9_-]", "-", args.label)
    folder = PROJECT / "runs" / run_id
    folder.mkdir(parents=True, exist_ok=False)
    record = {"schema_version": 1, "run_id": run_id, "label": args.label,
              "cwd": str(Path(args.cwd).resolve()), "command": command,
              "started": stamp(), "status": "running"}
    meta = folder / "metadata.json"
    meta.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    # Preserve the actual wrapper versions used by each future run.
    script_snapshot = folder / "project-scripts"
    script_snapshot.mkdir()
    for script in (PROJECT / "scripts").iterdir():
        if script.is_file():
            shutil.copy2(script, script_snapshot / script.name)
    print("RUN " + run_id, flush=True)
    print("LOG " + str(folder / "output.log"), flush=True)
    try:
        with (folder / "output.log").open("wb") as log:
            proc = subprocess.Popen(command, cwd=args.cwd, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, shell=False)
            assert proc.stdout is not None
            for chunk in iter(proc.stdout.readline, b""):
                log.write(chunk)
                log.flush()
                sys.stdout.write(chunk.decode("utf-8", errors="replace").replace("\x00", ""))
                sys.stdout.flush()
            record["exit_code"] = proc.wait()
        record["status"] = "passed" if record["exit_code"] == 0 else "failed"
    except OSError as exc:
        record.update(status="failed", exit_code=127, error=str(exc))
        (folder / "output.log").write_text(str(exc) + "\n", encoding="utf-8")
    record["finished"] = stamp()
    meta.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    with (PROJECT / "runs" / "events.jsonl").open("a", encoding="utf-8") as events:
        events.write(json.dumps(record) + "\n")
    print("RESULT " + record["status"] + " exit=" + str(record["exit_code"]), flush=True)
    return record["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
