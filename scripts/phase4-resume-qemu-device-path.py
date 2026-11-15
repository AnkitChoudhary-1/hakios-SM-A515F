#!/usr/bin/env python3
"""Resume a pinned Phase 4 QEMU review without rerunning accepted executions."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from phase4_support import PROJECT, documents, index_packet, new_packet, pin, require, write_json


def module(name, path):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def main():
    if os.name == "nt":
        source = "/mnt/c" + str(Path(__file__).resolve()).replace("\\", "/")[2:]
        return subprocess.call(["wsl", "-d", "A51-KernelBuilder", "--exec", "python3", "-B", source, *sys.argv[1:]])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", required=True)
    parser.add_argument("--seconds", type=int, default=120)
    args = parser.parse_args()
    require(15 <= args.seconds <= 300, "Invalid execution deadline")
    cycle = module("phase4_resume_cycle", PROJECT / "scripts/phase4-device-cycle.py")
    runner = module("phase4_resume_runner", PROJECT / "scripts/phase4-qemu-device-path.py")
    adapter = module("phase4_resume_adapter", PROJECT / "scripts/phase4-qemu-platform.py")
    retainer = module("phase4_resume_retainer", PROJECT / "scripts/phase4-retain-qemu-scratch.py")
    packet = new_packet("complete-loader-qemu-review", __file__)
    results, reused, failures = {}, [], []
    review = {"schema_version": 1, "packet": packet.relative_to(PROJECT).as_posix(),
              "passed": False, "suite_complete": False, "results": [],
              "device_operations": False, "phase_4_gate_passed": False}
    required = [(case, placement) for placement in runner.PLACEMENTS for case in runner.CASES]
    try:
        previous_path = cycle.resolve_file(PROJECT, args.review)
        cycle.verify_packet(previous_path.parent)
        previous = json.loads(previous_path.read_text(encoding="utf-8"))
        require(previous["packet"] == previous_path.parent.relative_to(PROJECT).as_posix(), "Review identity differs")
        review["resumed_review"] = {"path": args.review, **pin(previous_path)}
        shutil.copy2(previous_path, packet / "previous-review.json")
        selected = json.loads((PROJECT / "manifests/phase4-loader-qemu.json").read_text(encoding="utf-8"))
        require(selected["passed"] and selected["schema_version"] == 2 and selected["mode"] == "qemu" and
                selected["diagnostic"] == 0, "Wrong selected loader")
        cycle.verify_packet(PROJECT / selected["packet"])
        require(json.loads((PROJECT / selected["packet"] / "result.json").read_text(encoding="utf-8")) == selected,
                "Loader selection differs from its original result")
        for name, expected in selected["sources"].items():
            require(pin(cycle.resolve_file(PROJECT / "prototype/phase4-loader", name)) == expected,
                    "Current loader source changed: " + name)
        for name in ("loader.Image", "loader.elf", "payload.bin"):
            require(pin(Path(selected["work"]) / name) == selected["outputs"][name], "Build input changed: " + name)
        write_json(packet / "selected-loader.json", selected)
        for name in ("phase4-qemu-device-path.py", "phase4-device-cycle.py", "phase4-qemu-platform.py",
                     "phase4-retain-qemu-scratch.py", "phase4_envelope.py"):
            shutil.copy2(PROJECT / "scripts" / name, packet / name)
        seen = set()
        for row in previous["results"]:
            pair = (row["case"], row["placement"])
            require(pair in required and pair not in seen, "Unknown or duplicate previous case")
            seen.add(pair)
            original = cycle.checked_file(PROJECT, {"path": row["result"], **{k: row[k] for k in ("bytes", "sha256")}})
            cycle.verify_packet(original.parent)
            case = json.loads(original.read_text(encoding="utf-8"))
            require(case["packet"] == original.parent.relative_to(PROJECT).as_posix() and
                    case["case"] == pair[0] and case["load_address"] == pair[1] and
                    case["passed"] == row["passed"], "Case identity/outcome disagrees with review")
            if row["passed"] is not True:
                failures.append(row)
                continue
            require(case["execution_passed"] and case["qemu_exit_code"] == 0 and case["checks"] and
                    all(value is True for value in case["checks"].values()), "Previous execution checks failed")
            require(json.loads((original.parent / "selected-loader.json").read_text(encoding="utf-8")) == selected,
                    "Previous case used a different build, nonce or platform")
            require(pin(original.parent / "source.py") == pin(PROJECT / "scripts/phase4-qemu-device-path.py"),
                    "Previous execution used a different harness")
            for name in ("phase4_envelope.py", "phase4-qemu-platform.py", "phase4-retain-qemu-scratch.py"):
                require(pin(original.parent / name) == pin(PROJECT / "scripts" / name), "Case helper differs: " + name)
            require(pin(original.parent / "firmware.S") == pin(PROJECT / "prototype/phase4-loader/qemu_firmware.S"),
                    "Case firmware differs")
            cycle.verify_archives(original.parent, case)
            results[pair] = row
            reused.append(row["result"])
        review.update(reused_results=reused, preserved_failed_results=failures)
        print(json.dumps({"verified_reused_cases": len(reused), "pending_cases": len(required) - len(reused)}), flush=True)
        for case, placement in required:
            if (case, placement) in results:
                continue
            outcome = runner.run_case(selected, adapter, retainer, case, placement, args.seconds)
            row = {"case": case, "placement": placement, "passed": outcome["passed"],
                   "result": outcome["packet"] + "/result.json", **pin(PROJECT / outcome["packet"] / "result.json")}
            results[(case, placement)] = row
            review["results"] = [results[pair] for pair in required if pair in results]
            write_json(packet / "progress.json", review)
            if not outcome["passed"]:
                review["error"] = outcome.get("error", "Execution checks failed")
                break
        review["results"] = [results[pair] for pair in required if pair in results]
        review["passed"] = review["suite_complete"] = (len(results) == len(required) and
            all(row["passed"] for row in results.values()) and "error" not in review)
    except Exception as exc:
        review.update(error=str(exc), results=[results[pair] for pair in required if pair in results])
    write_json(packet / "result.json", review)
    # A rejected aggregation must never replace an already accepted selection.
    if "reused_results" in review:
        write_json(PROJECT / "manifests/phase4-complete-loader-qemu.json", review)
    state = json.loads((PROJECT / "state.json").read_text(encoding="utf-8"))
    if "reused_results" in review:
        state["phase_4_complete_loader_qemu"] = {"result": review["packet"] + "/result.json",
            "passed": review["passed"], "suite_complete": review["suite_complete"]}
    note = (f"\n\n## P4-024 — Resume exact matching QEMU evidence ({packet.name})\n\n"
        "Purpose/files: add scripts/phase4-resume-qemu-device-path.py; retain its source, original review and exact selected loader. "
        "Accept prior executions only after checking the indexed packets, result pins, identical build/nonce/platform, current loader/harness/helper/firmware bytes, "
        "every execution check, clean QEMU exit and decompressed execution/prefill/readback archives. Reject duplicate/unknown cases and mixed builds. "
        "Run only missing or previously failed cases with the unchanged harness; preserve all failures and write a pinned ordered aggregate. "
        "The preceding 60-case run stopped after 30 passing executions on the 1 GiB capacity prerequisite; no case-31 execution occurred. "
        "Lossless NTFS evidence compression completed in runs/20261114T230911983025Z-phase4-lossless-evidence-compression, recovering about 660 MiB without changing file bytes.\n\n"
        f"Verification: reused={len(reused)}, aggregate cases={len(results)}, passed={review['passed']}, suite_complete={review['suite_complete']}; "
        f"error={review.get('error')}. Exact originals and new results are pinned in `{review['packet']}/result.json`. "
        "No device operations occurred; hardware gates remain false.\n\n"
        "Limitations/rollback: this only establishes matching host execution. Retain previous reviews, failed scratch and compressed originals. "
        "Restore this packet's state/log before copies and select the pinned previous review to undo the selection; remove only the new resume utility if reverting. "
        "Phase 4 remains incomplete.\n")
    documents(packet, {"state.json": json.dumps(state, indent=2) + "\n",
        "docs/IMPLEMENTATION-LOG.md": (PROJECT / "docs/IMPLEMENTATION-LOG.md").read_text(encoding="utf-8") + note})
    index_packet(packet)
    print(json.dumps({"review": review["packet"], "passed": review["passed"],
        "suite_complete": review["suite_complete"], "reused": len(reused), "cases": len(results), "error": review.get("error")}), flush=True)
    return 0 if review["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
