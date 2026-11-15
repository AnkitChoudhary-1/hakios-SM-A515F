#!/usr/bin/env python3
"""Capture original read-only A51 hardware facts and independent known boot bytes."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess

from boot_formats import cells, strings, parse_fdt

PROJECT = Path(__file__).resolve().parents[1]
SERIAL = "A51_SERIAL_HERE"
BASELINE = "eb30609a62999e3282ac81e0a5e56411ef12ec1a39c107171bf3e01209c7cb67"
BOOT = PROJECT.parent / "everline-ksu/artifacts/A51-PixelOS-Everline-KernelSU-Next-boot.img"


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def main() -> int:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    packet = PROJECT / "evidence/phase-4/live-inventory" / stamp
    packet.mkdir(parents=True, exist_ok=False)
    records = []
    result = {"schema_version": 1, "scope": "read_only_android_observations_not_xnu_driver_validation",
              "serial": SERIAL, "phase_4_gate_passed": False,
              "operations": {"device_reads": True, "device_writes": False, "reboot": False},
              "checks": {}, "hardware_nodes": {}, "known_image": {}, "error": None}

    def query(name: str, args: list[str], limit: int = 2_097_152, timeout: int = 45, framed: bool = False) -> bytes:
        command = ["adb", "-s", SERIAL, *args]
        started = now()
        try:
            proc = subprocess.run(command, capture_output=True, timeout=timeout)
            out, err, rc = proc.stdout, proc.stderr, proc.returncode
        except subprocess.TimeoutExpired as exc:
            out, err, rc = exc.stdout or b"", (exc.stderr or b"") + b"\nTIMEOUT", 124
        transport_rc = rc
        if framed:
            (packet / (name + ".stdout.raw.bin")).write_bytes(out)
            footer = re.search(rb"\nHAKIOS_REMOTE_EXIT:([0-9]{1,3})\n$", out)
            if footer and int(footer.group(1)) <= 255:
                rc = transport_rc or int(footer.group(1))
                out = out[:footer.start()]
            else:
                rc = transport_rc or 125
        (packet / (name + ".stdout.bin")).write_bytes(out)
        (packet / (name + ".stderr.bin")).write_bytes(err)
        records.append({"name": name, "command": command, "started": started, "finished": now(),
                        "exit_code": rc, "transport_exit_code": transport_rc,
                        "remote_exit_framed": framed, "stdout_bytes": len(out), "stdout_sha256": hashlib.sha256(out).hexdigest(),
                        "stderr_bytes": len(err), "stdout": name + ".stdout.bin", "stderr": name + ".stderr.bin"})
        print(json.dumps({"query": name, "exit_code": rc, "bytes": len(out)}), flush=True)
        if len(out) > limit:
            raise RuntimeError(name + ": output exceeds bound")
        return out

    def root(name: str, command: str, binary: bool = False, limit: int = 2_097_152) -> bytes:
        # exec-out is byte-exact in this KernelSU session. Its missing remote
        # status is supplied by a bounded trailing frame; retain original bytes.
        # Commands producing successful binary data use cat/head (no diagnostics).
        if binary:
            framed = "{ " + command + "; }; hakios_capture_rc=$?; printf '\\nHAKIOS_REMOTE_EXIT:%d\\n' \"$hakios_capture_rc\""
            args = ["exec-out", "su", "-c", framed]
        else:
            args = ["shell", "su", "-c", shlex.quote(command)]
        return query(name, args, limit, framed=binary)

    def required(name: str, content: bytes, expected: str) -> None:
        passed = records[-1]["exit_code"] == 0 and content.decode("utf-8", "replace").strip() == expected
        result["checks"][name] = passed
        if not passed:
            raise RuntimeError(name + ": prerequisite mismatch")

    try:
        required("adb_state", query("adb-state", ["get-state"]), "device")
        required("model", query("model", ["shell", "getprop", "ro.product.model"]), "SM-A515F")
        required("boot_completed", query("boot-completed", ["shell", "getprop", "sys.boot_completed"]), "1")
        uid = root("root", "id")
        result["checks"]["root"] = records[-1]["exit_code"] == 0 and b"uid=0(root)" in uid
        if not result["checks"]["root"]:
            raise RuntimeError("root prerequisite failed")
        boot_id = root("boot-id-before", "cat /proc/sys/kernel/random/boot_id")
        required("boot_device", root("boot-device", "readlink -f /dev/block/by-name/boot"), "/dev/block/sda12")
        required("boot_bytes", root("boot-bytes", "blockdev --getsize64 /dev/block/sda12"), "61865984")
        boot_hash = root("boot-hash", "sha256sum /dev/block/sda12")
        result["checks"]["baseline"] = records[-1]["exit_code"] == 0 and boot_hash.split()[:1] == [BASELINE.encode()]
        if not result["checks"]["baseline"]:
            raise RuntimeError("live boot does not match pinned baseline")
        blob = root("live-fdt", "cat /sys/firmware/fdt", binary=True)
        if records[-1]["exit_code"]:
            raise RuntimeError("FDT binary read failed")
        tree = parse_fdt(blob)
        if len(blob) != tree.header["totalsize"]:
            raise RuntimeError("FDT has extra or missing bytes")
        nodes = tree.nodes
        phandles = {cells(p["phandle"])[0]: path for path, p in nodes.items() if "phandle" in p}
        selected = []
        for path, props in nodes.items():
            compat = strings(props["compatible"]) if "compatible" in props else []
            if any(word in path.lower() for word in ("decon", "dsim", "ufs@", "i2c@1387", "i2c@0x1387", "melfas", "mms", "sec_key", "gpio-key")) or any("melfas" in s for s in compat):
                selected.append(path)
        for path in selected:
            props = nodes[path]
            entry = {"raw": {k: v.hex() for k, v in props.items()}, "compatible": strings(props["compatible"]) if "compatible" in props else []}
            for key in ("reg", "interrupts", "gpios", "melfas,event_info", "melfas,max_x_y", "melfas,max_resolution", "max-x", "max-y"):
                if key in props:
                    entry[key] = cells(props[key])
            parent = path.rsplit("/", 1)[0] or "/"
            entry["parent"] = parent
            entry["parent_address_cells"] = cells(nodes[parent]["#address-cells"])[0] if "#address-cells" in nodes[parent] else 2
            entry["parent_size_cells"] = cells(nodes[parent]["#size-cells"])[0] if "#size-cells" in nodes[parent] else 1
            result["hardware_nodes"][path] = entry
        result["fdt"] = {"bytes": len(blob), "sha256": hashlib.sha256(blob).hexdigest(), "nodes": len(nodes), "phandles": phandles}
        for name, cmd in [
            ("battery", "dumpsys battery"), ("input-devices", "cat /proc/bus/input/devices"),
            ("input-capabilities", "getevent -lp"),
            ("fb-size", "cat /sys/class/graphics/fb0/virtual_size"),
            ("fb-bpp", "cat /sys/class/graphics/fb0/bits_per_pixel"),
            ("fb-info", "ls -l /sys/class/graphics/fb0"),
            ("block-devices", "cat /proc/partitions"),
            ("ufs-lun", "readlink -f /sys/class/block/sda/device"),
            ("ufs-lbs", "cat /sys/class/block/sda/queue/logical_block_size"),
            ("ufs-block-size", "cat /sys/class/block/sda/size"),
            ("boot-start", "cat /sys/class/block/sda12/start"),
            ("gpio-debug", "cat /sys/kernel/debug/gpio"),
            ("iomem", "cat /proc/iomem"), ("modules", "cat /proc/modules")]:
            root(name, cmd)
        first = root("known-boot-first-1m", "head -c 1048576 /dev/block/sda12", binary=True, limit=1_048_576)
        host = BOOT.read_bytes()
        result["checks"]["host_baseline"] = len(host) == 61_865_984 and hashlib.sha256(host).hexdigest() == BASELINE
        result["checks"]["independent_known_image"] = records[-1]["exit_code"] == 0 and len(first) == 1_048_576 and first == host[:1_048_576]
        if not result["checks"]["host_baseline"] or not result["checks"]["independent_known_image"]:
            raise RuntimeError("independent boot bytes do not match host baseline")
        by_name = {r["name"]: r for r in records}
        start = int((packet / "boot-start.stdout.bin").read_bytes().strip())
        block_size = int((packet / "ufs-lbs.stdout.bin").read_bytes().strip())
        if by_name["boot-start"]["exit_code"] or by_name["ufs-lbs"]["exit_code"] or block_size not in (512, 4096) or (start * 512) % block_size:
            raise RuntimeError("cannot determine boot absolute UFS logical block")
        result["known_image"] = {"source": str(BOOT), "baseline_sha256": BASELINE,
                                  "boot_partition_start_512_sectors": start, "ufs_logical_block_bytes": block_size,
                                  "ufs_boot_lba": start * 512 // block_size,
                                  "captured_bytes": len(first), "first_1m_sha256": hashlib.sha256(first).hexdigest(),
                                  "first_4k_sha256": hashlib.sha256(first[:4096]).hexdigest(),
                                  "first_64_bytes_hex": first[:64].hex()}
        end_id = root("boot-id-after", "cat /proc/sys/kernel/random/boot_id")
        required("same_android_boot", end_id, boot_id.decode().strip())
    except Exception as exc:
        result["error"] = str(exc)
    finally:
        result["queries"] = records
        result["inventory_valid"] = result["error"] is None and bool(result["checks"]) and all(result["checks"].values())
        result["unavailable_queries"] = [r["name"] for r in records if r["exit_code"] != 0]
        (packet / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        (packet / "source.py").write_bytes(Path(__file__).read_bytes())
        (packet / "boot_formats.py").write_bytes((PROJECT / "scripts/boot_formats.py").read_bytes())
        index = [{"path": p.name, "bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                 for p in sorted(packet.iterdir()) if p.is_file()]
        (packet / "index.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"packet": str(packet), "inventory_valid": result["inventory_valid"],
                          "error": result["error"], "known_image": result["known_image"]}), flush=True)
    return 0 if result["inventory_valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
