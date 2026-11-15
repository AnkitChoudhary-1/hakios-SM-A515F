#!/usr/bin/env python3
"""Export a reviewed, text-only work package without changing the working port.

Run in A51-KernelBuilder through scripts/run.py. This script never uses ADB,
boots a payload, or pushes Git. Raw evidence and external dependencies stay local.
"""
from __future__ import annotations

import argparse
import datetime as dt
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

PROJECT = Path(__file__).resolve().parents[1]
COMMON_COMMIT = "63fc2b4633bac3af8e57dadab9f5a8d4cb940438"
XNU_COMMIT = "c54f35ca767986246321eb901baf8f5ff7923f6a"
SERIAL_PATTERN = re.compile(r"\bRZ[0-9A-Z]{9,14}\b")
MAC_PATTERN = re.compile(r"\b(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\b")
SUFFIXES = {".py", ".sh", ".c", ".h", ".cpp", ".S", ".s", ".ld", ".md", ".json", ".tsv", ".config", ".patch", ".def", ".cmd", ".conf", ".inc"}
SOURCE_DIRS = ("scripts", "prototype", "diagnostics", "drivers", "userland", "docs")
EXCLUDED_PARTS = {"__pycache__", ".git", "prebuilt", "Binaries", "firmware", "fw-a51", "BUILD", "EXPORT_HDRS", "OBJ", "SYM"}
SECRET_PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "github_token": re.compile(r"\b(?:github_pat_[A-Za-z0-9_]{30,}|gh[pousr]_[A-Za-z0-9]{30,})\b"),
    "aws_access_key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "google_api_key": re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    "credential_url": re.compile(r"https?://[^\s/@]+:[^\s/@]+@"),
}


def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def stable_read(path):
    raw = path.read_bytes()
    if path.read_bytes() != raw:
        raise ValueError("File changed during capture: " + str(path))
    return raw


def allowed(path):
    return (path.suffix in SUFFIXES or path.name in {"Makefile", "conf", "map", "files", "MASTER", ".config", "device.conf", "a51_defconfig"}
            or path.name.startswith(("files.", "MASTER."))) and not any(
        word in path.parts for word in EXCLUDED_PARTS)


def sanitize(text, markdown_path=None):
    text = SERIAL_PATTERN.sub("A51_SERIAL_HERE", text)
    text = MAC_PATTERN.sub("MAC_ADDRESS_REDACTED", text)
    if markdown_path is not None:
        # Repair app-local Markdown links while retaining historical prose/commands.
        def link(match):
            label, target = match.groups()
            plain = target.strip("<>").replace("\\", "/")
            if "/hakios-a51/" in plain:
                relative = plain.split("/hakios-a51/", 1)[1]
                relative = re.sub(r":\d+$", "", relative)
                if relative.startswith(("evidence/", "runs/", "artifacts/")):
                    relative = "docs/PUBLICATION.md"
                return "[" + label + "](" + os.path.relpath(relative, str(markdown_path.parent)).replace("\\", "/") + ")"
            if "/hakios-assessment/ROADMAP.md" in plain:
                return "[" + label + "](" + os.path.relpath("docs/ROADMAP.md", str(markdown_path.parent)).replace("\\", "/") + ")"
            if plain.endswith("/AGENTS.md") and not plain.startswith("http"):
                return "[" + label + "](" + os.path.relpath("AGENTS.md", str(markdown_path.parent)).replace("\\", "/") + ")"
            if re.match(r"/?[A-Za-z]:/", plain):
                return label + " (external local reference; see PUBLICATION.md)"
            return match.group(0)
        text = re.sub(r"\[([^\]\n]+)\]\(([^\)\n]+)\)", link, text)
    return text


def git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
    return result.stdout


def candidates(root):
    names = set(git(root, "diff", "HEAD", "--name-only", "-z").decode().split("\0"))
    names.update(git(root, "ls-files", "--others", "--exclude-standard", "-z").decode().split("\0"))
    names.discard("")
    return names


def scan_tree(destination):
    failures, count = [], 0
    for path in sorted(destination.rglob("*")):
        relative_path = path.relative_to(destination)
        if not path.is_file() or ".git" in relative_path.parts or "__pycache__" in relative_path.parts or relative_path.parts[:2] == ("validation", "local"):
            continue
        relative = path.relative_to(destination).as_posix()
        raw = path.read_bytes()
        content = raw.decode("utf-8")
        count += 1
        if "\0" in content or SERIAL_PATTERN.search(content) or MAC_PATTERN.search(content):
            failures.append({"path": relative, "kind": "binary_or_device_identifier"})
        for kind, pattern in SECRET_PATTERNS.items():
            if pattern.search(content):
                failures.append({"path": relative, "kind": kind})
        if path.suffix == ".json":
            json.loads(content)
    return {"files_checked": count, "failures": failures, "passed": not failures}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", required=True)
    args = parser.parse_args()
    destination = Path(args.destination).resolve()
    expected_parent = (PROJECT / "publication").resolve()
    if expected_parent not in destination.parents or not (destination / ".git").is_dir():
        raise ValueError("Destination must be an existing clone below this project's publication directory")
    existing = [path for path in destination.iterdir() if path.name != ".git"]
    if existing:
        raise ValueError("Refuse to overwrite a populated publication clone")

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    private_record = PROJECT / "evidence/publication" / stamp
    private_record.mkdir(parents=True, exist_ok=False)
    exports, inputs, patch_records = [], {}, {}
    captured_paths, exported_paths = {}, set()
    templates = PROJECT / "publication/templates"
    template_paths = {source.relative_to(templates).as_posix() for source in templates.rglob("*") if source.is_file()}

    def capture(path, origin):
        raw = stable_read(path)
        if origin in inputs and inputs[origin] != pin(raw):
            raise ValueError("Source changed between captures: " + origin)
        inputs[origin] = pin(raw)
        captured_paths[path] = pin(raw)
        return raw

    def emit(relative, raw, origin=None, original=None):
        if relative in exported_paths:
            raise ValueError("Duplicate export: " + relative)
        exported_paths.add(relative)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        text = raw.decode("utf-8")
        if "\0" in text or len(raw) > 8 * 1024 * 1024:
            raise ValueError("Non-text or oversized export: " + relative)
        clean = sanitize(text, Path(relative) if relative.endswith(".md") else None).replace("\r\n", "\n").encode("utf-8")
        target.write_bytes(clean)
        row = {"path": relative, **pin(clean)}
        if origin:
            row.update(origin=origin, original=pin(original if original is not None else raw), transformed=(clean != (original if original is not None else raw)))
        exports.append(row)

    # Capture source families first, independently of changing build output files.
    for directory in SOURCE_DIRS:
        for source in sorted((PROJECT / directory).rglob("*")):
            if source.is_file() and allowed(source):
                rel = source.relative_to(PROJECT).as_posix()
                if rel in template_paths:
                    continue
                raw = capture(source, "hakios-a51/" + rel)
                original = raw
                if source.suffix == ".md":
                    parent = str(Path(rel).parent)
                    status_link = os.path.relpath("docs/PUBLIC-STATUS.md", parent).replace("\\", "/")
                    scope_link = os.path.relpath("docs/PUBLICATION.md", parent).replace("\\", "/")
                    note = ("> Publication note: this is a historical workspace document. "
                            f"Current completion decisions are in [PUBLIC-STATUS.md]({status_link}); "
                            f"raw local evidence is described in [PUBLICATION.md]({scope_link}).\n\n")
                    if directory == "docs":
                        raw = note.encode() + raw
                emit(rel, raw, "hakios-a51/" + rel, original=original)

    for name in ("source-lock.json", "dependencies.json", "ubuntu-packages.tsv",
                 "phase3-platform-adaptation.json", "phase3-platform-build.json", "phase3-platform-qemu.json",
                 "phase4-platform-adaptation.json", "phase4-platform-build.json", "phase4-platform-qemu.json",
                 "phase4-peripheral-native-tests.json", "phase4-readonly-revision.json"):
        source = PROJECT / "manifests" / name
        raw = capture(source, "hakios-a51/manifests/" + name)
        emit("manifests/" + name, raw, "hakios-a51/manifests/" + name)

    root = Path("/opt/a51-hakios/src/hakios-xnu-kernel")
    if git(root, "rev-parse", "HEAD").decode().strip() != COMMON_COMMIT:
        raise ValueError("Unexpected common baseline commit")
    native_base = root / "xnu-src/xnu-8796.121.2"
    if git(native_base, "rev-parse", "HEAD").decode().strip() != XNU_COMMIT:
        raise ValueError("Unexpected XNU baseline commit")
    common_tracked = set(git(root, "ls-tree", "-r", "--name-only", "-z", COMMON_COMMIT).decode().split("\0"))
    for phase in (3, 4):
        manifest = json.loads((destination / f"manifests/phase{phase}-platform-adaptation.json").read_text())
        port = Path(manifest["root"])
        native = port / "xnu-src/xnu-8796.121.2"
        if git(port, "rev-parse", "HEAD").decode().strip() != COMMON_COMMIT:
            raise ValueError("Unexpected port common commit")
        if git(native, "rev-parse", "HEAD").decode().strip() != XNU_COMMIT:
            raise ValueError("Unexpected port XNU commit")
        for label, baseline, modified in (("common", root, port), ("xnu", native_base, native)):
            names = candidates(modified)
            if label == "common":
                names.update(("devices/a51/device.conf", "devices/a51/configs/a51_defconfig"))
            diffs, rows = [], []
            for name in sorted(names):
                relative = Path(name)
                if not allowed(relative) or name.startswith(("xnu-src/", "xnu-deps/", "hakios-metal/")):
                    continue
                old_path, new_path = baseline / name, modified / name
                before_exists = name in common_tracked if label == "common" else old_path.is_file()
                if label == "common":
                    before = git(root, "show", COMMON_COMMIT + ":" + name) if before_exists else b""
                else:
                    before = capture(old_path, "baseline-xnu/" + name) if before_exists else b""
                after = capture(new_path, f"phase{phase}-{label}/" + name) if new_path.is_file() else b""
                if before == after:
                    continue
                before_text, after_text = before.decode("utf-8"), after.decode("utf-8")
                if "\0" in before_text or "\0" in after_text:
                    raise ValueError("Binary port difference: " + name)
                for line in difflib.unified_diff(before_text.splitlines(True), after_text.splitlines(True),
                    fromfile="a/" + name if before_exists else "/dev/null",
                    tofile="b/" + name if new_path.is_file() else "/dev/null"):
                    diffs.append(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n")
                rows.append({"path": name, "before_exists": before_exists, "before": pin(before),
                             "after_exists": new_path.is_file(), "after": pin(after)})
            patch_name = f"patches/phase{phase}-{label}.patch"
            emit(patch_name, "".join(diffs).encode())
            patch_records[patch_name] = {"base": "pinned common checkout with upstream xnu/apply.sh already applied" if label == "xnu" else COMMON_COMMIT,
                                        "files": rows, "cumulative_from_phase1": True, "hardware_gate_inferred": False}
            if label == "common":
                for name in ("devices/a51/device.conf", "devices/a51/configs/a51_defconfig"):
                    raw = capture(modified / name, f"phase{phase}-common/" + name)
                    emit(f"port/phase{phase}/" + name, raw, f"phase{phase}-common/" + name)

    # Source the license texts; proprietary SDKs and firmware are never copied.
    for rel, source in (("LICENSES/HakiOS-MIT.txt", root / "LICENSE"),
                        ("LICENSE.APSL", root / "LICENSE.APSL"),
                        ("LICENSES/GPL-2.0.txt", Path("/usr/share/common-licenses/GPL-2"))):
        raw = capture(source, "license-source/" + source.name)
        emit(rel, raw, "license-source/" + source.name)

    phase3_path = PROJECT / "evidence/phase-3/repeatability/20261114T132905926137Z/consecutive_runs_summary.json"
    phase3_raw = capture(phase3_path, phase3_path.relative_to(PROJECT).as_posix())
    phase3 = json.loads(phase3_raw)
    rows = []
    for record in phase3["results"]:
        selected = {key: record[key] for key in ("cycle", "stamp", "nonce", "candidate_sha256", "rollback_sha256",
            "baseline_verified_pre_flash", "candidate_verified_on_silicon", "baseline_verified_post_boot", "reconnect_mode",
            "boot_duration_seconds", "probe_executed", "nonce_matched", "user_program_executed", "user_program_exited",
            "timers_verified", "qualifying_cycle_passed") if key in record}
        selected["selected_observed_lines"] = [line for line in record.get("hakios_records", [])
            if re.search(r"HAKIOS_OUT: (?:HAKIOS_(?:USER_BEGIN|RUN_NONCE|PLATFORM|TIMER_SAMPLE|TIMER_PASS|USER_EXIT)|kernel\.ver=)", line)]
        rows.append(selected)
    phase3_summary = {key: phase3[key] for key in ("timestamp", "cycles_requested", "cycles_completed", "all_cycles_passed", "gate_criteria")}
    phase3_summary.update(results=rows, original_report=pin(phase3_raw), publication_is_derived_summary=True, complete_raw_replay_available=False)
    emit("validation/phase3-device-summary.json", (json.dumps(phase3_summary, indent=2) + "\n").encode())

    state_path = PROJECT / "state.json"
    state_raw = capture(state_path, "hakios-a51/state.json")
    state = json.loads(state_raw)
    if state.get("phase_4_device_gate_passed") is not False or state.get("phase_4_status") != "in_progress":
        raise ValueError("Phase 4 status changed; review the public status templates before publication")
    public_state = {key: state[key] for key in ("target", "active_phase", "phase_1_status", "phase_2_status", "phase_3_status",
        "phase_4_status", "planned_phases", "a51_xnu_boot_verified", "no_flash_a51_launch_verified",
        "phase_2_device_gate_passed", "phase_3_device_gate_passed", "phase_4_device_gate_passed", "phase_4_criteria") if key in state}
    public_state.update(publication_captured_utc=stamp, original_state=pin(state_raw), scope="selected current decisions; historical machine state remains local")
    emit("state.json", (json.dumps(public_state, indent=2) + "\n").encode())
    roadmap = PROJECT.parent / "hakios-assessment/ROADMAP.md"
    raw = capture(roadmap, "hakios-assessment/ROADMAP.md")
    note = "> Historical plan: use PUBLIC-STATUS.md for the current evidence and completion decisions.\n\n"
    emit("docs/ROADMAP.md", note.encode() + raw, "hakios-assessment/ROADMAP.md", original=raw)

    # Maintainer-facing documents are templates, kept outside the live port.
    for source in sorted(templates.rglob("*")):
        if source.is_file():
            rel = source.relative_to(templates).as_posix()
            if (destination / rel).exists():
                raise ValueError("Template would overwrite an exported file: " + rel)
            raw = capture(source, "publication-template/" + rel)
            emit(rel, raw, "publication-template/" + rel)

    # A separate root device descriptor reports only observed device behavior.
    device = (destination / "port/phase4/devices/a51/device.conf").read_text()
    device = device.replace("maintainer  HakiOS Team", "maintainer  AnkitChoudhary-1")
    device += "\tstatus      cpu         partial   One Cortex-A53 CPU, XNU PID 1/timers and recovery return verified; SMP unverified\n"
    emit("device.conf", device.encode())
    emit("configs/a51_defconfig", (destination / "port/phase4/devices/a51/configs/a51_defconfig").read_bytes())

    # Historical links to excluded local inputs should explain their absence.
    link_repairs = []
    for row in exports:
        relative = row["path"]
        if not relative.endswith(".md"):
            continue
        target_file = destination / relative
        def repair_link(match):
            label, target = match.groups()
            plain = target.strip("<>").split("#", 1)[0]
            if not plain or "://" in plain or plain.startswith("mailto:"):
                return match.group(0)
            if (target_file.parent / plain).exists():
                return match.group(0)
            replacement = os.path.relpath(destination / "docs/PUBLICATION.md", target_file.parent).replace("\\", "/")
            link_repairs.append({"path": relative, "missing_target": target, "redirected_to": replacement})
            return "[" + label + "](" + replacement + ")"
        content = target_file.read_text(encoding="utf-8")
        repaired = re.sub(r"\[([^\]\n]+)\]\(([^\)\n]+)\)", repair_link, content).encode("utf-8")
        if repaired != target_file.read_bytes():
            target_file.write_bytes(repaired)
            row.update(pin(repaired), transformed=True)

    # Detect concurrent source/manifest edits across the complete capture.
    for path, expected in captured_paths.items():
        if pin(stable_read(path)) != expected:
            raise ValueError("Input changed during publication capture: " + str(path))
    consistency = {}
    model_manifest = json.loads((destination / "manifests/phase4-peripheral-native-tests.json").read_text())
    consistency["historical_native_models_match_captured_sources"] = {
        name: inputs["hakios-a51/prototype/phase4-platform/" + name] == expected
        for name, expected in model_manifest["sources"].items()}
    consistency["phase4_template_matches_adapted_driver"] = {
        name: inputs["hakios-a51/prototype/phase4-platform/" + name] == inputs["phase4-common/drivers/core/" + name]
        for name in ("hakios.a51.c", "hakios.a51.h", "a51_ufs_readonly.h", "a51_input.h")}
    report = {"schema_version": 1, "captured_utc": stamp, "repository": "https://github.com/AnkitChoudhary-1/hakios-SM-A515F",
        "files": exports, "inputs": inputs, "patches": patch_records,
        "source_consistency": consistency, "capture_inputs_stable": True, "historical_link_repairs": link_repairs,
        "manifest_excluded_from_own_file_hashes": True,
        "excluded": ["complete evidence and run trees", "device/partition backups", "firmware", "Apple runtime and SDK files",
                     "binary build outputs", "unrelated Android projects", "personal device serials and MAC addresses"],
        "phase4_hardware_gate_passed": False, "existing_phone_operations": False}
    public_report = destination / "PUBLICATION-MANIFEST.json"
    public_report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    report["scan"] = scan_tree(destination)
    public_report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if scan_tree(destination) != report["scan"]:
        raise ValueError("Publication changed during final scan")
    (private_record / "export.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"packet": private_record.relative_to(PROJECT).as_posix(), "files": report["scan"]["files_checked"],
        "patches": {name: len(value["files"]) for name, value in patch_records.items()}, "scan": report["scan"]}, indent=2))
    return 0 if report["scan"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
