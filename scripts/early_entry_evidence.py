#!/usr/bin/env python3
"""Strict, offline replay of the selected Phase 2 early-entry evidence.

This verifier never invokes a compiler, QEMU, WSL, ADB, or a phone.  It checks
the retained QEMU, isolated-source preparation, and Android-kernel packets and
keeps every device/return gate false.  The selected legacy host/preparation
packets have no index and the kernel packet does not retain vmlinux; those
limits are reported rather than silently promoted to verified facts.
"""
from __future__ import annotations

import argparse
import datetime as dt
import difflib
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import struct
import sys
from typing import Any, Iterable


PROJECT = Path(__file__).resolve().parents[1]
MAX_JSON = 16 * 1024 * 1024
MAX_TEXT = 16 * 1024 * 1024
MAX_DEPTH = 48
MAX_NODES = 250_000
HEX256 = re.compile(r"[0-9a-f]{64}\Z")
ISO_SUFFIX = re.compile(r"(?:Z|[+-]\d\d:\d\d)\Z")

SELECTED = {
    "host": "evidence/phase-2/early-entry-host/20261111T162536291908Z",
    "host_result_sha256": "379f5c2a450632052fcb251575277151cbfef382bf1f59b984a157e4c4c23d4c",
    "prepare": "evidence/phase-2/early-entry-prepare/20261111T163522918342Z",
    "prepare_result_sha256": "557c6c90f306fbfc6b7219ffa5f570f4639daad12a107e364d21b3f3b14bd0ab",
    "patch_sha256": "bb958f092d82f5b1d5b81761d5198d2a8bf0e80657ecc48a02d27b6e207f409f",
    "kernel": "evidence/phase-2/early-entry-kernel/20261111T163522918342Z",
    "kernel_result_sha256": "5bbe01ecdfab1364cc9a0db05753fcc986fbe9a7e053469e899d02d8f44c7049",
    "kernel_index_sha256": "60fef1b76fff189e256528a900c4b9afa31875c152f57f7ade6dbb7d388fb4f6",
    "image_sha256": "87c0401361d4503afb0b266b15ff0caf1e64f505d61d53be700e8b6c6d8e9cf6",
}

SOURCE_NAMES = (
    "hakios_early_entry.S", "hakios_early_entry.h", "harness.S", "harness.c",
    "harness.ld", "host_test.py",
)
PROTOTYPE_NAMES = SOURCE_NAMES + ("hakios_early_report.c", "prepare.py", "README.md")
CASES = ((0, 1, 43), (0, 2, 43), (1, 1, 42), (2, 1, 50), (3, 1, 50))
EXPECTED_REGISTERS = (
    0x1010, 0x2020, 0x3030, 0x4040, 0x1818, 0x1919, 0x2020, 0x2121,
    0x2222, 0x2323, 0x2424, 0x2525, 0x2626, 0x2727, 0x2828, 0x2929,
    0x3030, 0, 0xA0000000,
)
REQUIRED_SYMBOLS = {
    "_text", "_end", "_edata", "__bss_start", "stext", "hakios_early_entry",
    "hakios_early_tiny_payload", "hakios_early_entry_continue", "hakios_early_record",
    "hakios_early_report", "__mmuoff_data_start", "__mmuoff_data_end",
}
ORIGINAL_FILES = {
    "arch/arm64/kernel/head.S": "fcf3c3937a06b1bb5a31a9b92d852f340dad3ea505ca50b4f1e9dfcef8292cf1",
    "arch/arm64/kernel/setup.c": "eafab4dca1a22c24bd1c26fb0976eed77d639e96ceff6c6692f205911ce68b7b",
    "arch/arm64/kernel/Makefile": "a628d655b96f4cff1432a39bf0d79cf2ff8d0d6d1545700f37064f5dcdbb834d",
}


class EvidenceError(ValueError):
    """A retained packet failed strict verification."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceError(message)


def exact_object(value: Any, keys: Iterable[str], where: str) -> dict[str, Any]:
    expected = set(keys)
    require(type(value) is dict and set(value) == expected,
            f"{where}: fields differ (missing={sorted(expected - set(value) if type(value) is dict else expected)}, "
            f"extra={sorted(set(value) - expected if type(value) is dict else [])})")
    return value


def strict_int(value: Any, where: str, minimum: int | None = None) -> int:
    require(type(value) is int, f"{where}: integer required")
    if minimum is not None:
        require(value >= minimum, f"{where}: value below minimum")
    return value


def strict_bool(value: Any, expected: bool, where: str) -> None:
    require(value is expected, f"{where}: must be {str(expected).lower()}")


def timestamp(value: Any, where: str) -> dt.datetime:
    require(type(value) is str and ISO_SUFFIX.search(value) is not None,
            f"{where}: timezone-aware timestamp required")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvidenceError(f"{where}: invalid timestamp") from exc
    require(parsed.tzinfo is not None and parsed.utcoffset() is not None,
            f"{where}: timezone offset required")
    return parsed.astimezone(dt.timezone.utc)


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular(path: Path, where: str, maximum: int | None = None) -> int:
    try:
        info = path.lstat()
    except OSError as exc:
        raise EvidenceError(f"{where}: missing or unreadable file") from exc
    require(stat.S_ISREG(info.st_mode) and not path.is_symlink(), f"{where}: regular non-symlink file required")
    if maximum is not None:
        require(info.st_size <= maximum, f"{where}: file exceeds {maximum} bytes")
    return info.st_size


def canonical_relative(value: Any, where: str) -> str:
    require(type(value) is str and value and "\\" not in value and "\x00" not in value,
            f"{where}: canonical POSIX relative path required")
    path = PurePosixPath(value)
    require(not path.is_absolute() and str(path) == value and all(part not in ("", ".", "..") for part in path.parts),
            f"{where}: path is absolute, noncanonical, or traverses")
    return value


def packet_file(folder: Path, relative: str, where: str) -> Path:
    relative = canonical_relative(relative, where)
    cursor = folder
    for part in PurePosixPath(relative).parts:
        cursor = cursor / part
        try:
            info = cursor.lstat()
        except OSError as exc:
            raise EvidenceError(f"{where}: missing path component") from exc
        require(not stat.S_ISLNK(info.st_mode), f"{where}: symlink path component rejected")
    regular(cursor, where)
    return cursor


def pin(path: Path) -> dict[str, Any]:
    return {"bytes": regular(path, str(path)), "sha256": sha256_path(path)}


def verify_pin(record: Any, path: Path, where: str) -> None:
    exact_object(record, {"bytes", "sha256"}, where)
    size = strict_int(record["bytes"], where + ".bytes", 0)
    require(type(record["sha256"]) is str and HEX256.fullmatch(record["sha256"]) is not None,
            where + ".sha256: lowercase SHA-256 required")
    require(size == regular(path, where) and record["sha256"] == sha256_path(path), where + ": file pin mismatch")


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(type(key) is str and key not in result, "duplicate or non-string JSON key")
        result[key] = value
    return result


def _constant(value: str) -> Any:
    raise EvidenceError("non-finite JSON number rejected: " + value)


def _json_shape(value: Any, depth: int = 0, counter: list[int] | None = None) -> None:
    counter = [0] if counter is None else counter
    counter[0] += 1
    require(counter[0] <= MAX_NODES and depth <= MAX_DEPTH, "JSON node/depth bound exceeded")
    require(value is None or type(value) in (dict, list, str, int, bool), "JSON floats or unsupported values rejected")
    if type(value) is dict:
        for key, child in value.items():
            require(type(key) is str, "JSON object key must be text")
            _json_shape(child, depth + 1, counter)
    elif type(value) is list:
        for child in value:
            _json_shape(child, depth + 1, counter)


def read_json(path: Path, where: str) -> Any:
    size = regular(path, where, MAX_JSON)
    data = path.read_bytes()
    require(len(data) == size, where + ": short/concurrent read")
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant,
                           parse_float=lambda _: (_ for _ in ()).throw(EvidenceError("JSON floats rejected")))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceError(where + ": invalid UTF-8 JSON") from exc
    _json_shape(value)
    return value


def text(path: Path, where: str) -> str:
    size = regular(path, where, MAX_TEXT)
    data = path.read_bytes()
    require(len(data) == size, where + ": short/concurrent read")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EvidenceError(where + ": invalid UTF-8") from exc


def actual_files(folder: Path) -> set[str]:
    require(folder.is_dir() and not folder.is_symlink(), str(folder) + ": packet directory required")
    result: set[str] = set()
    for path in folder.rglob("*"):
        relative = path.relative_to(folder).as_posix()
        info = path.lstat()
        require(not stat.S_ISLNK(info.st_mode), relative + ": symlink rejected")
        if stat.S_ISREG(info.st_mode):
            result.add(relative)
        else:
            require(stat.S_ISDIR(info.st_mode), relative + ": nonregular entry rejected")
    return result


def selected_folder(folder: Path, role: str) -> None:
    try:
        relative = folder.resolve(strict=True).relative_to(PROJECT.resolve(strict=True)).as_posix()
    except (OSError, ValueError) as exc:
        raise EvidenceError(role + ": selected packet must be below project root") from exc
    require(relative == SELECTED[role], role + ": packet is not the selected evidence path")


def command_record(record: Any, where: str, output_field: str) -> tuple[list[str], dt.datetime, dt.datetime, str]:
    keys = {"argv", "started_utc", "finished_utc", "exit_code", output_field}
    if output_field == "output":
        keys |= {"cwd", "timeout_seconds", "output_sha256"}
    exact_object(record, keys, where)
    require(type(record["argv"]) is list and record["argv"] and all(type(x) is str and x for x in record["argv"]),
            where + ".argv: nonempty string array required")
    started, finished = timestamp(record["started_utc"], where + ".started_utc"), timestamp(record["finished_utc"], where + ".finished_utc")
    require(started <= finished, where + ": inverted timestamps")
    require(type(record["exit_code"]) is int and record["exit_code"] == 0, where + ": nonzero or noninteger exit")
    relative = canonical_relative(record[output_field], where + "." + output_field)
    return record["argv"], started, finished, relative


def verify_command_times(records: list[tuple[dt.datetime, dt.datetime]], finished: dt.datetime, where: str) -> None:
    require(records, where + ": command list empty")
    for previous, current in zip(records, records[1:]):
        require(previous[1] <= current[0], where + ": commands overlap or are out of order")
    require(records[-1][1] <= finished, where + ": result finished before last command")


def _host_expected_files() -> set[str]:
    names = {"result.json", "assemble-payload.log", "payload-disassembly.log", "payload-sections.log"}
    names |= {"version-" + tool + ".log" for tool in (
        "clang", "ld.lld", "llvm-objcopy", "llvm-nm", "llvm-objdump", "llvm-readelf", "qemu-system-aarch64")}
    names |= {"sources/" + name for name in SOURCE_NAMES}
    for case, level, _ in CASES:
        tag = f"case-{case}-el-{level}"
        names.add(tag + ".elf")
        names |= {tag + "-" + suffix + ".log" for suffix in ("assemble", "compile", "link", "symbols", "binary", "qemu")}
    return names


def _host_commands(work: str) -> list[tuple[list[str], str, int]]:
    commands: list[tuple[list[str], str, int]] = []
    tools = ("clang", "ld.lld", "llvm-objcopy", "llvm-nm", "llvm-objdump", "llvm-readelf", "qemu-system-aarch64")
    commands.extend(([tool, "--version"], "version-" + tool + ".log", 30) for tool in tools)
    flags = ["--target=aarch64-none-elf", "-mcpu=cortex-a53", "-ffreestanding", "-fno-builtin",
             "-fno-stack-protector", "-mgeneral-regs-only", "-O2", "-Wall", "-Wextra", "-Werror", "-I", work]
    commands += [
        (["clang", *flags, "-c", "hakios_early_entry.S", "-o", "payload.o"], "assemble-payload.log", 30),
        (["llvm-objdump", "-d", "payload.o"], "payload-disassembly.log", 30),
        (["llvm-readelf", "-SW", "payload.o"], "payload-sections.log", 30),
    ]
    for case, level, _ in CASES:
        tag = f"case-{case}-el-{level}"
        commands += [
            (["clang", *flags, f"-DHKE_CASE={case}", "-c", "harness.S", "-o", tag + "-start.o"], tag + "-assemble.log", 30),
            (["clang", *flags, f"-DHKE_CASE={case}", "-c", "harness.c", "-o", tag + "-main.o"], tag + "-compile.log", 30),
            (["ld.lld", "-T", "harness.ld", "--build-id=none", "payload.o", tag + "-start.o", tag + "-main.o", "-o", tag + ".elf"], tag + "-link.log", 30),
            (["llvm-nm", "--defined-only", tag + ".elf"], tag + "-symbols.log", 30),
            (["llvm-objcopy", "-O", "binary", tag + ".elf", tag + ".bin"], tag + "-binary.log", 30),
            (["qemu-system-aarch64", "-machine", "virt,virtualization=on" if level == 2 else "virt", "-cpu", "cortex-a53", "-smp", "1", "-m", "64M", "-nographic", "-monitor", "none", "-nic", "none", "-no-reboot", "-kernel", tag + ".bin"], tag + "-qemu.log", 20),
        ]
    return commands


def _symbols_from_nm(contents: str, where: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for line in contents.splitlines():
        match = re.fullmatch(r"([0-9a-fA-F]+)\s+(\w)\s+(\S+)", line)
        if match:
            require(match.group(3) not in result, where + ": duplicate symbol")
            result[match.group(3)] = int(match.group(1), 16)
    return result


def _verify_qemu_case(folder: Path, case_record: Any, expected: tuple[int, int, int]) -> None:
    case, level, checks = expected
    where = f"host.cases[{case},{level}]"
    exact_object(case_record, {"case", "expected_el", "verified", "harness_checks", "record_hex", "registers_hex", "elf_sha256", "binary_sha256"}, where)
    require(type(case_record["case"]) is int and case_record["case"] == case, where + ": case mismatch")
    require(type(case_record["expected_el"]) is int and case_record["expected_el"] == level, where + ": EL mismatch")
    strict_bool(case_record["verified"], True, where + ".verified")
    require(type(case_record["harness_checks"]) is int and case_record["harness_checks"] == checks, where + ": check count mismatch")
    for field, length in (("record_hex", 512), ("registers_hex", 304)):
        require(type(case_record[field]) is str and re.fullmatch(rf"[0-9a-f]{{{length}}}", case_record[field]) is not None,
                where + "." + field + ": invalid bounded hexadecimal")
    for field in ("elf_sha256", "binary_sha256"):
        require(type(case_record[field]) is str and HEX256.fullmatch(case_record[field]) is not None, where + "." + field + ": invalid SHA-256")
    tag = f"case-{case}-el-{level}"
    require(case_record["elf_sha256"] == sha256_path(packet_file(folder, tag + ".elf", where + ".elf")), where + ": ELF pin mismatch")
    serial = text(packet_file(folder, tag + "-qemu.log", where + ".qemu"), where + ".qemu")
    pattern = (rf"HKE_TEST_V1 case={case} el={level} checks={checks} result=PASS\r?\n"
               rf"RECORD ([0-9a-f]{{512}})\r?\nREGISTERS ([0-9a-f]{{304}})\r?\n?\Z")
    match = re.fullmatch(pattern, serial)
    require(match is not None, where + ": transcript format/content mismatch")
    require(match.group(1) == case_record["record_hex"] and match.group(2) == case_record["registers_hex"], where + ": transcript/result mismatch")
    words = struct.unpack("<32Q", bytes.fromhex(match.group(1)))
    registers = struct.unpack("<19Q", bytes.fromhex(match.group(2)))
    require(registers == EXPECTED_REGISTERS, where + ": independently decoded registers mismatch")
    require(words[:3] == (0x31454C5241494B48, 1, 256), where + ": initialized record header mismatch")
    if case in (2, 3):
        require(words[3:] == (0,) * 29, where + ": refusal case wrote record payload")
        return
    symbols = _symbols_from_nm(text(packet_file(folder, tag + "-symbols.log", where + ".symbols"), where + ".symbols"), where)
    require({"stext", "hakios_early_tiny_payload", "hakios_early_entry_continue"} <= set(symbols), where + ": required symbols absent")
    require(words[5:9] == EXPECTED_REGISTERS[:4] and words[9] == level * 4, where + ": entry register capture mismatch")
    require(words[10:13] == (symbols["stext"], symbols["hakios_early_tiny_payload"], symbols["hakios_early_entry_continue"]), where + ": PC capture mismatch")
    require(words[13] == 0 and words[22:24] == (0x3030, 0xA0000000), where + ": SP/LR/NZCV mismatch")
    require(words[17] & 5 == 0 and words[19] == 4 << ((words[18] >> 16) & 15), where + ": cache contract mismatch")
    require(words[24:] == (0,) * 8, where + ": reserved record bytes changed")
    if case == 1:
        require(words[3:5] == (2, 1) and words[14] & 0x3C0 == 0x340 and words[20:22] == (0, 0), where + ": invalid-DAIF record mismatch")
    else:
        value = EXPECTED_REGISTERS[0] ^ EXPECTED_REGISTERS[1] ^ EXPECTED_REGISTERS[2] ^ EXPECTED_REGISTERS[3] ^ words[15] ^ words[16]
        value = ((value >> 7) | (value << 57)) & ((1 << 64) - 1)
        require(words[3:5] == (1, 0) and words[14] & 0x3C0 == 0x3C0 and words[20:22] == (value, 0x3143455845494B48),
                where + ": success record mismatch")


def verify_host(folder: Path, enforce_selection: bool = True) -> dict[str, Any]:
    folder = folder.resolve(strict=True)
    if enforce_selection:
        selected_folder(folder, "host")
        require(sha256_path(folder / "result.json") == SELECTED["host_result_sha256"], "host: selected result pin drift")
    require(actual_files(folder) == _host_expected_files(), "host: exact retained file set mismatch")
    result = read_json(packet_file(folder, "result.json", "host.result"), "host.result")
    exact_object(result, {"schema_version", "status", "scope", "work", "source_pins", "commands", "cases", "phone_queries", "phone_writes", "a51_payload_execution_verified", "a51_return_verified", "phase_2_device_gate_passed", "finished_utc"}, "host.result")
    require(type(result["schema_version"]) is int and result["schema_version"] == 1 and result["status"] == "passed" and result["scope"] == "synthetic-qemu-early-entry-only", "host: schema/status/scope mismatch")
    require(type(result["work"]) is str and result["work"].startswith("/opt/a51-hakios/experimental/early-entry-host/"), "host.work: unexpected isolated path")
    require(PurePosixPath(result["work"]).name == folder.name, "host.work: packet/build stamp mismatch")
    for key in ("phone_queries", "phone_writes", "a51_payload_execution_verified", "a51_return_verified", "phase_2_device_gate_passed"):
        strict_bool(result[key], False, "host." + key)
    exact_object(result["source_pins"], SOURCE_NAMES, "host.source_pins")
    for name in SOURCE_NAMES:
        verify_pin(result["source_pins"][name], packet_file(folder, "sources/" + name, "host.source." + name), "host.source_pins." + name)
    require(type(result["commands"]) is list, "host.commands: array required")
    expected_commands = _host_commands(result["work"])
    require(len(result["commands"]) == len(expected_commands), "host.commands: count mismatch")
    times: list[tuple[dt.datetime, dt.datetime]] = []
    seen_logs: set[str] = set()
    for index, (record, expected) in enumerate(zip(result["commands"], expected_commands)):
        argv, started, finished, log = command_record(record, f"host.commands[{index}]", "output")
        expected_argv, expected_log, expected_timeout = expected
        require(argv == expected_argv and record["cwd"] == result["work"] and log == expected_log,
                f"host.commands[{index}]: command/cwd/log mismatch")
        require(type(record["timeout_seconds"]) is int and record["timeout_seconds"] == expected_timeout,
                f"host.commands[{index}]: timeout mismatch")
        require(log not in seen_logs, f"host.commands[{index}]: duplicate log")
        seen_logs.add(log)
        log_path = packet_file(folder, log, f"host.commands[{index}].output")
        require(type(record["output_sha256"]) is str and record["output_sha256"] == sha256_path(log_path),
                f"host.commands[{index}]: output hash mismatch")
        times.append((started, finished))
    finished = timestamp(result["finished_utc"], "host.finished_utc")
    verify_command_times(times, finished, "host.commands")
    sections = text(packet_file(folder, "payload-sections.log", "host.payload-sections"), "host.payload-sections")
    require(re.search(r"\.mmuoff\.data\.write\s+PROGBITS\s+[0-9a-f]+\s+[0-9a-f]+\s+000100\s+00\s+WA\s+0\s+0\s+256", sections) is not None,
            "host: payload object section type/flags/size/alignment mismatch")
    require(type(result["cases"]) is list and len(result["cases"]) == len(CASES), "host.cases: count mismatch")
    for record, expected in zip(result["cases"], CASES):
        _verify_qemu_case(folder, record, expected)
    require(result["cases"][0]["elf_sha256"] == result["cases"][1]["elf_sha256"] and
            result["cases"][0]["binary_sha256"] == result["cases"][1]["binary_sha256"],
            "host: identical case-0 builds disagree across EL launch modes")
    return {"status": "passed", "cases": len(CASES), "checks": sum(x[2] for x in CASES),
            "packet_exact_file_set": True, "device_gates_false": True,
            "limitations": ["legacy packet has no index.json", "referenced .bin files were not retained, so binary_sha256 declarations cannot be independently rehashed"]}


def _once(contents: str, old: str, new: str, where: str) -> str:
    require(contents.count(old) == 1, where + ": patch context count mismatch")
    return contents.replace(old, new, 1)


def _expected_patch(folder: Path, prototype: Path) -> tuple[bytes, dict[str, tuple[str | None, str]]]:
    originals = {name: packet_file(folder, "original/" + name, "prepare.original." + name).read_bytes() for name in ORIGINAL_FILES}
    updated = {name: data.decode("utf-8") for name, data in originals.items()}
    updated["arch/arm64/kernel/head.S"] = _once(updated["arch/arm64/kernel/head.S"],
        "ENTRY(stext)\n\tbl\tpreserve_boot_args",
        "ENTRY(stext)\n\t/* Host-validated experimental diagnostic, before Linux boot-arg saving. */\n\tb\thakios_early_entry\n\t.global hakios_early_entry_continue\nhakios_early_entry_continue:\n\tbl\tpreserve_boot_args", "prepare.head.S")
    updated["arch/arm64/kernel/setup.c"] = _once(updated["arch/arm64/kernel/setup.c"],
        "#include <asm/mmu_context.h>\n", "#include <asm/mmu_context.h>\n#include \"hakios_early_entry.h\"\n", "prepare.setup.include")
    updated["arch/arm64/kernel/setup.c"] = _once(updated["arch/arm64/kernel/setup.c"],
        "void __init setup_arch(char **cmdline_p)\n{\n", "void __init setup_arch(char **cmdline_p)\n{\n\thakios_early_report();\n", "prepare.setup.call")
    updated["arch/arm64/kernel/Makefile"] = _once(updated["arch/arm64/kernel/Makefile"],
        "# Object file lists.\n", "# Object file lists.\narm64-obj-y += hakios_early_entry.o hakios_early_report.o\n", "prepare.Makefile.initial")
    updated["arch/arm64/kernel/Makefile"] = updated["arch/arm64/kernel/Makefile"].replace("arm64-obj-y += hakios_early_entry.o hakios_early_report.o\n", "", 1)
    updated["arch/arm64/kernel/Makefile"] = _once(updated["arch/arm64/kernel/Makefile"],
        "\t\t\t   smp.o smp_spin_table.o smccc-call.o\n",
        "\t\t\t   smp.o smp_spin_table.o smccc-call.o\n\narm64-obj-y += hakios_early_entry.o hakios_early_report.o\n", "prepare.Makefile.final")
    pieces: list[str] = []
    pins: dict[str, tuple[str | None, str]] = {}
    for name in ORIGINAL_FILES:
        old = originals[name].decode("utf-8")
        new = updated[name]
        pieces.extend(difflib.unified_diff(old.splitlines(True), new.splitlines(True), fromfile="a/" + name, tofile="b/" + name))
        pins[name] = (hashlib.sha256(originals[name]).hexdigest(), hashlib.sha256(new.encode("utf-8")).hexdigest())
    for short in ("hakios_early_entry.S", "hakios_early_entry.h", "hakios_early_report.c"):
        data = packet_file(prototype, short, "prepare.prototype." + short).read_bytes()
        relative = "arch/arm64/kernel/" + short
        pieces.extend(difflib.unified_diff([], data.decode("utf-8").splitlines(True), fromfile="/dev/null", tofile="b/" + relative))
        pins[relative] = (None, hashlib.sha256(data).hexdigest())
    return "".join(pieces).encode("utf-8"), pins


def verify_prepare(folder: Path, prototype: Path, enforce_selection: bool = True) -> dict[str, Any]:
    folder, prototype = folder.resolve(strict=True), prototype.resolve(strict=True)
    if enforce_selection:
        selected_folder(folder, "prepare")
        require(sha256_path(folder / "result.json") == SELECTED["prepare_result_sha256"], "prepare: selected result pin drift")
        require(sha256_path(folder / "early-entry.patch") == SELECTED["patch_sha256"], "prepare: selected patch pin drift")
    expected_files = {"result.json", "early-entry.patch"} | {"original/" + name for name in ORIGINAL_FILES}
    require(actual_files(folder) == expected_files, "prepare: exact retained file set mismatch")
    result = read_json(packet_file(folder, "result.json", "prepare.result"), "prepare.result")
    exact_object(result, {"schema_version", "status", "scope", "created_utc", "source", "source_lineage", "files", "patch_sha256", "local_instructions", "source_config_sha256", "configuration_unchanged", "phone_queries", "phone_writes", "a51_payload_execution_verified", "phase_2_device_gate_passed"}, "prepare.result")
    require(type(result["schema_version"]) is int and result["schema_version"] == 1 and result["status"] == "prepared" and result["scope"] == "isolated-host-source-only", "prepare: schema/status/scope mismatch")
    timestamp(result["created_utc"], "prepare.created_utc")
    require(type(result["source"]) is str and result["source"].startswith("/opt/a51-hakios/") and not result["source"].startswith("/opt/a51-everline/"), "prepare.source: isolated source path required")
    require(PurePosixPath(result["source"]).name == "src" and PurePosixPath(result["source"]).parent.name == folder.name,
            "prepare.source: packet/build stamp mismatch")
    require(result["source_lineage"] == "468ab8343364e4d3a267e670fa6a22fd4197a805; not a verified Git HEAD", "prepare: source lineage mismatch")
    require(result["local_instructions"] == [] and result["source_config_sha256"] is None, "prepare: unexpected local instructions or source config claim")
    for key in ("phone_queries", "phone_writes", "a51_payload_execution_verified", "phase_2_device_gate_passed"):
        strict_bool(result[key], False, "prepare." + key)
    strict_bool(result["configuration_unchanged"], True, "prepare.configuration_unchanged")
    patch, expected_pins = _expected_patch(folder, prototype)
    retained_patch = packet_file(folder, "early-entry.patch", "prepare.patch").read_bytes()
    require(retained_patch == patch, "prepare: patch bytes do not reproduce the six-file adaptation")
    require(result["patch_sha256"] == hashlib.sha256(patch).hexdigest(), "prepare: patch hash mismatch")
    exact_object(result["files"], expected_pins, "prepare.files")
    for name, (before, after) in expected_pins.items():
        record = exact_object(result["files"][name], {"before_sha256", "after_sha256"}, "prepare.files." + name)
        require(record["before_sha256"] == before and record["after_sha256"] == after, "prepare.files." + name + ": pin mismatch")
        if name in ORIGINAL_FILES:
            require(before == ORIGINAL_FILES[name], "prepare: original source pin differs from accepted baseline")
    return {"status": "passed", "changed_files": 6, "patch_sha256": result["patch_sha256"],
            "device_gates_false": True, "limitations": ["legacy preparation packet has no index.json", "prepared after-images are represented by the exact patch and pins rather than retained as complete files"]}


def _kernel_expected_files() -> set[str]:
    base = {"result.json", "index.json", "Image", "kernel.config", "compile.h", "compiler.log", "linker.log",
            "copy-source.log", "copy-output.log", "apply-exact-pinned-adaptation.log", "build-experimental-image.log",
            "symbol-map.log", "entry-disassembly.log", "original-metadata-before.json", "original-metadata-after.json"}
    return base | {"prototype/" + name for name in PROTOTYPE_NAMES}


def verify_index(folder: Path) -> dict[str, Any]:
    index = read_json(packet_file(folder, "index.json", "kernel.index"), "kernel.index")
    require(type(index) is dict and set(index) in ({"files"}, {"schema_version", "files"}), "kernel.index: schema fields mismatch")
    if "schema_version" in index:
        require(type(index["schema_version"]) is int and index["schema_version"] == 1, "kernel.index: unsupported schema")
    require(type(index["files"]) is dict and index["files"], "kernel.index.files: nonempty object required")
    indexed: set[str] = set()
    for relative, record in index["files"].items():
        relative = canonical_relative(relative, "kernel.index.path")
        require(relative != "index.json" and relative not in indexed, "kernel.index: duplicate/self entry")
        indexed.add(relative)
        verify_pin(record, packet_file(folder, relative, "kernel.index." + relative), "kernel.index." + relative)
    require(actual_files(folder) == indexed | {"index.json"}, "kernel.index: indexed and actual file sets differ")
    require(indexed | {"index.json"} == _kernel_expected_files(), "kernel: selected packet role set mismatch")
    return index


def parse_image_header(path: Path) -> dict[str, Any]:
    regular(path, "kernel.Image")
    with path.open("rb") as stream:
        header = stream.read(64)
    require(len(header) == 64 and header[56:60] == b"ARM\x64", "kernel.Image: ARM64 magic/header missing")
    code0, code1, text_offset, image_size, flags, res2, res3, res4, pe_offset = struct.unpack("<IIQQQQQQ4xI", header)
    branch = None
    if code0 & 0xFC000000 == 0x14000000:
        immediate = code0 & 0x03FFFFFF
        if immediate & 0x02000000:
            immediate -= 1 << 26
        branch = immediate * 4
    pages = (None, 4096, 16384, 65536)
    return {"text_offset": text_offset, "image_size": image_size, "stored_kernel_bytes": path.stat().st_size,
            "flags": flags, "endianness": "big" if flags & 1 else "little", "page_size": pages[(flags >> 1) & 3],
            "placement_any_2m_aligned_base": bool(flags & 8), "code0": hex(code0), "code1": hex(code1),
            "initial_branch_offset": branch, "reserved_words": [hex(res2), hex(res3), hex(res4)],
            "pe_header_offset": pe_offset, "status": "retained Linux Image header; actual Samsung execution state is unknown"}


def _decode_b(word: int, address: int, where: str) -> int:
    require(word & 0xFC000000 == 0x14000000, where + ": unconditional B instruction required")
    immediate = word & 0x03FFFFFF
    if immediate & 0x02000000:
        immediate -= 1 << 26
    return address + immediate * 4


def _image_word(path: Path, offset: int, where: str) -> int:
    require(type(offset) is int and 0 <= offset <= path.stat().st_size - 4 and offset % 4 == 0, where + ": invalid Image offset")
    with path.open("rb") as stream:
        stream.seek(offset)
        data = stream.read(4)
    require(len(data) == 4, where + ": short Image read")
    return struct.unpack("<I", data)[0]


def _kernel_commands(result: dict[str, Any]) -> list[tuple[str, Any]]:
    build = result["build_directory"]
    source, out = build + "/src", build + "/out"
    expected_prepare_suffix = "/hakios-a51/prototype/early-entry/prepare.py"
    # Bind the recorded command to the retained result pointer.  This also lets
    # corruption tests verify an isolated packet copy outside the project tree.
    expected_evidence_suffix = "/hakios-a51/" + str(PurePosixPath(result["preparation_result"]["path"]).parent)
    make = ["make", "-C", source, "O=" + out, "ARCH=arm64", "LLVM=1", "LLVM_IAS=1", "CC=clang", "LD=ld.lld",
            "AR=llvm-ar", "NM=llvm-nm", "OBJCOPY=llvm-objcopy", "OBJDUMP=llvm-objdump", "READELF=llvm-readelf",
            "CROSS_COMPILE=aarch64-linux-gnu-", "CROSS_COMPILE_ARM32=arm-linux-gnueabi-", "CLANG_TRIPLE=aarch64-linux-gnu-", "-j4", "Image"]
    return [
        ("compiler.log", ["clang", "--version"]),
        ("linker.log", ["ld.lld", "--version"]),
        ("copy-source.log", ["cp", "-a", "--reflink=auto", "/opt/a51-everline/src", source]),
        ("copy-output.log", ["cp", "-a", "--reflink=auto", "/opt/a51-everline/out", out]),
        ("apply-exact-pinned-adaptation.log", (expected_prepare_suffix, source, expected_evidence_suffix)),
        ("build-experimental-image.log", make),
        ("symbol-map.log", ["llvm-nm", "--defined-only", out + "/vmlinux"]),
        ("entry-disassembly.log", ["llvm-objdump", "-d", "--disassemble-symbols=stext,hakios_early_entry,hakios_early_tiny_payload,hakios_early_report", out + "/vmlinux"]),
    ]


def _verify_kernel_commands(folder: Path, result: dict[str, Any]) -> None:
    require(type(result["commands"]) is list, "kernel.commands: array required")
    expected = _kernel_commands(result)
    require(len(result["commands"]) == len(expected), "kernel.commands: count mismatch")
    times: list[tuple[dt.datetime, dt.datetime]] = []
    for index, (record, (expected_log, template)) in enumerate(zip(result["commands"], expected)):
        argv, started, finished, log = command_record(record, f"kernel.commands[{index}]", "log")
        require(log == expected_log, f"kernel.commands[{index}]: log mismatch")
        if index == 4:
            suffix, source, evidence_suffix = template
            require(len(argv) == 6 and argv[0].endswith("python3") and argv[1].replace("\\", "/").endswith(suffix)
                    and argv[2:4] == ["--source", source] and argv[4] == "--evidence" and argv[5].replace("\\", "/").endswith(evidence_suffix),
                    "kernel.commands[4]: preparation command mismatch")
        else:
            require(argv == template, f"kernel.commands[{index}]: argv mismatch")
        packet_file(folder, log, f"kernel.commands[{index}].log")
        times.append((started, finished))
    require(timestamp(result["started_utc"], "kernel.started_utc") <= times[0][0], "kernel: result starts after first command")
    verify_command_times(times, timestamp(result["finished_utc"], "kernel.finished_utc"), "kernel.commands")


def _pointer(record: Any, expected_path: str, path: Path, where: str) -> None:
    exact_object(record, {"path", "bytes", "sha256"}, where)
    require(record["path"] == expected_path, where + ": path mismatch")
    verify_pin({"bytes": record["bytes"], "sha256": record["sha256"]}, path, where)


def _symbol_map(path: Path) -> dict[str, int]:
    symbols: dict[str, int] = {}
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            fields = line.split()
            if fields and fields[-1] in REQUIRED_SYMBOLS:
                require(len(fields) >= 3 and re.fullmatch(r"[0-9a-fA-F]+", fields[0]) is not None,
                        "kernel.symbol-map: malformed required symbol")
                require(fields[-1] not in symbols, "kernel.symbol-map: duplicate required symbol")
                symbols[fields[-1]] = int(fields[0], 16)
    require(set(symbols) == REQUIRED_SYMBOLS, "kernel.symbol-map: required symbol set mismatch")
    return symbols


def verify_kernel(folder: Path, host_folder: Path, prepare_folder: Path, enforce_selection: bool = True) -> dict[str, Any]:
    folder, host_folder, prepare_folder = folder.resolve(strict=True), host_folder.resolve(strict=True), prepare_folder.resolve(strict=True)
    if enforce_selection:
        selected_folder(folder, "kernel")
        require(sha256_path(folder / "result.json") == SELECTED["kernel_result_sha256"], "kernel: selected result pin drift")
        require(sha256_path(folder / "index.json") == SELECTED["kernel_index_sha256"], "kernel: selected index pin drift")
        require(sha256_path(folder / "Image") == SELECTED["image_sha256"], "kernel: selected Image pin drift")
    index = verify_index(folder)
    result = read_json(packet_file(folder, "result.json", "kernel.result"), "kernel.result")
    fields = {"schema_version", "status", "scope", "build_directory", "started_utc", "source_lineage", "prototype_source_pins",
              "original_input_pins", "commands", "phone_queries", "phone_writes", "a51_payload_execution_verified", "phase_2_device_gate_passed",
              "qemu_test_result", "preparation_result", "adaptation_patch", "symbols", "image_header", "image", "retained_vmlinux",
              "host_build_verified", "configuration_unchanged", "original_metadata_unchanged", "original_input_bytes_unchanged", "finished_utc"}
    exact_object(result, fields, "kernel.result")
    require(type(result["schema_version"]) is int and result["schema_version"] == 1 and result["status"] == "passed" and result["scope"] == "isolated_pre_linux_payload_kernel_host_build", "kernel: schema/status/scope mismatch")
    require(type(result["build_directory"]) is str and result["build_directory"].startswith("/opt/a51-hakios/experimental/early-entry/"), "kernel.build_directory: isolated path required")
    require(PurePosixPath(result["build_directory"]).name == folder.name == prepare_folder.name,
            "kernel: build/kernel/preparation stamp mismatch")
    timestamp(result["started_utc"], "kernel.started_utc")
    require(result["source_lineage"] == "468ab8343364e4d3a267e670fa6a22fd4197a805; recorded, no verified Git HEAD", "kernel: source lineage mismatch")
    for key in ("phone_queries", "phone_writes", "a51_payload_execution_verified", "phase_2_device_gate_passed"):
        strict_bool(result[key], False, "kernel." + key)
    for key in ("host_build_verified", "configuration_unchanged", "original_metadata_unchanged", "original_input_bytes_unchanged"):
        strict_bool(result[key], True, "kernel." + key)
    exact_object(result["prototype_source_pins"], PROTOTYPE_NAMES, "kernel.prototype_source_pins")
    for name in PROTOTYPE_NAMES:
        verify_pin(result["prototype_source_pins"][name], packet_file(folder, "prototype/" + name, "kernel.prototype." + name), "kernel.prototype_source_pins." + name)
    input_names = {".config", "Module.symvers", "include/generated/utsrelease.h", "include/generated/compile.h", "include/generated/autoconf.h", "include/config/auto.conf", "include/config/kernel.release", "arch/arm64/boot/Image", "vmlinux", "System.map"}
    exact_object(result["original_input_pins"], input_names, "kernel.original_input_pins")
    for name in input_names:
        record = result["original_input_pins"][name]
        exact_object(record, {"bytes", "sha256"}, "kernel.original_input_pins." + name)
        strict_int(record["bytes"], "kernel.original_input_pins." + name + ".bytes", 0)
        require(type(record["sha256"]) is str and HEX256.fullmatch(record["sha256"]) is not None, "kernel.original_input_pins." + name + ": invalid SHA-256")
    verify_pin(result["original_input_pins"][".config"], packet_file(folder, "kernel.config", "kernel.kernel.config"), "kernel.original_input_pins..config")
    host_path = PROJECT / SELECTED["host"] / "result.json"
    prepare_path = PROJECT / SELECTED["prepare"] / "result.json"
    patch_path = PROJECT / SELECTED["prepare"] / "early-entry.patch"
    _pointer(result["qemu_test_result"], SELECTED["host"] + "/result.json", host_path, "kernel.qemu_test_result")
    _pointer(result["preparation_result"], SELECTED["prepare"] + "/result.json", prepare_path, "kernel.preparation_result")
    _pointer(result["adaptation_patch"], SELECTED["prepare"] + "/early-entry.patch", patch_path, "kernel.adaptation_patch")
    _verify_kernel_commands(folder, result)
    require("clang version 18.1.3 (1ubuntu1)" in text(folder / "compiler.log", "kernel.compiler.log") and
            "LLD 18.1.3" in text(folder / "linker.log", "kernel.linker.log"), "kernel: toolchain versions mismatch")
    symbols = _symbol_map(packet_file(folder, "symbol-map.log", "kernel.symbol-map"))
    exact_object(result["symbols"], REQUIRED_SYMBOLS, "kernel.symbols")
    for name in REQUIRED_SYMBOLS:
        require(type(result["symbols"][name]) is int and result["symbols"][name] == symbols[name], "kernel.symbols." + name + ": map mismatch")
    image = packet_file(folder, "Image", "kernel.Image")
    verify_pin(result["image"], image, "kernel.image")
    header = parse_image_header(image)
    require(result["image_header"] == header, "kernel.image_header: independently parsed header mismatch")
    require(header["image_size"] == symbols["_end"] - symbols["_text"] and header["initial_branch_offset"] == symbols["stext"] - symbols["_text"], "kernel: Image extent/header branch differs from symbols")
    require(header["text_offset"] == 0x80000 and header["flags"] == 0xA and header["reserved_words"][1] == "0xecefecef" and header["pe_header_offset"] == 0, "kernel: native Image header convention mismatch")
    for name in ("hakios_early_entry", "hakios_early_tiny_payload", "hakios_early_entry_continue", "hakios_early_report", "hakios_early_record"):
        require(symbols["_text"] <= symbols[name] < symbols["_edata"], "kernel: non-file-backed prototype symbol " + name)
    require(symbols["__mmuoff_data_start"] <= symbols["hakios_early_record"] and symbols["hakios_early_record"] + 256 <= symbols["__mmuoff_data_end"] <= symbols["_edata"] and symbols["hakios_early_record"] % 256 == 0,
            "kernel: record section bounds/alignment mismatch")
    record_offset = symbols["hakios_early_record"] - symbols["_text"]
    require(0 <= record_offset <= image.stat().st_size - 256, "kernel: record not retained in raw Image")
    with image.open("rb") as stream:
        stream.seek(record_offset)
        record_bytes = stream.read(256)
    require(record_bytes == struct.pack("<QQQ", 0x31454C5241494B48, 1, 256) + bytes(232), "kernel: initialized 256-byte record differs")
    stext_word = _image_word(image, symbols["stext"] - symbols["_text"], "kernel.stext.branch")
    require(_decode_b(stext_word, symbols["stext"], "kernel.stext.branch") == symbols["hakios_early_entry"], "kernel: stext does not branch to early entry")
    disassembly = text(packet_file(folder, "entry-disassembly.log", "kernel.entry-disassembly"), "kernel.entry-disassembly")
    matches = re.findall(r"^([0-9a-f]+):\s+([0-9a-f]{8})\s+b\s+0x([0-9a-f]+) <hakios_early_entry_continue>$", disassembly, re.M)
    require(len(matches) == 1, "kernel: expected one retained final branch to early-entry continuation")
    branch_address, logged_word, logged_target = int(matches[0][0], 16), int(matches[0][1], 16), int(matches[0][2], 16)
    require(symbols["hakios_early_entry"] <= branch_address < symbols["stext"] and logged_target == symbols["hakios_early_entry_continue"], "kernel: final branch symbol relationship mismatch")
    actual_word = _image_word(image, branch_address - symbols["_text"], "kernel.entry.final_branch")
    require(actual_word == logged_word and _decode_b(actual_word, branch_address, "kernel.entry.final_branch") == symbols["hakios_early_entry_continue"], "kernel: final branch bytes/log/target mismatch")
    before = packet_file(folder, "original-metadata-before.json", "kernel.original-metadata-before").read_bytes()
    after = packet_file(folder, "original-metadata-after.json", "kernel.original-metadata-after").read_bytes()
    require(before == after, "kernel: original metadata snapshots differ")
    exact_object(result["retained_vmlinux"], {"path", "bytes", "sha256"}, "kernel.retained_vmlinux")
    require(type(result["retained_vmlinux"]["path"]) is str and result["retained_vmlinux"]["path"] == result["build_directory"] + "/out/vmlinux", "kernel.retained_vmlinux.path: mismatch")
    strict_int(result["retained_vmlinux"]["bytes"], "kernel.retained_vmlinux.bytes", 1)
    require(type(result["retained_vmlinux"]["sha256"]) is str and HEX256.fullmatch(result["retained_vmlinux"]["sha256"]) is not None, "kernel.retained_vmlinux.sha256: invalid")
    # Semantic replay of both referenced prerequisite packets is part of kernel acceptance.
    host_summary = verify_host(host_folder, enforce_selection=enforce_selection)
    prepare_summary = verify_prepare(prepare_folder, folder / "prototype", enforce_selection=enforce_selection)
    return {"status": "passed", "image": pin(image), "symbols": len(symbols), "record_bytes_verified": 256,
            "entry_branches_verified": 2, "packet_exact_file_set": True, "device_gates_false": True,
            "host": host_summary, "prepare": prepare_summary,
            "limitations": ["kernel index is legacy and has no schema_version"] if "schema_version" not in index else []}


def verify_all(host: Path, prepare: Path, kernel: Path, enforce_selection: bool = True) -> dict[str, Any]:
    summary = verify_kernel(kernel, host, prepare, enforce_selection=enforce_selection)
    summary["limitations"].extend([
        "vmlinux is outside the indexed packet, so its retained hash and linked ELF section type/flags cannot be independently replayed offline",
        "only the copied .config is retained from the original-input pin set; the other original input bytes cannot be independently replayed from this packet",
        "the experimental build copied an existing output tree and therefore is incremental rather than a clean empty-output build",
        "host/QEMU execution and compilation do not establish A51 execution, persistent fault logging, watchdog coverage, or Android/recovery return",
        "the invalid-DAIF path changes DAIF before rejecting; unsupported-EL and oversized-CTR paths have no executed retained case",
    ])
    summary.update({"schema_version": 1, "scope": "offline_selected_early_entry_evidence_replay",
                    "phase_2_device_gate_passed": False, "a51_payload_execution_verified": False,
                    "a51_return_verified": False, "standalone_execution_verified": False,
                    "persistent_fault_logging_verified": False})
    return summary


def paths_from_args(args: argparse.Namespace) -> tuple[Path, Path, Path]:
    return (Path(args.host) if args.host else PROJECT / SELECTED["host"],
            Path(args.prepare) if args.prepare else PROJECT / SELECTED["prepare"],
            Path(args.kernel) if args.kernel else PROJECT / SELECTED["kernel"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("verify-all", "verify-host", "verify-prepare", "verify-kernel"), nargs="?", default="verify-all")
    parser.add_argument("--host")
    parser.add_argument("--prepare")
    parser.add_argument("--kernel")
    parser.add_argument("--allow-unselected", action="store_true", help="disable fixed selected-packet pins (for corruption tests only)")
    args = parser.parse_args(argv)
    host, prepare, kernel = paths_from_args(args)
    enforce = not args.allow_unselected
    try:
        if args.command == "verify-host":
            result = verify_host(host, enforce)
        elif args.command == "verify-prepare":
            result = verify_prepare(prepare, kernel / "prototype", enforce)
        elif args.command == "verify-kernel":
            result = verify_kernel(kernel, host, prepare, enforce)
        else:
            result = verify_all(host, prepare, kernel, enforce)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (EvidenceError, OSError) as exc:
        print("EARLY_ENTRY_EVIDENCE_REJECTED: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
