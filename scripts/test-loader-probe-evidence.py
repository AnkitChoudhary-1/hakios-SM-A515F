#!/usr/bin/env python3
"""Adversarial checks for the probe's independent serial/evidence reader.

These tests mutate disposable host copies only and never contact a phone.
Run through scripts/run.py so the exact suite and output are retained.
"""
import contextlib
import importlib.util
import io
import json
import shutil
import struct
import tempfile
import unittest
from unittest import mock
import zlib
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT / "evidence" / "test-fixtures" / "loader-probe"
FIXTURES.mkdir(parents=True, exist_ok=True)
SPEC = importlib.util.spec_from_file_location("loader_probe_builder", PROJECT / "scripts" / "build-loader-probe.py")
PROBE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROBE)


class SerialGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pointer = json.loads(PROBE.read(PROJECT / "manifests" / "loader-probe-current.json", 512 * 1024))
        cls.result_path = PROJECT / pointer["result"]
        cls.folder = cls.result_path.parent
        cls.result = json.loads(PROBE.read(cls.result_path, 512 * 1024))
        cls.serial = PROBE.read(cls.folder / cls.result["qemu_stdout"])
        cls.build_hash = cls.result["build_identity_sha256"]

    def rejected(self, serial):
        with self.assertRaises(ValueError):
            PROBE.decode_serial(serial, self.build_hash)

    def lines(self):
        return self.serial.decode("ascii").replace("\r", "").splitlines()

    @staticmethod
    def join(lines):
        return ("\n".join(lines) + "\n").encode("ascii")

    def mutate_frame(self, sequence, offset, value, fmt="<I", repair_crc=True):
        lines = self.lines()
        frame = bytearray.fromhex(lines[sequence + 1][6:])
        struct.pack_into(fmt, frame, offset, value)
        if repair_crc:
            struct.pack_into("<I", frame, 252, zlib.crc32(frame[:252]))
        lines[sequence + 1] = "FRAME " + frame.hex()
        return self.join(lines)

    def test_original_transcript_reconstructs_selected_result(self):
        self.assertEqual(PROBE.decode_serial(self.serial, self.build_hash), self.result["qemu"])

    def test_crlf_is_equivalent(self):
        serial = self.join(self.lines()).replace(b"\n", b"\r\n")
        self.assertEqual(PROBE.decode_serial(serial, self.build_hash), self.result["qemu"])

    def test_missing_frame(self):
        lines = self.lines()
        del lines[4]
        self.rejected(self.join(lines))

    def test_extra_frame(self):
        lines = self.lines()
        lines.insert(4, lines[3])
        self.rejected(self.join(lines))

    def test_reordered_frames(self):
        lines = self.lines()
        lines[2], lines[3] = lines[3], lines[2]
        self.rejected(self.join(lines))

    def test_duplicate_frame_with_same_line_count(self):
        lines = self.lines()
        lines[3] = lines[2]
        self.rejected(self.join(lines))

    def test_truncated_frame(self):
        lines = self.lines()
        lines[1] = lines[1][:-2]
        self.rejected(self.join(lines))

    def test_oversized_frame(self):
        lines = self.lines()
        lines[1] += "00"
        self.rejected(self.join(lines))

    def test_uppercase_hex(self):
        lines = self.lines()
        lines[1] = "FRAME " + lines[1][6:].upper()
        self.rejected(self.join(lines))

    def test_non_ascii(self):
        self.rejected(self.serial + b"\xff")

    def test_missing_banner(self):
        lines = self.lines()
        lines[0] = "UNRELATED"
        self.rejected(self.join(lines))

    def test_wrong_final_marker(self):
        lines = self.lines()
        lines[-1] = "QEMU_PROBE_FAIL"
        self.rejected(self.join(lines))

    def test_trailing_output(self):
        self.rejected(self.serial + b"EXTRA\n")

    def test_missing_final_marker(self):
        self.rejected(self.join(self.lines()[:-1]))

    def test_serial_read_bound(self):
        self.rejected(self.serial + b" " * 4096)

    def test_stray_carriage_return(self):
        self.rejected(self.serial.replace(b"FRAME ", b"FRA\rME ", 1))

    def test_invalid_expected_digest(self):
        with self.assertRaises(ValueError):
            PROBE.decode_serial(self.serial, "invalid")

    def test_wrong_expected_build_identity(self):
        with self.assertRaises(ValueError):
            PROBE.decode_serial(self.serial, "00" * 32)

    def test_inconsistent_entry_across_stages(self):
        # x0 may vary between machines, but it must agree across this run.
        self.rejected(self.mutate_frame(3, 128, 0x12345678, "<Q"))


# Separate tests make every changed semantic field visible in unittest output.
MUTATIONS = {
    "magic_with_valid_crc": (0, 0, 0, "<Q", True),
    "version_with_valid_crc": (0, 8, 2, "<I", True),
    "sequence_with_valid_crc": (1, 12, 0, "<I", True),
    "stage_with_valid_crc": (1, 16, 3, "<I", True),
    "status_with_valid_crc": (4, 20, 8, "<I", True),
    "mode_with_valid_crc": (0, 24, 1, "<I", True),
    "entry_flags_with_valid_crc": (0, 28, 0, "<I", True),
    "unknown_entry_flag_with_valid_crc": (0, 28, 0x7fff, "<I", True),
    "build_hash_with_valid_crc": (0, 32, 0, "<Q", True),
    "input_hash_with_valid_crc": (0, 64, 0, "<Q", True),
    "unused_fdt_hash_with_valid_crc": (0, 96, 1, "<Q", True),
    "entry_pc_with_valid_crc": (0, 160, 0xf0000000, "<Q", True),
    "entry_el_with_valid_crc": (0, 176, 2, "<Q", True),
    "zero_frequency_with_valid_crc": (0, 184, 0, "<Q", True),
    "before_payload_budget_with_valid_crc": (0, 240, 48, "<Q", True),
    "after_payload_budget_with_valid_crc": (4, 240, 64, "<Q", True),
    "payload_callback_status_with_valid_crc": (4, 248, 1, "<I", True),
    "return_callback_status_with_valid_crc": (6, 248, 1, "<I", True),
    "data_without_crc_repair": (0, 128, 1, "<Q", False),
    "crc_field_corruption": (0, 252, 0, "<I", False),
}


def mutation_test(arguments):
    def test(self):
        self.rejected(self.mutate_frame(*arguments))
    return test


for name, arguments in MUTATIONS.items():
    setattr(SerialGuards, "test_" + name, mutation_test(arguments))


class ReadGuards(unittest.TestCase):
    def test_exact_read_limit(self):
        with tempfile.TemporaryDirectory(prefix="hakios-probe-reader-", dir=FIXTURES) as temp:
            path = Path(temp) / "fixture"
            path.write_bytes(bytes(32))
            self.assertEqual(PROBE.read(path, 32), bytes(32))

    def test_exceeded_read_limit(self):
        with tempfile.TemporaryDirectory(prefix="hakios-probe-reader-", dir=FIXTURES) as temp:
            path = Path(temp) / "fixture"
            path.write_bytes(bytes(33))
            with self.assertRaises(ValueError):
                PROBE.read(path, 32)

    def test_nonregular_read(self):
        with tempfile.TemporaryDirectory(prefix="hakios-probe-reader-", dir=FIXTURES) as temp:
            with self.assertRaises(ValueError):
                PROBE.read(Path(temp))

    def test_invalid_read_limit(self):
        with tempfile.TemporaryDirectory(prefix="hakios-probe-reader-", dir=FIXTURES) as temp:
            path = Path(temp) / "fixture"
            path.write_bytes(b"")
            for limit in (-1, True, 16 * 1024 * 1024 + 1):
                with self.subTest(limit=limit), self.assertRaises(ValueError):
                    PROBE.read(path, limit)

    def test_json_duplicate_key(self):
        with self.assertRaises(ValueError):
            PROBE.json_data(b'{"a":1,"a":1}')

    def test_json_nonfinite_literals(self):
        for literal in (b"NaN", b"Infinity", b"-Infinity", b"1e999"):
            with self.subTest(literal=literal), self.assertRaises(ValueError):
                PROBE.json_data(literal)

    def test_json_nesting_bound(self):
        with self.assertRaises(ValueError):
            PROBE.json_data(b"[" * 2000 + b"0" + b"]" * 2000)

    def test_json_exact_nesting_limit(self):
        value = PROBE.json_data(b"[" * 64 + b"0" + b"]" * 64)
        for _ in range(64):
            value = value[0]
        self.assertEqual(value, 0)

    def test_json_exceeded_nesting_limit(self):
        with self.assertRaises(ValueError):
            PROBE.json_data(b"[" * 65 + b"0" + b"]" * 65)

    def test_reference_canonicality(self):
        for name in ("../outside", "a/../b", "/absolute", "C:/absolute", "a\\b", "a//b", "./a", ".", ""):
            with self.subTest(name=name), self.assertRaises(ValueError):
                PROBE.relative_name(name)


class EvidenceGuards(SerialGuards):
    # Do not inherit SerialGuards' tests a second time.
    pass


for name in dir(SerialGuards):
    if name.startswith("test_"):
        setattr(EvidenceGuards, name, None)


def evidence_test(mutation):
    def test(self):
        with tempfile.TemporaryDirectory(prefix="hakios-probe-evidence-", dir=FIXTURES) as temp:
            folder = Path(temp) / "capture"
            shutil.copytree(self.folder, folder)
            mutation(folder)
            with self.assertRaises((ValueError, OSError)):
                with contextlib.redirect_stdout(io.StringIO()):
                    PROBE.verify(folder)
    return test


def same_size_corruption(folder):
    result = json.loads(PROBE.read(folder / "result.json", 512 * 1024))
    path = folder / result["qemu_stdout"]
    data = bytearray(PROBE.read(path))
    data[20] ^= 1
    path.write_bytes(data)


def missing_file(folder):
    (folder / "probe.bin").unlink()


def extra_file(folder):
    (folder / "unexpected").write_bytes(b"extra")


def escaping_index_path(folder):
    path = folder / "index.json"
    index = json.loads(PROBE.read(path, 512 * 1024))
    index["files"][0]["path"] = "../outside"
    path.write_text(json.dumps(index), encoding="utf-8")


for name, mutation in {
    "same_size_serial_corruption": same_size_corruption,
    "missing_evidence_file": missing_file,
    "extra_evidence_file": extra_file,
    "escaping_index_path": escaping_index_path,
}.items():
    setattr(EvidenceGuards, "test_" + name, evidence_test(mutation))


def reindex(folder):
    files = []
    for path in sorted(folder.rglob("*")):
        if path.is_file() and path.name != "index.json":
            data = PROBE.read(path)
            files.append({"path": path.relative_to(folder).as_posix(), "size": len(data), "sha256": PROBE.sha(data)})
    PROBE.dump(folder / "index.json", {"schema_version": 1, "files": files})


def edit_result(mutation, records=False):
    def edit(folder):
        result = json.loads(PROBE.read(folder / "result.json", 512 * 1024))
        mutation(result)
        if records:
            for command in result["commands"]:
                PROBE.dump(folder / command["record"], {key: value for key, value in command.items() if key != "record"})
        PROBE.dump(folder / "result.json", result)
        reindex(folder)
    return edit


def edit_config(mutation):
    def edit(folder):
        path = folder / "identity-input.json"
        config = json.loads(PROBE.read(path, 512 * 1024))
        mutation(config)
        PROBE.dump(path, config)
        # Repair all local hashes/frames, so the test exercises semantic
        # reconstruction rather than merely a stale index or build digest.
        digest = PROBE.sha(PROBE.read(path))
        (folder / "identity.h").write_bytes(PROBE.identity_header(digest))
        result = json.loads(PROBE.read(folder / "result.json", 512 * 1024))
        result["build_identity_sha256"] = digest
        serial_path = folder / result["qemu_stdout"]
        lines = PROBE.read(serial_path).decode("ascii").replace("\r", "").splitlines()
        for sequence in range(7):
            frame = bytearray.fromhex(lines[sequence + 1][6:])
            frame[32:64] = bytes.fromhex(digest)
            crc = zlib.crc32(frame[:252])
            struct.pack_into("<I", frame, 252, crc)
            lines[sequence + 1] = "FRAME " + frame.hex()
            result["qemu"]["frames"][sequence].update(sha256=PROBE.sha(frame), crc32=f"{crc:08x}")
        serial_path.write_bytes(SerialGuards.join(lines))
        PROBE.dump(folder / "result.json", result)
        reindex(folder)
    return edit


def duplicate_result_key(folder):
    path = folder / "result.json"
    data = PROBE.read(path).rstrip()
    path.write_bytes(data[:-1] + b', "status": "passed"}\n')
    reindex(folder)


def nonfinite_result_field(folder):
    edit_result(lambda result: result.update(unexpected=float("nan")))(folder)


def oversized_index(folder):
    (folder / "index.json").write_bytes(b" " * (512 * 1024 + 1))


def unlink_role(folder):
    (folder / "probe.bin").unlink()
    reindex(folder)


def add_role(folder):
    (folder / "extra-role").write_bytes(b"extra")
    reindex(folder)


def empty_artifact(folder):
    (folder / "probe.elf").write_bytes(b"")
    reindex(folder)


def duplicate_index_role(folder):
    index = json.loads(PROBE.read(folder / "index.json", 512 * 1024))
    index["files"].append(index["files"][0])
    PROBE.dump(folder / "index.json", index)


def bool_index_schema(folder):
    index = json.loads(PROBE.read(folder / "index.json", 512 * 1024))
    index["schema_version"] = True
    PROBE.dump(folder / "index.json", index)


def outside_stdout(folder):
    result = json.loads(PROBE.read(folder / "result.json", 512 * 1024))
    outside = folder.parent / "outside-stdout"
    outside.write_bytes(PROBE.read(folder / result["host_stdout"]))
    result["host_stdout"] = str(outside)
    PROBE.dump(folder / "result.json", result)
    reindex(folder)


def altered_identity_header(folder):
    (folder / "identity.h").write_bytes(b"#define HP_BUILD_SHA256 {0}\n")
    reindex(folder)


def timestamp_inversion(result):
    result["started"], result["finished"] = result["finished"], result["started"]


def timestamp_offset(result):
    result["started"]["ist"] = result["started"]["utc"]


def command_overlap(result):
    result["commands"][1]["started"] = result["commands"][0]["started"]


REINDEXED = {
    "reindexed_missing_artifact_role": unlink_role,
    "reindexed_extra_artifact_role": add_role,
    "reindexed_empty_artifact": empty_artifact,
    "duplicate_index_role": duplicate_index_role,
    "boolean_index_schema": bool_index_schema,
    "oversized_index": oversized_index,
    "duplicate_result_json_key": duplicate_result_key,
    "nonfinite_result_json": nonfinite_result_field,
    "outside_result_stdout": outside_stdout,
    "reindexed_altered_identity_header": altered_identity_header,
    "reindexed_boolean_result_schema": edit_result(lambda r: r.update(schema_version=True)),
    "reindexed_changed_result_scope": edit_result(lambda r: r.update(scope="a51_device")),
    "reindexed_unknown_result_field": edit_result(lambda r: r.update(unexpected=1)),
    "reindexed_boolean_frame_sequence": edit_result(lambda r: r["qemu"]["frames"][0].update(sequence=False)),
    "reindexed_boolean_entry_register": edit_result(lambda r: r["qemu"]["entry_fields"].__setitem__(1, False)),
    "reindexed_qemu_fdt_integer": edit_result(lambda r: r["qemu"].update(fdt_consumed=0)),
    "reindexed_missing_commands": edit_result(lambda r: r.update(commands=[])),
    "reindexed_removed_command": edit_result(lambda r: r["commands"].pop(5)),
    "reindexed_reordered_commands": edit_result(lambda r: r["commands"].reverse()),
    "reindexed_unrelated_command": edit_result(lambda r: r["commands"][6].update(arguments=["true"]), records=True),
    "reindexed_boolean_command_exit": edit_result(lambda r: r["commands"][6].update(exit_code=False), records=True),
    "reindexed_changed_command_cwd": edit_result(lambda r: r["commands"][6].update(cwd="/tmp"), records=True),
    "reindexed_command_stdout_misassociation": edit_result(lambda r: r["commands"][6].update(stdout="commands/13.stdout"), records=True),
    "reindexed_result_stdout_misassociation": edit_result(lambda r: r.update(host_stdout="commands/00.stdout")),
    "reindexed_command_overlap": edit_result(command_overlap, records=True),
    "reindexed_result_timestamp_inversion": edit_result(timestamp_inversion),
    "reindexed_result_timestamp_offset": edit_result(timestamp_offset),
    "rebound_config_missing_source": edit_config(lambda c: c["sources"].pop("probe.h")),
    "rebound_config_missing_tool": edit_config(lambda c: c["tools"].pop("clang")),
    "rebound_config_changed_c_flags": edit_config(lambda c: c.update(c_flags=[])),
    "rebound_config_changed_arm_flags": edit_config(lambda c: c.update(arm_flags=[])),
    "rebound_config_changed_qemu_flags": edit_config(lambda c: c.update(qemu_flags=[])),
    "rebound_config_fdt_claim": edit_config(lambda c: c.update(fdt="a51_live_fdt")),
    "rebound_config_input_hex": edit_config(lambda c: c.update(input_hex="00")),
    "rebound_config_tool_version": edit_config(lambda c: c["tools"]["clang"].update(version="unrelated\n")),
}


for name, mutation in REINDEXED.items():
    setattr(EvidenceGuards, "test_" + name, evidence_test(mutation))


def unread_oversized_role(name, limit):
    def test(self):
        with tempfile.TemporaryDirectory(prefix="hakios-probe-evidence-", dir=FIXTURES) as temp:
            folder = Path(temp) / "capture"
            shutil.copytree(self.folder, folder)
            path = folder / name
            data = PROBE.read(path)
            path.write_bytes(data + b" " * (limit + 1 - len(data)))
            reindex(folder)
            with mock.patch.object(PROBE, "read", wraps=PROBE.read) as reads:
                with self.assertRaises(ValueError):
                    PROBE.verify(folder)
                self.assertNotIn(path, [call.args[0] for call in reads.call_args_list])
    return test


for name in ("result.json", "identity-input.json", "commands/06.json"):
    setattr(EvidenceGuards, "test_oversized_json_unread_" + name.replace("/", "_").replace(".", "_"),
            unread_oversized_role(name, 512 * 1024))

for name in ("commands/06.stdout", "commands/13.stdout"):
    setattr(EvidenceGuards, "test_oversized_output_unread_" + name.replace("/", "_").replace(".", "_"),
            unread_oversized_role(name, 4096))


if __name__ == "__main__":
    unittest.main(verbosity=2)
