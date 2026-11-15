#!/usr/bin/env python3
"""Record the current Phase 4 loader evidence, handoff and recovery guide."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from phase4_support import PROJECT, documents, index_packet, new_packet, pin, require, write_json


def read(relative):
    return json.loads((PROJECT / relative).read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--connection-run", required=True)
    args = parser.parse_args()
    inventory_path = (PROJECT / args.inventory).resolve()
    require(inventory_path.is_relative_to((PROJECT / "evidence/phase-4/live-inventory").resolve()), "Wrong inventory root")
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    require(inventory["inventory_valid"] and inventory["checks"]["baseline"] and
            inventory["checks"]["root"] and inventory["checks"]["same_android_boot"], "Fresh inventory failed")
    connection = read("runs/" + args.connection_run + "/metadata.json")
    require(connection["status"] == "passed" and connection["command"] == ["adb", "devices", "-l"], "Wrong connection evidence")
    require("A51_SERIAL_HERE" in (PROJECT / "runs" / args.connection_run / "output.log").read_text(encoding="utf-8"), "Target absent from connection evidence")
    candidates = {kind: read("manifests/phase4-candidate-" + kind + ".json") for kind in ("watchdog", "full", "snapshot")}
    preflights = {}
    for kind, candidate in candidates.items():
        require(candidate["schema_version"] == 2 and candidate["mode"] == "hardware" and candidate["built"], "Wrong candidate")
        found = []
        for result_path in sorted((PROJECT / "evidence/phase-4/device-preflight").glob("*/result.json")):
            result = json.loads(result_path.read_text(encoding="utf-8"))
            if (result.get("case") == kind and result.get("nonce") == candidate["nonce"] and
                    result.get("passed") and result.get("host_prerequisites_passed") and
                    result.get("device_operations") is False and
                    pin(result_path.parent / "source.py") == pin(PROJECT / "scripts/phase4-device-cycle.py")):
                found.append(result_path)
        require(found, "No current passing preflight: " + kind)
        preflights[kind] = {"result": found[-1].relative_to(PROJECT).as_posix(), **pin(found[-1]), "passed": True,
                            "device_operations": False, "nonce": candidate["nonce"]}
    native = read("manifests/phase4-loader-native-tests.json")
    qemu = read("manifests/phase4-complete-loader-qemu.json")
    models = read("manifests/phase4-device-cycle-tests.json")
    require(native["passed"] and native["native_checks"] == 4110 and native["envelope_checks"] == 106, "Native evidence changed")
    require(qemu["passed"] and qemu["suite_complete"] and len(qemu["results"]) == 40, "Incomplete QEMU evidence")
    require(models["passed"] and models["tests"] == 117 and models["device_operations"] is False, "Cycle evidence changed")
    packet = new_packet("device-path-documentation", __file__)
    inventory_rel = inventory_path.relative_to(PROJECT).as_posix()
    boot_id = (inventory_path.parent / "boot-id-after.stdout.bin").read_text(encoding="utf-8").strip()
    table = "\n".join("| " + kind + " | `" + candidate["packet"].rsplit("/", 1)[-1] + "` | `" +
                      candidate["candidate"]["sha256"] + "` | `" + candidate["nonce"] + "` |"
                      for kind, candidate in candidates.items())
    preflight_table = "\n".join("| " + kind + " | `" + row["result"] + "` | passed; host only |"
                                for kind, row in preflights.items())
    guide = r"""# Phase 4 device path, evidence and recovery

Phase 4 remains **IN PROGRESS** and its peripheral hardware gate remains **UNPASSED**. This guide records the corrected C loader and original-record capture path. Display, DSIM brightness, physical MSS100 touch, physical power/volume events, UFS DMA reads, larger-image loading and rejection of writes in the real storage submission path still require implementation and A51 evidence. Passive MMIO snapshots are prerequisites; eight GPIO register reads do not establish key events.

## Implementation and provenance

Work remains in `C:\Users\Ankit\Desktop\A51\hakios-a51` and `/opt/a51-hakios` in WSL distribution `A51-KernelBuilder`. Use `wsl -d A51-KernelBuilder --exec`; preserve the separate Android projects and the original Phase 3 tree. The Phase 4 platform tree is `/opt/a51-hakios/experimental/phase4-port/20261114T150320411427Z`; the preserved Phase 3 tree is `/opt/a51-hakios/experimental/phase3-port/20261114T013656044425Z`.

Successful full Phase 3 phone runs used the historical assembly through `scripts/build-xnu-boot-candidate.py` and `prototype/xnu-loader/pack_a51_payload.py`. The Phase 3 C loader has full QEMU execution and phone entry diagnostics; successful full C-loader XNU phone runs have not been established. The corrected Phase 4 path adapts that C loader. Historical `prototype/phase4-loader/a51_loader.S`, `recovery.S` and `return.S` remain retained references; the current builder compiles `entry.S`, `loader.c`, `validate.c` and `fdt_guard.c`, generated payload assembly and the carrier. Do not infer hardware success from the older assembly's results.

The accepted Samsung carrier keeps the measured 64-byte Image header and `stext` entry, including the vendor sentinel and original BSS-inclusive Image extent. The on-disk source slot is separately bounded to 36,334,080 bytes. QEMU covers placements `0x80080000` and `0x80278000`; neither host result establishes a current device placement. The loader validates entry state, every CRC, TOC count/schema, source/destination/zero ranges, configuration, BootArgs, return-slot and FDT reservations before payload copies. The initial RAM budget is 112 MiB; the arena is `[0x83000000,0x847f0000)`. Panic RAM is relocated and zeroed. BootVideo is deliberately zero/unavailable until measured scanout is established.

The selected platform build is `evidence/phase-4/platform-build/20261114T160328915812Z/result.json`: kernel SHA-256 `4b6232f6076c0ca12576f1328abee1785e3cb84853100e62049b86cd1676de43`, user program SHA-256 `b624c4a858fd218e19ccc2aaf263763245439e952964c0e56de1b5dfb15d7a70`. The source revision chain is original adaptation `20261114T154338406253Z`, probe correction `20261114T155443230088Z`, then SPI correction `20261114T160314417746Z`. Its final manifest SHA-256 is `904d8fc3c88e50e380112ed2a73e57fbae73e24ff95ed6d0e75f88f98ee4e448`. Snapshot preflight verifies indexed byte-exact before/after revisions, identities, order and build time, then matches the current templates to the final pins. The original FDT identifies the CPU GIC at `0x12301000`/`0x12302000`; the audio GIC at `0x14af1000`/`0x14af2000` cannot substitute for it.

## Selected evidence

Host evidence is retained at:

- Native ASan/UBSan: `evidence/phase-4/loader-native-tests/20261114T172736468080Z`, 4,110 validator checks and 106 envelope checks.
- Complete loader: `evidence/phase-4/complete-loader-qemu-review/20261114T175503291469Z`, all 40 cases passed, including actual XNU/PID 1/timers/SPI/physical return in QEMU. The selection uses `results`, not `cases`.
- Capture/cycle/source-history models: `evidence/phase-4/device-cycle-tests/20261114T182713063143Z`, all 117 models passed. These mock transport, filesystem history and time; `device_operations=false`. They do not establish hardware persistence or restoration.
- Every accepted QEMU execution image, arena prefill and required destination readback is retained in verified gzip archives. Each `scratch-retention.json` gives the exact reconstruction path and raw pin. Decompress to that isolated path and verify size/SHA-256 before reuse. Failed scratch, attempts and original indexes remain preserved.

Current complete hardware packages are 61,865,984 bytes each. Their nonces were unused when this guide was recorded; consult `evidence/phase-4/device-cycle/*/result.json` before reuse. A nonce is single-use even after a failed trial; rebuild a fresh package.

| Kind | Build packet | Candidate SHA-256 | Nonce |
|---|---|---|---|
@@CANDIDATES@@

| Kind | Current preflight result | Scope |
|---|---|---|
@@PREFLIGHTS@@

The reconnected Android inventory is `@@INVENTORY@@`; root, boot completion, model, unchanged Android UUID, pinned boot hash and independently retained first 1 MiB passed. Android boot UUID was `@@BOOT_ID@@`. UFS LUN 0 exposes 4096-byte blocks and the boot partition starts at absolute LBA 27792. These observations are Android evidence. GPIO debugfs remains unavailable. Connection run: `@@CONNECTION@@`. Recovery and DTBO are freshly checked by the cycle before any candidate write.

## Original persistent records and bounded trial

`scripts/phase4_device.py` retains exact stdout/stderr, command arguments, times, transport exit and mandatory `HAKIOS_REMOTE_EXIT` framing. A missing/nonzero remote exit cannot produce successful acquisition. The standalone loader commits console and pmsg banks at `0xf9d90000` and `0xf9e90000`, 512 KiB each, using the measured 12-byte `DBGC` header. Data is published before the completed header.

`scripts/phase4_pstore.py` reads the original recovery exports once per bank without scanning for a marker or discarding prefixes. It checks the exact candidate nonce, payload CRC and entire-envelope CRC. One valid bank can establish capture; two valid banks must match byte-for-byte and in their decoded fields. Conflicting valid banks are fatal. Only the exact upstream optional ECC notice is accepted, with bounded corrected-byte counts and zero unrecoverable blocks. Arbitrary suffixes, stale attribution, truncation and damaged checksums are rejected. Original frames and exports are retained even on failures.

The older `scripts/phase4_capture.py` and `manifests/phase4-log-reader.json` describe incompatible pre-correction formats. Their original module build is historical evidence, not a current reader. Do not load it or run the disabled `scripts/phase4-device-gate.py`.

The cycle requires the current matching hardware package, unchanged source pins, all 40 exact QEMU archives and passed native/capture/cycle evidence. Before staging it verifies root, SM-A515F, `/dev/block/sda12`, partition size, completed Android boot, UUID, baseline/recovery/DTBO pins and battery at least 20%. It journals durable intent/progress before staging, boot writes and reboots. The candidate and baseline staging files are unique and hash checked. A partial candidate write still triggers restoration.

After the bounded recovery wait, original nonce-bound evidence is checked. Restoration has at most two bounded attempts. It verifies recovery identity, stages the pinned baseline and checks the boot readback **before rebooting**. Final success requires completed Android with root, a fresh UUID, pinned boot/recovery/DTBO hashes and all staging files absent. A restoration failure stays a failure even if capture succeeded. If boot readback is unverified, preserve staging and use the independent procedure below; do not reboot that image. Source-built watchdog masks/clock/reset and ACPM behavior remain unverified until hardware execution. The watchdog trial deliberately waits without a direct PMU reset; a decremented counter alone cannot prove reset.

## Exact rebuild and execution commands

Run from `C:\Users\Ankit\Desktop\A51\hakios-a51`. Every consequential command goes through `scripts/run.py`; the wrapper also retains the exact script revisions. These commands rebuild new nonces and overwrite current selections while preserving older packets.

```powershell
python scripts/run.py --label p4-loader-native -- python -B scripts/phase4-test-loader.py
python scripts/run.py --label p4-cycle-models -- python -B scripts/phase4-test-device-cycle.py
python scripts/run.py --label p4-qemu-package -- python -B scripts/phase4-build-device-path.py --mode qemu --kind full
python scripts/run.py --label p4-loader-forty-cases -- python -B scripts/phase4-qemu-device-path.py --case all
python scripts/run.py --label p4-watchdog-package -- python -B scripts/phase4-build-device-path.py --mode hardware --kind watchdog
python scripts/run.py --label p4-full-package -- python -B scripts/phase4-build-device-path.py --mode hardware --kind full
python scripts/run.py --label p4-snapshot-package -- python -B scripts/phase4-build-device-path.py --mode hardware --kind snapshot --probe 1
python scripts/run.py --label p4-watchdog-preflight -- python -B scripts/phase4-device-cycle.py --kind watchdog --preflight-only
python scripts/run.py --label p4-full-preflight -- python -B scripts/phase4-device-cycle.py --kind full --preflight-only
python scripts/run.py --label p4-snapshot-preflight -- python -B scripts/phase4-device-cycle.py --kind snapshot --preflight-only
python scripts/run.py --label p4-current-inventory -- python -B scripts/phase4-inventory.py
```

Do not repeat unchanged host suites solely because a hardware trial is pending. Once fresh baseline/root and the matching host prerequisites pass, perform the watchdog trial first. Require verified restoration and original evidence before the full-loader trial; require full-loader execution before a passive snapshot. These trials are prerequisites and do not pass the peripheral gate.

```powershell
python scripts/run.py --label p4-watchdog-hardware -- python -B scripts/phase4-device-cycle.py --kind watchdog --seconds 240
python scripts/run.py --label p4-full-hardware -- python -B scripts/phase4-device-cycle.py --kind full --seconds 240
python scripts/run.py --label p4-snapshot-hardware -- python -B scripts/phase4-device-cycle.py --kind snapshot --seconds 240
```

## Independent pinned-baseline recovery

This procedure does not depend on the candidate loader or cycle script. Use the existing rooted recovery ADB connection on serial `A51_SERIAL_HERE`. When the phone is absent, physically enter the preserved recovery and reconnect USB; do not attempt repeated blind writes. Perform at most two recovery write attempts and keep every log. Do not touch recovery, DTBO, partition tables or userdata.

Pinned input: `C:\Users\Ankit\Desktop\A51\everline-ksu\artifacts\A51-PixelOS-Everline-KernelSU-Next-boot.img`, 61,865,984 bytes, SHA-256 `eb30609a62999e3282ac81e0a5e56411ef12ec1a39c107171bf3e01209c7cb67`. Recovery is SHA-256 `12412e2008d950260cda627ac7a6b8eac954b49ef9db5573a297f67e4fc85999`; DTBO is SHA-256 `41662c61ff3158448935025477a4e29d445823dab2cddafb18ea649c8ea925d6`.

Verify the host size/hash first. Then require, in order, recovery ADB mode, root UID 0, exact model SM-A515F, boot link `/dev/block/sda12`, boot size 61865984 and unchanged recovery/DTBO hashes. Review each output; stop at any failure. Direct `adb shell` commands below are for rooted recovery.

```powershell
python scripts/run.py --label p4-baseline-host-pin -- python -B -c "import pathlib,hashlib; b=pathlib.Path(r'C:\Users\Ankit\Desktop\A51\everline-ksu\artifacts\A51-PixelOS-Everline-KernelSU-Next-boot.img').read_bytes(); assert len(b)==61865984 and hashlib.sha256(b).hexdigest()=='eb30609a62999e3282ac81e0a5e56411ef12ec1a39c107171bf3e01209c7cb67'; print(len(b),hashlib.sha256(b).hexdigest())"
python scripts/run.py --label p4-recovery-state -- adb -s A51_SERIAL_HERE get-state
python scripts/run.py --label p4-recovery-root -- adb -s A51_SERIAL_HERE shell id
python scripts/run.py --label p4-recovery-model -- adb -s A51_SERIAL_HERE shell getprop ro.product.model
python scripts/run.py --label p4-recovery-target -- adb -s A51_SERIAL_HERE shell readlink -f /dev/block/by-name/boot
python scripts/run.py --label p4-recovery-size -- adb -s A51_SERIAL_HERE shell blockdev --getsize64 /dev/block/sda12
python scripts/run.py --label p4-recovery-preserved-pins -- adb -s A51_SERIAL_HERE shell sha256sum /dev/block/by-name/recovery /dev/block/by-name/dtbo
python scripts/run.py --label p4-recovery-stage-absent -- adb -s A51_SERIAL_HERE shell "test ! -e /tmp/hakios-p4-baseline-manual-restore.img && test ! -L /tmp/hakios-p4-baseline-manual-restore.img"
python scripts/run.py --label p4-recovery-push-baseline -- adb -s A51_SERIAL_HERE push C:/Users/Ankit/Desktop/A51/everline-ksu/artifacts/A51-PixelOS-Everline-KernelSU-Next-boot.img /tmp/hakios-p4-baseline-manual-restore.img
python scripts/run.py --label p4-recovery-staged-size -- adb -s A51_SERIAL_HERE shell stat -c %s /tmp/hakios-p4-baseline-manual-restore.img
python scripts/run.py --label p4-recovery-staged-hash -- adb -s A51_SERIAL_HERE shell sha256sum /tmp/hakios-p4-baseline-manual-restore.img
```

Require staged size 61865984 and the exact pinned baseline hash. Only after all the checks above succeed, write the single boot partition, sync and independently read it back. A failed/partial write requires another verified attempt in recovery; it does not authorize a reboot.

```powershell
python scripts/run.py --label p4-recovery-restore-boot -- adb -s A51_SERIAL_HERE shell dd if=/tmp/hakios-p4-baseline-manual-restore.img of=/dev/block/sda12 bs=4096 conv=fsync
python scripts/run.py --label p4-recovery-sync -- adb -s A51_SERIAL_HERE shell sync
python scripts/run.py --label p4-recovery-boot-readback -- adb -s A51_SERIAL_HERE shell sha256sum /dev/block/sda12
```

Require boot SHA-256 `eb30609a62999e3282ac81e0a5e56411ef12ec1a39c107171bf3e01209c7cb67` before the next commands. Preserve original pstore exports if still needed. Remove only the known temporary file, reboot, and require Android `sys.boot_completed=1`. Limit Android return observation to 240 seconds; if it fails, retain the failure and return to preserved recovery.

```powershell
python scripts/run.py --label p4-recovery-stage-cleanup -- adb -s A51_SERIAL_HERE shell rm -f /tmp/hakios-p4-baseline-manual-restore.img
python scripts/run.py --label p4-recovery-return-android -- adb -s A51_SERIAL_HERE reboot
python scripts/run.py --label p4-baseline-android-completed -- adb -s A51_SERIAL_HERE shell getprop sys.boot_completed
python scripts/run.py --label p4-baseline-android-root -- adb -s A51_SERIAL_HERE shell su -c id
python scripts/run.py --label p4-baseline-android-uuid -- adb -s A51_SERIAL_HERE shell cat /proc/sys/kernel/random/boot_id
python scripts/run.py --label p4-baseline-android-pins -- adb -s A51_SERIAL_HERE shell su -c "sha256sum /dev/block/sda12 /dev/block/by-name/recovery /dev/block/by-name/dtbo"
```

Compare the fresh Android UUID with the pre-trial/recovery UUIDs, require all three pinned hashes and root, then remove only the trial's recorded `/data/local/tmp/hakios-p4-<nonce>.img` staging path if it remains. A clean baseline return is recovery evidence, not a Phase 4 driver pass.

## Retained failures and rollback

The earlier Phase 4 completion decision was rejected because its framebuffer, brightness, touch/key and storage tests were simulated. `evidence/phase-4/completion-correction/20261114T145419130432Z` preserves the old decision and sources. The corrected complete-loader development retained failed builds, disk-full/truncated scratch cases and failed capture/cycle models; the intact 40-case suite supersedes those host failures without deleting them.

Snapshot preflight `evidence/phase-4/device-preflight/20261114T182239698261Z` failed before device actions because it compared current templates to the original adaptation. The indexed two-revision history fix and 15 added source-history models resolved that mismatch; the current snapshot preflight above passed. USB was absent in `20261114T181434086307Z-phase4-resume-windows-usb-enumeration`, `20261114T182020662694Z-phase4-current-adb-connection` and `20261114T182940409757Z-phase4-resumed-adb-presence`; the later connection/inventory above resolves that blocker for this capture only.

The source correction packet is `evidence/phase-4/loader-contract-correction/20261114T165547237527Z`. Restore its exact `before-pins.json` bytes to undo a source correction and remove only newly introduced files with `before=null`; retain the before/after patches and all outcomes. Current documentation has its own indexed before/after packet. Source/pointer rollback requires fresh matching host checks before another device trial. Original Android sources/backups, historical Phase 3 loader/build, original evidence and the Phase 1 completion bundle remain preserved.
"""
    guide = guide.replace("@@CANDIDATES@@", table).replace("@@PREFLIGHTS@@", preflight_table)
    guide = guide.replace("@@INVENTORY@@", inventory_rel).replace("@@BOOT_ID@@", boot_id).replace("@@CONNECTION@@", args.connection_run)
    current = ("\n\n## Current Phase 4 loader readiness\n\n"
               "The corrected C loader passed 4,110 ASan/UBSan validator checks, 106 envelope checks, all 40 complete-loader QEMU cases and 117 host capture/cycle/source-history models. "
               "Current watchdog, full and snapshot host preflights passed; these establish host readiness only. "
               f"The A51 reconnected in `{args.connection_run}`. Fresh rooted Android inventory `{inventory_rel}` passed with the pinned boot image and independent first 1 MiB. "
               "Corrected-loader/watchdog/persistent-record survival and actual peripheral hardware execution remain unverified. "
               "Display/brightness, physical touch/keys, UFS DMA/image loading and the real read-only submission path still require implementation and hardware gates. "
               "See [device path and recovery](C:/Users/Ankit/Desktop/A51/hakios-a51/docs/PHASE-4-DEVICE-PATH.md) for pins, provenance, failures, commands and bounded restoration. "
               "The older Phase 4 kernel reader uses an incompatible pre-correction format.\n")
    replacements = {"docs/PHASE-4-DEVICE-PATH.md": guide + "\n"}
    for relative in ("README.md", "docs/STATE.md", "docs/INDEX.md"):
        old = (PROJECT / relative).read_text(encoding="utf-8")
        first, separator, rest = old.partition("\n\n")
        replacements[relative] = first + separator + current.lstrip("\n") + "\n" + rest
    replacements["docs/STATE.md"] = replacements["docs/STATE.md"].replace(
        "- Current phone baseline/root must be freshly checked before hardware work.",
        "- Latest reconnected Android baseline/root and independent boot bytes passed; each hardware cycle rechecks identity and all partition pins before staging.")
    replacements["docs/INDEX.md"] = replacements["docs/INDEX.md"].replace(
        "Phase 4 groundwork: prototype/phase4-platform/hakios.a51.{c,h} and scripts/phase4_support.py; source only, execution pending.",
        "Phase 4 platform diagnostics/SPI and corrected C loader have host/QEMU evidence; silicon execution and real peripheral drivers remain pending. See docs/PHASE-4-DEVICE-PATH.md.")
    state = read("state.json")
    state["phase_4_status"], state["phase_4_device_gate_passed"] = "in_progress", False
    state["blockers"] = [
        "Corrected Phase 4 C-loader execution, original persistent-record survival and actual watchdog reset are hardware-unverified.",
        "Measured display/DSIM brightness, physical MSS100 touch and power/volume events remain unimplemented or unverified.",
        "Read-only UFS DMA submission, independent-byte reads and larger-image loading remain unimplemented or unverified.",
    ]
    state["next_action"] = "run_nonce_bound_watchdog_trial_restore_baseline_then_full_loader_and_passive_snapshot_before_real_peripheral_drivers"
    state["phase_4_inventory"] = {"result": inventory_rel, **pin(inventory_path)}
    state["phase_4_device_preflights"] = preflights
    state["phase_4_connection"] = {"run": args.connection_run, "adb_serial_present": True, "captured_boot_id": boot_id,
                                   "inventory": inventory_rel, "scope": "Android observation at capture; recheck at trial entry"}
    state["phase_4_log_reader"]["current_format_compatible"] = False
    state["phase_4_log_reader"]["limitation"] = "Historical pre-correction kernel reader; use phase4_pstore.py original recovery exports for current envelopes"
    state["phase_4_device_path_documentation"] = {"packet": packet.relative_to(PROJECT).as_posix(), "guide": "docs/PHASE-4-DEVICE-PATH.md"}
    replacements["state.json"] = json.dumps(state, indent=2) + "\n"
    note = f"""\n\n## P4-022 — Record corrected-loader readiness and independent recovery ({packet.name})

Purpose/files: add scripts/phase4-record-device-path-docs.py and docs/PHASE-4-DEVICE-PATH.md; synchronize README.md, docs/STATE.md, docs/INDEX.md and state.json with selected passing native/QEMU/model evidence, three current hardware-package preflights, reconnected root/baseline inventory and remaining peripheral gates. Explain actual C-loader versus historical full-Phase-3 assembly provenance, exact memory/source pins, original framed pstore attribution/checksums/ECC/conflicting-bank rules, durable cycle journaling, bounded rollback, exact rebuild/trial commands and an independent pinned-baseline recovery procedure. Mark the older reader's incompatible format while preserving its original result.

Verification: all three preflights passed against current cycle source/model pins. Reconnected inventory `{inventory_rel}` passed root, model, completed Android, stable UUID, pinned boot hash and independent first 1 MiB; GPIO debugfs remained unavailable. This recorder checked selected counts/pins and fresh inventory/connection/preflight identities before writing indexed before/after documents. No phone write, reboot or module operation occurred during this documentation step. Hardware execution remains pending.

Limitations/rollback: host readiness cannot satisfy any display/input/UFS gate. Restore only the exact document/state before copies in this packet and remove newly introduced guide/recorder files if deliberately reverting; preserve all original records and failures. Recheck live identity/pins before each hardware trial and use the independent recovery procedure only on the identified rooted recovery device. The open loader correction packet is finalized separately after this guide exists.
"""
    replacements["docs/IMPLEMENTATION-LOG.md"] = (PROJECT / "docs/IMPLEMENTATION-LOG.md").read_text(encoding="utf-8") + note
    documents(packet, replacements)
    write_json(packet / "result.json", {"recorded": True, "inventory": {"result": inventory_rel, **pin(inventory_path)},
               "preflights": preflights, "connection_run": args.connection_run, "device_operations": False,
               "phase_4_gate_passed": False, "document_files": list(replacements)})
    index_packet(packet)
    print(json.dumps({"recorded": True, "packet": packet.relative_to(PROJECT).as_posix(), "files": len(replacements)}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
