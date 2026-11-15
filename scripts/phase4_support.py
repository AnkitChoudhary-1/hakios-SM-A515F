"""Phase 4 provenance, command and document helpers. No device actions on import."""
from __future__ import annotations
import datetime as dt
import difflib
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

PROJECT = Path(__file__).resolve().parents[1]

def require(condition, message):
    if not condition:
        raise ValueError(message)

def pin(path):
    raw = Path(path).read_bytes()
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}

def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

def new_packet(kind, source):
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    packet = PROJECT / "evidence/phase-4" / kind / stamp
    packet.mkdir(parents=True, exist_ok=False)
    shutil.copy2(source, packet / "source.py")
    shutil.copy2(__file__, packet / "phase4_support.py")
    return packet

def index_packet(packet):
    write_json(packet / "index.json", [
        {"path": p.relative_to(packet).as_posix(), **pin(p)}
        for p in sorted(packet.rglob("*")) if p.is_file() and p != packet / "index.json"
    ])

def command(packet, records, name, argv, timeout=45, cwd=None, env=None, check=True):
    started = dt.datetime.now(dt.timezone.utc).isoformat()
    try:
        proc = subprocess.run(argv, capture_output=True, timeout=timeout, cwd=cwd, env=env)
    except subprocess.TimeoutExpired as exc:
        proc = subprocess.CompletedProcess(argv, 124, exc.stdout or b"", (exc.stderr or b"") + b"\ntimeout")
    (packet / (name + ".stdout")).write_bytes(proc.stdout)
    (packet / (name + ".stderr")).write_bytes(proc.stderr)
    records.append({"name": name, "argv": argv, "cwd": str(cwd) if cwd else None,
        "started": started, "finished": dt.datetime.now(dt.timezone.utc).isoformat(),
        "exit_code": proc.returncode, "stdout": pin(packet / (name + ".stdout")),
        "stderr": pin(packet / (name + ".stderr"))})
    write_json(packet / "commands.json", records)
    print(json.dumps({"command": name, "exit_code": proc.returncode,
        "stdout_bytes": len(proc.stdout), "stderr_bytes": len(proc.stderr)}), flush=True)
    if check and proc.returncode:
        raise RuntimeError(f"{name} failed, exit {proc.returncode}: {packet}")
    return proc

def documents(packet, replacements):
    changes = []
    patches = []
    for rel, new in replacements.items():
        path = PROJECT / rel
        old = path.read_bytes() if path.exists() else b""
        new = new.encode("utf-8")
        if old == new:
            continue
        for label, raw in (("before", old), ("after", new)):
            dest = packet / label / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(raw)
        path.write_bytes(new)
        changes.append({"path": rel, "before": pin(packet / "before" / rel), "after": pin(path)})
        patches.append("".join(difflib.unified_diff(old.decode("utf-8").splitlines(True),
            new.decode("utf-8").splitlines(True), fromfile="a/"+rel, tofile="b/"+rel)))
    write_json(packet / "document-changes.json", changes)
    (packet / "documents.patch").write_text("".join(patches), encoding="utf-8")
