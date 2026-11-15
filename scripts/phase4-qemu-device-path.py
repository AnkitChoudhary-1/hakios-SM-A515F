#!/usr/bin/env python3
"""Run the complete Phase 4 loader, preserving exact destination readbacks."""
from __future__ import annotations
import argparse
import datetime as dt
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import time
from phase4_support import PROJECT, new_packet, command, write_json, pin, require, documents, index_packet
from phase4_envelope import decode

IMAGE_BASE, LEGACY_BASE, MEASURED_BASE = 0x80080000, 0x80278000, 0x800d0000
PLACEMENTS = (IMAGE_BASE, LEGACY_BASE, MEASURED_BASE)
ARENA_BASE, ARENA_LIMIT = 0x83000000, 0x847f0000
CASES = ("full", "copy", "reset", "watchdog", "fault", "early-fault", "empty-toc", "bad-count", "bad-schema",
         "source-overflow", "copy-overflow", "empty-segment", "overlap", "bad-crc", "bad-entry",
         "bad-bootargs", "bad-slot", "slot-magic", "bad-log", "bad-fdt", "fdt-reservation")


def write_input(path, raw):
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def mutate(raw, fdt, selected, case):
    cfg = selected["symbols"]["payload_config"] - IMAGE_BASE
    toc = selected["symbols"]["payload_toc"] - IMAGE_BASE
    payload = selected["symbols"]["payload_base"] - IMAGE_BASE
    error, reason = 0, {"full": 0, "copy": 7, "reset": 3, "watchdog": 3, "fault": 6, "early-fault": 6}.get(case, 4)
    def config(index, value):
        struct.pack_into("<Q", raw, cfg + index * 8, value)
    def entry(index, field, value):
        struct.pack_into("<Q", raw, toc + index * 48 + field * 8, value)
    if case in ("copy", "reset", "watchdog", "fault"):
        config(11, {"copy": 4, "reset": 1, "watchdog": 2, "fault": 3}[case])
        if case == "fault": error = 9
    elif case == "early-fault":
        # Replace the first cache-transition instruction in this retained test
        # Image only. The shipped loader has no artificial fault instruction.
        at = selected["symbols"]["loader_cache_transition"] - IMAGE_BASE
        require(64 <= at < selected["symbols"]["loader_vectors"] - IMAGE_BASE,
                "Early fault injection is outside the entry routine")
        struct.pack_into("<I", raw, at, 0xd4200000 | (0x354 << 5))
        error = 9
    elif case == "empty-toc": config(2, 0); error = 1
    elif case == "bad-count": config(2, 65); error = 1
    elif case == "bad-schema": config(1, 2); error = 1
    elif case == "source-overflow": entry(0, 0, (1 << 64) - 1); error = 3
    elif case == "copy-overflow": entry(0, 2, (1 << 64) - 1); entry(0, 3, 1); error = 3
    elif case == "empty-segment": entry(0, 2, 0); entry(0, 3, 0); error = 3
    elif case == "overlap": entry(1, 1, selected["toc"][0]["destination"]); error = 3
    elif case == "bad-crc": raw[payload + selected["toc"][0]["source"]] ^= 1; error = 4
    elif case == "bad-entry": config(6, selected["layout"]["kernel_limit"]); error = 2
    elif case == "bad-bootargs": config(7, ARENA_LIMIT - 8); error = 2
    elif case == "bad-slot": config(8, selected["layout"]["kernel_limit"] - 8); error = 2
    elif case == "bad-log": config(14, selected["layout"]["kernel_limit"] - 4); error = 2
    elif case == "slot-magic":
        import zlib
        slot = selected["layout"]["stub_slot_pa"]
        for i, t in enumerate(selected["toc"]):
            if t["destination"] <= slot and slot + 32 <= t["destination"] + t["copy"]:
                at = payload + t["source"]
                raw[at + slot - t["destination"]] ^= 1
                entry(i, 4, zlib.crc32(raw[at:at + t["copy"]]))
                break
        else: raise ValueError("Missing backed source slot for corruption test")
        error = 6
    elif case == "bad-fdt": fdt[0] ^= 1; error = 7
    elif case == "fdt-reservation":
        at = struct.unpack_from(">I", fdt, 16)[0]
        struct.pack_into(">QQ", fdt, at, ARENA_BASE, 4096)
        error = 7
    return error, reason


def run_case(selected, adapter, retainer, case, placement, seconds):
    packet = new_packet("complete-loader-qemu", __file__)
    work = Path("/opt/a51-hakios/experimental/phase4-loader-qemu") / packet.name
    work.mkdir(parents=True, exist_ok=False)
    records = []
    result = {"schema_version": 1, "packet": packet.relative_to(PROJECT).as_posix(), "work": str(work),
              "case": case, "load_address": placement, "nonce": selected["nonce"], "passed": False,
              "loader_build_packet": selected["packet"], "device_operations": False, "phase_4_gate_passed": False,
              "scope": "Complete carrier/C loader and XNU in QEMU; Exynos reset/watchdog MMIO excluded"}
    proc = qmp = serial = None
    started = time.monotonic()
    try:
        result["capacity_before"] = retainer.capacity()
        original = Path(selected["work"])
        for rel in ("loader.Image", "loader.elf", "payload.bin"):
            require(pin(original / rel) == selected["outputs"][rel], "Selected loader input changed: " + rel)
        for rel in ("phase4_envelope.py", "phase4-qemu-platform.py", "phase4-retain-qemu-scratch.py"):
            shutil.copy2(PROJECT / "scripts" / rel, packet / rel)
        shutil.copy2(PROJECT / "prototype/phase4-loader/qemu_firmware.S", packet / "firmware.S")
        write_json(packet / "selected-loader.json", selected)
        raw = bytearray((original / "loader.Image").read_bytes())
        original_fdt = PROJECT / "evidence/phase-4/live-inventory/20261114T162645749263Z/live-fdt.stdout.bin"
        result["original_fdt"] = {"path": original_fdt.relative_to(PROJECT).as_posix(), **pin(original_fdt)}
        fdt = bytearray(original_fdt.read_bytes())
        expected_error, expected_reason = mutate(raw, fdt, selected, case)
        write_input(work / "test.Image", raw)
        (packet / "incoming-fdt.dtb").write_bytes(fdt)
        result["executed_image"] = pin(work / "test.Image")
        # Prefill every byte of the fixed arena, including all gaps. A rejected
        # layout must leave all of it unchanged, rather than only a small canary.
        block = b"".join(hashlib.sha256(f"P4-A51-{i}".encode()).digest() for i in range(128))
        prefill = block * ((ARENA_LIMIT - ARENA_BASE) // len(block))
        require(len(prefill) == ARENA_LIMIT - ARENA_BASE, "Prefill extent")
        write_input(work / "arena-prefill.bin", prefill)
        (packet / "arena-prefill.bin.gz").write_bytes(gzip.compress(prefill, mtime=0))
        result["prefill"] = pin(work / "arena-prefill.bin")
        env = dict(os.environ, PATH="/usr/lib/llvm-18/bin:" + os.environ["PATH"])
        command(packet, records, "compile-firmware", ["clang", "--target=aarch64-none-elf", "-mcpu=cortex-a53",
            "-nostdlib", "-fuse-ld=lld", "-Wl,--build-id=none", "-Wl,-Ttext=0x40200000",
            "-DQEMU_IMAGE_BASE=" + hex(placement), "-DQEMU_ENTRY_ICACHE=" + str(int(case == "early-fault")),
            str(packet / "firmware.S"), "-o", str(work / "firmware.elf")], env=env)
        monitor = work / "monitor.sock"
        argv = ["qemu-system-aarch64", "-M", "virt,gic-version=2,secure=on,virtualization=on",
                "-cpu", "cortex-a53", "-smp", "1", "-m", "3G", "-accel", "tcg,tb-size=384",
                "-display", "none", "-serial", "stdio", "-monitor", "none", "-no-reboot",
                "-qmp", f"unix:{monitor},server=on,wait=off",
                "-device", f"loader,file={work / 'firmware.elf'},cpu-num=0",
                "-device", f"loader,file={work / 'test.Image'},addr={hex(placement)},force-raw=on",
                "-device", f"loader,file={packet / 'incoming-fdt.dtb'},addr=0x8a100000,force-raw=on",
                "-device", f"loader,file={work / 'arena-prefill.bin'},addr=0x83000000,force-raw=on"]
        result.update(qemu_argv=argv, qemu_started=dt.datetime.now(dt.timezone.utc).isoformat())
        write_json(packet / "launch.json", result)
        print(json.dumps({"qemu_case": case, "load_address": hex(placement), "packet": result["packet"]}), flush=True)
        serial = (packet / "serial.log").open("wb")
        proc = subprocess.Popen(argv, stdout=serial, stderr=subprocess.STDOUT, env=env)
        for _ in range(100):
            if monitor.exists(): break
            require(proc.poll() is None, "QEMU exited before QMP")
            time.sleep(0.05)
        qmp = adapter.Qmp(monitor)
        decoded = None
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            require(proc.poll() is None, "QEMU exited unexpectedly")
            qmp.save(0xf9d90000, 512 * 1024, work / "poll-console.bin")
            try:
                candidate = decode((work / "poll-console.bin").read_bytes(), selected["nonce"])
                if candidate["fields"]["reason"] == expected_reason:
                    decoded = candidate
                    break
            except ValueError: pass
            time.sleep(0.3)
        require(decoded is not None, "Complete loader envelope deadline expired")
        qmp.command("stop")
        for pa, name, size in ((0xf9d90000, "console.bin", 512 * 1024), (0xf9e90000, "pmsg.bin", 512 * 1024),
                              (selected["symbols"]["loader_context"] + placement - IMAGE_BASE, "context.bin", 256),
                              (selected["symbols"]["loader_fault_frame"] + placement - IMAGE_BASE, "fault-frame.bin", 320)):
            qmp.save(pa, size, packet / name)
        decoded = decode((packet / "console.bin").read_bytes(), selected["nonce"])
        mirror = decode((packet / "pmsg.bin").read_bytes(), selected["nonce"])
        context = struct.unpack("<32Q", (packet / "context.bin").read_bytes())
        fields = decoded["fields"]
        (packet / "kernel-user.log").write_bytes(decoded["log"])
        checks = {"nonce_payload_and_envelope_crc": True,
                  "console_and_pmsg_match": decoded["envelope_pin"] == mirror["envelope_pin"],
                  "supported_entry": fields["entry_el"] == 4 and fields["entry_sctlr"] & 5 == 0,
                  "runtime_placement": fields["runtime_base"] == context[22] == placement,
                  "expected_reason": fields["reason"] == expected_reason,
                  "expected_error": fields["error"] == expected_error,
                  "context_matches_envelope": (context[18], context[19], context[23], context[24], context[25], context[26]) ==
                     tuple(fields[k] for k in ("stage", "error", "copied_bytes", "zeroed_bytes", "copy_entries", "validated"))}
        if case == "full":
            record = [adapter.MAGIC, *context[:4], context[16], context[15], context[17], context[12]]
            user_checks, samples = adapter.validate(decoded["log"].decode("utf-8", errors="replace"), selected["nonce"], record)
            checks.update(user_checks)
            checks.update(complete_untruncated_log=decoded["complete_log"],
                exact_return_log_source=context[0] == selected["layout"]["log_pa"] and context[1] == fields["requested"],
                validated_before_copy=fields["validated"] == 1,
                all_copy_entries=fields["copy_entries"] == len(selected["toc"]),
                exact_copy_counters=fields["copied_bytes"] == sum(e["copy"] for e in selected["toc"]) and
                                    fields["zeroed_bytes"] == sum(e["zero"] for e in selected["toc"]),
                orderly_return=fields["stage"] == 5 and context[2:4] == (0, 0))
            result["timer_samples"] = samples
        else:
            qmp.save(ARENA_BASE, ARENA_LIMIT - ARENA_BASE, work / "arena-after.bin")
            actual = (work / "arena-after.bin").read_bytes()
            (packet / "arena-after.bin.gz").write_bytes(gzip.compress(actual, mtime=0))
            result["destination_readback"] = pin(work / "arena-after.bin")
            if case == "copy":
                expected = bytearray(prefill)
                payload = (original / "payload.bin").read_bytes()
                for t in selected["toc"]:
                    at = t["destination"] - ARENA_BASE
                    expected[at:at + t["copy"]] = payload[t["source"]:t["source"] + t["copy"]]
                    expected[at + t["copy"]:at + t["copy"] + t["zero"]] = bytes(t["zero"])
                slot = selected["layout"]["stub_slot_pa"] - ARENA_BASE
                struct.pack_into("<3Q", expected, slot + 8,
                    selected["symbols"]["loader_return_stub"] + placement - IMAGE_BASE,
                    selected["config"][10], selected["config"][9])
                checks.update(all_destination_bytes_match=actual == expected, validated_before_copy=fields["validated"] == 1,
                    all_copy_entries=fields["copy_entries"] == len(selected["toc"]),
                    exact_copy_counters=fields["copied_bytes"] == sum(e["copy"] for e in selected["toc"]) and
                        fields["zeroed_bytes"] == sum(e["zero"] for e in selected["toc"]), copy_stop=fields["stage"] == 4)
                (packet / "arena-expected.bin.gz").write_bytes(gzip.compress(expected, mtime=0))
            else:
                checks.update(whole_arena_unchanged=actual == prefill,
                    no_copy_entries=fields["copy_entries"] == fields["copied_bytes"] == fields["zeroed_bytes"] == 0)
                if case in ("reset", "watchdog"):
                    checks["diagnostic_reached"] = fields["stage"] == 3 and fields["validated"] == 1
                elif case in ("fault", "early-fault"):
                    frame = struct.unpack("<40Q", (packet / "fault-frame.bin").read_bytes())
                    checks["stackless_brk_capture"] = frame[0] == 0x34544c464f494b48 and frame[33] >> 26 == 0x3c
                    if case == "early-fault":
                        checks.update(
                            pretransition_fault_pc=frame[34] == selected["symbols"]["loader_cache_transition"] + placement - IMAGE_BASE,
                            initialized_physical_stack=frame[32] == selected["symbols"]["loader_stack_top"] + placement - IMAGE_BASE,
                            captured_original_entry_state=(frame[36] == fields["entry_sctlr"] and
                                fields["entry_sctlr"] & 0x1000 != 0 and frame[37] == fields["entry_el"] == 4),
                            saved_firmware_registers=(frame[19:26] == (0x8a100000, 4, fields["entry_daif"],
                                fields["entry_sctlr"], fields["cntfrq"], fields["midr"], fields["mpidr"])),
                            early_fault_before_validation=fields["stage"] == 1 and fields["validated"] == 0,
                            exact_injected_brk_iss=frame[33] & 0xffff == 0x354)
                else:
                    checks["rejection_before_validation_and_copy"] = fields["stage"] == 1 and fields["validated"] == 0
        result.update(fields=fields, checks=checks, context=list(context), log=decoded["log_pin"],
                      elapsed_seconds=round(time.monotonic() - started, 3), passed=all(checks.values()))
    except Exception as exc:
        result["error"] = str(exc)
        if qmp:
            try:
                qmp.command("stop")
                qmp.save(0xf9d90000, 512 * 1024, packet / "failed-console.bin")
                qmp.save(selected["symbols"]["loader_context"] + placement - IMAGE_BASE, 256, packet / "failed-context.bin")
                qmp.save(selected["layout"]["log_len_pa"], 4, packet / "failed-log-length.bin")
                n = struct.unpack("<I", (packet / "failed-log-length.bin").read_bytes())[0]
                if 0 < n <= 1536 * 1024: qmp.save(selected["layout"]["log_pa"], n, packet / "failed-kernel.log")
            except Exception as capture_error: result["capture_error"] = str(capture_error)
    finally:
        if qmp:
            try: qmp.command("quit")
            except Exception: pass
            qmp.file.close(); qmp.sock.close()
        if proc:
            if proc.poll() is None:
                try: proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.terminate()
                    try: proc.wait(timeout=5)
                    except subprocess.TimeoutExpired: proc.kill(); proc.wait(timeout=5)
            result["qemu_exit_code"] = proc.returncode
            result["qemu_finished"] = dt.datetime.now(dt.timezone.utc).isoformat()
        if serial: serial.close()
        result["execution_passed"] = result["passed"]
        if result["passed"]:
            try:
                require(result["qemu_exit_code"] == 0, "QEMU did not exit cleanly")
                retainer.retain_case(packet, result)
                result["scratch_retention"] = {"path": result["packet"] + "/scratch-retention.json",
                                                **pin(packet / "scratch-retention.json")}
            except Exception as retention_error:
                result.update(passed=False, error="Evidence retention failed: " + str(retention_error))
        write_json(packet / "result.json", result)
        index_packet(packet)
        print(json.dumps({k: result.get(k) for k in ("case", "load_address", "passed", "error", "elapsed_seconds", "checks")}), flush=True)
    return result


def main():
    if os.name == "nt":
        source = "/mnt/c" + str(Path(__file__).resolve()).replace("\\", "/")[2:]
        return subprocess.call(["wsl", "-d", "A51-KernelBuilder", "--exec", "python3", "-B", source, *sys.argv[1:]])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=(*CASES, "all"), default="full")
    parser.add_argument("--load-address", type=lambda s: int(s, 0), default=IMAGE_BASE)
    parser.add_argument("--seconds", type=int, default=120)
    args = parser.parse_args()
    require(args.load_address in PLACEMENTS and 15 <= args.seconds <= 300, "Invalid placement/deadline")
    selected = json.loads((PROJECT / "manifests/phase4-loader-qemu.json").read_text())
    require(selected["passed"] and selected["mode"] == "qemu" and selected["diagnostic"] == 0, "Wrong selected loader")
    spec = importlib.util.spec_from_file_location("phase4_qemu_platform", PROJECT / "scripts/phase4-qemu-platform.py")
    adapter = importlib.util.module_from_spec(spec); spec.loader.exec_module(adapter)
    spec = importlib.util.spec_from_file_location("phase4_qemu_retention", PROJECT / "scripts/phase4-retain-qemu-scratch.py")
    retainer = importlib.util.module_from_spec(spec); spec.loader.exec_module(retainer)
    results = []
    for placement in (PLACEMENTS if args.case == "all" else (args.load_address,)):
        for case in (CASES if args.case == "all" else (args.case,)):
            results.append(run_case(selected, adapter, retainer, case, placement, args.seconds))
            if not results[-1]["passed"]: break
        if not results[-1]["passed"]: break
    packet = new_packet("complete-loader-qemu-review", __file__)
    review = {"packet": packet.relative_to(PROJECT).as_posix(), "passed": all(r["passed"] for r in results),
              "suite_complete": args.case == "all" and len(results) == len(CASES) * len(PLACEMENTS) and all(r["passed"] for r in results),
              "results": [{"case": r["case"], "placement": r["load_address"], "passed": r["passed"],
                           "result": r["packet"] + "/result.json", **pin(PROJECT / r["packet"] / "result.json")} for r in results],
              "device_operations": False, "phase_4_gate_passed": False}
    write_json(packet / "result.json", review)
    write_json(PROJECT / "manifests/phase4-complete-loader-qemu.json", review)
    state = json.loads((PROJECT / "state.json").read_text(encoding="utf-8"))
    state["phase_4_complete_loader_qemu"] = {"result": review["packet"] + "/result.json",
             "passed": review["passed"], "suite_complete": review["suite_complete"]}
    note = f"\n\n## P4-018 — Complete-loader QEMU execution ({packet.name})\n\nPurpose/files: scripts/phase4-qemu-device-path.py, retained QEMU executions and review, selected manifest/state and this log. Execute the accepted carrier and C loader with actual XNU/PID 1/SPI/timers/return; check console/pmsg attribution and both CRCs. Prefill the entire 25,100,288-byte arena for exact readback after copy-only, diagnostic and malformed-payload cases. Exact compressed execution images and destination bytes are verified against the raw pins before releasing successful-case scratch; cleanup receipts retain the reconstruction paths. Failed cases retain raw scratch.\n\nVerification: passed={review['passed']}; suite_complete={review['suite_complete']}; cases={len(results)}. Per-case original logs, FDT, source selection, launch arguments, exits and destination bytes are in the pinned results listed in `{review['packet']}/result.json`. These are QEMU results only; the Exynos hardware reset/watchdog MMIO is excluded. No device operations or peripheral hardware gates occurred.\n\nLimitations/rollback: full hardware entry/persistence/watchdog/return and real display/input/UFS remain pending. Select the preserved Phase 3 loader or prior corrected source/artifacts; rerun through scripts/run.py and retain failures. Phase 4 remains incomplete.\n"
    documents(packet, {"state.json": json.dumps(state, indent=2) + "\n",
        "docs/IMPLEMENTATION-LOG.md": (PROJECT / "docs/IMPLEMENTATION-LOG.md").read_text(encoding="utf-8") + note})
    index_packet(packet)
    print(json.dumps({"review": review["packet"], "passed": review["passed"], "suite_complete": review["suite_complete"]}), flush=True)
    return 0 if review["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
