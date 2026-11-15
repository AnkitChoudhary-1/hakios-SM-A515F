"""Shared byte-preserving evidence helpers for the Phase 3 continuation."""
from __future__ import annotations

import datetime as dt
import difflib
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

PROJECT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def pin(path: Path) -> dict:
    raw = path.read_bytes()
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def json_write(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def packet_new(kind: str, source: Path) -> Path:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    packet = PROJECT / "evidence/phase-3" / kind / stamp
    packet.mkdir(parents=True, exist_ok=False)
    shutil.copy2(source, packet / "source.py")
    shutil.copy2(__file__, packet / "phase3_support.py")
    return packet


def packet_index(packet: Path) -> None:
    json_write(packet / "index.json", [
        {"path": p.relative_to(packet).as_posix(), **pin(p)}
        for p in sorted(packet.rglob("*")) if p.is_file() and p != packet / "index.json"
    ])


def packet_verify(packet: Path) -> None:
    for item in json.loads((packet / "index.json").read_text(encoding="utf-8")):
        path = packet / item["path"]
        require(path.is_file() and pin(path) == {k: item[k] for k in ("bytes", "sha256")},
                "Evidence checksum mismatch: " + str(path))


def command(packet: Path, records: list, name: str, argv: list[str], timeout=45,
            cwd=None, env=None, check=True) -> subprocess.CompletedProcess:
    require(all(isinstance(s, str) for s in argv), "Command arguments must be strings")
    started = dt.datetime.now(dt.timezone.utc).isoformat()
    try:
        proc = subprocess.run(argv, capture_output=True, timeout=timeout, cwd=cwd, env=env)
    except subprocess.TimeoutExpired as exc:
        proc = subprocess.CompletedProcess(argv, 124, exc.stdout or b"", (exc.stderr or b"") + b"\ntimeout")
    (packet / (name + ".stdout")).write_bytes(proc.stdout)
    (packet / (name + ".stderr")).write_bytes(proc.stderr)
    record = {"name": name, "argv": argv, "cwd": str(cwd) if cwd else None,
              "started": started, "finished": dt.datetime.now(dt.timezone.utc).isoformat(),
              "exit_code": proc.returncode, "stdout": pin(packet / (name + ".stdout")),
              "stderr": pin(packet / (name + ".stderr"))}
    records.append(record)
    json_write(packet / "commands.json", records)
    print(json.dumps({"command": name, "exit_code": proc.returncode,
                      "stdout_bytes": len(proc.stdout), "stderr_bytes": len(proc.stderr)}), flush=True)
    if check and proc.returncode:
        raise RuntimeError(f"{name} failed, exit {proc.returncode}; retained original output in {packet}")
    return proc


def update_documents(packet: Path, replacements: dict[str, str]) -> None:
    # Decode all original files before the first mutation, retaining exact bytes.
    originals = {rel: (PROJECT / rel).read_bytes() for rel in replacements}
    for data in originals.values():
        data.decode("utf-8")
    changes, patches = [], []
    for rel, text in replacements.items():
        old, new = originals[rel], text.encode("utf-8")
        if old == new:
            continue
        for label, data in (("before", old), ("after", new)):
            copy = packet / label / rel
            copy.parent.mkdir(parents=True, exist_ok=True)
            copy.write_bytes(data)
        (PROJECT / rel).write_bytes(new)
        changes.append({"path": rel, "before": pin(packet / "before" / rel),
                        "after": pin(PROJECT / rel)})
        patches.append("".join(difflib.unified_diff(old.decode("utf-8").splitlines(True),
            text.splitlines(True), fromfile="a/" + rel, tofile="b/" + rel)))
    json_write(packet / "changes.json", changes)
    (packet / "adaptations.patch").write_text("".join(patches), encoding="utf-8")
