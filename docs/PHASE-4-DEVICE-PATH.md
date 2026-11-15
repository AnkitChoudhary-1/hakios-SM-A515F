> Publication note: this is a historical workspace document. Current completion decisions are in [PUBLIC-STATUS.md](PUBLIC-STATUS.md); raw local evidence is described in [PUBLICATION.md](PUBLICATION.md).

# Phase 4 device path, evidence and recovery

Phase 4 remains **IN PROGRESS** and its peripheral hardware gate remains **UNPASSED**. This guide records the corrected C loader and original-record capture path. Display, DSIM brightness, physical MSS100 touch, physical power/volume events, UFS DMA reads, larger-image loading and rejection of writes in the real storage submission path still require implementation and A51 evidence. Passive MMIO snapshots are prerequisites; eight GPIO register reads do not establish key events.

## Implementation and provenance

Work remains in `C:\Users\Ankit\Desktop\A51\hakios-a51` and `/opt/a51-hakios` in WSL distribution `A51-KernelBuilder`. Use `wsl -d A51-KernelBuilder --exec`; preserve the separate Android projects and the original Phase 3 tree. The Phase 4 platform tree is `/opt/a51-hakios/experimental/phase4-port/20261114T150320411427Z`; the preserved Phase 3 tree is `/opt/a51-hakios/experimental/phase3-port/20261114T013656044425Z`.

Successful full Phase 3 phone runs used the historical assembly through `scripts/build-xnu-boot-candidate.py` and `prototype/xnu-loader/pack_a51_payload.py`. The Phase 3 C loader has full QEMU execution and phone entry diagnostics; successful full C-loader XNU phone runs have not been established. The corrected Phase 4 path adapts that C loader. Historical `prototype/phase4-loader/a51_loader.S`, `recovery.S` and `return.S` remain retained references; the current builder compiles `entry.S`, `loader.c`, `validate.c` and `fdt_guard.c`, generated payload assembly and the carrier. Do not infer hardware success from the older assembly's results.

The accepted Samsung carrier keeps the measured 64-byte Image header and `stext` entry, including the vendor sentinel and original BSS-inclusive Image extent. The on-disk source slot is separately bounded to 36,334,080 bytes. The original successful accepted-carrier entry probe measured PC `0x800d0040`, Image base/x3 `0x800d0000` and FDT/x0 `0x8a100000`. The corrected loader accepts `0x80080000`, `0x80278000` and `0x800d0000`; current C-loader hardware placement still requires attributable evidence. The loader validates entry state, every CRC, TOC count/schema, source/destination/zero ranges, configuration, BootArgs, return-slot and FDT reservations before payload copies. The initial RAM budget is 112 MiB; the arena is `[0x83000000,0x847f0000)`. Panic RAM is relocated and zeroed. BootVideo is deliberately zero/unavailable until measured scanout is established.

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
| watchdog | `20261114T175713980557Z` | `8bf12833258dc8b66e68a6cc686a198924809c5f2a3d95b901e49795bcc1d97a` | `e5cc3b00abd341028bf2e4cc54017d70` |
| full | `20261114T181615768285Z` | `a7b776859dbee3314556f23aff77c7ccebb6203a2aeb8fd9ab91cec0c43a3e95` | `bfe74d24d2eb4f0fb93547796a99ce0f` |
| snapshot | `20261114T182039617765Z` | `aef0257d190bc352f6504e53aeaf18d99a679c6715cc74a5db4b421be0a7c979` | `e7b469f25e234d4eb71da916ea14523f` |

| Kind | Current preflight result | Scope |
|---|---|---|
| watchdog | `evidence/phase-4/device-preflight/20261114T182948557021Z/result.json` | passed; host only |
| full | `evidence/phase-4/device-preflight/20261114T224020077333Z/result.json` | passed; host only |
| snapshot | `evidence/phase-4/device-preflight/20261114T224104308776Z/result.json` | passed; host only |

The reconnected Android inventory is `evidence/phase-4/live-inventory/20261114T224140609574Z/result.json`; root, boot completion, model, unchanged Android UUID, pinned boot hash and independently retained first 1 MiB passed. Android boot UUID was `b365efde-5604-4032-bc39-c79a743883c8`. UFS LUN 0 exposes 4096-byte blocks and the boot partition starts at absolute LBA 27792. These observations are Android evidence. GPIO debugfs remains unavailable. Connection run: `20261114T224011767869Z-phase4-reconnected-debugging-adb`. Recovery and DTBO are freshly checked by the cycle before any candidate write.

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

## Measured-placement correction and failed watchdog review

Exception vectors, stack, cleared BSS and saved entry context now precede cache changes. Matching 63-case QEMU execution and cycle-model validation are pending; the previous passing 60-case suite predates these entry changes. An injected pre-cache-transition exception with I-cache enabled is checked at all three placements; hardware entry and persistence remain separate gates.

Original probe: `evidence/phase-3/entry-probe-device/20261114T045658970138Z/result.json`; both original nonce/CRC-bound banks replayed identically. Last trial: `evidence/phase-4/device-cycle/20261114T224503780422Z/result.json`. Candidate staging/write/readback passed and recovery reconnected in 55.719 seconds, but console acquisition failed and pmsg was unrelated Android data. No attributable envelope was captured. Entry failure and persistence loss remain separate hypotheses because loader_main publishes stage 1 before validation. The baseline was restored/readback verified and returned to completed rooted Android UUID `1e8256ad-99af-4884-9669-e64ae465f32c`, with unchanged recovery/DTBO and no staging. The later current baseline inventory has Android UUID `302e4e3f-b785-4b0d-85fe-5c9cfd9359af`. Inventory `evidence/phase-4/live-inventory/20261114T231927713848Z/result.json` independently rechecked the baseline and first 1 MiB.

Nonce `e5cc3b00abd341028bf2e4cc54017d70` is consumed. All hardware packages/preflights listed above predate the measured-placement correction and must be rebuilt before another trial. Keep unrelated pmsg bytes private in the original evidence; do not print them.

Rebuild changed sources through scripts/run.py: phase4-test-device-cycle.py; phase4-build-device-path.py --mode qemu --kind full; phase4-qemu-device-path.py --case all. The full suite now requires 63 cases at three exact placements, including early exceptions before cache changes. The unchanged native validator/envelope evidence remains reusable when its source pins match. Build a fresh watchdog nonce/package and run a matching preflight after matching host execution passes. Require attributable watchdog evidence and verified restoration before full corrected-loader execution; require full execution before passive snapshots/peripheral work.

Rollback: restore the exact source before bytes in loader-contract-correction/20261114T233200428604Z and this review packet's document before copies; retain every old source/result/failed bank and run matching host checks before reuse. No device operation occurred while recording this review.
