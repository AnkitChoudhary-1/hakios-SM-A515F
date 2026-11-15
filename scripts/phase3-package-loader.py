#!/usr/bin/env python3
"""Package the selected bounded hardware loader into the pinned Samsung slot."""
from __future__ import annotations
import json
import os
from pathlib import Path
from phase3_support import PROJECT, json_write, packet_new, packet_index, pin, require
from samsung_boot_dry_run import reconstruct_in_memory

BASELINE = PROJECT.parent / "everline-ksu/artifacts/A51-PixelOS-Everline-KernelSU-Next-boot.img"
RECOVERY = PROJECT.parent / "everline-ksu/backups/a51-twrp-original-recovery.img"
DTBO = PROJECT.parent / "everline-ksu/backups/a51-pixelos-original-dtbo.img"
BOOT_PIN = {"bytes": 61865984, "sha256": "eb30609a62999e3282ac81e0a5e56411ef12ec1a39c107171bf3e01209c7cb67"}
RECOVERY_PIN = {"bytes": 71106560, "sha256": "12412e2008d950260cda627ac7a6b8eac954b49ef9db5573a297f67e4fc85999"}
DTBO_PIN = {"bytes": 8388608, "sha256": "41662c61ff3158448935025477a4e29d445823dab2cddafb18ea649c8ea925d6"}


def loader_path(selected):
    root = selected["work"]
    require(root.startswith("/opt/a51-hakios/experimental/phase3-loader/"), "Wrong isolated loader root")
    return Path(root) if os.name == "posix" else Path("//wsl.localhost/A51-KernelBuilder" + root)


def main():
    selected = json.loads((PROJECT / "manifests/phase3-loader-hardware.json").read_text())
    require(selected["passed"] and selected["mode"] == "hardware", "Hardware loader is not built")
    for path, expected in ((BASELINE, BOOT_PIN), (RECOVERY, RECOVERY_PIN), (DTBO, DTBO_PIN)):
        require(pin(path) == expected, "Rollback pin changed: " + str(path))
    image = loader_path(selected) / "loader.Image"
    require(pin(image) == selected["outputs"]["loader.Image"], "Selected loader changed")
    raw, report = reconstruct_in_memory(BASELINE.read_bytes(), image.read_bytes())
    require([x["name"] for x in report["changed_regions"]] ==
            ["header.kernel_size", "header.id", "kernel.slot", "avb.boot_digest"], "Unexpected boot changes")
    packet = packet_new("bounded-loader-package", Path(__file__))
    json_write(packet / "selected-loader.json", selected)
    json_write(packet / "reconstruction.json", report)
    artifacts = PROJECT / "artifacts/phase-3/bounded-loader" / packet.name
    artifacts.mkdir(parents=True, exist_ok=False)
    candidate = artifacts / "boot.img"
    with candidate.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    require(pin(candidate) ==
            {"bytes": report["candidate"]["bytes"], "sha256": report["candidate"]["sha256"]}, "Candidate readback failed")
    result = {"schema_version": 1, "packet": packet.relative_to(PROJECT).as_posix(), "passed": True,
              "nonce": selected["nonce"], "diagnostic": selected["diagnostic"], "checkpoint": selected["checkpoint"],
              "entry_style": selected.get("entry_style", "standalone"),
              "loader_build_packet": selected["packet"], "loader_image": selected["outputs"]["loader.Image"],
              "candidate": {"path": candidate.relative_to(PROJECT).as_posix(), **pin(candidate)},
              "baseline": BOOT_PIN, "recovery": RECOVERY_PIN, "dtbo": DTBO_PIN,
              "device_operations": False, "phase_3_device_gate_passed": False}
    json_write(packet / "result.json", result)
    packet_index(packet)
    json_write(PROJECT / "manifests/phase3-bounded-candidate.json", result)
    print(json.dumps(result, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
