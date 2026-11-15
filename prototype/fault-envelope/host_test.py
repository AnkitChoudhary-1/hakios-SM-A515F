#!/usr/bin/env python3
"""Execute the stackless fault envelope in isolated QEMU; replay on either host.

No ADB, device image, A51 address, upstream change or device watchdog is used.
Fatal cases are stopped and read through QMP after their commit is observed.
The host deadline only bounds the fixture process; it is not fault recovery.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import struct
import subprocess
import tempfile
import time

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
NAMES = ["envelope.S", "envelope.h", "harness.S", "harness.c", "harness.ld", "host_test.py"]
BEFORE = struct.pack("<Q", 0xcafedeadfacec0de) * 64
AFTER = struct.pack("<Q", 0xdeadbeefcafef00d) * 64
ARGS = [0x1010, 0x2020, 0x3030, 0x4040]
PRESERVED = ARGS + [r * 257 for r in range(18, 31)] + [0, 0xa0000000]
FALSE_FLAGS = ["phone_queries", "phone_writes", "a51_payload_execution_verified",
               "a51_return_verified", "persistent_device_fault_logs_verified",
               "device_watchdog_verified", "phase_2_device_gate_passed"]


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def cases():
    result = []
    for el in (1, 2):
        for sp0 in (False, True):
            for guard, faults in ((0, range(6)), (1, (0,)), (2, (0,))):
                for fault in faults:
                    result.append(dict(el=el, sp0=sp0, guard=guard, fault=fault,
                        fatal=guard == 0 and fault >= 3))
            if el == 1:
                result.append(dict(el=el, sp0=sp0, guard=3, fault=0, fatal=False))
    for case in result:
        case["name"] = "f%d-g%d-el%d-sp%d" % (
            case["fault"], case["guard"], case["el"], int(not case["sp0"]))
    return result


def symbols(data):
    return {name: int(address, 16) for address, name in
            re.findall(r"^([0-9a-fA-F]+)\s+\w\s+(\S+)$", data.decode(), re.M)}


def validate(case, sym, record, registers, before, after, park_pc=None):
    """Independent decode of raw guest memory, including architectural state."""
    checks = 0
    def check(ok, message):
        nonlocal checks
        checks += 1
        require(ok, case["name"] + ": " + message)
    check(len(record) == 512 and len(registers) == 192, "packet extents")
    check(before == BEFORE and after == AFTER, "adjacent record guards")
    r = struct.unpack("<64Q", record)
    regs = struct.unpack("<24Q", registers)
    check(r[:3] == (0x31464c45494b4148, 1, 512), "initialized record header")
    check(sym["hkf_vectors"] % 2048 == 0 and
          sym["hkf_vectors_end"] - sym["hkf_vectors"] == 2048, "vector ABI")
    check(sym["hkf_record"] % 512 == 0 and
          sym["hkf_record_end"] - sym["hkf_record"] == 512, "record ABI")
    check(sym["hkf_record"] - sym["fixture_record_before"] == 512 and
          sym["fixture_record_after"] == sym["hkf_record_end"], "guard adjacency")
    check(r[30:] == (0,) * 34, "reserved record bytes")
    spsel = int(not case["sp0"])
    daif = 0x340 if case["guard"] == 1 else 0x3c0
    if not case["fatal"]:
        check(list(regs[:19]) == PRESERVED, "x0-x3/x18-x30/SP/NZCV preservation")
        check(regs[19:23] == (daif, spsel, case["el"] * 4, sym["fixture_vectors"]),
              "DAIF/SPSel/EL/incoming VBAR preservation")
        expected_bits = {0: 0, 1: 0, 2: 4, 3: 1}[case["guard"]]
        check(regs[23] & 5 == expected_bits, "SCTLR guard state")
    else:
        check(regs == (0,) * 24, "fatal case did not reach continuation")
        check(park_pc in (sym["hkf_park"], sym["hkf_park"] + 4),
              "stopped vCPU at fatal park")
    if case["guard"]:
        check(r[3:] == (0,) * 61, "unsafe-entry guard left record untouched")
        return checks
    check(r[4] == case["el"] * 4 and r[5] & 5 == 0, "entry EL/SCTLR")
    check(r[6:12] == (0x3c0, 0xa0000000, spsel, sym["fixture_vectors"], 0, 30 * 257),
          "entry DAIF/NZCV/SPSel/VBAR/SP/LR capture")
    check(list(r[12:16]) == ARGS, "entry argument capture")
    line_encoding = (r[16] >> 16) & 15
    check(line_encoding < 7 and r[17] == 4 << line_encoding, "cache-line contract")
    check(r[25:28] == (sym["hkf_entry"], sym["hkf_fault_site"], sym["hkf_continue"]),
          "entry/site/continuation PC capture")
    check(r[28:30] == (int(case["fatal"]), 1), "VBAR armed/commit state")
    if not case["fatal"]:
        check(r[5] == regs[23], "SCTLR preserved after envelope")
    if case["fault"] == 0:
        value = ARGS[0] ^ ARGS[1] ^ ARGS[2] ^ ARGS[3]
        value = ((value >> 7) | (value << 57)) & ((1 << 64) - 1)
        check(r[3] == 2 and r[18:24] == (0,) * 6 and r[24] == value,
              "normal completion/value/no fault")
    else:
        esr = (0x02000000 if case["fault"] == 2 else
               0xf2000043 if case["fault"] == 3 else 0xf2000042)
        pc = sym["hkf_wrong_site"] if case["fault"] == 4 else sym["hkf_fault_site"]
        check(r[3] == (4 if case["fatal"] else 3) and r[23] == 1 and r[24] == 0,
              "one captured fault and expected recovery policy")
        check(r[18:23] == (spsel * 4, esr, pc, 0x5151,
                          0xa0000000 | 0x3c0 | case["el"] * 4 | spsel),
              "vector/ESR/ELR/FAR/SPSR capture")
    return checks


class QMP:
    def __init__(self, path, trace):
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.settimeout(5)
        self.trace = trace
        self.serial = 0
        deadline = time.monotonic() + 5
        while True:
            try:
                self.socket.connect(str(path))
                break
            except (FileNotFoundError, ConnectionRefusedError):
                require(time.monotonic() < deadline, "QMP connection deadline")
                time.sleep(0.02)
        self.stream = self.socket.makefile("rwb", buffering=0)
        greeting = self.read()
        require("QMP" in greeting, "QMP greeting")
        self.execute("qmp_capabilities")

    def read(self):
        line = self.stream.readline(1024 * 1024)
        require(bool(line), "QMP disconnected")
        message = json.loads(line)
        self.trace.append(dict(at_utc=now(), receive=message))
        return message

    def execute(self, command, arguments=None):
        self.serial += 1
        message = dict(execute=command, id=self.serial)
        if arguments is not None:
            message["arguments"] = arguments
        self.trace.append(dict(at_utc=now(), send=message))
        self.stream.write((json.dumps(message) + "\n").encode())
        while True:
            reply = self.read()
            if reply.get("id") == self.serial:
                require("error" not in reply, "QMP error: " + str(reply))
                return reply["return"]

    def hmp(self, command):
        return self.execute("human-monitor-command", {"command-line": command})

    def close(self):
        self.stream.close()
        self.socket.close()


def build():
    require(os.name == "posix", "build in A51-KernelBuilder WSL; --verify works on Windows")
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    evidence = PROJECT / "evidence/phase-2/fault-envelope-host" / stamp
    work = Path("/opt/a51-hakios/experimental/fault-envelope-host") / stamp
    evidence.mkdir(parents=True, exist_ok=False)
    work.mkdir(parents=True, exist_ok=False)
    (evidence / "sources").mkdir()
    result = dict(schema_version=1, status="running", scope="synthetic-qemu-fault-envelope-only",
                  work=str(work), source_pins={}, artifacts={}, commands=[], cases=[])
    result.update({flag: False for flag in FALSE_FLAGS})
    def write():
        (evidence / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    def retain(name, data):
        require(Path(name).name == name and name not in result["artifacts"], "artifact name")
        (evidence / name).write_bytes(data)
        result["artifacts"][name] = dict(bytes=len(data), sha256=sha(data))
    for name in NAMES:
        data = (HERE / name).read_bytes()
        (work / name).write_bytes(data)
        (evidence / "sources" / name).write_bytes(data)
        result["source_pins"][name] = dict(bytes=len(data), sha256=sha(data))
    env = dict(os.environ, PATH="/usr/lib/llvm-18/bin:" + os.environ["PATH"])
    write()
    def run(argv, name, timeout=30):
        command = dict(argv=[str(a) for a in argv], cwd=str(work), started_utc=now(),
                       timeout_seconds=timeout, output=name + ".log")
        try:
            p = subprocess.run(command["argv"], cwd=work, env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, timeout=timeout)
            output, code = p.stdout, p.returncode
        except subprocess.TimeoutExpired as exc:
            output, code = exc.stdout or b"", 124
        command.update(finished_utc=now(), exit_code=code)
        retain(command["output"], output)
        result["commands"].append(command)
        write()
        require(code == 0, name + " failed: " + str(evidence / command["output"]))
        return output

    def guest(case, sym, binary):
        tag = case["name"]
        trace = []
        with tempfile.TemporaryDirectory(prefix="hkf-qmp-") as monitor_dir:
            qmp_path = Path(monitor_dir) / "monitor.sock"
            argv = ["qemu-system-aarch64", "-machine",
                    "virt,virtualization=on" if case["el"] == 2 else "virt",
                    "-cpu", "cortex-a53", "-smp", "1", "-m", "64M", "-display", "none",
                    "-monitor", "none", "-serial", "file:" + tag + ".serial",
                    "-nic", "none", "-no-reboot", "-S", "-qmp",
                    "unix:" + str(qmp_path) + ",server=on,wait=off", "-kernel", binary]
            command = dict(argv=argv, cwd=str(work), started_utc=now(), timeout_seconds=15,
                           output=tag + "-qemu.log", qmp_trace=tag + "-qmp.json")
            result["commands"].append(command)
            write()
            process = subprocess.Popen(argv, cwd=work, env=env, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT)
            monitor = None
            try:
                monitor = QMP(qmp_path, trace)
                monitor.execute("cont")
                park_pc = None
                if case["fatal"]:
                    deadline = time.monotonic() + 5
                    while True:
                        commit = monitor.hmp("xp /1gx 0x%x" % (sym["hkf_record"] + 232))
                        values = re.findall(r":\s+0x([0-9a-fA-F]{16})", commit)
                        if values == ["0000000000000001"]:
                            break
                        require(time.monotonic() < deadline, "fatal commit deadline: " + tag)
                        time.sleep(0.02)
                    monitor.execute("stop")
                    info = monitor.hmp("info registers")
                    match = re.search(r"\bPC=([0-9a-fA-F]+)", info)
                    require(match is not None, "stopped vCPU PC: " + tag)
                    park_pc = int(match[1], 16)
                    retain(tag + "-cpu.txt", info.encode())
                    for name, address, size in [
                            ("memory", sym["fixture_record_before"], 1536),
                            ("registers", sym["fixture_registers"], 192)]:
                        filename = tag + "-" + name + ".bin"
                        reply = monitor.hmp("pmemsave 0x%x %d %s" % (address, size, filename))
                        require(not reply.strip(), "QEMU memory retrieval: " + reply)
                        retain(filename, (work / filename).read_bytes())
                    memory = (work / (tag + "-memory.bin")).read_bytes()
                    before, record, after = memory[:512], memory[512:1024], memory[1024:]
                    registers = (work / (tag + "-registers.bin")).read_bytes()
                    monitor.execute("quit")
                output, _ = process.communicate(timeout=5)
                require(process.returncode == 0, "QEMU failed: " + tag)
                serial = (work / (tag + ".serial")).read_bytes()
                retain(tag + ".serial", serial)
                if case["fatal"]:
                    require(not serial, "fatal fixture emitted a continuation packet")
                else:
                    require(serial.count(b"HKF_CONTINUED_V1\n") == 1, "continuation marker")
                    packets = {}
                    for label, size in [("RECORD", 512), ("REGISTERS", 192),
                                        ("BEFORE", 512), ("AFTER", 512)]:
                        hits = re.findall(r"^" + label + r" ([0-9a-f]{%d})$" % (size * 2),
                                          serial.decode(), re.M)
                        require(len(hits) == 1, "serial packet: " + label)
                        packets[label] = bytes.fromhex(hits[0])
                    record, registers = packets["RECORD"], packets["REGISTERS"]
                    before, after = packets["BEFORE"], packets["AFTER"]
                    retain(tag + "-memory.bin", before + record + after)
                    retain(tag + "-registers.bin", registers)
                count = validate(case, sym, record, registers, before, after, park_pc)
                return dict(**case, checks=count, verified=True, park_pc=park_pc)
            finally:
                if process.poll() is None:
                    process.kill()
                output, _ = process.communicate()
                command.update(finished_utc=now(), exit_code=process.returncode)
                retain(command["output"], output)
                retain(command["qmp_trace"], (json.dumps(trace, indent=2) + "\n").encode())
                if monitor is not None:
                    monitor.close()
                write()
    try:
        for tool in ["clang", "ld.lld", "llvm-objcopy", "llvm-nm", "llvm-objdump",
                     "llvm-readelf", "qemu-system-aarch64"]:
            run([tool, "--version"], "version-" + tool)
        flags = ["--target=aarch64-none-elf", "-mcpu=cortex-a53", "-ffreestanding",
                 "-fno-builtin", "-fno-stack-protector", "-mgeneral-regs-only", "-O2",
                 "-Wall", "-Wextra", "-Werror", "-I", str(work)]
        for case in cases():
            tag = case["name"]
            defs = ["-DHKF_TEST_FAULT=" + str(case["fault"]),
                    "-DHKF_GUARD=" + str(case["guard"]), "-DHKF_SP0=" + str(int(case["sp0"]))]
            for source, role in [("envelope.S", "payload"), ("harness.S", "start"),
                                 ("harness.c", "main")]:
                run(["clang", *flags, *defs, "-c", source, "-o", tag + "-" + role + ".o"],
                    tag + "-" + role)
            elf, binary = tag + ".elf", tag + ".bin"
            run(["ld.lld", "-T", "harness.ld", "--build-id=none",
                 *[tag + "-" + role + ".o" for role in ("payload", "start", "main")],
                 "-o", elf], tag + "-link")
            sym = symbols(run(["llvm-nm", "--defined-only", elf], tag + "-symbols"))
            run(["llvm-objcopy", "-O", "binary", elf, binary], tag + "-binary")
            run(["llvm-objdump", "-d", tag + "-payload.o"], tag + "-disassembly")
            run(["llvm-readelf", "-SW", elf], tag + "-sections")
            retain(elf, (work / elf).read_bytes())
            retain(binary, (work / binary).read_bytes())
            result["cases"].append(guest(case, sym, binary))
            write()
            print("PASS " + tag + " checks=" + str(result["cases"][-1]["checks"]), flush=True)
        result.update(status="passed", synthetic_continuations=sum(not c["fatal"] for c in cases()),
                      synthetic_fatal_records=sum(c["fatal"] for c in cases()),
                      checks=sum(c["checks"] for c in result["cases"]))
    except BaseException as exc:
        result.update(status="failed", error=str(exc))
        raise
    finally:
        result["finished_utc"] = now()
        write()
        print("RESULT " + str(evidence / "result.json"), flush=True)


def verify(evidence):
    evidence = evidence.resolve()
    result = json.loads((evidence / "result.json").read_text(encoding="utf-8"))
    require(result["status"] == "passed" and result["schema_version"] == 1, "unpassed evidence")
    require(result["scope"] == "synthetic-qemu-fault-envelope-only", "scope")
    require(all(result[flag] is False for flag in FALSE_FLAGS), "device claim boundary")
    require(set(result["source_pins"]) == set(NAMES), "source inventory")
    for name, pin in result["source_pins"].items():
        data = (evidence / "sources" / name).read_bytes()
        require(len(data) == pin["bytes"] and sha(data) == pin["sha256"], "source pin: " + name)
    for name, pin in result["artifacts"].items():
        require(Path(name).name == name, "artifact path")
        data = (evidence / name).read_bytes()
        require(len(data) == pin["bytes"] and sha(data) == pin["sha256"], "artifact pin: " + name)
    require(len(result["cases"]) == len(cases()), "case count")
    checks = 0
    for expected, case in zip(cases(), result["cases"]):
        require(all(case[key] == value for key, value in expected.items()) and
                case["verified"] is True, "case contract")
        tag = case["name"]
        sym = symbols((evidence / (tag + "-symbols.log")).read_bytes())
        memory = (evidence / (tag + "-memory.bin")).read_bytes()
        registers = (evidence / (tag + "-registers.bin")).read_bytes()
        require(len(memory) == 1536, "memory packet bounds")
        pc = None
        if case["fatal"]:
            info = (evidence / (tag + "-cpu.txt")).read_text()
            pc = int(re.search(r"\bPC=([0-9a-fA-F]+)", info)[1], 16)
        count = validate(case, sym, memory[512:1024], registers, memory[:512], memory[1024:], pc)
        require(count == case["checks"] and pc == case["park_pc"], "replayed observations")
        checks += count
    require(checks == result["checks"] and all(c["exit_code"] == 0 for c in result["commands"]),
            "checks/command outcomes")
    print("PASS replay cases=%d checks=%d files=%d" %
          (len(cases()), checks, len(result["artifacts"]) + len(NAMES) + 1))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", type=Path, help="offline replay of one retained host result")
    args = parser.parse_args()
    if args.verify:
        verify(args.verify)
    else:
        build()


if __name__ == "__main__":
    main()
