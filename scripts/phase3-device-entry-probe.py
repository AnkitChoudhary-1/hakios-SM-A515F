#!/usr/bin/env python3
"""Execute one accepted-Image entry probe, capture raw pstore and restore boot."""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import shlex
import shutil
import time
from phase3_support import PROJECT, command, packet_new, packet_index, packet_verify, pin, json_write, update_documents, require
from phase3_entry_probe import decode

spec = importlib.util.spec_from_file_location("package", PROJECT / "scripts/phase3-package-loader.py")
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)
SERIAL = "A51_SERIAL_HERE"
BOOT = "/dev/block/sda12"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=180)
    args = parser.parse_args()
    require(60 <= args.seconds <= 300, "Invalid boot deadline")
    selected = json.loads((PROJECT / "manifests/phase3-entry-probe.json").read_text(encoding="utf-8"))
    require(selected["passed"] and len(selected["qemu"]) == 2 and all(c["passed"] for c in selected["qemu"]), "Both QEMU placements must pass")
    require({c["base"] for c in selected["qemu"]} == {0x80080000, 0x80278000}, "Different placements tested")
    packet_verify(PROJECT / selected["packet"])
    require(pin(PROJECT / "prototype/phase3-entry-probe/entry.S") == selected["source"], "Probe source changed")
    for name, expected in selected["helper_pins"].items():
        require(pin(PROJECT / "scripts" / name) == expected, "Probe helper changed: " + name)
    candidate = PROJECT / selected["candidate"]["path"]
    require(pin(candidate) == {k: selected["candidate"][k] for k in ("bytes", "sha256")}, "Candidate pin mismatch")
    for path, expected in ((package.BASELINE, package.BOOT_PIN), (package.RECOVERY, package.RECOVERY_PIN), (package.DTBO, package.DTBO_PIN)):
        require(pin(path) == expected, "Rollback input changed")
    for path in (PROJECT / "evidence/phase-3/entry-probe-device").glob("*/selected-probe.json"):
        require(json.loads(path.read_text())["nonce"] != selected["nonce"], "Hardware probe nonce already used")
    packet = packet_new("entry-probe-device", Path(__file__))
    for name in ("phase3_entry_probe.py", "phase3-package-loader.py"):
        shutil.copy2(PROJECT / "scripts" / name, packet / name)
    json_write(packet / "selected-probe.json", selected)
    records = []
    result = {"packet": packet.relative_to(PROJECT).as_posix(), "nonce": selected["nonce"], "candidate": selected["candidate"],
              "checks": {}, "operations": {"device_reads": True, "file_writes": 0, "boot_writes": 0, "reboots": 0},
              "passed": False, "baseline_restored": False, "qualifying_run": False, "phase_3_device_gate_passed": False}
    installed = False
    staged = "/data/local/tmp/hakios-entry-" + selected["nonce"] + ".img"

    def adb(name, argv, **kw):
        return command(packet, records, name, ["adb", "-s", SERIAL, *argv], **kw)

    def mode(name):
        return adb(name, ["get-state"], timeout=8, check=False).stdout.decode("ascii", errors="replace").strip()

    def shell(name, text, recovery=False, **kw):
        argv = ["shell", text] if recovery else ["shell", "su", "-c", shlex.quote(text)]
        return adb(name, argv, **kw).stdout.decode("utf-8", errors="replace").strip()

    def wait_android(label, seconds, previous):
        start = time.monotonic()
        i = 0
        while time.monotonic() - start < seconds:
            current = mode(f"{label}-state-{i:03}")
            if current == "recovery":
                return current
            if current == "device":
                done = shell(f"{label}-completed-{i:03}", "getprop sys.boot_completed", check=False, timeout=10)
                boot = shell(f"{label}-boot-id-{i:03}", "cat /proc/sys/kernel/random/boot_id", check=False, timeout=10)
                if done == "1" and re.fullmatch(r"[0-9a-f-]{36}", boot) and boot != previous:
                    return current
            i += 1
            time.sleep(3)
        return "deadline"

    def capture(recovery):
        shell("capture-root", "id", recovery=recovery)
        shell("capture-boot-id", "cat /proc/sys/kernel/random/boot_id", recovery=recovery)
        shell("capture-pstore-files", "ls -ln /sys/fs/pstore", recovery=recovery, check=False)
        shell("capture-dmesg", "dmesg", recovery=recovery, check=False)
        found, errors = [], []
        for bank in ("console", "pmsg"):
            text = "test -r /sys/fs/pstore/" + bank + "-ramoops-0 && cat /sys/fs/pstore/" + bank + "-ramoops-0"
            argv = ["exec-out", "sh", "-c", text] if recovery else ["exec-out", "su", "-c", text]
            raw = adb("capture-original-" + bank, argv, check=False)
            (packet / (bank + ".original")).write_bytes(raw.stdout)
            try:
                require(raw.returncode == 0, "Original " + bank + " unavailable")
                fields = decode(raw.stdout, selected["nonce"])
            except ValueError as exc:
                errors.append(bank + ": " + str(exc))
                continue
            found.append((bank, fields))
        result["capture_diagnostics"] = errors
        require(found, "No current entry record: " + "; ".join(errors))
        fields = found[0][1]
        require(all(f == fields for _, f in found), "Valid entry records conflict")
        result["capture_banks"] = [b for b, _ in found]
        result["entry"] = fields
        result["checks"].update({"fresh_nonce_crc_footer": True, "entry_pc_matches_image": fields["pc"] == fields["x3"] + 64,
            "continuation_matches_image": fields["continuation"] == fields["x3"] + selected["continuation_offset"],
            "firmware_arguments_agree": fields["x3"] == fields["x1"] + fields["x2"],
            "el1_mmu_dcache_off": fields["entry_el"] == 4 and fields["sctlr"] & 5 == 0,
            "a53_26mhz": (fields["midr"] >> 4) & 0xfff == 0xd03 and fields["cntfrq"] == 26000000})

    try:
        require(mode("initial-state") == "device", "Boot-completed baseline Android required")
        require(shell("initial-root", "id").startswith("uid=0(root)"), "Android root unavailable")
        require(shell("initial-model", "getprop ro.product.model") == "SM-A515F", "Wrong phone")
        require(shell("initial-completed", "getprop sys.boot_completed") == "1", "Android boot incomplete")
        result["boot_id_before"] = shell("initial-boot-id", "cat /proc/sys/kernel/random/boot_id")
        require(shell("initial-boot-target", "readlink -f /dev/block/by-name/boot") == BOOT, "Wrong boot target")
        require(shell("initial-boot-size", "blockdev --getsize64 " + BOOT) == str(package.BOOT_PIN["bytes"]), "Wrong boot size")
        for name, target, expected in (("boot", BOOT, package.BOOT_PIN), ("recovery", "/dev/block/by-name/recovery", package.RECOVERY_PIN), ("dtbo", "/dev/block/by-name/dtbo", package.DTBO_PIN)):
            require(shell("initial-hash-" + name, "sha256sum " + target).split()[0] == expected["sha256"], "Device pin mismatch: " + name)
        battery = re.search(r"^\s*level:\s*(\d+)", shell("initial-battery", "dumpsys battery"), re.M)
        require(battery and int(battery[1]) >= 20, "Battery must be measured above 20 percent")
        print("Installing accepted-Image entry diagnostic; original Linux will continue.", flush=True)
        result["operations"]["file_writes"] += 1
        adb("stage-candidate", ["push", str(candidate), staged], timeout=120)
        require(shell("staged-candidate-hash", "sha256sum " + staged).split()[0] == selected["candidate"]["sha256"], "Staged candidate differs")
        installed = True
        result["operations"]["boot_writes"] += 1
        shell("write-candidate", "dd if=" + staged + " of=" + BOOT + " bs=4096 conv=fsync", timeout=90)
        shell("sync-candidate", "sync")
        require(shell("candidate-readback", "sha256sum " + BOOT).split()[0] == selected["candidate"]["sha256"], "Candidate readback differs")
        json_write(packet / "progress.json", result)
        result["operations"]["reboots"] += 1
        adb("boot-candidate", ["reboot"], timeout=20)
        started = time.monotonic()
        current = wait_android("probe-return", args.seconds, result["boot_id_before"])
        result["return_mode"] = current
        result["return_seconds"] = round(time.monotonic() - started, 3)
        if current in ("device", "recovery"):
            capture(current == "recovery")
        require(current == "device", "Probe failed to continue to completed Android")
        result["checks"]["fresh_android_continuation"] = True
    except Exception as exc:
        result["error"] = str(exc)
        print("Entry diagnostic failed: " + str(exc), flush=True)
    finally:
        try:
            current = mode("restore-state")
            if installed:
                deadline = time.monotonic() + 180
                i = 0
                while current not in ("device", "recovery") and time.monotonic() < deadline:
                    time.sleep(3)
                    current = mode(f"restore-wait-{i:03}")
                    i += 1
                require(current in ("device", "recovery"), "ADB unavailable for baseline restoration")
                recovery = current == "recovery"
                require(shell("restore-root", "id", recovery=recovery).startswith("uid=0(root)"), "Restoration root unavailable")
                require(shell("restore-target", "readlink -f /dev/block/by-name/boot", recovery=recovery) == BOOT, "Restoration target differs")
                previous = shell("restore-previous-boot", "cat /proc/sys/kernel/random/boot_id", recovery=recovery)
                rollback = ("/tmp/" if recovery else "/data/local/tmp/") + "hakios-entry-baseline-" + selected["nonce"] + ".img"
                result["operations"]["file_writes"] += 1
                adb("stage-baseline", ["push", str(package.BASELINE), rollback], timeout=120)
                require(shell("staged-baseline-hash", "sha256sum " + rollback, recovery=recovery).split()[0] == package.BOOT_PIN["sha256"], "Staged baseline differs")
                result["operations"]["boot_writes"] += 1
                shell("restore-baseline", "dd if=" + rollback + " of=" + BOOT + " bs=4096 conv=fsync", recovery=recovery, timeout=90)
                shell("restore-sync", "sync", recovery=recovery)
                require(shell("restore-readback", "sha256sum " + BOOT, recovery=recovery).split()[0] == package.BOOT_PIN["sha256"], "Restored readback differs")
                shell("remove-baseline-staging", "rm -f " + rollback, recovery=recovery)
                result["operations"]["reboots"] += 1
                adb("reboot-baseline", ["reboot"], timeout=20)
                require(wait_android("baseline-return", 240, previous) == "device", "Fresh baseline Android deadline")
            require(shell("final-root", "id").startswith("uid=0(root)"), "Final root unavailable")
            require(shell("final-boot-hash", "sha256sum " + BOOT).split()[0] == package.BOOT_PIN["sha256"], "Final baseline differs")
            result["boot_id_after"] = shell("final-boot-id", "cat /proc/sys/kernel/random/boot_id")
            shell("remove-candidate-staging", "rm -f " + staged)
            result["baseline_restored"] = True
            result["checks"]["baseline_readback_boot_root"] = True
        except Exception as exc:
            result["restoration_error"] = str(exc)
            print("Baseline restoration unverified: " + str(exc), flush=True)
        result["passed"] = bool(result["checks"]) and all(result["checks"].values()) and "error" not in result and result["baseline_restored"]
        json_write(packet / "result.json", result)
        json_write(PROJECT / "manifests/phase3-last-entry-probe.json", result)
        state = json.loads((PROJECT / "state.json").read_text(encoding="utf-8"))
        state["active_task"] = "phase_3_resolve_loader_entry_and_reset"
        cont = state["phase_3_continuation"]
        cont.update({"entry_probe_device": result["packet"] + "/result.json", "entry_probe_passed": result["passed"],
                     "baseline_restored": result["baseline_restored"]})
        if result["baseline_restored"]:
            cont["last_verified_android_boot_id"] = result["boot_id_after"]
        current = (PROJECT / "docs/STATE.md").read_text(encoding="utf-8")
        current += f"\n\nP3-024: accepted-Image entry diagnostic `{result['packet']}` {'PASSED' if result['passed'] else 'FAILED'}; baseline restoration {'verified' if result['baseline_restored'] else 'unverified'}. Original binary console/pmsg, entry records, command times and boot IDs are retained. This diagnostic continues Linux and never qualifies as XNU execution; Phase 3 remains 0/3.\n"
        log = (PROJECT / "docs/IMPLEMENTATION-LOG.md").read_text(encoding="utf-8")
        log += f"\n\n### P3-024 — Execute accepted-Image entry/pstore diagnostic and restore baseline\n\nPurpose/files: scripts/phase3-device-entry-probe.py, docs/STATE.md, state.json and this log. Selected build source/helpers, candidate, rollback pins and two QEMU placements are verified before the bounded phone cycle. Only boot is written; original binary pstore bytes, dmesg, boot IDs and all command timings remain in `{result['packet']}`.\n\nVerification: passed={result['passed']}; baseline_restored={result['baseline_restored']}; checks={json.dumps(result['checks'], sort_keys=True)}. Error={result.get('error', 'none')}; restoration_error={result.get('restoration_error', 'none')}. The used nonce is retired.\n\nLimitations/rollback: pre-Linux entry/persistence diagnostic only, no XNU execution or qualifying Phase 3 run. Boot restoration uses the pinned original image, partition readback and a fresh completed rooted Android boot. Recovery/DTBO/userdata are never written. Restore indexed before documents for bookkeeping only; preserve original binaries, sources and failed evidence. Phase 4 is authorized after the Phase 3 gate.\n"
        update_documents(packet, {"state.json": json.dumps(state, indent=2) + "\n", "docs/STATE.md": current, "docs/IMPLEMENTATION-LOG.md": log})
        packet_index(packet)
        print(json.dumps(result, indent=2), flush=True)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
