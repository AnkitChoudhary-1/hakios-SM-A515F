> Publication note: this is a historical workspace document. Current completion decisions are in [PUBLIC-STATUS.md](PUBLIC-STATUS.md); raw local evidence is described in [PUBLICATION.md](PUBLICATION.md).

# Privileged read-only A51 observations

Date: 11 November 2026. Status: schema-2 collector, 41 guards on Windows/native WSL, offline replay on both hosts and independent live-FDT libfdt comparison verified. Phase 2 remains in progress; no loader, experimental image or device payload has been implemented or executed.

The user enabled KernelSU superuser access for Shell/com.android.shell (UID 2000). The collector uses that existing access to read Android state. This is separate from the immutable Phase 1 inventory and the [retained-source trace](SOURCE-TRACE.md), which made no phone queries. Root access and a Linux-exported device tree are now observed; original firmware entry state, owned usable RAM and a payload's log/return path remain unproved.

## Selected evidence

| Record | Identity and scope |
|---|---|
| [Live report](PUBLICATION.md) | Schema 2; 210,892 bytes; SHA-256 `771929edd98643aed7c7ecb50fec5354510bae39cfb8f7b1d56fd938c59bd9fd` |
| Live index | 153 files, 1,936,751 indexed bytes; 49 queries, two tools, three base FDT copies and report |
| Capture interval | 11 November, 12:45:59–12:46:30 IST; UTC `07:15:59.057361`–`07:16:30.943515`; selected serial `A51_SERIAL_HERE` |
| Linux-exported FDT | 224,774 bytes, 1,087 nodes; SHA-256 `c6a08859495a32310a10918fc50fbd3238daa546eb40c665407d1559b75eaaf6` |
| [Independent libfdt result](PUBLICATION.md) | 27,862 bytes; SHA-256 `bc0348f16b431d56de7274544f024c81e150256d9294e79b6fa0c6e7a15f2682`; one FDT, 1,087 nodes, 38 selected nodes, 91 critical properties, six commands, 14 indexed files/662,492 bytes |
| Current live pointer | `manifests/live-loader-current.json`; publish only after complete reconstruction and consistent root/boot/FDT observations |

The selected capture completed with 44 successful reads and five remote command failures. Each unavailable interface returned remote exit 1 with ADB transport exit 0: `reg` for `ion_video_stream`, `ion_crypto` and `wifibt_if`, `/sys/kernel/debug`, and `/sys/kernel/kexec_loaded`. Their error bytes and true statuses are retained. Collector exit 0 means its required root/boot/FDT capture and reconstruction passed; it does not mean every optional query succeeded or that the device execution gate passed.

## Collector and replay contract

`scripts/capture-live-loader.py` has a fixed list of 49 read-only queries and requires an explicit device serial. It has no device-write, mount, reboot, kexec or payload operation. Query groups cover root and boot IDs, Android properties, uname/CPU/configuration, FDT/sysfs properties, iomem/meminfo, selected log interfaces, and boot/DTBO/recovery links/sizes/hashes. Beginning/end root IDs, boot IDs and FDT bytes constrain observations to one Android boot; they do not make every workload-dependent reading simultaneous.

Schema 2 wraps each Android-shell command with `pipefail` and a nonce-tagged terminal exit footer. It retains the exact `.response`, extracted `.stdout` and host `.stderr` for every query. Remote stderr can be merged into the response by `adb exec-out`; the host stderr file is not a separate remote-error channel. Offline replay extracts and reconstructs remote status from the raw response, separately retains transport status, and rejects missing/malformed status footers or fabricated success.

Replay verifies the command allowlist, serial, raw/extracted identities, exact indexed file set, canonical contained paths, strict JSON types, finite numbers, timestamps/UTC–IST offsets/order and reconstructed observations. Current capture/parser scripts must match the retained tool copies. The pinned source-trace report, its base-FDT associations and unchanged local Android input hashes are rechecked. Replay contacts no phone and does not rewrite the capture or pointer. Unavailable original inputs or mismatched historical tools must be restored before replay; retained copies are local integrity evidence, not remote-source authentication.

Bounds: JSON 2 MiB, ordinary retained files 4 MiB, indexed bytes 32 MiB, at most 256 indexed files, and 30 seconds per bounded query process. Individual reads have smaller allowlisted limits; raw responses receive only 128 additional status bytes. Both process streams are capped, timeout/overflow/transport failure cannot become success, and decompressed configuration is bounded. Raw FDT/console/response files remain local evidence; routine console/report summaries omit chosen boot arguments and seed values. No pmsg/user-log capture is included.

## What the phone established

The selected root queries returned `uid=0(root)` and `u:r:su:s0`. Model/device/hardware, bootloader `A515FXXU8HWI5`, Android 16 build `BP4A.251205.006`, kernel `4.14.357-Everline-KSUN-A51` and reported revision 9 agree with the earlier inventory. CPUs 0–7 were online. ROM properties still report locked/green; they do not resolve actual bootloader acceptance of an experimental image.

The unchanged Linux-exported FDT reports `Samsung A51 EUR OPEN REV02 based on Exynos9611`; compatible values are `samsung,armv8` and `samsung,exynos9610`. Model/compatible match independent sysfs reads. Root address/size cells are 2/1. No chosen seed properties or `stdout-path` are present; initrd properties identify `[0x89000000, 0x89143800)`. This does not locate the FDT itself in physical RAM or recover the original firmware x0–x3, original overlay index or pre-Linux fixups. The traced Linux export path can follow seed removal.

The live FDT declares 6,327,107,584 bytes in these five ranges:

| Start, inclusive | End, exclusive |
|---|---|
| `0x80000000` | `0xBAB00000` |
| `0xC0000000` | `0xE0000000` |
| `0xE1900000` | `0x100000000` |
| `0x880000000` | `0x900000000` |
| `0x900000000` | `0x980000000` |

These are live Linux tree declarations. Compared with original/installed base FDTs, the tree adds 458 nodes/197 properties and changes 81 properties, with no removals and unchanged memreserve. Against recovery it adds 458 nodes/196 properties, changes 81 properties and removes one node/two properties. The differences do not independently identify who made each change or authenticate one exact overlay application.

Privileged `/proc/iomem` exposes actual addresses, including Linux kernel code/data. Its four System RAM records agree with the live tree's RAM union and merge the two contiguous high banks. Linux resource labels omit page-level, dynamic, secure, firmware, DMA and allocator ownership. They cannot establish a free interval for the loader. MemTotal is 5,707,016 KiB; MemAvailable 2,315,972 KiB is a transient workload reading. CMA total is 135,168 KiB and free is 0.

Live configuration confirms `CONFIG_KEXEC=n`, `CONFIG_DEBUG_FS=n`, `CONFIG_KSU=y` and `CONFIG_KSU_MANUAL_HOOK=y`. Relocation/KASLR, OF, PSCI and pstore are enabled; ARCH_KEEP_MEMBLOCK is absent/unknown. Dynamic reservation `reg` properties remain absent/unreadable, so their actual placements remain unknown. Mounting debugfs would not create code omitted from this kernel. **The QEMU address `0xF0000000` is still inside modem reservation `[0xED000000, 0xF5A00000)`; no A51 destination is selected.**

Existing Android `console-ramoops-0` was read in full (46,155 bytes), and filtered previous `/proc/last_kmsg` was retrieved (39,823 bytes); reset reason was `RPON`. The pstore listing includes a pmsg file, whose contents were not read. Current filtered dmesg lacks the selected early memory/reset records. Previous Android records contain dynamic-node initialization, a 36 MiB CMA allocation at `0x0000000979000000`, legacy PSCI v0.1 function IDs and Android reboot handling. They are not tied to the current boot ID and cannot establish current ownership, a new payload's logging, an agent-triggered reboot or return after that payload. Configured pstore/reset handlers remain candidates requiring a separate owned-buffer and demonstrated return design.

Live partition identities match unchanged retained inputs:

| Partition | Bytes | SHA-256 |
|---|---:|---|
| boot, installed KernelSU image | 61,865,984 | `eb30609a62999e3282ac81e0a5e56411ef12ec1a39c107171bf3e01209c7cb67` |
| DTBO, original backup | 8,388,608 | `41662c61ff3158448935025477a4e29d445823dab2cddafb18ea649c8ea925d6` |
| recovery, original TWRP backup | 71,106,560 | `12412e2008d950260cda627ac7a6b8eac954b49ef9db5573a297f67e4fc85999` |

These are read-only size/hash comparisons, not a new backup, restore test or loader acceptance result. The original pre-KernelSU boot backup is preserved separately.

## Verification and failure history

| Run | Result |
|---|---|
| `20261111T063829997778Z-phase2-adb-root-preflight` | Failed: Shell had no usable su access |
| `20261111T064057016051Z-phase2-adb-root-after-shell-grant` | Root verified after the user's KernelSU Shell grant, exit 0 |
| `20261111T071239553483Z-phase2-live-loader-guards-windows` | 41 tests passed, 60.292 seconds |
| `20261111T071847453498Z-phase2-live-loader-guards-wsl-native` | Identical 41 tests passed, 11.901 seconds |
| `20261111T071558473193Z-phase2-live-loader-readonly-capture-corrected` | Schema-2 capture/self-verification passed, exit 0 |
| `20261111T072031747867Z-phase2-live-loader-readback-windows` | 153-file offline reconstruction passed, exit 0 |
| `20261111T072031931620Z-phase2-live-loader-readback-wsl` | Same reconstruction passed, exit 0 |
| `20261111T072218828656Z-phase2-live-loader-observation-review` | Retained findings review passed, exit 0 |
| `20261111T073047037157Z-phase2-live-fdt-libfdt-crosscheck` | DTC 1.7.0 comparison passed, exit 0 |

The first schema-1 capture, `evidence/phase-2/live-loader/20261111T065651432980Z`, retains 100 indexed files and report SHA-256 `feda0d78e715b561d1dac118bbf77fad20efcc8a30abf24250ee451345287e37`. ADB transport exit 0 concealed five remote failures, making its query success counts unsuitable for selection. Schema 2 corrected status capture before the final suites/capture/replays. Preserve schema 1 and its matching run snapshots; current schema-2 replay intentionally rejects it.

The DrvFS suite `20261111T071239658097Z-phase2-live-loader-guards-wsl` was extremely slow and deliberately stopped after the identical native suite passed. Stop run `20261111T071955894368Z-phase2-live-loader-slow-wsl-guard-stop` verified the exact observed Linux PID/command line before terminating it; no distro shutdown occurred. Exit 15 is a retained interrupted run, with no observed assertion failure and a possible incomplete fixture under `evidence/test-fixtures`. Preserve that record/fixture. Four byte-identical scripts and `inputs.json` remain at `/opt/a51-hakios/validation/live-loader/20261111T071559056361Z`; this is a separate native validation directory, not the accepted upstream checkout.

The guards exercise binary/status separation, pipeline failure, bounded processes/decompression, inconsistent root/boot/FDT/sysfs observations, fabricated/reindexed statuses and summaries, query/path/file/index bounds, strict types, timestamp order, provenance/tool/local-input drift and malformed/overflowing JSON/iomem/FDT/configuration. They use synthetic host fixtures and do not contact the phone. Collector/parser code remained unchanged after the passed suites, capture and replays.

The independent comparison is a logged inline checker, preserving the existing `check-boot-audit-libfdt.py` and historical source-trace tool identities. Its exact Python source is `command[-1]` in `runs/20261111T073047037157Z-phase2-live-fdt-libfdt-crosscheck/metadata.json`, SHA-256 `48cfbc9a148fbac5afde0085a0f03e6e02715c03391fb3255ebb3012de00acea`. It pins the selected live report, retains the compared blob, DTC/package/binary identities and raw command outputs, and compares header, node count, memreserve, root children and critical raw property bytes. It accesses no phone and applies no overlay. A fresh run creates a separate timestamped result; existing bytes remain unchanged.

## Repeatable commands and rollback

From `C:\Users\Ankit\Desktop\A51\hakios-a51`, offline reconstruction:

```powershell
python ./scripts/run.py --label live-loader-readback -- python ./scripts/capture-live-loader.py --verify evidence/phase-2/live-loader/20261111T071559056361Z/report.json
python ./scripts/run.py --label live-loader-readback-wsl -- wsl -d A51-KernelBuilder -u root -- python3 /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/capture-live-loader.py --verify evidence/phase-2/live-loader/20261111T071559056361Z/report.json
```

For a deliberate new read-only capture with the connected/root-enabled phone:

```powershell
python ./scripts/run.py --label live-loader-capture -- python ./scripts/capture-live-loader.py --serial A51_SERIAL_HERE
```

Verify the emitted report on both hosts before selecting new state evidence. A new capture may differ with Android workload/boot state; it never overwrites a timestamped folder. Guard entry points are `python ./scripts/test-live-loader.py` and the identical retained native WSL `scripts/test-live-loader.py`; run them through the project recorder and verify matching native copies before relying on the retained native directory. No new guard run, rebuild or QEMU run is needed for documentation-only changes when executable tools and pinned inputs remain unchanged.

P2-009/P2-010 in [IMPLEMENTATION-LOG.md](IMPLEMENTATION-LOG.md) record implementation, corrections, documentation and verification. Pre-synchronization copies of 16 current documents/state/roadmap are indexed at `evidence/phase-2/live-handoff-docs/20261111T073251238016Z`; restore only a specific named file after comparing its recorded hash and synchronize the replacement state. Preserve original Android images, upstream sources, archived roadmaps and all 264 Phase 1 bundle files. Replay historical captures with matching tool revisions in a compatible project root; do not weaken hashes or overwrite failures. No phone restoration is required for these host/read-only changes.

The next engineering work is to resolve Samsung entry/acceptance and owned memory, then implement the bounded loader/test payload with retrieval and return described in [LOADER-DESIGN.md](LOADER-DESIGN.md). The runtime ownership importer remains unimplemented. Global continuation phone-query status is true; historical source-trace query/live flags remain false. All ownership, executable placement/destination, new-loader acceptance, payload-log retrieval, return, no-flash launch and Phase 2 device gates remain false. A51-specific XNU and hardware-driver work has not started.

Latest live-observation handoff verification: `20261111T075409338453Z-phase2-live-final-documentation-state-check-corrected` passed, checking 149 links/21 documents, selected report/pointer/hashes/counts, unchanged tools, 16 rollback copies and all 264 Phase 1 bundle files. Phase 1 current-input integrity `20261111T075246825826Z-phase2-live-final-phase1-live-integrity` also passed. Only completed results are selected; Phase 1 remains complete, Phase 2 remains in progress and its device execution/log/return gate remains false.
