#!/usr/bin/env python3
"""Inspect a bounded replay of one retained QEMU payload; never set device gates."""
import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import socket
import struct
import subprocess
import time
import xml.etree.ElementTree as ET

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("platform_qemu", PROJECT / "scripts/phase3-qemu-platform.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def pin(path):
    raw = path.read_bytes()
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


class Registers:
    """Read QEMU's actual advertised system registers over its local GDB socket."""
    def __init__(self, path, packet):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(5)
        self.sock.connect(str(path))
        self.command("qSupported:qXfer:features:read+")
        self.registers = {}
        self.next_number = 0
        self.features("target.xml", packet)

    def command(self, command):
        raw = command.encode()
        self.sock.sendall(b"$" + raw + b"#" + f"{sum(raw) & 255:02x}".encode())
        while self.sock.recv(1) != b"$":
            pass
        raw = bytearray()
        while True:
            char = self.sock.recv(1)
            if not char:
                raise RuntimeError("GDB disconnected")
            if char == b"#":
                break
            raw += char
        checksum = self.sock.recv(2)
        if int(checksum, 16) != sum(raw) & 255:
            raise RuntimeError("GDB packet checksum mismatch")
        self.sock.sendall(b"+")
        decoded = bytearray()
        index = 0
        while index < len(raw):
            if raw[index] == ord("}"):
                index += 1
                decoded.append(raw[index] ^ 0x20)
            elif raw[index] == ord("*"):
                index += 1
                decoded.extend(bytes([decoded[-1]]) * (raw[index] - 29))
            else:
                decoded.append(raw[index])
            index += 1
        return decoded.decode()

    def features(self, name, packet):
        assert re.fullmatch(r"[a-zA-Z0-9_.-]+", name)
        raw = ""
        while True:
            part = self.command(f"qXfer:features:read:{name}:{len(raw):x},800")
            if not part or part[0] not in "ml":
                raise RuntimeError("GDB XML unavailable: " + repr(part))
            raw += part[1:]
            if part[0] == "l":
                break
        (packet / ("gdb-" + name)).write_text(raw)
        # QEMU 8.2 emits xi:include without declaring the xi namespace.
        # Keep its original XML above; normalize only the parser's input.
        parse_xml = raw
        if "xi:" in raw and "xmlns:xi=" not in raw:
            parse_xml = re.sub(r"(<(?:target|feature)\b)",
                               r'\1 xmlns:xi="http://www.w3.org/2001/XInclude"',
                               raw, count=1)
        root = ET.fromstring(parse_xml)
        for element in root.iter():
            if element.tag.endswith("include"):
                self.features(element.attrib["href"], packet)
            elif element.tag == "reg":
                number = int(element.attrib.get("regnum", self.next_number))
                self.registers[element.attrib["name"]] = number
                self.next_number = number + 1

    def capture(self):
        values = {}
        for name, number in self.registers.items():
            if re.search(r"CNT|DAIF|TCR|TTBR|SCTLR|VBAR|HCR|SCR|CPACR|TPIDR|ISR", name.upper()):
                raw = self.command(f"p{number:x}")
                values[name] = hex(int.from_bytes(bytes.fromhex(raw), "little")) if re.fullmatch(r"[0-9a-fA-F]+", raw) else raw
        return values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", required=True)
    parser.add_argument("--seconds", type=int, default=25)
    args = parser.parse_args()
    assert 5 <= args.seconds <= 60
    source = (PROJECT / args.packet).resolve()
    assert source.is_relative_to((PROJECT / "evidence/phase-3/platform-qemu").resolve())
    previous = json.loads((source / "result.json").read_text())
    build = json.loads((PROJECT / previous["build_packet"] / "result.json").read_text())
    kernel = PROJECT / previous["build_packet"] / "artifacts/hakios-kernel"
    assert pin(kernel) == build["artifacts"]["hakios-kernel"]
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    packet = PROJECT / "evidence/phase-3/qemu-diagnostics" / stamp
    work = Path("/opt/a51-hakios/experimental/phase3-qemu-diagnostics") / stamp
    packet.mkdir(parents=True, exist_ok=False)
    work.mkdir(parents=True, exist_ok=False)
    shutil.copy2(Path(__file__), packet / "source.py")
    result = {"schema_version": 1, "packet": str(packet.relative_to(PROJECT)),
              "source_packet": args.packet, "source_result": pin(source / "result.json"),
              "kernel": pin(kernel), "scope": "QEMU diagnostics only, replayed nonce",
              "device_operations": False, "phase_3_device_gate_passed": False,
              "commands": [], "snapshots": []}
    env = dict(os.environ, PATH="/usr/lib/llvm-18/bin:" + os.environ["PATH"])
    proc = None
    qmp = None
    try:
        nm_argv = ["llvm-nm", "-n", str(kernel)]
        result["commands"].append(nm_argv)
        nm = subprocess.check_output(nm_argv, env=env, text=True)
        (packet / "symbols.txt").write_text(nm)
        symbols = {}
        for line in nm.splitlines():
            parts = line.split()
            if len(parts) == 3 and re.fullmatch(r"[0-9a-fA-F]+", parts[0]):
                symbols[parts[2]] = int(parts[0], 16)
        argv = previous["commands"][-1].copy()
        argv[argv.index("-qmp") + 1] = f"unix:{work / 'monitor.sock'},server=on,wait=off"
        argv += ["-d", "guest_errors,unimp", "-D", str(packet / "guest-errors.log"),
                 "-gdb", f"unix:{work / 'gdb.sock'},server=on,wait=off"]
        result["commands"].append(argv)
        with (packet / "serial.log").open("wb") as log:
            proc = subprocess.Popen(argv, env=env, stdout=log, stderr=subprocess.STDOUT)
            start = time.monotonic()
            while not (work / "monitor.sock").exists() and proc.poll() is None and time.monotonic() - start < 10:
                time.sleep(.1)
            qmp = module.Qmp(work / "monitor.sock")
            registers = None
            for index in range(1, 3):
                deadline = start + args.seconds * index / 2
                while proc.poll() is None and time.monotonic() < deadline:
                    time.sleep(.2)
                if proc.poll() is not None:
                    break
                qmp.command("stop")
                snap = {"elapsed_seconds": time.monotonic() - start, "globals": {}, "monitor": {}}
                if registers is None:
                    registers = Registers(work / "gdb.sock", packet)
                snap["system_registers"] = registers.capture()
                snap["gic_mmio"] = {}
                # Read registers without acknowledging or ending an interrupt.
                for name, pa in (("GICD_CTLR", 0x08000000), ("GICD_TYPER", 0x08000004),
                                 ("GICD_IGROUPR0", 0x08000080), ("GICD_ISENABLER0", 0x08000100),
                                 ("GICD_ISPENDR0", 0x08000200), ("GICD_ISACTIVER0", 0x08000300),
                                 ("GICD_PRIORITY_TIMER", 0x08000418),
                                 ("GICC_CTLR", 0x08010000), ("GICC_PMR", 0x08010004),
                                 ("GICC_BPR", 0x08010008), ("GICC_RPR", 0x08010014),
                                 ("GICC_HPPIR", 0x08010018)):
                    path = packet / f"{name}-{index}.bin"
                    qmp.save(pa, 4, path)
                    snap["gic_mmio"][name] = hex(int.from_bytes(path.read_bytes(), "little"))
                for command in ("info registers -a", "info pic", "info irq"):
                    text = qmp.command("human-monitor-command", {"command-line": command})
                    name = command.replace(" ", "-") + f"-{index}.txt"
                    (packet / name).write_text(text)
                    snap["monitor"][command] = name
                regs = (packet / snap["monitor"]["info registers -a"]).read_text()
                for name, width in (("_loader_log_len", 4), ("_hakios_timer_irqs", 8),
                                    ("_hakios_boot_midr", 8), ("_gic_unhandled_count", 8),
                                    ("_gic_last_unhandled", 4), ("_loader_return_entered", 1)):
                    if name not in symbols:
                        continue
                    pa = symbols[name] + module.SLIDE
                    path = packet / f"{name}-{index}.bin"
                    qmp.save(pa, width, path)
                    snap["globals"][name] = int.from_bytes(path.read_bytes(), "little")
                length = snap["globals"].get("_loader_log_len", 0)
                if 0 < length <= 1536 * 1024 and "_loader_log" in symbols:
                    qmp.save(symbols["_loader_log"] + module.SLIDE, length, packet / f"live-kernel-log-{index}.bin")
                for name in ("PC", "SP", "X29", "X30"):
                    match = re.search(r"\b" + name + r"=([0-9a-fA-F]+)", regs)
                    if not match:
                        continue
                    value = int(match.group(1), 16)
                    snap[name] = hex(value)
                    prior_symbols = [(address, key) for key, address in symbols.items() if address <= value]
                    if prior_symbols:
                        address, key = max(prior_symbols)
                        snap[name + "_symbol"] = f"{key}+0x{value-address:x}"
                    if name in ("SP", "X29"):
                        command = f"x /64gx 0x{value:x}"
                        (packet / f"stack-{name}-{index}.txt").write_text(qmp.command("human-monitor-command", {"command-line": command}))
                result["snapshots"].append(snap)
                print(json.dumps(snap, indent=2), flush=True)
                qmp.command("cont")
            qmp.command("quit")
            proc.wait(timeout=5)
        result["diagnostic_captured"] = bool(result["snapshots"])
    except Exception as exc:
        result["error"] = repr(exc)
    finally:
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        if proc is not None:
            result["qemu_exit_code"] = proc.returncode
        (packet / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print("DIAGNOSTIC " + str(packet.relative_to(PROJECT)), flush=True)
    return 0 if result.get("diagnostic_captured") else 1


if __name__ == "__main__":
    raise SystemExit(main())
