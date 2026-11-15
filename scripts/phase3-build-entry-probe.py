#!/usr/bin/env python3
"""Patch only measured padding/stext in the accepted Image and verify in QEMU."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import time
import uuid
from phase3_support import PROJECT, command, packet_new, packet_index, packet_verify, pin, json_write, update_documents, require
from phase3_entry_probe import decode
from samsung_boot_dry_run import reconstruct_in_memory


def branch(source, target):
    delta = target - source
    require(delta % 4 == 0 and -(1 << 27) <= delta < (1 << 27), "Branch displacement out of bounds")
    return struct.pack("<I", 0x14000000 | ((delta // 4) & 0x3ffffff))


def main():
    require(os.name == "posix", "Run in isolated A51-KernelBuilder WSL")
    packet = packet_new("entry-probe-build", Path(__file__))
    work = Path("/opt/a51-hakios/experimental/phase3-entry-probe") / packet.name
    work.mkdir(parents=True, exist_ok=False)
    original_result = PROJECT / "evidence/phase-2/early-entry-kernel/20261113T004224388744Z/result.json"
    build = json.loads(original_result.read_text())
    original = Path(build["build_directory"]) / "out/arch/arm64/boot/Image"
    require(pin(original) == {"bytes": 36334080, "sha256": "3054cfe40d06c17963575d6e067ced0c38f8e532bb490e49f828ae66b0e5c420"}, "Accepted Image changed")
    raw = bytearray(original.read_bytes())
    require(not any(raw[64:2048]), "Known header padding is no longer empty")
    stext = build["symbols"]["stext"] - build["symbols"]["_text"]
    continuation = build["symbols"]["hakios_early_entry"] - build["symbols"]["_text"]
    require(raw[stext:stext + 4] == branch(stext, continuation), "Original entry instruction differs")
    nonce = uuid.uuid4().hex
    source = PROJECT / "prototype/phase3-entry-probe/entry.S"
    shutil.copy2(source, packet / "entry.S")
    shutil.copy2(PROJECT / "scripts/phase3_entry_probe.py", packet / "phase3_entry_probe.py")
    helper_names = ("phase3_entry_probe.py", "phase3-device-entry-probe.py", "samsung_boot_dry_run.py", "phase3-package-loader.py")
    for name in helper_names:
        shutil.copy2(PROJECT / "scripts" / name, packet / name)
    (work / "probe.ld").write_text(f"ENTRY(probe_entry)\n__continue = {hex(0x80080000 + continuation)};\nSECTIONS {{ . = 0x80080040; .text : {{ *(.text) }} /DISCARD/ : {{ *(.comment) *(.note*) }} }}\n")
    records = []
    env = dict(os.environ, PATH="/usr/lib/llvm-18/bin:" + os.environ["PATH"])
    command(packet, records, "compile", ["clang", "--target=aarch64-none-elf", "-mcpu=cortex-a53", "-nostdlib", "-fuse-ld=lld",
        "-DNONCE_HI=0x" + nonce[:16], "-DNONCE_LO=0x" + nonce[16:], "-Wl,--build-id=none", "-Wl,-T," + str(work / "probe.ld"),
        str(packet / "entry.S"), "-o", str(work / "probe.elf")], env=env)
    command(packet, records, "objcopy", ["llvm-objcopy", "-O", "binary", str(work / "probe.elf"), str(work / "probe.bin")], env=env)
    nm = command(packet, records, "symbols", ["llvm-nm", "-n", str(work / "probe.elf")], env=env).stdout.decode()
    symbols = {t[2]: int(t[0], 16) for line in nm.splitlines() if len(t := line.split()) == 3}
    probe = (work / "probe.bin").read_bytes()
    require(len(probe) <= 1984 and symbols["probe_entry"] == 0x80080040, "Probe exceeds original padding")
    raw[64:64 + len(probe)] = probe
    raw[stext:stext + 4] = branch(stext, 64)
    require(raw[:64] == original.read_bytes()[:64], "Original Samsung header changed")
    image = work / "probe.Image"
    image.write_bytes(raw)
    result = {"packet": packet.relative_to(PROJECT).as_posix(), "nonce": nonce, "work": str(work),
              "scope": "Pre-Linux entry/pstore diagnostic, original Linux continues; no XNU gate claim",
              "original_result": pin(original_result), "original_image": pin(original), "image": pin(image),
              "source": pin(source), "helper_pins": {name: pin(PROJECT / "scripts" / name) for name in helper_names},
              "symbols": symbols, "stext_offset": stext, "continuation_offset": continuation, "probe_bytes": len(probe),
              "changed_spans": [[64, 64 + len(probe)], [stext, stext + 4]], "qemu": [], "passed": False,
              "device_operations": False, "phase_3_device_gate_passed": False}
    spec = importlib.util.spec_from_file_location("qemu_platform", PROJECT / "scripts/phase3-qemu-platform.py")
    platform = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(platform)
    firmware = (PROJECT / "prototype/phase3-loader/qemu_firmware.S").read_text()
    firmware = firmware.replace("    br x9", "    ldr x1, =0x80000000\n    ldr x2, =0x278000\n    ldr x3, =QEMU_IMAGE_BASE\n    br x9", 1)
    (packet / "firmware.S").write_text(firmware)
    for base in (0x80080000, 0x80278000):
        case = packet / hex(base)
        case.mkdir()
        command(packet, records, "firmware-" + hex(base), ["clang", "--target=aarch64-none-elf", "-mcpu=cortex-a53", "-nostdlib", "-fuse-ld=lld",
            "-Wl,--build-id=none", "-Wl,-Ttext=0x40200000", "-DQEMU_IMAGE_BASE=" + hex(base), str(packet / "firmware.S"), "-o", str(work / "firmware.elf")], env=env)
        monitor = work / "monitor.sock"
        if monitor.exists():
            monitor.unlink()
        argv = ["qemu-system-aarch64", "-M", "virt,gic-version=2,secure=on,virtualization=on", "-cpu", "cortex-a53", "-smp", "1", "-m", "3G", "-display", "none",
            "-serial", "none", "-monitor", "none", "-qmp", f"unix:{monitor},server=on,wait=off", "-no-reboot",
            "-device", f"loader,file={work / 'firmware.elf'},cpu-num=0", "-device", f"loader,file={image},addr={hex(base)},force-raw=on"]
        json_write(case / "launch.json", argv)
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        qmp = None
        try:
            for _ in range(100):
                if monitor.exists():
                    break
                require(proc.poll() is None, "QEMU stopped before probe")
                time.sleep(0.05)
            qmp = platform.Qmp(monitor)
            start = time.monotonic()
            fields = None
            while time.monotonic() - start < 15:
                qmp.save(0xf9d90000, 512 * 1024, work / "console.bin")
                try:
                    fields = decode((work / "console.bin").read_bytes(), nonce)
                    break
                except ValueError:
                    time.sleep(0.1)
            require(fields is not None, "QEMU entry record deadline")
            qmp.command("stop")
            qmp.save(0xf9d90000, 512 * 1024, case / "console.bin")
            qmp.save(0xf9e90000, 512 * 1024, case / "pmsg.bin")
            require(decode((case / "pmsg.bin").read_bytes(), nonce) == fields, "QEMU probe banks differ")
            require(fields["pc"] == base + 64 and fields["continuation"] == base + continuation and fields["x0"] == 0x8a100000 and fields["x3"] == base, "QEMU entry PC/arguments differ")
            item = {"base": base, "fields": fields, "passed": True}
            result["qemu"].append(item)
            json_write(case / "result.json", item)
        finally:
            if qmp:
                try:
                    qmp.command("quit")
                except Exception:
                    pass
            if proc.poll() is None:
                proc.terminate()
            stdout, stderr = proc.communicate(timeout=5)
            (case / "qemu.stdout").write_bytes(stdout)
            (case / "qemu.stderr").write_bytes(stderr)
    baseline = PROJECT.parent / "everline-ksu/artifacts/A51-PixelOS-Everline-KernelSU-Next-boot.img"
    require(pin(baseline) == {"bytes": 61865984, "sha256": "eb30609a62999e3282ac81e0a5e56411ef12ec1a39c107171bf3e01209c7cb67"}, "Baseline pin changed")
    candidate_bytes, reconstruction = reconstruct_in_memory(baseline.read_bytes(), bytes(raw))
    artifacts = PROJECT / "artifacts/phase-3/entry-probe" / packet.name
    artifacts.mkdir(parents=True, exist_ok=False)
    candidate = artifacts / "boot.img"
    candidate.write_bytes(candidate_bytes)
    result.update({"passed": True, "candidate": {"path": candidate.relative_to(PROJECT).as_posix(), **pin(candidate)}})
    json_write(packet / "reconstruction.json", reconstruction)
    json_write(packet / "result.json", result)
    json_write(PROJECT / "manifests/phase3-entry-probe.json", result)
    current = (PROJECT / "docs/STATE.md").read_text(encoding="utf-8")
    current += f"\n\nP3-023: complete-loader QEMU reset/full at observed `0x80278000` passed in packets 20261114T044111807678Z and 20261114T044111810089Z (full 12.761 seconds). The load discrepancy does not reproduce missing logs in QEMU. A new stackless pre-Linux diagnostic preserves the accepted Samsung Image header and patches only verified empty padding plus the original stext branch. It records nonce/CRC-bound measured registers to both pstore banks, then continues original Linux. Both placements passed QEMU. Selected probe `{result['packet']}` awaits phone execution; it does not launch XNU or qualify for Phase 3. Phase 3 remains 0/3; Phase 4 is authorized after its gate.\n"
    state = json.loads((PROJECT / "state.json").read_text())
    state["active_task"] = "phase_3_accepted_image_entry_persistence_probe"
    state["phase_3_continuation"]["entry_probe_build"] = result["packet"] + "/result.json"
    log = (PROJECT / "docs/IMPLEMENTATION-LOG.md").read_text(encoding="utf-8")
    log += f"\n\n### P3-023 — Execute observed-placement replay and prepare accepted-image entry/pstore probe\n\nPurpose/files: prototype/phase3-entry-probe/entry.S, scripts/phase3_entry_probe.py, scripts/phase3-build-entry-probe.py, scripts/phase3-device-entry-probe.py, docs/STATE.md, state.json and this log. Isolate the missing-entry/persistence cause by retaining the known accepted Image header and original Linux path. The stackless diagnostic changes only verified zero header padding and stext's first branch, preserves required arguments/callee state and masks, writes measured register records with fresh nonce and CRC to the two measured pstore banks, then branches to the original early entry. No original Android source/image is changed.\n\nVerification: observed-placement reset/full QEMU packets 20261114T044111807678Z and 20261114T044111810089Z passed, including actual PID 1, timers and return. New probe {result['packet']} passed at 0x80080000 and 0x80278000; original header byte equality, bounded patch extents, current nonce/CRC, both banks and PC/argument displacement checked. Original Image and baseline pins retained. Hardware entry/persistence awaits execution.\n\nLimitations/rollback: host replay cannot establish firmware acceptance or persistent hardware records. This diagnostic does not run XNU, test a hardware watchdog or count for Phase 3. Restore indexed document copies for bookkeeping; candidates are isolated and original sources stay untouched. After a phone attempt, use pinned baseline boot readback and fresh Android/root verification; never write recovery/DTBO/userdata. Preserve failed packets and retire the nonce. Phase 3 remains 0/3, Phase 4 continuation authorized.\n"
    update_documents(packet, {"docs/STATE.md": current, "state.json": json.dumps(state, indent=2) + "\n", "docs/IMPLEMENTATION-LOG.md": log})
    packet_index(packet)
    print(json.dumps({"packet": result["packet"], "nonce": nonce, "passed": True, "probe_bytes": len(probe)}, indent=2), flush=True)


if __name__ == "__main__":
    main()
