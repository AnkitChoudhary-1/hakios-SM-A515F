#!/usr/bin/env python3
"""Failure models for the real cycle/ADB framing code; never run real ADB."""
from __future__ import annotations

import contextlib
import copy
import fnmatch
import gzip
import io
import json
from pathlib import Path
import shlex
import shutil
import subprocess
from unittest import mock

from phase4_device import Device, BOOT, SERIAL
from phase4_pstore import acquire, decode_export
from phase4_support import PROJECT, new_packet, pin, require, write_json, index_packet, documents
import phase4_device


def load(name, path):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cycle = load("phase4_cycle_under_test", PROJECT / "scripts/phase4-device-cycle.py")
fixtures = load("phase4_envelope_model_fixtures", PROJECT / "scripts/phase4-test-capture.py")
NONCE = fixtures.NONCE
BOOT_IDS = ("11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222",
            "33333333-3333-4333-8333-333333333333")


class VirtualClock:
    def __init__(self):
        self.value = 0.0

    def now(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


def user_log(snapshot=""):
    # Deliberately modeled text, never selected as hardware evidence.
    text = ("HAKIOS_USER_BEGIN pid=1 uid=0 console=3\n"
            f"HAKIOS_RUN_NONCE={NONCE}\n"
            "HAKIOS_PLATFORM gic=2 cores=1 midr=0x410fd034\n" + snapshot)
    for i in range(1, 4):
        text += (f"HAKIOS_TIMER_SAMPLE index={i} select_rc=0 elapsed_us=1000000 "
                 f"irq_before={i - 1} irq_after={i} read_rc=0 pass=1\n")
    return (text + "HAKIOS_TIMER_PASS samples=3\nHAKIOS_USER_EXIT outcome=0 timer_verified=1\n"
            "panic: initproc (signal 0, exit 0)\n").encode("ascii")


def envelope(kind="watchdog", log=None, **changes):
    diagnostic = {"watchdog": 2, "reset": 1, "fault": 3}.get(kind, 0)
    fields = {"entry_sctlr": 0, "midr": 0x410fd034, "mpidr": 0x80000000,
              "wdt_before": 4096, "wdt_after": 4094}
    if diagnostic:
        fields.update(stage=3, error=0, reason=3, code=diagnostic, validated=1, log_valid=0,
                      copy_entries=0, copied_bytes=0, zeroed_bytes=0)
        log = b"" if log is None else log
        if kind == "fault":
            fields.update(error=9, reason=6, code=0x3c << 26)
    else:
        fields.update(stage=5, error=0, reason=0, code=0, copy_entries=1, copied_bytes=32, zeroed_bytes=16)
        log = user_log() if log is None else log
    fields.update(changes)
    raw = fixtures.fixture(log, **fields)
    if kind == "fault":
        unsigned = raw[:raw.rfind(b"HAKIOS_P4_ENVELOPE_CRC32=")]
        raw = fixtures.sign(unsigned.replace(b"HAKIOS_P4_LOG_BEGIN\n",
            b"HAKIOS_LOADER_FAULT model_fixture=1\nHAKIOS_P4_LOG_BEGIN\n", 1))
    return raw


class ModelDevice(Device):
    """Interpret controlled requests, then use Device's actual output framing."""
    def __init__(self, packet, selected, *, rules=None, banks=None):
        super().__init__(packet)
        self.selected = selected
        self.rules = rules or {}
        self.banks = {"console": envelope(selected["kind"]), "pmsg": envelope(selected["kind"])} if banks is None else banks
        self.current_name = ""
        self.state = "device"
        self.boot_id = BOOT_IDS[0]
        self.boot_hash = selected["rollback_pins"]["template"]["sha256"]
        self.files = {}
        self.events = []
        self.rule_hits = {}
        self.journal_checks = 0
        self.baseline_readback_ok = False

    def adb(self, name, args, **kwargs):
        self.current_name = name
        try:
            return super().adb(name, args, **kwargs)
        finally:
            if self.records and self.records[-1]["name"] == name:
                self.records[-1].update(modeled_transport=True, actual_device_operation=False)
                write_json(self.packet / "commands.json", self.records)

    def assert_intent(self, category):
        progress = json.loads((self.packet / "progress.json").read_text(encoding="utf-8"))
        rows = [json.loads(line) for line in (self.packet / "intent.jsonl").read_text(encoding="utf-8").splitlines()]
        require(rows[-1]["operation"] == self.current_name and rows[-1]["category"] == category,
                "Mutation reached transport without its exact journal intent")
        require(progress["operations"][category] == sum(row["category"] == category for row in rows),
                "Progress was not durable before the modeled operation")
        if self.current_name == "write-candidate":
            require(progress["candidate_write_attempted"], "Partial-write restoration requirement not persisted")
        self.journal_checks += 1

    def run_command(self, argv, **kwargs):
        name = self.current_name
        require(argv[:3] == ["adb", "-s", SERIAL], "Wrong modeled ADB target")
        require(kwargs.get("capture_output") is True and kwargs.get("timeout", 0) > 0, "Unbounded/uncaptured request")
        args = argv[3:]
        framed = args[:1] == ["exec-out"]
        command = args[-1] if framed else ""
        self.events.append({"name": name, "argv": argv, "state_before": self.state, "modeled": True})
        rule = {}
        for pattern, row in self.rules.items():
            if fnmatch.fnmatchcase(name, pattern):
                self.rule_hits[pattern] = self.rule_hits.get(pattern, 0) + 1
                if self.rule_hits[pattern] in row.get("on", [self.rule_hits[pattern]]):
                    rule = row
                break
        raw = b""
        if args == ["get-state"]:
            raw = self.state.encode("ascii") + b"\n"
        elif args[:1] == ["push"]:
            self.assert_intent("file_writes")
            self.files[args[2]] = pin(Path(args[1]))
            if rule.get("partial"):
                self.files[args[2]] = {"bytes": 1, "sha256": "0" * 64}
            raw = b"MODELED push\n"
        elif args == ["reboot"]:
            self.assert_intent("reboots")
            if name == "return-baseline-android":
                require(self.baseline_readback_ok, "Reboot requested before verified baseline readback")
            if not rule.get("no_effect"):
                if name == "boot-candidate":
                    self.state, self.boot_id = "recovery", BOOT_IDS[1]
                else:
                    self.state, self.boot_id = "device", BOOT_IDS[2]
            raw = b""
        elif framed:
            require(args[1:3] in (["su", "-c"], ["sh", "-c"]), "Unexpected root transport")
            require("HAKIOS_REMOTE_EXIT:%d" in command and "hakios_capture_rc=$?" in command,
                    "Actual Device root framing was bypassed")
            if "dd if=" in command:
                self.assert_intent("boot_writes")
                remote = command.split("dd if=", 1)[1].split(" of=", 1)[0]
                require(command.split(" of=", 1)[1].startswith(BOOT + " bs=4096 conv=fsync"), "Wrong modeled boot write")
                require(remote in self.files, "Write attempted without modeled staging")
                self.boot_hash = "f" * 64 if rule.get("partial") else self.files[remote]["sha256"]
                self.baseline_readback_ok = False
            elif command.startswith("{ rm -f "):
                self.assert_intent("file_removals")
                remote = shlex.split(command.split("{ rm -f ", 1)[1].split(" &&", 1)[0])[0]
                if not rule.get("no_effect"):
                    self.files.pop(remote, None)
            elif name.endswith("-root"):
                raw = b"uid=0(root) gid=0(root)\n"
            elif name.endswith("-model"):
                raw = b"SM-A515F\n"
            elif name.endswith("-boot-target"):
                raw = BOOT.encode("ascii") + b"\n"
            elif name.endswith("-boot-size"):
                raw = b"61865984\n"
            elif "-size-" in name:
                role = name.split("-size-", 1)[1]
                raw = str(self.selected["rollback_pins"][role]["bytes"]).encode("ascii") + b"\n"
            elif "-hash-" in name:
                role = name.split("-hash-", 1)[1]
                value = self.boot_hash if role == "template" else self.selected["rollback_pins"][role]["sha256"]
                raw = value.encode("ascii") + b"  modeled-partition\n"
            elif name.endswith("-boot-id"):
                raw = self.boot_id.encode("ascii") + b"\n"
            elif "-completed" in name:
                raw = b"1\n"
            elif name == "initial-battery":
                raw = b"MODELED battery\n  level: 80\n"
            elif name.startswith("capture-original-"):
                bank = name.split("capture-original-", 1)[1]
                raw = self.banks.get(bank, b"")
                if not raw:
                    rule = {"remote_rc": 1, **rule}
            elif name.endswith("-absent"):
                remote = command.split("test ! -e ", 1)[1].split(" &&", 1)[0]
                if remote in self.files:
                    rule = {"remote_rc": 1, **rule}
            elif name.startswith("stage-") and name.endswith("-size"):
                remote = command.split("stat -c %s ", 1)[1].split(";", 1)[0]
                raw = str(self.files[remote]["bytes"]).encode("ascii") + b"\n"
            elif name.startswith("stage-") and name.endswith("-hash"):
                remote = command.split("sha256sum ", 1)[1].split(";", 1)[0]
                raw = self.files[remote]["sha256"].encode("ascii") + b"  modeled-staging\n"
            elif name.endswith("-readback"):
                raw = self.boot_hash.encode("ascii") + b"  modeled-boot\n"
            elif name.endswith("-sync") or name == "capture-pstore-files":
                raw = b""
            else:
                raise AssertionError("Unhandled modeled root request: " + name)
        else:
            raise AssertionError("Unhandled modeled ADB request: " + repr(args))
        raw = rule.get("stdout", raw)
        if isinstance(raw, str):
            raw = raw.encode("ascii")
        transport_rc, remote_rc = rule.get("transport_rc", 0), rule.get("remote_rc", 0)
        if name.startswith("restore-baseline-") and name.endswith("-readback"):
            self.baseline_readback_ok = (not transport_rc and not remote_rc and
                raw.split()[:1] == [self.selected["rollback_pins"]["template"]["sha256"].encode("ascii")])
        output = raw
        if framed and rule.get("framing") != "missing":
            output += f"\nHAKIOS_REMOTE_EXIT:{remote_rc}\n".encode("ascii")
        if rule.get("framing") == "extra":
            output += b"unexpected trailing bytes"
        if rule.get("timeout"):
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"], output=output, stderr=b"MODELED timeout")
        return subprocess.CompletedProcess(argv, transport_rc, output, b"MODELED transport fixture\n")


def check_adaptation_model(folder, variant, accepted):
    """Indexed local source-history fixtures; never hardware evidence."""
    project = folder / "project"
    base_rel = "evidence/phase-4/platform-adaptation/20261114T010000000001Z"
    build_rel = "evidence/phase-4/platform-build/20261114T040000000001Z"
    base, build_packet = project / base_rel, project / build_rel
    base.mkdir(parents=True)
    build_packet.mkdir(parents=True)
    sources = {
        "hakios.a51.c": "static const unsigned short gpio_regs[] = {0x20, 0x24};\n"
                        "BANK(0x11850000, 0x1000, HAKIOS_A51_GPIO, gpio_regs)\n",
        "hakios.a51.h": "#define HAKIOS_A51_GPIO (1u << 0)\n",
        "hello.c": "/* MODEL ONLY: user ABI fixture */\n",
    }
    templates = project / "prototype/phase4-platform"
    templates.mkdir(parents=True)
    for name, source in sources.items():
        (templates / name).write_text(source, encoding="utf-8")
    current = {"packet": base_rel, "root": "/opt/a51-hakios/experimental/phase4-port/model-only",
               "applied": True, "device_operations": False, "phase_4_gate_passed": False,
               "source_pins": {name: pin(templates / name) for name in sources}}
    write_json(base / "result.json", current)
    index_packet(base)
    previous = base / "result.json"
    revision_paths = []
    if variant != "original":
        stamps = ("20261114T020000000001Z", "20261114T050000000001Z" if variant == "post-build" else "20261114T030000000001Z")
        for i, stamp in enumerate(stamps):
            rel = "evidence/phase-4/probe-build-correction/" + stamp
            packet = project / rel
            before = packet / "before/manifests/phase4-platform-adaptation.json"
            after = packet / "after/manifests/phase4-platform-adaptation.json"
            before.parent.mkdir(parents=True)
            after.parent.mkdir(parents=True)
            before.write_bytes(previous.read_bytes())
            (templates / "hakios.a51.c").write_text(sources["hakios.a51.c"] + f"/* MODEL revision {i + 1} */\n", encoding="utf-8")
            current["source_pins"]["hakios.a51.c"] = pin(templates / "hakios.a51.c")
            current.setdefault("revision_packets", []).append(rel)
            write_json(after, current)
            write_json(packet / "result.json", {"applied": True, "device_operations": False, "scope": "MODEL ONLY"})
            index_packet(packet)
            previous = after
            revision_paths.append(packet)
    manifests = project / "manifests"
    manifests.mkdir()
    if variant == "duplicate":
        current["revision_packets"].append(current["revision_packets"][-1])
    elif variant == "reordered":
        current["revision_packets"].reverse()
    elif variant == "omitted":
        current["revision_packets"].pop()
    elif variant == "current-drift":
        current["source_pins"]["hakios.a51.c"]["sha256"] = "0" * 64
    elif variant == "wrong-root":
        current["root"] = "/opt/another-project"
    elif variant == "broken-before":
        before = revision_paths[1] / "before/manifests/phase4-platform-adaptation.json"
        before.write_bytes(before.read_bytes() + b"\n")
        index_packet(revision_paths[1])
    elif variant == "broken-index":
        index = revision_paths[1] / "index.json"
        rows = json.loads(index.read_text(encoding="utf-8"))
        rows[0]["sha256"] = "0" * 64
        write_json(index, rows)
    elif variant == "missing-index":
        (revision_paths[1] / "index.json").unlink()
    elif variant == "source-drift":
        with (templates / "hakios.a51.c").open("ab") as stream:
            stream.write(b"/* unretained MODEL drift */\n")
    write_json(manifests / "phase4-platform-adaptation.json", current)
    build = {"packet": build_rel, "adaptation_packet": base_rel, "root": "/opt/a51-hakios/experimental/phase4-port/model-only",
             "build_verified": True, "device_operations": False, "scope": "MODEL ONLY"}
    write_json(build_packet / "result.json", build)
    index_packet(build_packet)
    if variant == "build-drift":
        build["root"] = "/opt/another-project"
    write_json(manifests / "phase4-platform-build.json", build)
    cmdline = "hakios_a51_probe=0" if variant == "invalid-mask" else "hakios_a51_probe=1"
    if variant == "duplicate-mask":
        cmdline += " hakios_a51_probe=1"
    selected = {"platform_build": {"path": "manifests/phase4-platform-build.json",
                **pin(manifests / "phase4-platform-build.json")}, "cmdline": cmdline}
    with mock.patch.object(cycle, "PROJECT", project):
        try:
            contract = cycle.snapshot_contract(selected)
        except (ValueError, FileNotFoundError) as exc:
            require(not accepted, "Valid indexed MODEL source history rejected: " + str(exc))
            write_json(folder / "validation.json", {"rejected": True, "error": str(exc), "scope": "MODEL ONLY"})
        else:
            require(accepted, "Invalid MODEL source history accepted")
            require(contract["registers"] == [{"pa": 0x11850020, "group": 1}, {"pa": 0x11850024, "group": 1}],
                    "Derived register contract differs from independent fixture")
            require(contract["built_adaptation"]["path"] == previous.relative_to(project).as_posix(),
                    "Wrong original/revised source provenance")
            write_json(folder / "validation.json", {"contract": contract, "scope": "MODEL ONLY"})


def main():
    packet = new_packet("device-cycle-tests", __file__)
    for name in (*cycle.SCRIPT_NAMES, "phase4-test-capture.py", "phase3-qemu-platform.py"):
        shutil.copy2(PROJECT / "scripts" / name, packet / name)
    root = packet / "models"
    root.mkdir()
    candidate, baseline = root / "candidate.model", root / "baseline.model"
    candidate.write_bytes(b"MODELED candidate: scaled host-only fixture; never a phone image\n")
    baseline.write_bytes(b"MODELED rollback: scaled host-only fixture; never a phone image\n")
    selected = {"kind": "watchdog", "nonce": NONCE, "candidate": {"path": "models/candidate.model", **pin(candidate)},
        "diagnostic": 2, "config": [0] * 18, "toc": [{"copy": 32, "zero": 16}], "layout": {"log_pa": 0x83f00000},
        "rollback_pins": {"template": pin(baseline), "recovery": {"bytes": 1024, "sha256": "a" * 64},
                          "dtbo": {"bytes": 1024, "sha256": "b" * 64}}}
    selected["config"][17] = 4096
    checks, errors = {}, {}

    def test(name, fn):
        folder = root / name
        folder.mkdir()
        try:
            with (folder / "modeled-output.log").open("w", encoding="utf-8") as output, contextlib.redirect_stdout(output):
                fn(folder)
            checks[name] = True
            print("MODEL PASS " + name, flush=True)
        except Exception as exc:
            checks[name] = False
            errors[name] = repr(exc)
            print("MODEL FAIL " + name + ": " + repr(exc), flush=True)

    def run_model(folder, *, rules=None, banks=None, changes=None, passed=False, untouched=False,
                  restored=False, rollback_failed=False, final_failed=False):
        selection = copy.deepcopy(selected)
        selection.update(changes or {})
        clock = VirtualClock()
        device = ModelDevice(folder, selection, rules=rules, banks=banks)
        runner = cycle.Cycle(folder, selection, candidate, baseline, device, seconds=60,
                             clock=clock.now, sleep=clock.sleep)
        runner.result.update(device_operations=False, hardware_evidence=False,
                             scope="MODEL ONLY; virtual clock and simulated transport; no real ADB process")
        with mock.patch.object(phase4_device.subprocess, "run", side_effect=device.run_command):
            result = runner.run()
        write_json(folder / "result.json", {**result, "device_operations": False, "scope": "MODEL ONLY; Cycle uses simulated transport"})
        write_json(folder / "modeled-events.json", device.events)
        require(result["passed"] is passed and result["phase_4_gate_passed"] is False, "Incorrect cycle/gate decision")
        require(all(any(fnmatch.fnmatchcase(event["name"], pattern) for event in device.events) for pattern in (rules or {})),
                "A requested failure model was never exercised")
        if untouched:
            require(not result["operations"]["boot_writes"] and not result["operations"]["reboots"], "Failure before write mutated boot")
        if restored:
            require(result["baseline_restored"] and result["baseline_verified"] and
                    device.boot_hash == selection["rollback_pins"]["template"]["sha256"] and not device.files,
                    "Verified restoration/cleanup missing")
        if rollback_failed:
            require("restoration_error" in result and not result["baseline_verified"] and
                    not any(row["name"] == "return-baseline-android" for row in device.events),
                    "Failed baseline verification allowed reboot/completion")
            require(len(result["restoration_attempts"]) == 2, "Rollback did not make both bounded attempts")
        if final_failed:
            require("restoration_error" in result and not result["baseline_verified"], "Final verification failure accepted")
        if result["operations"]["boot_writes"]:
            require(result["candidate_write_attempted"] and device.journal_checks > 0, "Write not journaled")
        return result, device, clock

    def basic(folder):
        run_model(folder, passed=True, restored=True)
    test("watchdog-success-and-intent-before-every-mutation", basic)
    for kind in ("reset", "fault", "full"):
        test(kind + "-success", lambda folder, kind=kind: run_model(folder, changes={"kind": kind,
             "diagnostic": {"reset": 1, "fault": 3}.get(kind, 0)}, passed=True, restored=True))

    def absent(folder):
        result, device, clock = run_model(folder, rules={"initial-state": {"stdout": ""}}, untouched=True)
        require(len(device.events) == 1 and clock.value == 0 and result["baseline_untouched"], "Absent phone caused polling or operations")
    test("absent-phone-returns-without-rollback-polling", absent)
    for name, key, raw in (
        ("wrong-model", "initial-model", "SM-A516F\n"),
        ("missing-root", "initial-root", "uid=2000(shell)\n"),
        ("wrong-boot-target", "initial-boot-target", "/dev/block/sda13\n"),
        ("wrong-boot-size", "initial-boot-size", "61865983\n"),
        ("initial-android-incomplete", "initial-completed", "0\n"),
        ("invalid-initial-uuid", "initial-boot-id", "invalid\n"),
        ("wrong-initial-boot-hash", "initial-hash-template", "0" * 64),
        ("wrong-initial-recovery-hash", "initial-hash-recovery", "0" * 64),
        ("wrong-initial-dtbo-size", "initial-size-dtbo", "1023\n"),
        ("insufficient-battery", "initial-battery", "level: 19\n"),
        ("missing-battery", "initial-battery", "unavailable\n")):
        test(name, lambda folder, key=key, raw=raw: run_model(folder, rules={key: {"stdout": raw}}, untouched=True))
    for name, key, rule in (
        ("partial-candidate-push", "stage-candidate", {"transport_rc": 1, "partial": True}),
        ("candidate-push-timeout", "stage-candidate", {"timeout": True, "partial": True}),
        ("staging-path-already-exists", "stage-candidate-absent", {"remote_rc": 1}),
        ("candidate-staged-size-mismatch", "stage-candidate-size", {"stdout": "1\n"}),
        ("candidate-staged-hash-mismatch", "stage-candidate-hash", {"stdout": "0" * 64}),
        ("candidate-staging-missing-frame", "stage-candidate-hash", {"framing": "missing"})):
        test(name, lambda folder, key=key, rule=rule: run_model(folder, rules={key: rule}, untouched=True))
    for name, key, rule in (
        ("partial-candidate-write-restores", "write-candidate", {"remote_rc": 1, "partial": True}),
        ("candidate-write-timeout-restores", "write-candidate", {"timeout": True, "partial": True}),
        ("candidate-write-missing-frame-restores", "write-candidate", {"framing": "missing", "partial": True}),
        ("candidate-sync-failure-restores", "write-candidate-sync", {"remote_rc": 1}),
        ("candidate-readback-mismatch-restores", "write-candidate-readback", {"stdout": "0" * 64})):
        test(name, lambda folder, key=key, rule=rule: run_model(folder, rules={key: rule}, restored=True))
    for reboot in ("boot-candidate", "return-baseline-android"):
        test(reboot + "-lost-acknowledgement", lambda folder, reboot=reboot: run_model(
            folder, rules={reboot: {"transport_rc": 1}}, passed=True, restored=True))
    test("candidate-never-enters-recovery", lambda folder: run_model(folder,
        rules={"boot-candidate": {"no_effect": True}}, restored=True))
    test("capture-root-unavailable", lambda folder: run_model(folder,
        rules={"capture-root": {"stdout": "uid=2000(shell)\n"}}, restored=True))
    test("stale-recovery-uuid", lambda folder: run_model(folder,
        rules={"capture-boot-id": {"stdout": BOOT_IDS[0]}}, restored=True))
    test("invalid-recovery-uuid", lambda folder: run_model(folder,
        rules={"capture-boot-id": {"stdout": "invalid"}}, restored=True))
    valid = envelope()
    for name, banks in (
        ("missing-envelope", {}),
        ("arbitrary-prefix-envelope", {bank: b"junk\n" + valid for bank in ("console", "pmsg")}),
        ("arbitrary-suffix-envelope", {bank: valid + b"junk\n" for bank in ("console", "pmsg")}),
        ("stale-nonce-envelope", {bank: valid.replace(NONCE.encode(), b"f" * 32) for bank in ("console", "pmsg")}),
        ("bad-envelope-crc", {bank: valid.replace(b"stage=3", b"stage=2", 1) for bank in ("console", "pmsg")}),
        ("conflicting-valid-banks", {"console": valid, "pmsg": envelope(wdt_after=4093)})):
        test(name, lambda folder, banks=banks: run_model(folder, banks=banks, restored=True))
    for framing, rule in (
        ("failed-remote-exit", {"remote_rc": 1}),
        ("missing-remote-exit", {"framing": "missing"}),
        ("trailing-remote-exit-data", {"framing": "extra"}),
        ("failed-transport-with-valid-body", {"transport_rc": 1}),
        ("timeout-with-valid-body", {"timeout": True})):
        test("valid-envelope-" + framing, lambda folder, rule=rule: run_model(folder,
             rules={"capture-original-*": rule}, restored=True))
    test("one-valid-bank-accepted", lambda folder: run_model(folder,
         banks={"console": b"missing", "pmsg": valid}, passed=True, restored=True))
    test("matching-banks-with-different-ecc-notices", lambda folder: run_model(folder,
         banks={"console": valid + b"\nNo errors detected\n", "pmsg": valid + b"\n2 Corrected bytes, 0 unrecoverable blocks\n"},
         passed=True, restored=True))
    for placement in (0x80278000, 0x800d0000):
        test("measured-runtime-" + hex(placement), lambda folder, placement=placement: run_model(folder,
             banks={bank: envelope(runtime_base=placement) for bank in ("console", "pmsg")},
             passed=True, restored=True))
    for name, changes in (
        ("wrong-entry-el", {"entry_el": 8}), ("mmu-enabled-at-entry", {"entry_sctlr": 1}),
        ("wrong-boot-cpu", {"midr": 0x410fd094}), ("wrong-core-affinity", {"mpidr": 1}),
        ("wrong-counter-frequency", {"cntfrq": 62500000}), ("wrong-runtime-placement", {"runtime_base": 0x81000000}),
        ("watchdog-not-counting-down", {"wdt_after": 4096}), ("watchdog-zero-count", {"wdt_after": 0}),
        ("diagnostic-copied-payload", {"copy_entries": 1}), ("wrong-diagnostic-code", {"code": 1})):
        test(name, lambda folder, changes=changes: run_model(folder,
             banks={bank: envelope(**changes) for bank in ("console", "pmsg")}, restored=True))
    for failure, suffix, rule in (
        ("push", "", {"transport_rc": 1, "partial": True}),
        ("staged-size", "-size", {"stdout": "1\n"}),
        ("staged-hash", "-hash", {"stdout": "0" * 64}),
        ("write", "", {"remote_rc": 1, "partial": True}),
        ("sync", "-sync", {"remote_rc": 1}),
        ("readback", "-readback", {"stdout": "0" * 64})):
        prefix = "stage-baseline-" if failure in ("push", "staged-size", "staged-hash") else "restore-baseline-"
        test("transient-rollback-" + failure, lambda folder, prefix=prefix, suffix=suffix, rule=rule:
             run_model(folder, rules={prefix + "0" + suffix: rule}, passed=True, restored=True))
        test("persistent-rollback-" + failure, lambda folder, prefix=prefix, suffix=suffix, rule=rule:
             run_model(folder, rules={prefix + "0" + suffix: rule, prefix + "1" + suffix: rule}, rollback_failed=True))
    test("rollback-target-root-failure", lambda folder: run_model(folder,
         rules={"restore-*-root": {"stdout": "uid=2000(shell)"}}, rollback_failed=True))
    test("rollback-target-model-failure", lambda folder: run_model(folder,
         rules={"restore-*-model": {"stdout": "SM-A516F"}}, rollback_failed=True))
    test("android-return-never-completes", lambda folder: run_model(folder,
         rules={"android-return-completed-*": {"stdout": "0"}}, final_failed=True))
    test("baseline-reboot-no-android-return", lambda folder: run_model(folder,
         rules={"return-baseline-android": {"no_effect": True}}, final_failed=True))
    for name, key, rule in (
        ("final-root-unavailable", "final-root", {"stdout": "uid=2000(shell)"}),
        ("final-android-incomplete", "final-completed", {"stdout": "0"}),
        ("final-uuid-stale-android", "final-boot-id", {"stdout": BOOT_IDS[0]}),
        ("final-uuid-stale-recovery", "final-boot-id", {"stdout": BOOT_IDS[1]}),
        ("final-uuid-invalid", "final-boot-id", {"stdout": "invalid"}),
        ("final-boot-hash-mismatch", "final-hash-template", {"stdout": "0" * 64}),
        ("final-recovery-hash-mismatch", "final-hash-recovery", {"stdout": "0" * 64}),
        ("final-dtbo-hash-mismatch", "final-hash-dtbo", {"stdout": "0" * 64}),
        ("final-staging-cleanup-failure", "remove-*-hakios-p4-" + NONCE + ".img", {"remote_rc": 1, "no_effect": True})):
        test(name, lambda folder, key=key, rule=rule: run_model(folder, rules={key: rule}, final_failed=True))
    test("transient-recovery-staging-cleanup-rechecked-in-android", lambda folder: run_model(folder,
        rules={"remove-00-hakios-p4-baseline-" + NONCE + "-0.img": {"remote_rc": 1}}, passed=True, restored=True))

    def ecc_check(folder, suffix, accepted):
        raw = valid + suffix
        (folder / "original.model").write_bytes(raw)
        try:
            decoded = decode_export(raw, NONCE)
        except ValueError:
            require(not accepted, "Valid ECC export was rejected")
        else:
            require(accepted and decoded["fields"]["nonce"] == NONCE, "Invalid ECC export was accepted")
    for name, suffix, accepted in (
        ("ecc-no-notice", b"", True), ("ecc-no-errors", b"\nNo errors detected\n", True),
        ("ecc-corrected-recoverable", b"\n7 Corrected bytes, 0 unrecoverable blocks\n", True),
        ("ecc-unrecoverable-blocks", b"\n7 Corrected bytes, 1 unrecoverable blocks\n", False),
        ("ecc-overflow-count", b"\n2147483648 Corrected bytes, 0 unrecoverable blocks\n", False),
        ("ecc-negative-count", b"\n-1 Corrected bytes, 0 unrecoverable blocks\n", False),
        ("ecc-notice-before-envelope", b"\nNo errors detected\n\njunk", False),
        ("ecc-arbitrary-suffix", b"\nNo errors detected\nX", False),
        ("ecc-missing-newline", b"\nNo errors detected", False),
        ("ecc-double-notice", b"\nNo errors detected\n\nNo errors detected\n", False)):
        test(name, lambda folder, suffix=suffix, accepted=accepted: ecc_check(folder, suffix, accepted))

    # An independent, explicit register fixture checks the hardware parser.
    contract = {"groups": 1, "bytes": 3096, "version": 1,
        "registers": [{"pa": 0x11850020, "group": 1}, {"pa": 0x11850024, "group": 1}],
        "banks": [{"pa": 0x11850000, "group": 1, "count": 2}]}
    snapshot = ("HAKIOS_A51_SNAPSHOT_SIZE rc=0 bytes=3096\n"
        "HAKIOS_A51_ABI small_rc=-12 write_rc=-1\n"
        "HAKIOS_A51_PROBE_BEGIN pa=0x11850000 group=0x1\n"
        "HAKIOS_A51_PROBE_DONE pa=0x11850000 count=2\n"
        "HAKIOS_A51_SNAPSHOT rc=0 version=1 count=2 groups=0x1 sequence=1 counter=26 pass=1\n"
        "HAKIOS_A51_REG index=0 pa=0x11850020 group=0x1 value=0x100\n"
        "HAKIOS_A51_REG index=1 pa=0x11850024 group=0x1 value=0x0\n"
        "HAKIOS_A51_SPI rc=-6 flags=0x0\nHAKIOS_A51_DIAG_PASS\n")
    for name, raw, accepted in (
        ("snapshot-hardware-markers", snapshot, True),
        ("snapshot-missing-markers", "", False),
        ("snapshot-wrong-mmio-address", snapshot.replace("pa=0x11850024", "pa=0x11850028"), False),
        ("snapshot-missing-register", snapshot.replace("HAKIOS_A51_REG index=1 pa=0x11850024 group=0x1 value=0x0\n", ""), False),
        ("snapshot-duplicate-register", snapshot + "HAKIOS_A51_REG index=1 pa=0x11850024 group=0x1 value=0x0\n", False),
        ("snapshot-unfinished-bank", snapshot.replace("HAKIOS_A51_PROBE_DONE pa=0x11850000 count=2\n", ""), False),
        ("snapshot-wrong-abi", snapshot.replace("small_rc=-12", "small_rc=0"), False),
        ("snapshot-synthetic-spi-rejected", snapshot.replace("HAKIOS_A51_SPI rc=-6 flags=0x0", "HAKIOS_A51_SPI rc=0 flags=0x1ff"), False),
        ("snapshot-zero-sequence", snapshot.replace("sequence=1", "sequence=0"), False),
        ("snapshot-overflow-register", snapshot.replace("value=0x100", "value=0x100000000"), False)):
        def check_snapshot(folder, raw=raw, accepted=accepted):
            selection = copy.deepcopy(selected)
            selection.update(kind="snapshot", diagnostic=0, snapshot_contract=contract)
            logged = user_log(raw)
            decoded = decode_export(envelope("snapshot", logged), NONCE)
            result = {"checks": {}, "return_seconds": 3}
            (folder / "original.model").write_bytes(envelope("snapshot", logged))
            try:
                cycle.validate_capture(decoded, selection, result)
            except ValueError:
                require(not accepted, "Valid modeled hardware markers were rejected")
            else:
                require(accepted, "Missing/corrupted hardware markers passed")
            write_json(folder / "validation.json", {**result, "scope": "MODEL ONLY"})
        test(name, check_snapshot)

    for variant in ("original", "revised", "duplicate", "reordered", "omitted", "post-build",
                    "current-drift", "wrong-root", "broken-before", "broken-index", "missing-index",
                    "source-drift", "build-drift", "invalid-mask", "duplicate-mask"):
        test("snapshot-source-history-" + variant,
             lambda folder, variant=variant: check_adaptation_model(folder, variant, variant in ("original", "revised")))

    passed = bool(checks) and all(checks.values())
    result = {"passed": passed, "tests": len(checks), "checks": checks, "errors": errors,
        "device_operations": False, "phase_4_gate_passed": False, "packet": packet.relative_to(PROJECT).as_posix(),
        "sources": {name: pin(PROJECT / "scripts" / name) for name in cycle.SCRIPT_NAMES},
        "test_source": pin(Path(__file__)),
        "scope": "Failure models with virtual clock, scaled local payloads and mocked subprocess.run; real Device framing and Cycle/validator code. No ADB process or device command was executed."}
    write_json(packet / "result.json", result)
    state = json.loads((PROJECT / "state.json").read_text(encoding="utf-8"))
    state["phase_4_device_cycle_tests"] = {"result": (packet / "result.json").relative_to(PROJECT).as_posix(),
                                          **pin(packet / "result.json"), "passed": passed, "tests": len(checks), "device_operations": False}
    state["phase_4_status"], state["phase_4_device_gate_passed"] = "in_progress", False
    note = f"\n\n## P4-020 — Device cycle and original pstore failure models ({packet.name})\n\nPurpose/files: scripts/phase4-test-device-cycle.py, phase4-device-cycle.py, phase4_pstore.py and the pinned framing/decoder sources. Exercise actual Device framing and the nonce-bound cycle with mocked subprocess.run and virtual time. Models cover pre-write identity, partial staging/writes, original/failed capture, conflicting banks, rollback retries/readback-before-reboot, final Android/root/UUID/partition/cleanup checks, exact ECC notices and real snapshot marker validation. Operation intent/progress must be durable before every modeled mutation.\n\nVerification: passed={passed}; tests={len(checks)}; errors={errors}. Original modeled commands/frames, assertions, progress/intent and outcomes are retained in `{result['packet']}`. Every fixture is a model, using scaled local bytes; no real ADB process, phone write/reboot or hardware gate occurred.\n\nLimitations/rollback: these tests validate host failure handling, not persistent record survival or drivers on the A51. Preserve failures, select the loader-correction packet's before bytes to undo code changes, then rebuild fresh model evidence and hardware candidates through scripts/run.py. Phase 4 remains incomplete.\n"
    documents(packet, {"state.json": json.dumps(state, indent=2) + "\n",
        "docs/IMPLEMENTATION-LOG.md": (PROJECT / "docs/IMPLEMENTATION-LOG.md").read_text(encoding="utf-8") + note})
    index_packet(packet)
    write_json(PROJECT / "manifests/phase4-device-cycle-tests.json", result)
    print(json.dumps({"passed": passed, "tests": len(checks), "errors": errors, "packet": result["packet"], "device_operations": False}), flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
