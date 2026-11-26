"""Record saved scheduling/DHCP evidence; never contacts or changes the phone."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def timing(values):
    values = sorted(values)
    if not values:
        return None
    return {"samples": len(values), "median_ms": values[len(values) // 2] / 1000,
            "p95_ms": values[min(len(values) - 1, int(len(values) * .95))] / 1000,
            "maximum_ms": values[-1] / 1000}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("run", type=Path)
    ap.add_argument("--reviewed-screenshot")
    ap.add_argument("--review-note")
    args = ap.parse_args()
    run = args.run.resolve()
    test = json.loads((run / "test-manifest.json").read_text())
    package = json.loads((run / "package-manifest.json").read_text())
    assert package["profile"] == "full-quality-recovery"
    assert test["manual_return"] and test["kernel_return_after_seconds"] == 0
    for entry, component in (("kernel", "kernel"), ("ramdisk", "root.apfs"),
                             ("resident", "flashboot.apfs")):
        assert test["entries"][entry]["sha256"] == package["components"][component]["sha256"]
    files = sorted(run.glob("log-*.txt"))
    # Snapshots overlap; preserve first-observed order without counting twice.
    rows = list(dict.fromkeys(line for p in files for line in
                             p.read_text(errors="replace").replace("\0", "").splitlines()))
    select = lambda text: [line for line in rows if text in line]
    bindings = []
    copies, draws, temperatures = [], [], []
    for line in rows:
        m = re.fullmatch(r"tl: render tid (\d+) requested (-?\d+) bound (-?\d+) result (-?\d+)", line)
        if m:
            bindings.append(dict(zip(("tid", "requested", "bound", "result"), map(int, m.groups()))))
        m = re.fullmatch(r"tl: v (\d+) ready (\d+) shown (\d+) done (\d+) cpu (\d+) (\d+)", line)
        if m:
            copies.append(tuple(map(int, m.groups())))
        m = re.fullmatch(r"tl: g (\d+) began (\d+) ended (\d+) (\d+) cpu (\d+)", line)
        if m:
            draws.append(tuple(map(int, m.groups())))
        m = re.search(r"temperatures (\d+), (\d+), (\d+) \(hottest (\d+), (\d+), (\d+)\); "
                      r"(\d+) steps down, (\d+) up", line)
        if m:
            temperatures.append(tuple(map(int, m.groups())))
    presenter = select("tl: display presenter bound")
    screenshot = None
    if args.reviewed_screenshot:
        path = run / args.reviewed_screenshot
        assert path.parent == run and path.suffix == ".png" and path.is_file() and args.review_note
        screenshot = {"file": path.name, "sha256": sha(path), "review": args.review_note}
    report = {
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "run": str(run), "profile": package["profile"],
        "test_manifest_sha256": sha(run / "test-manifest.json"),
        "logs": [{"file": p.name, "bytes": p.stat().st_size, "sha256": sha(p)} for p in files],
        "tested_components_match_package": True,
        "manual_return": True, "collection_completed": test.get("collection_completed", False),
        "last_loader_result": test.get("last_loader_result"),
        "host_collection_seconds": test["host_collection_seconds"],
        "effective_cmdline": select("cmdline: debug="),
        "render_geometry": select("initial main screen size:"),
        "presenter_binding": presenter, "compositor_bindings": bindings,
        "presenter_binding_confirmed": "tl: display presenter bound cpu 0 actual 0" in presenter,
        "compositor_bindings_confirmed": bool(bindings) and all(
            b["requested"] == b["bound"] == 1 and b["result"] == 0 for b in bindings),
        "copy_cpu_pairs": dict(Counter(f"{c[4]}->{c[5]}" for c in copies)),
        "draw_cpu_counts": dict(Counter(str(d[4]) for d in draws)),
        "copy_execution_time": timing([c[3] - c[2] for c in copies if c[3] >= c[2]]),
        "draw_execution_time": timing([d[2] - d[1] for d in draws if d[2] >= d[1]]),
        "clock_reports": select("a51gpu: verified clocks:"),
        "temperature_maxima_c": dict(zip(("a53", "a73", "gpu"),
            (max(t[i] for t in temperatures) for i in (3, 4, 5)))) if temperatures else None,
        "maximum_downsteps": max((t[6] for t in temperatures), default=None),
        "maximum_restorations": max((t[7] for t in temperatures), default=None),
        "dhcp_reports": select("tl: net DHCP"),
        "radio_reports": select("tl: wifi"), "http_probes": select("net_test: fetch"),
        "dhcp_recovery_requests": select("persistent lease failure refresh"),
        "gpu_reports": select("a51gpu: kept GPU:"),
        "reviewed_screenshot": screenshot, "owner_feedback": None,
        "measured_panel_fps": None, "sustained_40_50_fps_verified": False,
        "late_dhcp_recovery_verified": False,
        "limitations": [
            "Copy completions and pending-buffer replacements are not distinct panel presentations.",
            "Timing samples mix workloads; they do not establish a controlled before/after improvement.",
            "Initial DHCP/HTTPS success does not verify recovery after the one-hour lease.",
            "A still screenshot cannot establish animation quality or rule out intermittent corruption.",
            "Charging, audio, Metal and third-party apps were not changed in this candidate."]}
    (run / "runtime-verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("collection_completed", "last_loader_result",
        "presenter_binding_confirmed", "compositor_bindings_confirmed", "copy_cpu_pairs",
        "draw_cpu_counts", "copy_execution_time", "draw_execution_time", "temperature_maxima_c",
        "maximum_downsteps", "maximum_restorations", "dhcp_reports", "http_probes")}, indent=2))


if __name__ == "__main__":
    main()
