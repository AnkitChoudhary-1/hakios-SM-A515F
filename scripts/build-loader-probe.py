#!/usr/bin/env python3
"""Build/test the isolated synthetic C probe in native WSL and QEMU virt.

No phone interface, physical A51 layout or upstream checkout is used.
"""
import argparse
import datetime as dt
import hashlib
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import zlib
from pathlib import Path, PurePosixPath

PROJECT = Path(__file__).resolve().parents[1]
INPUT = b"HAKIOS-PROBE-v1!"
FRAME_SIZE = 256
QEMU_FLAGS = ["-machine", "virt", "-cpu", "cortex-a53", "-smp", "1", "-m", "64M",
              "-nographic", "-monitor", "none", "-nic", "none", "-no-reboot"]
C_FLAGS = ["-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-Wconversion", "-Wshadow"]
ARM_FLAGS = ["--target=aarch64-none-elf", "-mcpu=cortex-a53", "-ffreestanding",
             "-fno-builtin", "-fno-stack-protector", "-mgeneral-regs-only"]
TOOLS = ["clang", "ld.lld", "llvm-objcopy", "llvm-nm", "qemu-system-aarch64"]
SOURCES = {"probe.c", "probe.h", "test_probe.c", "qemu/main.c", "qemu/start.S", "qemu/virt.ld", "build-loader-probe.py"}
SCOPE = "native_host_tests_and_qemu_virt_probe_only"
JSON_LIMIT = 512 * 1024


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read(path, limit=16 * 1024 * 1024):
    if type(limit) is not int or limit < 0 or limit > 16 * 1024 * 1024:
        raise ValueError("invalid read limit")
    if not path.is_file():
        raise ValueError(f"nonregular file: {path}")
    with path.open("rb") as f:
        data = f.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"oversized file: {path}")
    return data


def dump(path, obj):
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def timestamp():
    now = dt.datetime.now(dt.timezone.utc)
    return {"utc": now.isoformat(), "ist": now.astimezone(dt.timezone(dt.timedelta(hours=5, minutes=30))).isoformat()}


def object_fields(value, keys, label):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError(f"invalid {label} fields")


def json_data(data):
    try:
        text = data.decode("utf-8", errors="strict")
    except (AttributeError, UnicodeError) as exc:
        raise ValueError("JSON must contain UTF-8 bytes") from exc
    depth = 0
    quoted = False
    escaped = False
    for character in text:
        if quoted:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
        elif character == '"':
            quoted = True
        elif character in "[{":
            depth += 1
            if depth > 64:
                raise ValueError("JSON nesting exceeds 64 levels")
        elif character in "]}":
            depth -= 1
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError("duplicate JSON key")
            value[key] = item
        return value

    def constant(value):
        raise ValueError(f"nonfinite JSON value: {value}")

    def floating(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("nonfinite JSON number")
        return number

    try:
        return json.loads(text, object_pairs_hook=pairs, parse_constant=constant, parse_float=floating)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("invalid or excessively nested JSON") from exc


def typed_equal(first, second):
    # JSON boolean, number and integer representations must remain distinct.
    try:
        return json.dumps(first, sort_keys=True, separators=(",", ":"), allow_nan=False) == json.dumps(
            second, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("invalid comparison value") from exc


def digest(value):
    if type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("invalid SHA-256")
    return value


def relative_name(value):
    if type(value) is not str or not value or len(value) > 256 or ":" in value or "\\" in value:
        raise ValueError("invalid evidence path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value or value == ".":
        raise ValueError("noncanonical evidence path")
    return value


def recorded_time(value):
    object_fields(value, {"utc", "ist"}, "timestamp")
    parsed = []
    for key, suffix in [("utc", "+00:00"), ("ist", "+05:30")]:
        text = value[key]
        if type(text) is not str or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?" + re.escape(suffix), text):
            raise ValueError("invalid timestamp offset/format")
        try:
            parsed.append(dt.datetime.fromisoformat(text))
        except ValueError as exc:
            raise ValueError("invalid timestamp date") from exc
    if parsed[0] != parsed[1]:
        raise ValueError("UTC/IST timestamp disagreement")
    return parsed[0]


def identity_header(identity):
    def initializer(value):
        return "{" + ",".join("0x" + value[i:i+2] for i in range(0, 64, 2)) + "}"
    return (f"#define HP_BUILD_SHA256 {initializer(identity)}\n"
            f"#define HP_INPUT_SHA256 {initializer(sha(INPUT))}\n").encode("ascii")


def expected_commands(work, tools):
    src = work + "/source"
    native = work + "/test-probe"
    elf = work + "/probe.elf"
    binary = work + "/probe.bin"
    commands = [[tools[name]["path"], "--version"] for name in TOOLS]
    commands.extend([
        [tools["clang"]["path"], *C_FLAGS, "-g", "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
         "-I", src, src + "/probe.c", src + "/test_probe.c", "-o", native],
        [native],
    ])
    arm_c = [flag if flag != "-std=c11" else "-std=gnu11" for flag in C_FLAGS]
    for name in ["probe.c", "qemu/main.c", "qemu/start.S"]:
        commands.append([tools["clang"]["path"], *arm_c, *ARM_FLAGS, "-I", src, "-I", work,
                         "-c", src + "/" + name, "-o", work + "/" + PurePosixPath(name).stem + ".o"])
    commands.extend([
        [tools["ld.lld"]["path"], "-T", src + "/qemu/virt.ld", "--build-id=none",
         work + "/start.o", work + "/probe.o", work + "/main.o", "-o", elf],
        [tools["llvm-nm"]["path"], "-u", elf],
        [tools["llvm-objcopy"]["path"], "-O", "binary", elf, binary],
        [tools["qemu-system-aarch64"]["path"], *QEMU_FLAGS, "-kernel", binary],
    ])
    return commands


def decode_serial(data, build_hash):
    digest(build_hash)
    if type(data) is not bytes or len(data) > 4096:
        raise ValueError("invalid or oversized serial transcript")
    try:
        text = data.decode("ascii", errors="strict").replace("\r\n", "\n")
    except UnicodeError as exc:
        raise ValueError("non-ASCII serial transcript") from exc
    if "\r" in text:
        raise ValueError("stray carriage return")
    lines = text.splitlines()
    if lines[0:1] != ["HAKIOS_QEMU_PROBE_V1"] or lines[-1:] != ["QEMU_PROBE_PASS"] or len(lines) != 9:
        raise ValueError("QEMU transcript does not contain exactly the banner, seven frames and success")
    frames = []
    entry = None
    for seq, line in enumerate(lines[1:8]):
        if not re.fullmatch(r"FRAME [0-9a-f]{512}", line):
            raise ValueError("invalid frame line")
        f = bytes.fromhex(line[6:])
        version, sequence, stage, status, mode, flags = struct.unpack_from("<6I", f, 8)
        if f[:8] != b"HAKIPRB1" or (version, sequence, stage, status, mode, flags) != (1, seq, seq + 1, 0, 2, 0x3fff):
            raise ValueError("invalid successful QEMU frame semantics")
        if struct.unpack_from("<I", f, 252)[0] != zlib.crc32(f[:252]):
            raise ValueError("frame CRC mismatch")
        if f[32:64].hex() != build_hash or f[64:96] != hashlib.sha256(INPUT).digest() or f[96:128] != bytes(32):
            raise ValueError("identity mismatch")
        regs = struct.unpack_from("<14Q", f, 128)
        if regs[4] != 0x40080000 or regs[6] != 1 or regs[7] == 0:
            raise ValueError("unexpected QEMU entry PC/EL/frequency")
        if entry is not None and regs != entry:
            raise ValueError("entry record changed")
        entry = regs
        fuel, callback_status = struct.unpack_from("<QI", f, 240)
        if fuel != (64 if seq < 4 else 48) or callback_status:
            raise ValueError("unexpected budget/callback outcome")
        frames.append({"sequence": seq, "stage": stage, "status": status, "fuel": fuel,
                       "sha256": sha(f), "crc32": f"{zlib.crc32(f[:252]):08x}"})
    return {"frames": frames, "entry_fields": list(entry), "entry_flags": 0x3fff,
            "entry_scope": "qemu_virt_measured_before_stack_setup", "fdt_consumed": False}


def verify(folder):
    folder = folder.resolve()
    index_path = folder / "index.json"
    if index_path.is_symlink():
        raise ValueError("symlinked index")
    index = json_data(read(index_path, JSON_LIMIT))
    object_fields(index, {"schema_version", "files"}, "index")
    required = {"result.json", "identity-input.json", "identity.h", "test-probe", "probe.elf", "probe.bin"}
    required.update("source/" + name for name in SOURCES)
    required.update(f"commands/{i:02d}.{suffix}" for i in range(14) for suffix in ["json", "stdout", "stderr"])
    if type(index["schema_version"]) is not int or index["schema_version"] != 1 or type(index["files"]) is not list or len(index["files"]) != len(required):
        raise ValueError("invalid index schema or role count")
    listed = {}
    total = 0
    for item in index["files"]:
        object_fields(item, {"path", "size", "sha256"}, "index entry")
        name = relative_name(item["path"])
        if name in listed or name not in required:
            raise ValueError("duplicate or unexpected evidence role")
        limit = (JSON_LIMIT if name.endswith(".json") or name == "identity.h" else
                 4096 if name in {"commands/06.stdout", "commands/13.stdout"} else 16 * 1024 * 1024)
        if type(item["size"]) is not int or item["size"] < 0 or item["size"] > limit:
            raise ValueError("invalid file size")
        digest(item["sha256"])
        if total + item["size"] > 64 * 1024 * 1024:
            raise ValueError("oversized evidence set")
        path = folder / name
        if path.is_symlink() or not path.resolve().is_relative_to(folder.resolve()):
            raise ValueError("evidence path escape")
        data = read(path, limit)
        if item["size"] != len(data) or item["sha256"] != sha(data):
            raise ValueError(f"identity mismatch: {name}")
        total += len(data)
        if total > 64 * 1024 * 1024:
            raise ValueError("oversized evidence set")
        listed[name] = data
    if set(listed) != required:
        raise ValueError("missing evidence role")
    actual = set()
    entries = 0
    for path in folder.rglob("*"):
        entries += 1
        if entries > len(required) + 4:
            raise ValueError("extra evidence entries")
        if path.is_symlink():
            raise ValueError("symlinked evidence entry")
        if path.is_file():
            actual.add(path.relative_to(folder).as_posix())
        elif not path.is_dir():
            raise ValueError("nonregular evidence entry")
        if len(actual) > len(required) + 1:
            raise ValueError("extra evidence files")
    if actual != set(listed) | {"index.json"}:
        raise ValueError("evidence file set mismatch")

    def evidence(name, limit=16 * 1024 * 1024):
        name = relative_name(name)
        if name not in listed or len(listed[name]) > limit:
            raise ValueError("unindexed or oversized evidence reference")
        return listed[name]

    result = json_data(evidence("result.json", JSON_LIMIT))
    object_fields(result, {"schema_version", "status", "started", "finished", "work", "phone_queries", "phone_writes",
                          "a51_destination_selected", "phase_2_device_gate_passed", "a51_xnu_boot_verified", "scope",
                          "build_identity_sha256", "commands", "host_stdout", "host_checks", "qemu_stdout", "qemu"}, "result")
    if type(result["schema_version"]) is not int or result["schema_version"] != 1 or result["scope"] != SCOPE or result["status"] != "passed" or any(result[k] is not False for k in
            ["phone_queries", "phone_writes", "a51_destination_selected", "phase_2_device_gate_passed", "a51_xnu_boot_verified"]):
        raise ValueError("invalid success or device claim")
    start, finish = recorded_time(result["started"]), recorded_time(result["finished"])
    if finish < start:
        raise ValueError("result timestamp inversion")
    work = result["work"]
    if type(work) is not str or not re.fullmatch(r"/opt/a51-hakios/prototype/loader/\d{8}T\d{12}Z", work):
        raise ValueError("invalid isolated work path")
    config = json_data(evidence("identity-input.json", JSON_LIMIT))
    object_fields(config, {"sources", "tools", "c_flags", "arm_flags", "qemu_flags", "input_hex", "input_sha256", "fdt"}, "identity input")
    identity = digest(result["build_identity_sha256"])
    if identity != sha(evidence("identity-input.json", JSON_LIMIT)):
        raise ValueError("build identity mismatch")
    object_fields(config["sources"], SOURCES, "source roles")
    object_fields(config["tools"], TOOLS, "tool roles")
    if not typed_equal(config["c_flags"], C_FLAGS) or not typed_equal(config["arm_flags"], ARM_FLAGS) or not typed_equal(config["qemu_flags"], QEMU_FLAGS) or config["input_hex"] != INPUT.hex() or config["input_sha256"] != sha(INPUT) or config["fdt"] != "not_consumed":
        raise ValueError("identity configuration differs from the host/QEMU contract")
    for name, source_digest in config["sources"].items():
        if sha(evidence("source/" + relative_name(name))) != digest(source_digest):
            raise ValueError("source identity mismatch")
    if evidence("identity.h", JSON_LIMIT) != identity_header(identity):
        raise ValueError("generated identity header mismatch")
    for name in TOOLS:
        tool = config["tools"][name]
        object_fields(tool, {"path", "sha256", "version"}, "tool identity")
        path = tool["path"]
        if type(path) is not str or len(path) > 512 or "\\" in path or ":" in path or not path.startswith("/") or ".." in PurePosixPath(path).parts or PurePosixPath(path).as_posix() != path or PurePosixPath(path).name != name:
            raise ValueError("invalid recorded tool path")
        digest(tool["sha256"])
        if type(tool["version"]) is not str or not tool["version"] or len(tool["version"]) > 65536:
            raise ValueError("invalid tool version")
    expected = expected_commands(work, config["tools"])
    if type(result["commands"]) is not list or len(result["commands"]) != len(expected):
        raise ValueError("command role count mismatch")
    previous = start
    for sequence, (command, arguments) in enumerate(zip(result["commands"], expected)):
        object_fields(command, {"arguments", "cwd", "started", "finished", "exit_code", "timed_out", "stdout", "stderr", "record"}, "command")
        prefix = f"commands/{sequence:02d}"
        if type(command["exit_code"]) is not int or command["exit_code"] != 0 or command["timed_out"] is not False or command["cwd"] != work or not typed_equal(command["arguments"], arguments) or any(command[key] != prefix + suffix for key, suffix in [("stdout", ".stdout"), ("stderr", ".stderr"), ("record", ".json")]):
            raise ValueError("unsuccessful or mismatched command role")
        stored = json_data(evidence(command["record"], JSON_LIMIT))
        if not typed_equal({key: value for key, value in command.items() if key != "record"}, stored):
            raise ValueError("command record mismatch")
        command_start, command_finish = recorded_time(command["started"]), recorded_time(command["finished"])
        if not previous <= command_start <= command_finish <= finish:
            raise ValueError("command timing inversion or overlap")
        previous = command_finish
        if evidence(command["stderr"]):
            raise ValueError("unexpected command diagnostic")
        if sequence < 5 and evidence(command["stdout"]).decode("utf-8", errors="strict") != config["tools"][TOOLS[sequence]]["version"]:
            raise ValueError("tool version/output mismatch")
    if evidence("commands/11.stdout").strip():
        raise ValueError("freestanding undefined-symbol output is nonempty")
    if result["host_stdout"] != "commands/06.stdout" or result["qemu_stdout"] != "commands/13.stdout":
        raise ValueError("test output role mismatch")
    host = evidence(result["host_stdout"], 4096)
    match = re.fullmatch(rb"HOST_PROBE_PASS checks=([1-9][0-9]*)\r?\n", host)
    if type(result["host_checks"]) is not int or not match or int(match[1]) != result["host_checks"] or not 30 <= result["host_checks"] <= 1000000:
        raise ValueError("host tests not accepted")
    decoded = decode_serial(evidence(result["qemu_stdout"], 4096), identity)
    if not typed_equal(decoded, result["qemu"]):
        raise ValueError("QEMU result reconstruction mismatch")
    for name, machine in [("test-probe", 62), ("probe.elf", 183)]:
        data = evidence(name)
        if len(data) < 64 or data[:7] != b"\x7fELF\x02\x01\x01" or struct.unpack_from("<H", data, 18)[0] != machine:
            raise ValueError("artifact ELF role mismatch")
    if not evidence("probe.bin"):
        raise ValueError("empty QEMU binary")
    print(f"PROBE_EVIDENCE_VERIFIED files={len(listed)} bytes={total} host_checks={result['host_checks']} frames=7")
    return result


def build():
    if sys.platform != "linux":
        raise ValueError("fresh builds require native WSL; --verify-result also works on Windows")
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = PROJECT / "evidence" / "phase-2" / "loader-probe" / stamp
    folder.mkdir(parents=True, exist_ok=False)
    work = Path("/opt/a51-hakios/prototype/loader") / stamp
    work.mkdir(parents=True, exist_ok=False)
    sources = {p.relative_to(PROJECT / "prototype" / "loader").as_posix(): p
               for p in (PROJECT / "prototype" / "loader").rglob("*") if p.is_file()}
    sources["build-loader-probe.py"] = Path(__file__).resolve()
    for name, path in sources.items():
        for dest in [folder / "source" / name, work / "source" / name]:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, dest)
    commands = []

    def run(args, timeout=45):
        i = len(commands)
        prefix = f"commands/{i:02d}"
        (folder / "commands").mkdir(exist_ok=True)
        record = {"arguments": list(map(str, args)), "cwd": str(work), "started": timestamp(), "timed_out": False}
        print("COMMAND " + json.dumps(record["arguments"]), flush=True)
        try:
            child = subprocess.run(record["arguments"], cwd=work, capture_output=True, timeout=timeout,
                                   env={**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
                                        "UBSAN_OPTIONS": "halt_on_error=1"})
            out, err, code = child.stdout, child.stderr, child.returncode
        except subprocess.TimeoutExpired as exc:
            out, err, code = exc.stdout or b"", exc.stderr or b"", 124
            record["timed_out"] = True
        record.update(exit_code=code, finished=timestamp(), stdout=prefix + ".stdout", stderr=prefix + ".stderr")
        (folder / record["stdout"]).write_bytes(out)
        (folder / record["stderr"]).write_bytes(err)
        dump(folder / (prefix + ".json"), record)
        commands.append({**record, "record": prefix + ".json"})
        print(out.decode("utf-8", errors="replace"), end="", flush=True)
        print(err.decode("utf-8", errors="replace"), end="", flush=True)
        if code:
            raise RuntimeError(f"command failed exit={code}, evidence={folder}")
        return out

    result = {"schema_version": 1, "status": "running", "started": timestamp(), "work": str(work),
              "phone_queries": False, "phone_writes": False, "a51_destination_selected": False,
              "phase_2_device_gate_passed": False, "a51_xnu_boot_verified": False,
              "scope": "native_host_tests_and_qemu_virt_probe_only"}
    try:
        tools = {}
        for tool in TOOLS:
            path = shutil.which(tool)
            if not path:
                raise ValueError(f"missing tool: {tool}")
            version = run([path, "--version"])
            tools[tool] = {"path": path, "sha256": hashlib.file_digest(Path(path).open("rb"), "sha256").hexdigest(),
                           "version": version.decode("utf-8", errors="replace")}
        config = {"sources": {name: sha(read(path)) for name, path in sorted(sources.items())},
                  "tools": tools, "c_flags": C_FLAGS, "arm_flags": ARM_FLAGS, "qemu_flags": QEMU_FLAGS,
                  "input_hex": INPUT.hex(), "input_sha256": sha(INPUT), "fdt": "not_consumed"}
        dump(folder / "identity-input.json", config)
        identity = sha(read(folder / "identity-input.json"))
        result["build_identity_sha256"] = identity
        generated = work / "identity.h"
        generated.write_bytes(identity_header(identity))
        shutil.copyfile(generated, folder / "identity.h")
        src = work / "source"
        native = work / "test-probe"
        run([tools["clang"]["path"], *C_FLAGS, "-g", "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
             "-I", src, src / "probe.c", src / "test_probe.c", "-o", native])
        host = run([native], timeout=30)
        result["host_stdout"] = commands[-1]["stdout"]
        match = re.search(rb"^HOST_PROBE_PASS checks=([0-9]+)$", host, re.M)
        if not match:
            raise ValueError("missing native guard success")
        result["host_checks"] = int(match[1])
        # GNU assembly extensions are confined to this QEMU adapter.
        arm_c = [flag if flag != "-std=c11" else "-std=gnu11" for flag in C_FLAGS]
        for name in ["probe.c", "qemu/main.c", "qemu/start.S"]:
            obj = work / (Path(name).stem + ".o")
            run([tools["clang"]["path"], *arm_c, *ARM_FLAGS, "-I", src, "-I", work,
                 "-c", src / name, "-o", obj])
        elf = work / "probe.elf"
        run([tools["ld.lld"]["path"], "-T", src / "qemu/virt.ld", "--build-id=none",
             work / "start.o", work / "probe.o", work / "main.o", "-o", elf])
        undefined = run([tools["llvm-nm"]["path"], "-u", elf])
        if undefined.strip():
            raise ValueError("freestanding ELF has undefined symbols")
        binary = work / "probe.bin"
        run([tools["llvm-objcopy"]["path"], "-O", "binary", elf, binary])
        for file in [native, elf, binary]:
            shutil.copyfile(file, folder / file.name)
        serial = run([tools["qemu-system-aarch64"]["path"], *QEMU_FLAGS, "-kernel", binary], timeout=20)
        result["qemu_stdout"] = commands[-1]["stdout"]
        result["qemu"] = decode_serial(serial, identity)
        result["status"] = "passed"
    except (ValueError, RuntimeError, OSError) as exc:
        result.update(status="failed", error=str(exc))
    result.update(commands=commands, finished=timestamp())
    dump(folder / "result.json", result)
    files = []
    for path in sorted(folder.rglob("*")):
        if path.is_file():
            data = read(path)
            files.append({"path": path.relative_to(folder).as_posix(), "size": len(data), "sha256": sha(data)})
    dump(folder / "index.json", {"schema_version": 1, "files": files})
    if result["status"] != "passed":
        print(f"PROBE_FAILED {folder}: {result['error']}")
        return 1
    verify(folder)
    dump(PROJECT / "manifests" / "loader-probe-current.json",
         {"result": (folder / "result.json").relative_to(PROJECT).as_posix(), "sha256": sha(read(folder / "result.json")),
          "scope": result["scope"], "phase_2_device_gate_passed": False})
    print(f"PROBE_RESULT {folder / 'result.json'}")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--build", action="store_true")
    actions.add_argument("--verify-result", type=Path)
    args = parser.parse_args()
    try:
        if args.verify_result:
            if args.verify_result.name != "result.json":
                raise ValueError("--verify-result requires the result.json file")
            verify(args.verify_result.resolve().parent)
            return 0
        return build()
    except (ValueError, RuntimeError, OSError, KeyError) as exc:
        print(f"PROBE_ERROR {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
