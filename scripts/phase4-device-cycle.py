#!/usr/bin/env python3
"""Run one nonce-bound Phase 4 trial and restore the pinned Android baseline."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import time

from phase4_device import Device, SERIAL, BOOT, BASELINE_SHA256
from phase4_pstore import acquire
from phase4_support import PROJECT, new_packet, pin, require, write_json, index_packet, documents

CASES = ("full", "copy", "reset", "watchdog", "fault", "early-fault", "empty-toc", "bad-count",
         "bad-schema", "source-overflow", "copy-overflow", "empty-segment", "overlap",
         "bad-crc", "bad-entry", "bad-bootargs", "bad-slot", "slot-magic", "bad-log",
         "bad-fdt", "fdt-reservation")
PLACEMENTS = (0x80080000, 0x80278000, 0x800d0000)
SOURCE_NAMES = ("entry.S", "loader.c", "loader.h", "loader.ld", "validate.c", "validate.h",
                "fdt_guard.c", "fdt_guard.h", "pack_phase4_payload.py",
                "xnu_trampoline.S", "xnu_trampoline.h")
SCRIPT_NAMES = ("phase4-device-cycle.py", "phase4_pstore.py", "phase4_device.py", "phase4_envelope.py",
                "phase3-qemu-platform.py", "phase4_support.py", "phase4-test-capture.py")
UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def resolve_file(root, relative):
    require(isinstance(relative, str) and relative and "\\" not in relative and
            not Path(relative).is_absolute() and ".." not in Path(relative).parts,
            "Invalid retained relative path")
    path = root / relative
    require(path.resolve().is_relative_to(root.resolve()) and path.is_file() and not path.is_symlink(),
            "Retained input is missing or redirected: " + relative)
    return path


def checked_file(root, item):
    path = resolve_file(root, item["path"])
    require(pin(path) == {key: item[key] for key in ("bytes", "sha256")},
            "Input pin mismatch: " + item["path"])
    return path


def verify_packet(packet):
    require(packet.resolve().is_relative_to((PROJECT / "evidence/phase-4").resolve()) and not packet.is_symlink(),
            "Wrong Phase 4 evidence root")
    rows = json.loads((packet / "index.json").read_text(encoding="utf-8"))
    seen = set()
    for row in rows:
        require(row["path"] not in seen and row["path"] != "index.json", "Duplicate/self-indexed evidence")
        seen.add(row["path"])
        checked_file(packet, row)
    actual = {p.relative_to(packet).as_posix() for p in packet.rglob("*") if p.is_file() and p != packet / "index.json"}
    require(actual == seen, "Evidence inventory differs from its index: " + str(packet))


def verify_archives(packet, case):
    receipt_path = checked_file(PROJECT, case["scratch_retention"])
    require(receipt_path.parent == packet, "Scratch receipt belongs to another case")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    require(receipt["complete"] and receipt["case_packet"] == case["packet"], "Incomplete scratch retention")
    expected_names = {"test.Image", "arena-prefill.bin"}
    if case["case"] != "full":
        expected_names.add("arena-after.bin")
    actual_names = set()
    for row in receipt["files"]:
        name = Path(row["raw_path"]).name
        require(name in expected_names and name not in actual_names and row["exact_decompression_verified"],
                "Unexpected/unverified scratch archive")
        actual_names.add(name)
        archive = checked_file(PROJECT, {"path": row["archive"], **row["archive_pin"]})
        require(archive.parent == packet and archive.name == name + ".gz", "Archive belongs to another case")
        digest, size = hashlib.sha256(), 0
        with gzip.open(archive, "rb") as stream:
            while block := stream.read(1048576):
                size += len(block)
                require(size <= row["raw_pin"]["bytes"], "Archive exceeds its original byte bound")
                digest.update(block)
        require({"bytes": size, "sha256": digest.hexdigest()} == row["raw_pin"], "Archive decompression changed")
        if name == "test.Image":
            require(row["raw_pin"] == case["executed_image"], "Execution image/receipt disagree")
        elif name == "arena-prefill.bin":
            require(row["raw_pin"] == case["prefill"], "Arena prefill/receipt disagree")
        elif name == "arena-after.bin":
            require(row["raw_pin"] == case["destination_readback"], "Destination readback/receipt disagree")
    require(actual_names == expected_names, "Missing exact execution/readback archive")


def built_platform_adaptation(build):
    """Follow the exact retained revisions checked by the platform builder."""
    build_packet = resolve_file(PROJECT, build["packet"] + "/result.json").parent
    verify_packet(build_packet)
    require(build["build_verified"] and
            json.loads((build_packet / "result.json").read_text(encoding="utf-8")) == build,
            "Platform build selection differs from the original result")
    original_packet = resolve_file(PROJECT, build["adaptation_packet"] + "/result.json").parent
    verify_packet(original_packet)
    previous = original_packet / "result.json"
    current_path = resolve_file(PROJECT, "manifests/phase4-platform-adaptation.json")
    current = json.loads(current_path.read_text(encoding="utf-8"))
    revisions = current.get("revision_packets", [])
    require(isinstance(revisions, list) and len(revisions) <= 32 and
            all(isinstance(rel, str) for rel in revisions) and len(set(revisions)) == len(revisions),
            "Invalid or duplicate platform revision chain")
    followed = []
    for rel in revisions:
        packet = resolve_file(PROJECT, rel + "/result.json").parent
        require(re.fullmatch(r"[0-9]{8}T[0-9]{12}Z", packet.name) and
                original_packet.name < packet.name < build_packet.name,
                "Platform revision was not retained before the selected build")
        verify_packet(packet)
        before = resolve_file(packet, "before/manifests/phase4-platform-adaptation.json")
        after = resolve_file(packet, "after/manifests/phase4-platform-adaptation.json")
        require(pin(before) == pin(previous), "Broken platform adaptation revision chain")
        followed.append(rel)
        revision = json.loads(after.read_text(encoding="utf-8"))
        require(revision.get("revision_packets") == followed and revision["applied"] and
                revision["root"] == build["root"] and revision["packet"] == build["adaptation_packet"],
                "Platform revision identity or order changed")
        previous = after
    require(pin(current_path) == pin(previous) and current["applied"] and
            current["root"] == build["root"] and current["packet"] == build["adaptation_packet"],
            "Current platform adaptation differs from the retained build inputs")
    return current, {"path": previous.relative_to(PROJECT).as_posix(), **pin(previous),
                     "revision_packets": followed}


def snapshot_contract(selected):
    """Derive the expected passive registers from the pinned built source."""
    build = json.loads(checked_file(PROJECT, selected["platform_build"]).read_text(encoding="utf-8"))
    original, provenance = built_platform_adaptation(build)
    texts = {}
    for name in ("hakios.a51.c", "hakios.a51.h", "hello.c"):
        path = PROJECT / "prototype/phase4-platform" / name
        require(pin(path) == original["source_pins"][name], "Snapshot source differs from the built platform: " + name)
        texts[name] = path.read_text(encoding="utf-8")
    groups = {name: 1 << int(bit) for name, bit in re.findall(
        r"#define\s+(HAKIOS_A51_(?:GPIO|I2C|DSIM|DECON|UFS|DPP|SYSMMU))\s+\(1u << (\d+)\)", texts["hakios.a51.h"])}
    offsets = {name: [int(value, 0) for value in values.split(",") if value.strip()]
        for name, values in re.findall(r"static const unsigned short (\w+)\[\] = \{([^}]+)\};", texts["hakios.a51.c"])}
    arguments = re.findall(r"(?:^|\s)hakios_a51_probe=(\d+)(?=\s|$)", selected["cmdline"])
    require(len(arguments) == 1 and 1 <= int(arguments[0]) <= 127, "Missing or duplicate snapshot probe mask")
    mask, registers, banks = int(arguments[0]), [], []
    for base, size, group, array in re.findall(
            r"BANK\((0x[0-9a-f]+), (0x[0-9a-f]+), (HAKIOS_A51_\w+), (\w+)\)", texts["hakios.a51.c"]):
        if not groups[group] & mask:
            continue
        values = offsets[array]
        require(values and all(0 <= n <= int(size, 0) - 4 and n % 4 == 0 for n in values), "Invalid source register bound")
        banks.append({"pa": int(base, 0), "group": groups[group], "count": len(values)})
        registers.extend({"pa": int(base, 0) + n, "group": groups[group]} for n in values)
    require(0 < len(registers) <= 192 and len({row["pa"] for row in registers}) == len(registers),
            "Invalid/duplicate snapshot register contract")
    return {"groups": mask, "bytes": 3096, "version": 1, "registers": registers, "banks": banks,
            "source_pins": {name: original["source_pins"][name] for name in texts},
            "built_adaptation": provenance}


def validate_snapshot(log, selected, result):
    contract = selected["snapshot_contract"]
    summary = re.findall(r"^HAKIOS_A51_SNAPSHOT rc=(-?\d+) version=(\d+) count=(\d+) groups=0x([0-9a-f]+) sequence=(\d+) counter=(\d+) pass=([01])$", log, re.M)
    registers = re.findall(r"^HAKIOS_A51_REG index=(\d+) pa=0x([0-9a-f]+) group=0x([0-9a-f]+) value=0x([0-9a-f]+)$", log, re.M)
    begins = re.findall(r"^HAKIOS_A51_PROBE_BEGIN pa=0x([0-9a-f]+) group=0x([0-9a-f]+)$", log, re.M)
    dones = re.findall(r"^HAKIOS_A51_PROBE_DONE pa=0x([0-9a-f]+) count=(\d+)$", log, re.M)
    expected = contract["registers"]
    metadata = False
    if len(summary) == 1:
        rc, version, count, mask, sequence, counter, passed = summary[0]
        metadata = (int(rc) == 0 and int(version) == contract["version"] and int(count) == len(expected) and
                    int(mask, 16) == contract["groups"] and int(sequence) > 0 and int(counter) > 0 and passed == "1")
    rows_ok = len(registers) == len(expected) and all(
        int(row[0]) == i and int(row[1], 16) == wanted["pa"] and int(row[2], 16) == wanted["group"] and
        0 <= int(row[3], 16) <= 0xffffffff for i, (row, wanted) in enumerate(zip(registers, expected)))
    banks_ok = ([(int(pa, 16), int(group, 16)) for pa, group in begins] ==
                [(row["pa"], row["group"]) for row in contract["banks"]] and
                [(int(pa, 16), int(count)) for pa, count in dones] ==
                [(row["pa"], row["count"]) for row in contract["banks"]])
    result["checks"].update({
        "hardware_snapshot_abi": log.count("HAKIOS_A51_SNAPSHOT_SIZE rc=0 bytes=3096\n") == 1 and
                                 log.count("HAKIOS_A51_ABI small_rc=-12 write_rc=-1\n") == 1,
        "hardware_snapshot_metadata": metadata,
        "all_source_bound_registers": rows_ok,
        "all_source_bound_banks_completed": banks_ok,
        "snapshot_diagnostic_pass": log.count("HAKIOS_A51_DIAG_PASS\n") == 1 and "HAKIOS_A51_DIAG_FAIL" not in log,
        "qemu_spi_disabled_on_phone": log.count("HAKIOS_A51_SPI rc=-6 flags=0x0\n") == 1 and
                                      "HAKIOS_A51_GUARD" not in log and "hakios_qemu_spi=" not in log})
    result["snapshot_registers"] = [{"index": int(i), "pa": int(pa, 16), "group": int(group, 16), "value": int(value, 16)}
                                    for i, pa, group, value in registers]


def load_prerequisites(kind):
    require(shutil.disk_usage(PROJECT).free >= 256 * 1048576, "Insufficient host space for device evidence")
    selected = json.loads((PROJECT / ("manifests/phase4-candidate-" + kind + ".json")).read_text(encoding="utf-8"))
    diag = {"reset": 1, "watchdog": 2, "fault": 3}.get(kind, 0)
    require(selected["schema_version"] == 2 and selected["built"] and selected["passed"] and
            selected["mode"] == "hardware" and selected["kind"] == kind and selected["diagnostic"] == diag and
            selected["config"][10] == 0 and selected["config"][11] == diag,
            "Wrong or obsolete hardware candidate")
    require(re.fullmatch(r"[0-9a-f]{32}", selected["nonce"]), "Invalid candidate nonce")
    require(selected["layout"]["video"] == "unavailable_zero_bootvideo" and
            selected["initial_memory_budget_bytes"] == 112 * 1024 * 1024,
            "Unreviewed hardware video/memory contract")
    require("hakios_qemu_spi=" not in selected["cmdline"] and
            selected["cmdline"].split().count("hakios_run_nonce=" + selected["nonce"]) == 1,
            "Hardware boot arguments contain simulation or wrong attribution")
    candidate = checked_file(PROJECT, selected["candidate"])
    require(selected["candidate"]["bytes"] == 61865984 and selected["candidate"]["sha256"] != BASELINE_SHA256,
            "Candidate is not a complete experimental boot image")
    verify_packet(PROJECT / selected["packet"])
    baseline = module("phase4_baseline_pins", PROJECT / "scripts/build-xnu-boot-candidate.py")
    for role, item in selected["rollback_pins"].items():
        require(role in baseline.EXPECTED_PINS and (item["bytes"], item["sha256"]) == baseline.EXPECTED_PINS[role],
                "Unrecognized rollback pin: " + role)
        checked_file(PROJECT.parent, item)
    require(set(selected["rollback_pins"]) == set(baseline.EXPECTED_PINS), "Missing rollback input")
    qemu = json.loads((PROJECT / "manifests/phase4-complete-loader-qemu.json").read_text(encoding="utf-8"))
    require(qemu["passed"] and qemu["suite_complete"], "Complete-loader QEMU suite is unpassed")
    verify_packet(PROJECT / qemu["packet"])
    required = {(case, address) for case in CASES for address in PLACEMENTS}
    observed = set()
    for row in qemu["results"]:
        pair = (row["case"], row["placement"])
        require(pair in required and pair not in observed and row["passed"], "Missing/duplicate/failed QEMU case")
        observed.add(pair)
        case_path = checked_file(PROJECT, {"path": row["result"], **{key: row[key] for key in ("bytes", "sha256")}})
        packet = case_path.parent
        verify_packet(packet)
        case = json.loads(case_path.read_text(encoding="utf-8"))
        require(case["passed"] and case["execution_passed"] and all(case["checks"].values()) and
                case["case"] == row["case"] and case["load_address"] == row["placement"], "QEMU result disagrees with review")
        tested = json.loads((packet / "selected-loader.json").read_text(encoding="utf-8"))
        require(tested["schema_version"] == 2 and tested["mode"] == "qemu" and
                tested["platform_build"] == selected["platform_build"] and
                tested["rollback_pins"] == selected["rollback_pins"], "QEMU tested different platform/rollback inputs")
        for name in SOURCE_NAMES:
            require(tested["sources"][name] == selected["sources"][name] == pin(PROJECT / "prototype/phase4-loader" / name),
                    "Loader source changed after QEMU: " + name)
        for key in ("original_image", "original_result", "helper_pin", "header_hex", "stext_offset", "loader_entry_offset"):
            require(tested["carrier"][key] == selected["carrier"][key], "Carrier contract differs from QEMU: " + key)
        verify_archives(packet, case)
    require(observed == required, "Not all " + str(len(required)) + " QEMU cases are present")
    require(selected["carrier"]["helper_pin"] == pin(PROJECT / "scripts/phase4_carrier.py"), "Carrier helper changed")
    checked_file(PROJECT, selected["platform_build"])
    native = json.loads((PROJECT / "manifests/phase4-loader-native-tests.json").read_text(encoding="utf-8"))
    require(native["passed"] and native["native_checks"] >= 4110 and native["envelope_checks"] >= 106,
            "Native validator/envelope prerequisites are unpassed")
    verify_packet(PROJECT / native["packet"])
    models = json.loads((PROJECT / "manifests/phase4-device-cycle-tests.json").read_text(encoding="utf-8"))
    require(models["passed"] and models["tests"] >= 16 and models["device_operations"] is False,
            "Device cycle failure tests are unpassed")
    verify_packet(PROJECT / models["packet"])
    for name in SCRIPT_NAMES:
        require(models["sources"][name] == pin(PROJECT / "scripts" / name), "Cycle/capture source changed after tests: " + name)
    for old in (PROJECT / "evidence/phase-4/device-cycle").glob("*/result.json"):
        require(json.loads(old.read_text(encoding="utf-8")).get("nonce") != selected["nonce"],
                "A device cycle nonce cannot be reused; build a fresh package")
    if kind == "snapshot":
        selected["snapshot_contract"] = snapshot_contract(selected)
    return selected, candidate, baseline.TEMPLATE


def validate_capture(decoded, selected, result):
    fields = decoded["fields"]
    checks = result["checks"]
    checks.update({"original_nonce_and_both_crcs": True, "no_conflicting_valid_banks": True,
        "supported_entry": fields["entry_el"] == 4 and fields["entry_sctlr"] & 5 == 0,
        "a53_boot_core": (fields["midr"] >> 4) & 0xfff == 0xd03 and fields["mpidr"] & 0xffffff == 0,
        "counter_26mhz": fields["cntfrq"] == 26000000,
        "supported_runtime_placement": fields["runtime_base"] in PLACEMENTS,
        "watchdog_counted_down": 0 < fields["wdt_after"] < fields["wdt_before"] <= selected["config"][17]})
    kind = selected["kind"]
    if kind in ("reset", "watchdog", "fault"):
        checks["no_diagnostic_payload_copy"] = fields["validated"] == 1 and not any(fields[key] for key in
            ("copy_entries", "copied_bytes", "zeroed_bytes"))
        if kind == "fault":
            checks["stackless_fault"] = (fields["error"] == 9 and fields["reason"] == 6 and
                fields["code"] >> 26 == 0x3c and b"HAKIOS_LOADER_FAULT" in decoded["diagnostic"])
        else:
            checks["expected_diagnostic"] = (fields["stage"] == 3 and fields["error"] == 0 and
                fields["reason"] == 3 and fields["code"] == selected["diagnostic"])
        if kind == "watchdog":
            checks["bounded_watchdog_return"] = 0 < result["return_seconds"] < 90
    else:
        checker = module("phase4_hardware_user_checker", PROJECT / "scripts/phase3-qemu-platform.py")
        record = [checker.MAGIC, selected["layout"]["log_pa"], fields["requested"], fields["reason"],
                  fields["code"], fields["midr"], fields["cntfrq"], fields["mpidr"], fields["entry_el"]]
        user, samples = checker.validate(decoded["log"].decode("utf-8", "replace"), selected["nonce"], record)
        user["counter_frequency"] = fields["cntfrq"] == 26000000
        checks.update(user)
        checks["single_user_frame"] = decoded["log"].count(b"HAKIOS_USER_BEGIN pid=1 uid=0 console=") == 1
        checks["physical_return"] = fields["stage"] == 5 and fields["error"] == fields["reason"] == fields["code"] == 0
        checks["complete_original_log"] = decoded["complete_log"]
        checks["exact_copy_counters"] = (fields["validated"] == 1 and fields["copy_entries"] == len(selected["toc"]) and
            fields["copied_bytes"] == sum(row["copy"] for row in selected["toc"]) and
            fields["zeroed_bytes"] == sum(row["zero"] for row in selected["toc"]))
        result["timer_samples"] = samples
        if kind == "snapshot":
            validate_snapshot(decoded["log"].decode("utf-8", "replace").replace("\r", ""), selected, result)
    require(all(checks.values()), "Hardware evidence checks failed: " + ", ".join(key for key, value in checks.items() if not value))


class Cycle:
    def __init__(self, packet, selected, candidate, baseline, device, *, seconds=240,
                 clock=time.monotonic, sleep=time.sleep, validator=validate_capture):
        self.packet, self.selected, self.candidate, self.baseline, self.device = packet, selected, candidate, baseline, device
        self.seconds, self.clock, self.sleep, self.validator = seconds, clock, sleep, validator
        self.may_have_written = self.initial_verified = self.capture_attempted = False
        self.staging = []
        self.result = {"schema_version": 2, "case": selected["kind"], "nonce": selected["nonce"],
            "serial": SERIAL, "candidate": selected["candidate"], "checks": {}, "passed": False,
            "baseline_restored": False, "baseline_verified": False, "phase_4_gate_passed": False,
            "operations": {"file_writes": 0, "boot_writes": 0, "reboots": 0, "file_removals": 0},
            "operation_counts_are_attempts": True, "device_operations": True,
            "candidate_write_attempted": False,
            "scope": "Loader/persistence/watchdog/XNU trial; peripheral Phase 4 gates remain separate"}

    def persist(self):
        temporary = self.packet / "progress.tmp"
        with temporary.open("wb") as stream:
            stream.write((json.dumps(self.result, indent=2) + "\n").encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.packet / "progress.json")

    def intent(self, category, name):
        event = {"operation": name, "category": category, "monotonic": self.clock()}
        with (self.packet / "intent.jsonl").open("ab") as stream:
            stream.write((json.dumps(event) + "\n").encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        self.result["operations"][category] += 1
        self.persist()

    def wait_mode(self, label, *, android=False, deadline=None):
        start, deadline = self.clock(), self.seconds if deadline is None else deadline
        for i in range(120):
            state = self.device.mode(f"{label}-{i:03}")
            if android and state == "device":
                try:
                    if self.device.text(f"{label}-completed-{i:03}", "getprop sys.boot_completed", timeout=10) == "1":
                        return state
                except Exception:
                    pass
            elif not android and state in ("device", "recovery"):
                return state
            if self.clock() - start >= deadline:
                self.result.setdefault("wait_deadlines", []).append({"label": label, "last_state": state,
                    "elapsed_seconds": self.clock() - start, "android_completion_required": android})
                return ""
            self.sleep(3)
        self.result.setdefault("wait_deadlines", []).append({"label": label, "last_state": state,
            "elapsed_seconds": self.clock() - start, "android_completion_required": android})
        return ""

    def target(self, label, recovery):
        text = self.device.text
        require(text(label + "-root", "id", recovery=recovery).startswith("uid=0(root)"), "Device root unavailable")
        require(text(label + "-model", "getprop ro.product.model", recovery=recovery) == "SM-A515F", "Wrong phone model")
        require(text(label + "-boot-target", "readlink -f /dev/block/by-name/boot", recovery=recovery) == BOOT, "Wrong boot target")
        require(text(label + "-boot-size", "blockdev --getsize64 " + BOOT, recovery=recovery) == "61865984", "Wrong boot partition size")

    def hashes(self, label, recovery=False):
        for role, target in (("template", BOOT), ("recovery", "/dev/block/by-name/recovery"), ("dtbo", "/dev/block/by-name/dtbo")):
            expected = self.selected["rollback_pins"][role]
            require(self.device.text(label + "-size-" + role, "blockdev --getsize64 " + target, recovery=recovery) == str(expected["bytes"]),
                    "Partition size changed: " + role)
            actual = self.device.text(label + "-hash-" + role, "sha256sum " + target, recovery=recovery).split()
            require(actual and actual[0] == expected["sha256"], "Partition hash changed: " + role)

    def stage(self, name, local, remote, expected, recovery=False):
        require(pin(local) == {key: expected[key] for key in ("bytes", "sha256")}, "Local staging input changed: " + name)
        require(re.fullmatch(r"/(?:data/local/tmp|tmp)/hakios-p4-(?:baseline-)?[0-9a-f]{32}(?:-[01])?\.img", remote), "Wrong staging path")
        quoted = shlex.quote(remote)
        self.device.root(name + "-absent", "test ! -e " + quoted + " && test ! -L " + quoted, recovery=recovery)
        self.staging.append(remote)  # A failed push can leave a partial file.
        self.result["staging_paths"] = list(self.staging)
        self.intent("file_writes", name)
        self.device.adb(name, ["push", str(local), remote], timeout=120)
        require(self.device.text(name + "-size", "stat -c %s " + quoted, recovery=recovery) == str(expected["bytes"]), "Staged image size mismatch")
        hashed = self.device.text(name + "-hash", "sha256sum " + quoted, recovery=recovery).split()
        require(hashed and hashed[0] == expected["sha256"], "Staged image hash mismatch")

    def write_boot(self, name, remote, expected, recovery=False):
        if name == "write-candidate":
            self.may_have_written = True  # Before dd: partial failure needs rollback.
            self.result["candidate_write_attempted"] = True
        self.intent("boot_writes", name)
        self.device.root(name, "dd if=" + shlex.quote(remote) + " of=" + BOOT + " bs=4096 conv=fsync", recovery=recovery, timeout=90)
        self.device.root(name + "-sync", "sync", recovery=recovery)
        hashed = self.device.text(name + "-readback", "sha256sum " + BOOT, recovery=recovery).split()
        require(hashed and hashed[0] == expected["sha256"], "Boot readback mismatch: " + name)

    def reboot(self, name):
        self.intent("reboots", name)
        try:
            self.device.adb(name, ["reboot"], timeout=20)
        except Exception as exc:
            # A transport failure after reboot does not identify the new boot.
            # Recovery/Android state, UUID and original nonce evidence decide.
            self.result.setdefault("reboot_transport_errors", []).append({"name": name, "error": str(exc)})

    def capture(self):
        self.capture_attempted = True
        require(self.device.text("capture-root", "id", recovery=True).startswith("uid=0(root)"), "Recovery root unavailable")
        boot_id = self.device.text("capture-boot-id", "cat /proc/sys/kernel/random/boot_id", recovery=True)
        require(UUID.fullmatch(boot_id) and boot_id != self.result["boot_id_before"], "Fresh recovery UUID unverified")
        self.result["recovery_boot_id"] = boot_id
        self.device.root("capture-pstore-files", "ls -ln /sys/fs/pstore", recovery=True, check=False)
        decoded = acquire(self.device, self.packet, self.selected["nonce"], self.result)
        self.validator(decoded, self.selected, self.result)

    def cleanup(self, remote, recovery=False):
        name = f"remove-{self.result['operations']['file_removals']:02}-" + Path(remote).name
        self.intent("file_removals", name)
        quoted = shlex.quote(remote)
        self.device.root(name, "rm -f " + quoted + " && test ! -e " + quoted + " && test ! -L " + quoted, recovery=recovery)

    def restore(self):
        if self.may_have_written:
            self.result["restoration_attempts"] = []
            restored = False
            for attempt in range(2):
                try:
                    current = self.device.mode(f"restore-state-{attempt}")
                    if current not in ("device", "recovery"):
                        print("Waiting for recovery to restore the pinned baseline.", flush=True)
                        current = self.wait_mode(f"restore-wait-{attempt}", deadline=180)
                    require(current in ("device", "recovery"), "ADB unavailable; baseline restoration needs the connected phone")
                    recovery = current == "recovery"
                    self.target(f"restore-{attempt}", recovery)
                    if recovery and not self.capture_attempted:
                        try:
                            self.capture()
                        except Exception as exc:
                            self.result["capture_error"] = str(exc)
                    remote = ("/tmp/" if recovery else "/data/local/tmp/") + "hakios-p4-baseline-" + self.selected["nonce"] + f"-{attempt}.img"
                    self.stage(f"stage-baseline-{attempt}", self.baseline, remote, self.selected["rollback_pins"]["template"], recovery)
                    self.write_boot(f"restore-baseline-{attempt}", remote, self.selected["rollback_pins"]["template"], recovery)
                    self.result["restoration_attempts"].append({"attempt": attempt, "readback_verified": True})
                    restored = True
                    try:
                        self.cleanup(remote, recovery)
                    except Exception as exc:
                        self.result.setdefault("cleanup_diagnostics", []).append(str(exc))
                    self.reboot("return-baseline-android")
                    break
                except Exception as exc:
                    self.result["restoration_attempts"].append({"attempt": attempt, "readback_verified": False, "error": str(exc)})
                    self.persist()
            require(restored, "Pinned baseline readback could not be restored; preserve staging and use recovery")
            require(self.wait_mode("android-return", android=True) == "device", "Baseline Android return deadline expired")
        elif not self.initial_verified:
            # Missing Android at entry needs no rollback or long return polling.
            self.result["baseline_untouched"] = True
            return
        else:
            require(self.device.mode("unchanged-android") == "device", "Android unavailable after staging failure; no boot write attempted")
        self.target("final", False)
        require(self.device.text("final-completed", "getprop sys.boot_completed") == "1", "Final Android boot incomplete")
        self.hashes("final")
        boot_id = self.device.text("final-boot-id", "cat /proc/sys/kernel/random/boot_id")
        require(UUID.fullmatch(boot_id), "Final Android UUID invalid")
        if self.may_have_written:
            require(boot_id != self.result["boot_id_before"] and boot_id != self.result.get("recovery_boot_id"), "Fresh baseline Android UUID unverified")
        self.result["boot_id_after"] = boot_id
        for remote in self.staging:
            self.cleanup(remote)
        self.result["baseline_verified"] = True
        self.result["baseline_restored"] = self.may_have_written
        self.result["checks"]["baseline_boot_root_and_unchanged_recovery_dtbo"] = True
        self.result["checks"]["all_staging_absent"] = True

    def run(self):
        staged = "/data/local/tmp/hakios-p4-" + self.selected["nonce"] + ".img"
        try:
            require(self.device.mode("initial-state") == "device", "Pinned baseline Android is required; A51 is absent or in another mode")
            self.target("initial", False)
            require(self.device.text("initial-completed", "getprop sys.boot_completed") == "1", "Initial Android boot incomplete")
            boot_id = self.device.text("initial-boot-id", "cat /proc/sys/kernel/random/boot_id")
            require(UUID.fullmatch(boot_id), "Initial Android UUID invalid")
            self.result["boot_id_before"] = boot_id
            self.hashes("initial")
            self.initial_verified = True
            battery = self.device.text("initial-battery", "dumpsys battery")
            level = re.search(r"^\s*level:\s*(\d+)", battery, re.M)
            require(level and 20 <= int(level[1]) <= 100, "Battery level not verified at 20 percent or higher")
            self.stage("stage-candidate", self.candidate, staged, self.selected["candidate"])
            self.write_boot("write-candidate", staged, self.selected["candidate"])
            started = self.clock()
            self.reboot("boot-candidate")
            self.sleep(3)
            # Baseline Android can still be visible briefly after adb reboot.
            current = ""
            for i in range(100):
                current = self.device.mode(f"candidate-return-{i:03}")
                if current == "recovery" or self.clock() - started >= self.seconds:
                    break
                self.sleep(3)
            self.result["return_seconds"] = round(self.clock() - started, 3)
            require(current == "recovery", "Candidate did not reach recovery before the deadline")
            self.result["checks"]["recovery_reconnected"] = True
            self.capture()
        except Exception as exc:
            self.result["error"] = str(exc)
            print("Trial evidence failed: " + str(exc), flush=True)
        finally:
            try:
                self.restore()
            except Exception as exc:
                self.result["restoration_error"] = str(exc)
                print("Baseline restoration unverified: " + str(exc), flush=True)
            self.result["passed"] = (bool(self.result["checks"]) and all(self.result["checks"].values()) and
                self.result["baseline_restored"] and "error" not in self.result and "restoration_error" not in self.result)
            self.persist()
        return self.result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=("watchdog", "reset", "fault", "full", "snapshot"), required=True)
    parser.add_argument("--seconds", type=int, default=240)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    require(60 <= args.seconds <= 300, "Invalid device deadline")
    packet = new_packet("device-preflight" if args.preflight_only else "device-cycle", __file__)
    for name in (*SCRIPT_NAMES[1:], "phase4_carrier.py"):
        shutil.copy2(PROJECT / "scripts" / name, packet / name)
    result = {"packet": packet.relative_to(PROJECT).as_posix(), "case": args.kind,
              "passed": False, "host_prerequisites_passed": False, "device_operations": False,
              "phase_4_gate_passed": False}
    try:
        selected, candidate, baseline = load_prerequisites(args.kind)
        write_json(packet / "selected-candidate.json", selected)
        result.update(host_prerequisites_passed=True, nonce=selected["nonce"])
        if args.preflight_only:
            result["passed"] = True
        else:
            cycle = Cycle(packet, selected, candidate, baseline, Device(packet), seconds=args.seconds)
            result.update(cycle.run())
    except Exception as exc:
        result["error"] = str(exc)
    write_json(packet / "result.json", result)
    state = json.loads((PROJECT / "state.json").read_text(encoding="utf-8"))
    key = "phase_4_device_preflight" if args.preflight_only else "phase_4_last_device_cycle"
    state[key] = {"result": (packet / "result.json").relative_to(PROJECT).as_posix(), **pin(packet / "result.json"),
                  "passed": result["passed"], "error": result.get("error"), "baseline_restored": result.get("baseline_restored", False)}
    state["phase_4_status"], state["phase_4_device_gate_passed"] = "in_progress", False
    note = f"\n\n## P4-021 — Phase 4 device preflight/trial ({packet.name})\n\nPurpose/files: scripts/phase4-device-cycle.py, phase4_pstore.py, selected evidence and state/log. Require pinned schema-v2 hardware inputs, all {len(CASES) * len(PLACEMENTS)} exact QEMU execution archives and tested capture/cycle sources before device writes. Journal staging, boot-write and reboot intent before commands. Retain original framed pstore output and verify attribution/checksums; always attempt baseline restoration after an attempted candidate write, including partial failures. Verify baseline readback before reboot and fresh Android/root/UUID, unchanged recovery/DTBO and staging absence afterwards.\n\nVerification: preflight_only={args.preflight_only}; host_prerequisites_passed={result['host_prerequisites_passed']}; passed={result['passed']}; baseline_restored={result.get('baseline_restored', False)}; error={result.get('error')}; restoration_error={result.get('restoration_error')}. Exact commands, intent/progress and original output are in `{result['packet']}`. Device-operation counts are attempts; zero boot-write/reboot counts establish no such operation was attempted. Loader trials alone do not pass display/input/UFS/image hardware gates.\n\nRollback/recovery: retain every failed packet. If baseline readback is unverified, keep the phone in connected recovery and use the independent pinned baseline procedure in docs/PHASE-4-DEVICE-PATH.md; never reboot an unverified image. Ignore this isolated candidate to return to the preserved Phase 3 sources. Rebuild a new nonce before another cycle; run all commands through scripts/run.py. Phase 4 remains incomplete.\n"
    documents(packet, {"state.json": json.dumps(state, indent=2) + "\n",
        "docs/IMPLEMENTATION-LOG.md": (PROJECT / "docs/IMPLEMENTATION-LOG.md").read_text(encoding="utf-8") + note})
    index_packet(packet)
    write_json(PROJECT / ("manifests/phase4-device-preflight.json" if args.preflight_only else "manifests/phase4-last-device-cycle.json"), result)
    print(json.dumps(result, indent=2), flush=True)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
