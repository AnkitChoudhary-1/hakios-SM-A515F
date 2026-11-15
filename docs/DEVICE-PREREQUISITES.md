> Publication note: this is a historical workspace document. Current completion decisions are in [PUBLIC-STATUS.md](PUBLIC-STATUS.md); raw local evidence is described in [PUBLICATION.md](PUBLICATION.md).

# Connected A51 prerequisite tests

11 November 2026. Implemented and verified read-only Android observations after the user connected the SM-A515F and authorized tests. Phase 2 remains in progress. This session queried the phone; it did not execute a HakiOS payload, load a module, reboot, mount, flash or write a partition.

The completed packet contains 35 queries: 33 successes and two genuine remote failures. Root, model and boot ID agreed at beginning/end. The Linux-exported FDT and compressed kernel configuration were unchanged, matched the earlier selected capture, and belonged to the same Android boot. All eight CPU IDs `0-7` were possible, present and online at both CPU-mask reads; this is an observation, not a hotplug/shutdown test.

## Results and practical meaning

| Observation | Meaning and limit |
|---|---|
| `CONFIG_KEXEC=n`, `CONFIG_EFI=n`, `CONFIG_DEBUG_FS=n` | The installed Linux configuration lacks those facilities. Firmware acceptance and alternative handoff mechanisms remain unverified. |
| `CONFIG_MODULES=y`, `CONFIG_MODVERSIONS=y`, `CONFIG_MODULE_SIG=n`; `modules_disabled=0` | A kernel-module diagnostic is a candidate. Exact installed build ABI, exported symbol compatibility, SELinux acceptance and an actual successful module load remain unverified. |
| Rooted collector child has `CAP_SYS_MODULE` and `CAP_SYS_BOOT`, `NoNewPrivs=0`, `Seccomp=0` | These are permissions/security facts for the child reading `/proc/self/status`; they are not a launch route or permissions proof for every future process. |
| `/proc/modules` returned zero records | No loaded module records were exposed during that query. Built-in drivers are not counted. |
| MemTotal 5,707,016 KiB; MemAvailable 1,430,940 KiB; MemFree 54,224 KiB | About 1.36 GiB was estimated available to Android. The counters are non-atomic and establish no owned physical interval. |
| CmaTotal 135,168 KiB; CmaFree 12 KiB; later `nr_free_cma=0` | CMA was almost exhausted during these distinct snapshots. No contiguous allocation was attempted. |
| Buddy snapshot had blocks only at orders 0–3 | No blocks were reported at orders 4–10 in that snapshot. Fragmentation reinforces why a large free/available total cannot choose a loader destination. |
| pstore mounted, existing console/pmsg entries listed, `/proc/last_kmsg` metadata readable | Existing Android log infrastructure is visible. New-payload/fault logging, persistence across a test/reset and return remain unproved. No log content was read in this supplement. |
| Active-console read succeeded with zero bytes | That interface listed no enabled console names. It does not establish UART absence or availability. |
| `panic=5`, `panic_on_oops=1`, `sysrq=0`, `dmesg_restrict=0`, `kptr_restrict=2` | Current Linux policy values, not tested fault/reset behavior. |

The two failures both had remote exit 1 despite ADB transport exit 0. `/proc/sys/kernel/kexec_load_disabled` was absent. The grouped metadata query failed because `/dev/mem` and `/dev/kmem` were absent, while it successfully listed `/dev/ion`, `/dev/watchdog` and `/dev/watchdog0`. Listing these device nodes did not open them. A failed group is not reported as a successful query.

## Collector, source review and exclusions

`scripts/capture-device-prerequisites.py` adds a fixed 35-command allowlist, an explicit serial, per-query 15-second transport timeout/output bounds, nonce-tagged remote status, exact stdout/response/host-stderr pins and UTC/IST times. Three frozen tool copies and three historical input copies accompany the query files. Offline replay verifies file/command roles, hashes, ordered times, remote statuses, historical input association and a reconstructed summary. Every entry/ownership/placement/payload/log/fault/return/no-flash/Phase 2 gate stays false. The historical `capture-live-loader.py`, its packet and current manifest remain unchanged.

Read-only permission bits alone do not establish a side-effect-free read. The source review excluded watchdog `reset_confirm` (its show callback can start/confirm reset), `/proc/pagetypeinfo` (PAGE_OWNER can drain page caches), and `/proc/sys/vm/stat_refresh` (read can schedule counter refresh). No watchdog sysfs attributes, device-node contents, registers, raw physical memory, syscalls for launch, hotplug controls or driver ioctls were used. The fresh config also has `CONFIG_PAGE_OWNER=n` and `CONFIG_WATCHDOG_SYSFS=n`; the collector retains unconditional exclusions.

Pinned source citations and byte hashes are in the two completed logs `runs/20261111T121329433379Z-phase2-live-supplement-proc-cpu-console-source-review/metadata.json` and `runs/20261111T121533477481Z-phase2-live-supplement-source-read-handlers/metadata.json`. They cover proc/self/status and capability numbering, module listing/policy, allocator counters, CPU masks, sysctl read handlers and active console. Android source lineage `468ab8343364e4d3a267e670fa6a22fd4197a805` is recorded, not a verified Git HEAD. Source behavior remains an interpretation; the phone capture verifies the exposed observations.

## Evidence, verification and commands

Selected report: `evidence/phase-2/device-prerequisites/20261111T121643948118Z/report.json`; 53,210 bytes; SHA-256 `0a442d955e7e8773638761d83cba23f665b943d7e289ed10790f61694bdd8717`. The index contains 112 files / 1,429,229 bytes; its SHA-256 is `4bb928aafe247fd7794ab5f713eb945e554e0dc0e8b52380afcf28ef291f4afa`. FDT SHA-256 remains `c6a08859495a32310a10918fc50fbd3238daa546eb40c665407d1559b75eaaf6`.

Capture `runs/20261111T121643415636Z-phase2-connected-device-prerequisites-capture/metadata.json` passed. Windows replay `runs/20261111T121808633696Z-phase2-device-prerequisites-replay-windows/metadata.json` and WSL replay `runs/20261111T121808835067Z-phase2-device-prerequisites-replay-wsl/metadata.json` passed; WSL retained its known nested-virtualization warning and completed. Three offline corruption checks `runs/20261111T122447888297Z-phase2-device-prerequisites-corruption-checks-corrected/metadata.json` rejected a false remote-success claim, a repinned Phase 2 gate promotion, and changed query bytes. The first corruption-check wrapper failed with `ModuleNotFoundError: boot_formats`; adding the project script path to that wrapper fixed it. The failed run `20261111T122420234404Z-phase2-device-prerequisites-corruption-checks` and copied fixtures remain preserved; the frozen collector was unchanged.

From the Windows project root:

```powershell
python scripts/run.py --label device-prerequisites-replay -- python scripts/capture-device-prerequisites.py --verify evidence/phase-2/device-prerequisites/20261111T121643948118Z
python scripts/run.py --label device-prerequisites-handoff -- python scripts/check-device-prerequisites-handoff.py
```

To make a new authorized read-only capture, use `--serial A51_SERIAL_HERE` instead of `--verify`. A new timestamped packet is created, but no current live-loader manifest is replaced. Select it in state only after completed capture/replay evidence. To replay an older script revision, use its frozen copies in a compatible project root; do not execute fixture mutations against the selected packet.

## Next experiment and rollback

The next concrete candidate is a tiny allocation/logging-only diagnostic module built against the exact installed kernel ABI. First establish matching `.config`, generated headers, `Module.symvers`, toolchain/commit provenance and exported APIs. Then design a strictly bounded allocation (initially one page), identity/ownership/lifetime reporting, readable logs, failure cleanup and unload. Module loading has not been tested. This candidate stays within Android and cannot pass the bare-metal Phase 2 gate. Physical handoff still needs CPU/DMA/cache/MMU/interrupt control, a payload entry ABI, persistent fault logs and demonstrated Android/recovery return. A custom Samsung image remains an unresolved alternative.

Nine indexed before-copies are in `evidence/phase-2/device-prerequisites-docs/20261111T1220Z/before/`. Restore their explicitly recorded original paths for documentation/state/checker rollback; remove or revert the new collector/handoff guide/checker as appropriate while preserving evidence/run history. No device restoration is needed for this session. The baseline handoff checker now permits an aggregate query flag only when the supplement verifies and is bound to the unchanged historical capture; historical prototype/source/runtime query flags remain false. All 264 Phase 1 bundle files remain part of the final preservation check.

Completed connected-device handoff `runs/20261111T122714120837Z-phase2-connected-device-final-handoff-check/metadata.json` passed exit 0: 112 supplemental files, both host replays, three corruption checks, nine rollback copies and all 264 Phase 1 bundle files verified. Current query flag is true, every device execution/ownership/log/return gate stays false, and Phase 2 remains in progress.

## Later execution result

The read-only capture above remains a historical P2-013 record. P2-014 subsequently verified the exact installed module ABI through a [one-page Android diagnostic](PAGE-PROBE.md), successful normal load/unload and failed-init cleanup. Current-session temporary-file writes are true; this earlier packet remains read-only. All standalone loader/payload/physical handoff/fault/return gates remain false.
