#!/usr/bin/env python3
"""Execute the captured A53/GICv2 kernel, PID 1 and timer tests in QEMU virt."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import struct
import subprocess
import sys
import time
import uuid

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "prototype/xnu-loader"))
from hakios_devicetree import build_exynos9611_device_tree, DeviceTreeReader, DeviceTreeWriter
from hakios_macho import BootArgs, MachOFile

MAGIC = 0x315254514F494B48
RECORD_PA = 0x80090000
SLIDE = 0x80000000 - 0xFFFFFFF004000000


def pin(path):
    raw = path.read_bytes()
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def align(n, alignment=65536):
    return (n + alignment - 1) & -alignment


def validate(log, nonce, record):
    begin = log.find("HAKIOS_USER_BEGIN pid=1 uid=0 console=")
    footer = "HAKIOS_USER_EXIT outcome=0 timer_verified=1"
    end = log.find(footer, begin)
    text = log[begin:end + len(footer)] if begin >= 0 and end > begin else ""
    samples = re.findall(r"HAKIOS_TIMER_SAMPLE index=(\d+) select_rc=(-?\d+) elapsed_us=(-?\d+) irq_before=(\d+) irq_after=(\d+) read_rc=(-?\d+) pass=([01])", text)
    sample_ok = len(samples) == 3
    last_irq = 0
    for i, values in enumerate(samples, 1):
        n, rc, elapsed, before, after, read_rc, passed = map(int, values)
        sample_ok &= n == i and 900000 <= elapsed <= 3000000 and before >= last_irq and after > before and rc == 0 and read_rc == 0 and passed == 1
        last_irq = after
    platform = re.search(r"HAKIOS_PLATFORM gic=2 cores=1 midr=0x([0-9a-f]+)", text)
    checks = {
        "attributable_nonce": f"HAKIOS_RUN_NONCE={nonce}\n" in text,
        "pid_1_root_console": bool(re.search(r"HAKIOS_USER_BEGIN pid=1 uid=0 console=[0-9]+", text)),
        "three_measured_timer_samples": bool(sample_ok),
        "timer_pass": "HAKIOS_TIMER_PASS samples=3" in text,
        "user_pass_and_zero_exit": footer in text,
        "no_test_failure": "HAKIOS_TIMER_FAIL" not in log and "HAKIOS_USER_FAIL" not in log,
        "gicv2_single_core": bool(platform),
        "midr_matches_capture": bool(platform) and int(platform.group(1), 16) == record[5],
        "cortex_a53": ((record[5] >> 4) & 0xfff) == 0xd03,
        "expected_pid1_exit": "(signal 0, exit 0)" in log and "initproc" in log,
        "physical_stub_return": record[0] == MAGIC and record[3] == 0 and record[4] == 0 and record[8] == 4,
        "counter_frequency": record[6] == 62500000,
    }
    return checks, samples


class Qmp:
    def __init__(self, path):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(5)
        self.sock.connect(str(path))
        self.file = self.sock.makefile("rb")
        self.read()
        self.command("qmp_capabilities")

    def read(self):
        raw = self.file.readline()
        if not raw:
            raise RuntimeError("QMP disconnected")
        return json.loads(raw)

    def command(self, execute, arguments=None):
        self.sock.sendall((json.dumps({"execute": execute, "arguments": arguments or {}}) + "\n").encode())
        while True:
            reply = self.read()
            if "error" in reply:
                raise RuntimeError(str(reply["error"]))
            if "return" in reply:
                return reply["return"]

    def save(self, pa, length, path):
        # HMP accepts a quoted filename; paths are controlled, contain no quotes/newlines.
        assert not any(c in str(path) for c in '"\n\r')
        output = self.command("human-monitor-command", {"command-line": f'pmemsave 0x{pa:x} 0x{length:x} "{path}"'})
        if output:
            raise RuntimeError("pmemsave: " + output)
        if path.stat().st_size != length:
            raise RuntimeError("pmemsave size mismatch")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=120)
    args = parser.parse_args()
    assert 15 <= args.seconds <= 300
    workspace = json.loads((PROJECT / "manifests/phase3-workspace.json").read_text())
    root = Path(workspace["root"])
    build = json.loads((PROJECT / "manifests/phase3-platform-build.json").read_text())
    assert build["build_verified"] and build["root"] == str(root)
    for rel in ("hakios-kernel", "userland/hello"):
        assert pin(root / rel) == build["artifacts"][rel]
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    packet = PROJECT / "evidence/phase-3/platform-qemu" / stamp
    work = Path("/opt/a51-hakios/experimental/phase3-qemu") / stamp
    packet.mkdir(parents=True, exist_ok=False)
    work.mkdir(parents=True, exist_ok=False)
    shutil.copy2(Path(__file__), packet / "source.py")
    shutil.copy2(PROJECT / "prototype/a51-platform/qemu_entry.S", packet / "qemu_entry.S")
    nonce = uuid.uuid4().hex
    result = {"schema_version": 1, "packet": str(packet.relative_to(PROJECT)), "nonce": nonce,
              "scope": "QEMU virt TCG Cortex-A53 GICv2, EL3 to nonsecure EL1 only", "passed": False,
              "build_packet": build["packet"], "commands": [], "device_operations": False,
              "phase_3_device_gate_passed": False}
    proc = None
    try:
        raw = bytearray((root / "hakios-kernel").read_bytes())
        macho = MachOFile(raw)
        slot = macho.find_loader_stub_slot()
        assert slot and macho.entry_point_va
        ranges = [(s.vmaddr + SLIDE, s.vmaddr + SLIDE + s.vmsize) for s in macho.segments if s.vmsize]
        assert min(a for a, b in ranges) >= 0x82330000
        for i, (a, b) in enumerate(ranges):
            assert 0x80000000 <= a < b < 0xc0000000
            assert all(b <= c or d <= a for c, d in ranges[:i])
        ramdisk_pa = align(max(b for a, b in ranges))
        hello = (root / "userland/hello").read_bytes()
        ramdisk_size = align(len(hello), 4096)
        ba_pa = align(ramdisk_pa + ramdisk_size)
        dt_pa = ba_pa + 0x10000
        tree = DeviceTreeReader(build_exynos9611_device_tree(ramdisk_pa=ramdisk_pa,
            ramdisk_size=ramdisk_size, timebase_hz=62500000)).root
        writer = DeviceTreeWriter()
        overrides = {
            "/arm-io": {"ranges": struct.pack("<QQQQ", 0, 0x08000000, 0x10000000, 0)},
            "/arm-io/gic": {"reg": struct.pack("<QQQQ", 0, 0x1000, 0x10000, 0x1000)},
            "/arm-io/uart0": {"reg": struct.pack("<QQ", 0x01000000, 0x1000), "compatible": b"arm,pl011\0"},
            "/pram": {"reg": struct.pack("<QQ", 0x8f000000, 0x80000)},
            "/chosen": {"random-seed": os.urandom(64)},
        }

        def emit(node, path):
            writer.begin_node(node["name"])
            values = dict(node["props"], **overrides.get(path, {}))
            for key, value in values.items():
                if key != "name":
                    writer.add_prop(key, value)
            for child in node["children"]:
                emit(child, path + "/" + child["name"])
            writer.end_node()

        emit(tree, "")
        dt_blob = writer.finish()
        top = align(dt_pa + len(dt_blob))
        ba = BootArgs(physBase=0x80000000, virtBase=0xFFFFFFF004000000, memSize=0x40000000,
            topOfKernelData=top, deviceTreeP=dt_pa - SLIDE, deviceTreeLength=len(dt_blob),
            commandLine=f"rd=md0 -v cpus=1 serial=3 debug=0x8 hello_wait=3 loader_return_after=20 hakios_run_nonce={nonce} hakios_kver=p3-a53-gicv2")
        env = dict(os.environ, PATH="/usr/lib/llvm-18/bin:" + os.environ["PATH"])
        argv = ["clang", "--target=aarch64-none-elf", "-mcpu=cortex-a53", "-nostdlib", "-fuse-ld=lld",
                "-Wl,-Ttext=0x80080000", "-Wl,--build-id=none", f"-DQEMU_STACK_PA=0x{top + 0x20000:x}",
                f"-DQEMU_BOOTARGS_PA=0x{ba_pa:x}", f"-DQEMU_XNU_ENTRY_PA=0x{macho.entry_point_va + SLIDE:x}",
                str(PROJECT / "prototype/a51-platform/qemu_entry.S"), "-o", str(work / "entry.elf")]
        result["commands"].append(argv)
        subprocess.run(argv, env=env, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        nm = subprocess.check_output(["llvm-nm", str(work / "entry.elf")], env=env, text=True)
        return_pa = int(next(line.split()[0] for line in nm.splitlines() if line.endswith(" qemu_loader_return")), 16)
        struct.pack_into("<3Q", raw, slot[0] + 8, return_pa, 0, SLIDE & ((1 << 64) - 1))
        devices = [f"loader,file={work / 'entry.elf'},cpu-num=0"]
        for i, seg in enumerate(macho.segments):
            if not seg.vmsize:
                continue
            data = bytes(raw[seg.fileoff:seg.fileoff + seg.filesize]) + bytes(seg.vmsize - seg.filesize)
            path = packet / f"segment-{i}-{seg.name}.bin"
            path.write_bytes(data)
            devices.append(f"loader,file={path},addr=0x{seg.vmaddr + SLIDE:x},force-raw=on")
        for name, pa, data in (("bootargs.bin", ba_pa, ba.pack()), ("devicetree.bin", dt_pa, dt_blob),
                                ("hello.bin", ramdisk_pa, hello)):
            path = packet / name
            path.write_bytes(data)
            devices.append(f"loader,file={path},addr=0x{pa:x},force-raw=on")
        shutil.copy2(work / "entry.elf", packet / "entry.elf")
        result["layout"] = {"segments": ranges, "ramdisk_pa": ramdisk_pa, "bootargs_pa": ba_pa,
                            "devicetree_pa": dt_pa, "top": top, "return_pa": return_pa}
        qmp_path = work / "monitor.sock"
        argv = ["qemu-system-aarch64", "-M", "virt,gic-version=2,secure=on,virtualization=on", "-cpu", "cortex-a53", "-smp", "1",
                "-m", "2G", "-accel", "tcg,tb-size=384", "-display", "none", "-serial", "stdio",
                "-monitor", "none", "-qmp", f"unix:{qmp_path},server=on,wait=off", "-no-reboot"]
        for device in devices:
            argv += ["-device", device]
        result["commands"].append(argv)
        print(f"QEMU A53/GICv2 nonce={nonce} deadline={args.seconds}s packet={packet}", flush=True)
        log = (packet / "serial.log").open("wb")
        proc = subprocess.Popen(argv, env=env, stdout=log, stderr=subprocess.STDOUT)
        start = time.monotonic()
        while not qmp_path.exists() and proc.poll() is None and time.monotonic() - start < 10:
            time.sleep(.1)
        qmp = Qmp(qmp_path)
        record_file = packet / "return-record.bin"
        record = (0,) * 9
        while proc.poll() is None and time.monotonic() - start < args.seconds:
            qmp.save(RECORD_PA, 256, record_file)
            record = struct.unpack_from("<9Q", record_file.read_bytes())
            if record[0] == MAGIC:
                break
            time.sleep(1)
        result["elapsed_seconds"] = time.monotonic() - start
        result["record"] = [hex(n) for n in record]
        if record[0] != MAGIC:
            raise RuntimeError("No physical return record within the host deadline")
        pa, length = record[1:3]
        assert 0 < length <= 1536 * 1024 and any(a <= pa and pa + length <= b for a, b in ranges)
        qmp.save(pa, length, packet / "kernel-user.log")
        text = (packet / "kernel-user.log").read_text(errors="replace").replace("\r", "")
        result["checks"], result["timer_samples"] = validate(text, nonce, record)
        result["passed"] = all(result["checks"].values())
        result["log"] = pin(packet / "kernel-user.log")
        for line in text.splitlines():
            if line.startswith(("HAKIOS_", "gic:", "panic(cpu", "pid 1 exited")):
                print(line, flush=True)
        qmp.command("quit")
        proc.wait(timeout=5)
    except Exception as exc:
        result["error"] = str(exc)
    finally:
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        if proc is not None:
            result["qemu_exit_code"] = proc.returncode
        (packet / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        (PROJECT / "manifests/phase3-platform-qemu.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ("packet", "passed", "checks", "error") if k in result}, indent=2), flush=True)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
