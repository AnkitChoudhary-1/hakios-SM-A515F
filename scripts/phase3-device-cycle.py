#!/usr/bin/env python3
"""Run one attributable A51 loader cycle, retain pstore, and restore baseline."""
from __future__ import annotations
import argparse
import importlib.util
import json
from pathlib import Path
import re
import shlex
import shutil
import time
from phase3_support import PROJECT, command, packet_new, packet_index, packet_verify, json_write, pin, require
from phase3_envelope import decode

spec = importlib.util.spec_from_file_location("phase3_package_loader", PROJECT / "scripts/phase3-package-loader.py")
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)
SERIAL = "A51_SERIAL_HERE"
BOOT = "/dev/block/sda12"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=("reset", "watchdog", "fault", "full"), required=True)
    parser.add_argument("--seconds", type=int, default=240)
    args = parser.parse_args()
    require(60 <= args.seconds <= 300, "Invalid device deadline")
    selected = json.loads((PROJECT / "manifests/phase3-bounded-candidate.json").read_text())
    loader = json.loads((PROJECT / "manifests/phase3-loader-hardware.json").read_text())
    diag = {"full": 0, "reset": 1, "watchdog": 2, "fault": 3}[args.case]
    require(selected["passed"] and selected["diagnostic"] == diag and selected["checkpoint"] == 0,
            "Wrong selected diagnostic candidate")
    require(loader["passed"] and loader["packet"] == selected["loader_build_packet"] and loader["nonce"] == selected["nonce"],
            "Candidate/loader selection mismatch")
    packet_verify(PROJECT / selected["packet"])
    candidate = PROJECT / selected["candidate"]["path"]
    require(pin(candidate) == {k: selected["candidate"][k] for k in ("bytes", "sha256")}, "Candidate pin mismatch")
    for path, expected in ((package.BASELINE, package.BOOT_PIN), (package.RECOVERY, package.RECOVERY_PIN),
                           (package.DTBO, package.DTBO_PIN)):
        require(pin(path) == expected, "Rollback input changed")
    for case in ("full", "reset", "fault", "bad-toc", "bad-fdt"):
        verified = json.loads((PROJECT / f"manifests/phase3-loader-qemu-{case}.json").read_text())
        require(verified["passed"], "Complete-loader QEMU prerequisite failed: " + case)
        packet_verify(PROJECT / verified["packet"])
        tested = json.loads((PROJECT / verified["packet"] / "selected-loader.json").read_text())
        require(tested["input_artifacts"] == loader["input_artifacts"], "QEMU tested different kernel/hello bytes")
        require(tested.get("entry_style", "standalone") == loader.get("entry_style", "standalone"), "QEMU tested a different entry envelope")
        if loader.get("entry_style") == "accepted-carrier":
            require(tested["carrier"] == loader["carrier"] and pin(PROJECT / "scripts/phase3_carrier.py") == loader["carrier"]["helper_pin"], "Carrier envelope/helper changed")
        for name in ("entry.S", "loader.c", "loader.ld", "loader.h", "fdt_guard.c", "fdt_guard.h"):
            require(tested["source_pins"][name] == loader["source_pins"][name], "Loader source changed after QEMU: " + name)
    previous = PROJECT / "evidence/phase-3/loader-device-cycle"
    for path in previous.glob("*/result.json"):
        old = json.loads(path.read_text())
        require(old.get("nonce") != selected["nonce"], "A hardware run nonce cannot be reused")
    packet = packet_new("loader-device-cycle", Path(__file__))
    for name in ("phase3_envelope.py", "phase3-package-loader.py", "phase3-qemu-platform.py"):
        shutil.copy2(PROJECT / "scripts" / name, packet / name)
    json_write(packet / "selected-candidate.json", selected)
    json_write(packet / "selected-loader.json", loader)
    records = []
    result = {"schema_version": 1, "packet": packet.relative_to(PROJECT).as_posix(), "case": args.case,
              "nonce": selected["nonce"], "candidate": selected["candidate"], "checks": {},
              "operations": {"device_reads": True, "file_writes": 0, "boot_writes": 0, "reboots": 0},
              "baseline_restored": False, "qualifying_run": False, "passed": False,
              "phase_3_device_gate_passed": False}
    installed = False
    capture_attempted = False
    staged = "/data/local/tmp/hakios-p3-" + selected["nonce"] + ".img"

    def adb(name, argv, **kwargs):
        return command(packet, records, name, ["adb", "-s", SERIAL, *argv], **kwargs)

    def mode(name):
        return adb(name, ["get-state"], timeout=8, check=False).stdout.strip().decode("ascii", errors="replace")

    def shell(name, text, recovery=False, **kwargs):
        argv = ["shell", text] if recovery else ["shell", "su", "-c", shlex.quote(text)]
        return adb(name, argv, **kwargs).stdout.decode("utf-8", errors="replace").strip()

    def wait_recovery(label, deadline):
        start = time.monotonic()
        for i in range(100):
            current = mode(f"{label}-{i:03}")
            if current == "recovery":
                return current
            if time.monotonic() - start >= deadline:
                return current
            time.sleep(3)
        return current

    def retain_console():
        nonlocal capture_attempted
        capture_attempted = True
        shell("capture-recovery-root", "id", recovery=True)
        shell("capture-recovery-boot-id", "cat /proc/sys/kernel/random/boot_id", recovery=True)
        shell("capture-pstore-files", "ls -ln /sys/fs/pstore", recovery=True, check=False)
        shell("capture-ramoops-parameters", 'for p in /sys/module/ramoops/parameters/*; do printf "%s=" "$p"; cat "$p"; done', recovery=True, check=False)
        shell("capture-recovery-attachment", "dmesg | grep -E 'persistent_ram:|ramoops:|pstore:'", recovery=True, check=False)
        decoded = None
        failures = []
        for bank in ("console", "pmsg"):
            captured = adb("capture-original-" + bank, ["exec-out", "sh", "-c",
                "test -r /sys/fs/pstore/" + bank + "-ramoops-0 && cat /sys/fs/pstore/" + bank + "-ramoops-0"], check=False)
            (packet / (bank + ".original")).write_bytes(captured.stdout)
            try:
                require(captured.returncode == 0 and captured.stdout.startswith(b"HAKIOS_P3_ENVELOPE_V1 "), "No original " + bank + " envelope")
                validated = decode(captured.stdout, selected["nonce"])
            except (ValueError, RuntimeError) as exc:
                failures.append(str(exc))
                continue
            # A conflict between two valid copies is fatal, outside the
            # missing/invalid-bank handler. Restoration still runs in finally.
            if decoded is None:
                decoded = validated
                result["capture_bank"] = bank
            else:
                require(decoded["fields"] == validated["fields"] and decoded["log"] == validated["log"], "Pstore copies disagree")
        result["capture_diagnostics"] = failures
        require(decoded is not None, "; ".join(failures))
        fields = decoded["fields"]
        result["envelope"] = fields
        result["original_log"] = decoded["log_pin"]
        (packet / "kernel-user.log").write_bytes(decoded["log"])
        (packet / "fault-diagnostic.log").write_bytes(decoded["diagnostic"])
        checks = result["checks"]
        checks.update({"fresh_nonce_crc_footer": True, "supported_entry": fields["entry_el"] == 4 and fields["entry_sctlr"] & 5 == 0,
                       "a53_boot_core": (fields["midr"] >> 4) & 0xfff == 0xd03,
                       "counter_26mhz": fields["cntfrq"] == 26000000,
                       "watchdog_counted_down": 0 < fields["wdt_after"] < fields["wdt_before"] <= 65535})
        if args.case in ("reset", "watchdog"):
            checks["expected_diagnostic"] = fields["stage"] == 3 and fields["error"] == 0 and fields["reason"] == 3 and fields["code"] == diag
        elif args.case == "fault":
            checks["stackless_fault"] = fields["error"] == 9 and fields["reason"] == 6 and fields["code"] >> 26 == 0x3c and b"HAKIOS_LOADER_FAULT" in decoded["diagnostic"]
        else:
            spec = importlib.util.spec_from_file_location("phase3_qemu_platform", PROJECT / "scripts/phase3-qemu-platform.py")
            checker = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(checker)
            record = [checker.MAGIC, loader["layout"]["log_pa"], fields["requested"], fields["reason"],
                      fields["code"], fields["midr"], fields["cntfrq"], fields["mpidr"], fields["entry_el"]]
            user_checks, samples = checker.validate(decoded["log"].decode("utf-8", errors="replace"), selected["nonce"], record)
            user_checks["counter_frequency"] = fields["cntfrq"] == 26000000
            checks.update(user_checks)
            checks["physical_return"] = fields["stage"] == 5 and fields["error"] == 0 and fields["reason"] == 0 and fields["code"] == 0
            checks["complete_untruncated_log"] = decoded["complete_log"]
            result["timer_samples"] = samples
            result["working_core"] = {"midr": hex(fields["midr"]), "mpidr": hex(fields["mpidr"]), "cores": 1}

    try:
        require(mode("initial-state") == "device", "Baseline Android is required before a cycle")
        require(shell("initial-root", "id").startswith("uid=0(root)"), "Android root unavailable")
        require(shell("initial-model", "getprop ro.product.model") == "SM-A515F", "Wrong phone model")
        require(shell("initial-completed", "getprop sys.boot_completed") == "1", "Android boot incomplete")
        result["boot_id_before"] = shell("initial-boot-id", "cat /proc/sys/kernel/random/boot_id")
        require(shell("initial-boot-target", "readlink -f /dev/block/by-name/boot") == BOOT, "Wrong boot target")
        require(shell("initial-boot-size", "blockdev --getsize64 " + BOOT) == str(package.BOOT_PIN["bytes"]), "Wrong boot size")
        for name, target, expected in (("boot", BOOT, package.BOOT_PIN), ("recovery", "/dev/block/by-name/recovery", package.RECOVERY_PIN),
                                       ("dtbo", "/dev/block/by-name/dtbo", package.DTBO_PIN)):
            require(shell("initial-hash-" + name, "sha256sum " + target).split()[0] == expected["sha256"], "Device pin mismatch: " + name)
        battery = shell("initial-battery", "dumpsys battery")
        found = re.search(r"^\s*level:\s*(\d+)", battery, re.M)
        require(found and int(found[1]) >= 20, "Battery level not verified above 20 percent")
        print("Pinned candidate/rollback verified; staging the " + args.case + " diagnostic.", flush=True)
        result["operations"]["file_writes"] += 1
        adb("stage-candidate", ["push", str(candidate), staged], timeout=120)
        require(shell("staged-candidate-hash", "sha256sum " + shlex.quote(staged)).split()[0] == selected["candidate"]["sha256"], "Staged candidate mismatch")
        installed = True  # A failed/partial write also requires restoration.
        result["operations"]["boot_writes"] += 1
        shell("write-candidate", "dd if=" + shlex.quote(staged) + " of=" + BOOT + " bs=4096 conv=fsync", timeout=90)
        shell("sync-candidate", "sync")
        require(shell("candidate-readback", "sha256sum " + BOOT).split()[0] == selected["candidate"]["sha256"], "Candidate partition readback mismatch")
        json_write(packet / "progress.json", result)
        result["operations"]["reboots"] += 1
        adb("boot-candidate", ["reboot"], timeout=20)
        time.sleep(3)
        started = time.monotonic()
        require(wait_recovery("candidate-return", args.seconds) == "recovery", "Candidate did not return to recovery before the deadline")
        result["return_seconds"] = round(time.monotonic() - started, 3)
        result["checks"]["recovery_reconnected"] = True
        retain_console()
    except Exception as exc:
        result["error"] = str(exc)
        print("Cycle evidence failed: " + str(exc), flush=True)
    finally:
        try:
            current = mode("restoration-state")
            if installed:
                if current not in ("device", "recovery"):
                    print("Waiting for the existing recovery to restore baseline.", flush=True)
                    current = wait_recovery("restoration-wait", 180)
                require(current in ("device", "recovery"), "ADB unavailable; pinned baseline restoration needs recovery")
                recovery = current == "recovery"
                if recovery and not capture_attempted:
                    try:
                        retain_console()
                    except Exception as exc:
                        result["capture_error"] = str(exc)
                require(shell("restore-root", "id", recovery=recovery).startswith("uid=0(root)"), "Restoration root unavailable")
                require(shell("restore-boot-target", "readlink -f /dev/block/by-name/boot", recovery=recovery) == BOOT, "Restoration target mismatch")
                rollback = ("/tmp/" if recovery else "/data/local/tmp/") + "hakios-p3-baseline-" + selected["nonce"] + ".img"
                result["operations"]["file_writes"] += 1
                adb("stage-baseline", ["push", str(package.BASELINE), rollback], timeout=120)
                require(shell("staged-baseline-hash", "sha256sum " + rollback, recovery=recovery).split()[0] == package.BOOT_PIN["sha256"], "Staged baseline mismatch")
                result["operations"]["boot_writes"] += 1
                shell("restore-baseline", "dd if=" + rollback + " of=" + BOOT + " bs=4096 conv=fsync", recovery=recovery, timeout=90)
                shell("restore-sync", "sync", recovery=recovery)
                require(shell("restored-readback", "sha256sum " + BOOT, recovery=recovery).split()[0] == package.BOOT_PIN["sha256"], "Restored readback mismatch")
                shell("remove-rollback-staging", "rm -f " + rollback, recovery=recovery)
                result["operations"]["reboots"] += 1
                adb("return-baseline-android", ["reboot"], timeout=20)
                time.sleep(5)
            for i in range(80):
                if mode(f"android-return-{i:03}") == "device" and shell(f"android-completed-{i:03}", "getprop sys.boot_completed", check=False, timeout=10) == "1":
                    break
                time.sleep(3)
            else:
                raise RuntimeError("Baseline Android boot deadline expired")
            require(shell("final-root", "id").startswith("uid=0(root)"), "Baseline root unverified")
            require(shell("final-boot-hash", "sha256sum " + BOOT).split()[0] == package.BOOT_PIN["sha256"], "Final baseline pin mismatch")
            result["boot_id_after"] = shell("final-boot-id", "cat /proc/sys/kernel/random/boot_id")
            if installed:
                require(result["boot_id_after"] != result["boot_id_before"], "Fresh baseline reboot unverified")
            shell("remove-candidate-staging", "rm -f " + staged)
            result["baseline_restored"] = True
            result["checks"]["baseline_readback_boot_root"] = True
        except Exception as exc:
            result["restoration_error"] = str(exc)
            print("Baseline restoration unverified: " + str(exc), flush=True)
        result["passed"] = bool(result["checks"]) and all(result["checks"].values()) and result["baseline_restored"] and "error" not in result
        result["qualifying_run"] = args.case == "full" and result["passed"]
        json_write(packet / "result.json", result)
        packet_index(packet)
        json_write(PROJECT / "manifests/phase3-last-device-cycle.json", result)
        print(json.dumps({k: result[k] for k in ("packet", "case", "passed", "qualifying_run", "baseline_restored", "checks", "error", "restoration_error") if k in result}, indent=2), flush=True)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
