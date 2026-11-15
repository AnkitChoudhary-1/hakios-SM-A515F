#!/usr/bin/env python3
"""Execute the complete bounded loader with its real kernel and console path."""
from __future__ import annotations
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import time
from phase3_support import PROJECT, command, packet_new, packet_index, json_write, pin, require
from phase3_envelope import decode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=("full", "reset", "fault", "bad-toc", "bad-fdt"), default="full")
    parser.add_argument("--seconds", type=int, default=120)
    parser.add_argument("--load-address", type=lambda s: int(s, 0), default=0x80080000)
    args = parser.parse_args()
    require(0x80080000 <= args.load_address <= 0x84000000 and args.load_address % 4096 == 0, "Invalid replay placement")
    require(15 <= args.seconds <= 300 and os.name == "posix", "Use bounded WSL QEMU")
    selected = json.loads((PROJECT / "manifests/phase3-loader-qemu.json").read_text())
    require(selected["passed"] and selected["mode"] == "qemu" and selected["diagnostic"] == 0, "Wrong selected loader")
    original = Path(selected["work"])
    require(pin(original / "loader.Image") == selected["outputs"]["loader.Image"], "Loader Image changed")
    require(pin(original / "loader.elf") == selected["outputs"]["loader.elf"], "Loader ELF changed")
    packet = packet_new("loader-qemu", Path(__file__))
    work = Path("/opt/a51-hakios/experimental/phase3-loader-qemu") / packet.name
    work.mkdir(parents=True, exist_ok=False)
    shutil.copy2(PROJECT / "scripts/phase3_envelope.py", packet / "phase3_envelope.py")
    shutil.copy2(PROJECT / "scripts/phase3-qemu-platform.py", packet / "user-checker.py")
    shutil.copy2(PROJECT / "prototype/phase3-loader/qemu_firmware.S", packet / "firmware.S")
    json_write(packet / "selected-loader.json", selected)
    result = {"packet": packet.relative_to(PROJECT).as_posix(), "case": args.case,
              "nonce": selected["nonce"], "loader_build_packet": selected["packet"],
              "load_address": args.load_address,
              "scope": "Actual complete Image in QEMU; hardware reset/watchdog MMIO excluded",
              "device_operations": False, "phase_3_device_gate_passed": False, "passed": False}
    records = []
    proc = None
    qmp = None
    serial = None
    spec = importlib.util.spec_from_file_location("phase3_qemu_platform", PROJECT / "scripts/phase3-qemu-platform.py")
    platform = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(platform)
    try:
        raw = bytearray((original / "loader.Image").read_bytes())
        cfg = selected["symbols"]["payload_config"] - 0x80080000
        if args.case in ("reset", "fault"):
            struct.pack_into("<Q", raw, cfg + 11 * 8, 1 if args.case == "reset" else 3)
        elif args.case == "bad-toc":
            struct.pack_into("<Q", raw, cfg + 2 * 8, 65)
        image = work / "test.Image"
        image.write_bytes(raw)
        fdt = bytearray((PROJECT / "evidence/phase-2/live-fdt-libfdt/20261111T073056068990Z/live.dtb").read_bytes())
        if args.case == "bad-fdt":
            fdt[0] ^= 1
        (packet / "incoming-fdt.dtb").write_bytes(fdt)
        result["executed_image"] = pin(image)
        env = dict(os.environ, PATH="/usr/lib/llvm-18/bin:" + os.environ["PATH"])
        command(packet, records, "compile-firmware", ["clang", "--target=aarch64-none-elf", "-mcpu=cortex-a53",
            "-nostdlib", "-fuse-ld=lld", "-Wl,--build-id=none", "-Wl,-Ttext=0x40200000",
            "-DQEMU_IMAGE_BASE=" + hex(args.load_address),
            str(packet / "firmware.S"), "-o", str(work / "firmware.elf")], env=env)
        monitor = work / "monitor.sock"
        argv = ["qemu-system-aarch64", "-M", "virt,gic-version=2,secure=on,virtualization=on",
                "-cpu", "cortex-a53", "-smp", "1", "-m", "3G", "-accel", "tcg,tb-size=384",
                "-display", "none", "-serial", "stdio", "-monitor", "none", "-no-reboot",
                "-qmp", f"unix:{monitor},server=on,wait=off",
                "-device", f"loader,file={work / 'firmware.elf'},cpu-num=0",
                "-device", f"loader,file={image},addr={hex(args.load_address)},force-raw=on",
                "-device", f"loader,file={packet / 'incoming-fdt.dtb'},addr=0x8a100000,force-raw=on"]
        result["qemu_argv"] = argv
        json_write(packet / "launch.json", result)
        serial = (packet / "serial.log").open("wb")
        start = time.monotonic()
        proc = subprocess.Popen(argv, stdout=serial, stderr=subprocess.STDOUT, env=env)
        for _ in range(100):
            if monitor.exists():
                break
            require(proc.poll() is None, "QEMU exited before QMP")
            time.sleep(0.05)
        qmp = platform.Qmp(monitor)
        capture = work / "console.bin"
        expected_reason = {"full": 0, "reset": 3, "fault": 6, "bad-toc": 4, "bad-fdt": 4}[args.case]
        decoded = None
        while time.monotonic() - start < args.seconds:
            require(proc.poll() is None, "QEMU exited unexpectedly")
            qmp.save(0xf9d90000, 512 * 1024, capture)
            try:
                candidate = decode(capture.read_bytes(), selected["nonce"])
                if candidate["fields"]["reason"] == expected_reason:
                    decoded = candidate
                    break
            except ValueError:
                pass
            time.sleep(0.3)
        require(decoded is not None, "Complete loader envelope deadline expired")
        qmp.command("stop")
        qmp.save(0xf9d90000, 512 * 1024, packet / "console.bin")
        decoded = decode((packet / "console.bin").read_bytes(), selected["nonce"])
        qmp.save((selected["symbols"]["loader_context"] + args.load_address - 0x80080000), 192, packet / "context.bin")
        qmp.save((selected["symbols"]["loader_fault_frame"] + args.load_address - 0x80080000), 320, packet / "fault-frame.bin")
        qmp.save(0xf9e90000, 512 * 1024, packet / "pmsg.bin")
        mirrored = decode((packet / "pmsg.bin").read_bytes(), selected["nonce"])
        require(mirrored["fields"] == decoded["fields"] and mirrored["log"] == decoded["log"], "Pstore mirror mismatch")
        context = struct.unpack("<24Q", (packet / "context.bin").read_bytes())
        fields = decoded["fields"]
        (packet / "kernel-user.log").write_bytes(decoded["log"])
        checks = {"nonce_crc_footer": True, "supported_entry": fields["entry_el"] == 4 and fields["entry_sctlr"] & 5 == 0,
                  "expected_reason": fields["reason"] == expected_reason,
                  "context_matches_envelope": context[18] == fields["stage"] and context[19] == fields["error"]}
        if args.case == "full":
            user_checks, samples = platform.validate(decoded["log"].decode("utf-8", errors="replace"),
                selected["nonce"], [0, *context[:4], context[16], context[15], context[17], context[12]])
            user_checks["physical_stub_return"] = fields["stage"] == 5 and fields["error"] == 0 and context[2:4] == (0, 0)
            checks.update(user_checks)
            checks["complete_untruncated_log"] = decoded["complete_log"]
            checks["exact_generated_log_pointer"] = context[0] == selected["layout"]["log_pa"] and context[1] == fields["requested"]
            result["timer_samples"] = samples
        elif args.case == "reset":
            checks["reset_diagnostic_reached"] = fields["stage"] == 3 and fields["error"] == 0 and fields["code"] == 1
        elif args.case == "fault":
            frame = struct.unpack("<40Q", (packet / "fault-frame.bin").read_bytes())
            checks["stackless_brk_capture"] = frame[0] == 0x33544c464f494b48 and frame[33] >> 26 == 0x3c and fields["error"] == 9
        else:
            checks["rejection_before_copy"] = fields["stage"] == 2 and fields["error"] == (1 if args.case == "bad-toc" else 2)
        result.update({"checks": checks, "fields": fields, "context": list(context), "log": decoded["log_pin"],
                       "elapsed_seconds": round(time.monotonic() - start, 3), "passed": all(checks.values())})
    except Exception as exc:
        result["error"] = str(exc)
        if qmp:
            try:
                qmp.command("stop")
                qmp.save(0xf9d90000, 512 * 1024, packet / "failed-console.bin")
                qmp.save((selected["symbols"]["loader_context"] + args.load_address - 0x80080000), 192, packet / "failed-context.bin")
                qmp.save(selected["layout"]["log_len_pa"], 4, packet / "failed-log-length.bin")
                length = struct.unpack("<I", (packet / "failed-log-length.bin").read_bytes())[0]
                if 0 < length <= 1536 * 1024:
                    qmp.save(selected["layout"]["log_pa"], length, packet / "failed-kernel.log")
            except Exception as capture_error:
                result["capture_error"] = str(capture_error)
    finally:
        if qmp:
            try:
                qmp.command("quit")
            except Exception:
                pass
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        if serial:
            serial.close()
        json_write(packet / "result.json", result)
        packet_index(packet)
        json_write(PROJECT / f"manifests/phase3-loader-qemu-{args.case}.json", result)
        print(json.dumps({k: result[k] for k in ("packet", "case", "passed", "elapsed_seconds", "checks", "error") if k in result}, indent=2), flush=True)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
