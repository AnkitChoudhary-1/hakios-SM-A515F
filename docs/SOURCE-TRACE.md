> Publication note: this is a historical workspace document. Current completion decisions are in [PUBLIC-STATUS.md](PUBLIC-STATUS.md); raw local evidence is described in [PUBLICATION.md](PUBLICATION.md).

# Retained A51 entry, memory, logging and return source trace

Date: 11 November 2026, Asia/Calcutta. Status: implemented and verified on Windows and WSL. The results establish source and retained-image declarations; actual Samsung entry state, live memory ownership, payload logging and return remain unknown.

The [retained-image audit](PHASE-2-HOST-AUDIT.md) and [host layout validator](PAYLOAD-LAYOUT.md) already establish image bounds and reject unsupported A51 placement. This trace preserves the Linux code behind the remaining entry/FDT/memory/log/reset questions. It implements no loader, runtime-evidence importer or device probe. Phase 1 remains complete; Phase 2 remains in progress with its device gate false.

## Selected evidence and provenance

The selected [report](PUBLICATION.md) is `evidence/phase-2/source-trace/20261111T054315892562Z/report.json`, 84,557 bytes, SHA-256 `a6f9211b459ef8309c53b6e39403a0ebad792cf013b904d7a2771b218c9a86b9`. Its [index](PUBLICATION.md) covers 82 files: the specification, three inputs, 28 complete source files, 40 numbered excerpts, three base FDTs, six tool scripts and the report. The index does not index itself. `manifests/loader-source-trace-current.json` selects this report; historical claims use its explicit path and hash.

Capture `20261111T054302281738Z-phase2-loader-source-trace-complete-restart-capture` passed exit 0. Independent replays `20261111T054549070815Z-phase2-source-trace-complete-restart-readback-windows` and `20261111T054549260339Z-phase2-source-trace-complete-restart-readback-wsl` passed exit 0. Each replay also verified the original boot audit: 25 indexed files, 18 original hashes and 11 FDT summaries. Evidence summary `20261111T054620406876Z-phase2-source-trace-final-evidence-summary` confirmed the final specification, source excerpt, FDT identities and recorded test outcomes.

The source root is `/opt/a51-everline/src`, the separate existing Android project. **This directory has no Git metadata.** Commit `468ab8343364e4d3a267e670fa6a22fd4197a805` is recorded lineage from the retained repack record (external local reference; see PUBLICATION.md), whose `kernel_source` URL ends in that commit. It is not a verified checkout HEAD, and this trace does not compare every source file with the remote commit. Individual file sizes and SHA-256 hashes pin the inspected bytes. `checkout.lineage_is_recorded_not_verified_git_checkout=true` makes that distinction machine-readable. The Android tree was read only.

| Input | Retained identity and meaning |
|---|---|
| Capture specification | `specification.json`, 8,681 bytes; SHA-256 `6a9ea44aa987f030a269a6ce4fd7209c8b0235afdf8ce5d85126f200e70ef3d1`; exact source paths, inclusive excerpt bounds, 22 symbols and boot-report pin |
| Original-byte boot audit | `inputs/boot-report.json`; SHA-256 `37f373bba0ea4002cb8853a09298355a8e24045c40f51853c97ebaecc50a344b`; reconstructed against original images and references on every trace replay |
| Retained Android configuration | `inputs/kernel.config`, 160,992 bytes; SHA-256 `9862a2b3ca684c08a0423681e77bf8503c2b7c2e18bd182ca3c1370681f8adb1`; historical build configuration, not a new phone query |
| Recorded source lineage | `inputs/repack-validation.json`, 1,911 bytes; SHA-256 `2ced1959920eb5a1daf1343c89b36c40caf1a3d7d419a73957385597c8e8712b`; source URL and prior repack record |
| Original/installed boot base FDT | Both 134,872 bytes, SHA-256 `6935ac20f1a8b9984ba863e918fffa192b2667d74b2c287a2cf451a32f159349`; two separately associated copies of identical bytes |
| Recovery base FDT | 135,152 bytes, SHA-256 `83090fe69a539557743c895925f1bf470b05d013c25a323e747046acfcb7100c`; retained separately from boot |

The FDT copies come from the already verified boot audit, not from `/sys/firmware/fdt`. No live tree or overlay is captured or applied by this tool. Raw PSCI/reboot/log/dynamic-reservation properties and decoded cells/strings are retained alongside declared RAM/reservation summaries.

## Configuration facts

The report records each selected symbol's exact value, one-based line and source text. An absent symbol is `null` with no line/text, rather than an inferred disabled value. Duplicate definitions are rejected.

| Symbols | Retained values | Consequence for investigation |
|---|---|---|
| `CONFIG_KEXEC` | `n` | Existing Linux cannot establish a kexec route from this configuration |
| `CONFIG_RELOCATABLE`, `CONFIG_RANDOMIZE_BASE` | `y` | Relocation/KASLR branches must be considered; actual placement and original entry registers are unmeasured |
| `CONFIG_HAVE_MEMBLOCK` | `y` | Source uses memblock; its existence does not provide an exported ownership map |
| `CONFIG_ARCH_KEEP_MEMBLOCK` | Absent/unknown | Do not interpret absence as an explicit `n` or proof of retained tables |
| `CONFIG_DEBUG_FS`, `CONFIG_SAMSUNG_PRODUCT_SHIP` | `n`, `y` | The inspected debugfs/memsize exports are unavailable under this configuration; product-ship redaction is a separate source constraint |
| `CONFIG_SYSFS`, `CONFIG_ARM_PSCI_FW`, `CONFIG_EXYNOS_REBOOT`, `CONFIG_SEC_REBOOT` | `y` | Source contains conditional FDT export and multiple reset initialization paths; successful runtime initialization remains unverified |
| `CONFIG_WATCHDOG`, `CONFIG_S3C2410_WATCHDOG` | `y` | Watchdog code is selected, with mapping/clock/IRQ/PMU prerequisites |
| `CONFIG_DEBUG_SNAPSHOT`, `CONFIG_SEC_DEBUG`, `CONFIG_SEC_DEBUG_LAST_KMSG`, `CONFIG_SEC_PM_DEBUG` | `y` | Debug/log code is selected; buffers, permissions and previous-log copying still matter |
| `CONFIG_PSTORE`, `CONFIG_PSTORE_RAM`, `CONFIG_PSTORE_CONSOLE`, `CONFIG_PSTORE_PMSG`, `CONFIG_EXYNOS_SECURE_LOG` | `y` | Persistent-log clients are selected; this does not demonstrate retrieval after a new payload |

## Entry and live-FDT implications

The [retained entry excerpt](PUBLICATION.md) covers `arch/arm64/kernel/head.S` lines 113–163. `stext` calls `preserve_boot_args` before EL setup. The function saves the original x0 FDT pointer through x21. With `CONFIG_RANDOMIZE_BASE=y`, it stores zeros for saved x1–x3. Consequently, later reads of `boot_args` cannot prove the original x1–x3 entry values. Linux's expected zero values and its saved zeros are different evidence.

The ARM64 boot protocol and additional `head.S` excerpts describe entry registers, exception level, interrupt/cache/MMU/timer/DMA requirements, relocation and BSS initialization. These are Linux source requirements. They do not establish the Samsung bootloader's actual PC/SP/CurrentEL, relocation, CPU/cache state, secondary-CPU activity, fixups or an XNU entry ABI. Android header addresses remain outside the declared banks; no executable A51 destination is derived.

The [FDT export excerpt](PUBLICATION.md) covers `drivers/of/fdt.c` lines 1392–1417. With SYSFS, Linux creates `/sys/firmware/fdt` with `S_IRUSR` (0400), only if `initial_boot_params` exists and its CRC matches the saved CRC. Root access alone does not guarantee that this file exists.

The [chosen-node excerpt](PUBLICATION.md) covers lines 1140–1193: Linux may consume and remove `rng-seed` and then refresh the CRC. An exported blob can therefore differ from the bytes present at initial entry while passing the export check. A future live capture must retain its exact bytes/hash, time, boot identity, access result and observed changes; calling it the untouched bootloader input would require additional evidence.

## Memory ownership and observability

`drivers/of/of_reserved_mem.c` records actual dynamic allocation bases/sizes through memblock and calls the vendor memsize record hook. The corresponding [record-capacity excerpt](PUBLICATION.md) covers `mm/memblock.c` lines 460–579: records are limited to 64 entries and use shortened names. Such records cannot be assumed to enumerate every secure, firmware, DMA or kernel owner.

The [export excerpt](PUBLICATION.md) covers lines 1873–2082. Both `/sys/kernel/debug/memblock/*` and the inspected `/proc/memsize/kernel`/`reserved` creation are inside `CONFIG_DEBUG_FS && !CONFIG_ARCH_DISCARD_MEMBLOCK`. DEBUG_FS is disabled in the retained configuration. Enabling or mounting debugfs is not part of this work and cannot make code omitted from the kernel appear. The source's product-ship branch additionally prints zero reservation addresses and hides nomap details; a future configuration with exports would still need to account for redaction.

The three retained base FDTs declare three separate 2 GiB banks, 15 fixed spans and three size-only dynamic reservations. Dynamic ION/WLBT locations, kernel/page-table/FDT/initrd allocations and secure/bootloader ownership remain unresolved. **QEMU's `0xF0000000` is inside declared modem memory `[0xED000000, 0xF5A00000)` and remains excluded.** Neither a static gap, a reservation name nor root-readable diagnostics establish owned loader memory. The host layout contract still has no runtime importer and selects no A51 destination.

## Reset and return implications

All three retained base FDTs declare `/psci` with `compatible="arm,psci"` and `method="smc"`, plus DT CPU suspend/off/on IDs. This legacy binding selects `psci_0_1_init` in `drivers/firmware/psci.c` lines 691–754. That path initializes the supplied CPU functions and a conditional SMCCC-version observation; it does not register the standard SYSTEM_RESET restart handler found in the separate >=0.2 initialization path. This is a Linux binding/initialization finding, not proof that the firmware lacks SYSTEM_RESET or has a particular PSCI version. Firmware reset capabilities and their usability from a new payload remain unknown.

The corrected [machine-restart excerpt](PUBLICATION.md) covers the complete path in `arch/arm64/kernel/process.c` lines 143–179. Linux disables local interrupts and stops secondary CPUs, conditionally attempts EFI reset, calls a debug-snapshot hook, and then uses `arm_pm_restart` if installed or the generic restart handlers otherwise. If reset returns, Linux prints a failure and halts. This does not supply a callable reset routine after abandoning Linux's execution state.

The [Exynos restart excerpt](PUBLICATION.md) shows DT matching, `pmu_base` mapping, callback installation and SoC-specific state dependencies. The [Samsung wrapper excerpt](PUBLICATION.md) shows saving the previous `arm_pm_restart` as `mach_restart`, installing the wrapper, updating reboot reason/cache state and calling the saved routine. Both use `subsys_initcall` (level 4); Makefile linkage and initcall mechanics are also retained. The active handler, initialization success and hardware effect on the running phone were not measured. A printed registration message alone would not prove a successful PMU mapping.

`drivers/watchdog/s3c2410_wdt.c` lines 1272–1479 retain watchdog probe dependencies on resources, mapped registers, clocks, IRQ and PMU/configuration. A configured watchdog or a source register address does not prove a usable timeout/reset route. No PSCI call, reset-register write, watchdog programming or reboot command was executed. Demonstrated return must cover the actual probe, its changed CPU/memory/device state and recovered logs.

## Logging and retrieval implications

The debug-snapshot reservation definitions are in `arch/arm64/boot/dts/exynos/exynos9610-rmem.dtsi` and its address macros; `exynos9610-debug.dtsi` defines a distinct debug SoC client. The retained FDTs declare the log regions, including a 2 MiB `log_pstore` region. Those regions already have owners and cannot become payload scratch/log storage by inference.

`lib/debug-snapshot-local.h` establishes the initializer field order: size, virtual address, physical address, persist, enabled. The [default-item excerpt](PUBLICATION.md) shows `log_pstore` with `persist=true` and initially `enabled=false`; header/kernel/platform logging defaults do not have the same persistence flag. Mapping, activation, conditional clearing/preservation, previous-buffer validation/copy and logging hooks are separate steps retained in the source. A persistence flag is not successful persistence or later retrieval.

| Source route | Declaration | Remaining limitation |
|---|---|---|
| `/proc/sec_log` | `lib/debug-snapshot.c` lines 863–917, mode 0440 under SEC_PM_DEBUG; created only when the kernel-log buffer exists | Permission/access and initialized buffer must be observed; this exposes Linux logging, not a validated new-payload log |
| `/proc/last_kmsg` | `drivers/samsung/debug/sec_debug_last_kmsg.c` lines 21–104, mode 0444; created only after a previous-buffer copy exists | Valid previous data, allocation/copy, boot identity and survival through the chosen reset must be demonstrated |
| Debug-snapshot ramoops | `lib/debug-snapshot-pstore.c` lines 207–244; 512 KiB record/console/ftrace/pmsg sizes; fills buffer address/size when `log_pstore` is enabled | Registration and a persistent region do not demonstrate a mounted/accessed record or retention after a foreign payload |
| Exynos secure log | `drivers/soc/samsung/exynos-seclog.c` retained in full | Secure-world/client ownership and platform state apply; not an owned payload buffer |

UART, framebuffer, RAM records and existing debug logs remain candidates for investigation. No new probe-log format is implemented by this host tool. A future route needs an owned buffer/transport, bounded records with build/input/FDT identity and a successful retrieval after the actual return/reset sequence.

## Implemented contract and resource bounds

`scripts/source_trace.py` implements collection, path/JSON/config validation, FDT fact extraction, numbered byte excerpts, indexing and original-byte reconstruction. `scripts/trace-loader-sources.py` exposes mutually exclusive `--capture` and `--verify-trace`; `--spec` selects a project-relative specification for capture. `scripts/test-source-trace.py` supplies meaningful integrity and boundary fixtures. The default specification is `manifests/loader-source-trace.json`, version 1, target `a51-retained-source`.

Capture first verifies the pinned boot report against original inputs, matches config/repack copies to audited references, checks the recorded lineage URL, and reads sources through canonical root-relative paths. The specification permits at most 64 sources, 64 distinct configuration symbols, eight excerpts per source and 128 distinct excerpts overall. Excerpt bounds are inclusive one-based integers, fit the actual source, span at most 4,096 lines and end by line 100,000. Numbered excerpts preserve original line-ending bytes and final-newline presence. No source file is edited.

| Resource | Maximum |
|---|---:|
| Specification, report, index and retained JSON inputs | 512 KiB each |
| Source, excerpt, configuration or tool file | 4 MiB each |
| Base FDT | 2 MiB each |
| Aggregate indexed contents | 32 MiB |
| Indexed files | 256 |

Reads check size before allocation and use a bounded read to detect growth. JSON rejects duplicate keys, nonfinite literals and floating-point overflow such as `1e309`. Schema/integer/boolean checks and exact reconstructed JSON preserve the distinction between `false`, `0` and other types. Paths reject noncanonical forms, traversal, absolute indexed paths, duplicates and symlink escapes. The exact indexed file set excludes extra/unindexed files and self-reference.

Replay uses the **retained specification**, not a newly edited default manifest. It checks the bounded index and every retained size/hash, rebuilds the report and exact file set from the original sources/images/config/tools, regenerates each excerpt and FDT fact, and compares exact bytes. It requires those original inputs and matching tool revisions to remain accessible. Retained copies support inspection, but this is not a self-contained offline reconstruction of unavailable originals or a remote source-commit authenticity check.

After capture and replay succeed, the CLI writes a temporary current-pointer file and replaces `loader-source-trace-current.json`. Failed preflight does not publish a report; a later write/verification failure can leave a partial timestamped folder, which must be retained for diagnosis. Replay changes neither evidence nor the pointer. All nine report/pointer flags stay false: `phone_writes`, `phone_queries`, `phase_2_device_gate_passed`, `safe_for_loader_placement`, `a51_destination_selected`, `live_fdt_selection_verified`, `runtime_memory_ownership_verified`, `probe_log_retrieval_verified` and `return_to_android_verified`.

## Verification, failed attempts and corrections

Initial 32-test suites passed on Windows in `20261111T052008943521Z-phase2-source-trace-guards-windows` and WSL in `20261111T052008840112Z-phase2-source-trace-guards-wsl`. Range preflight `20261111T052044501035Z-phase2-source-trace-range-preflight` failed because the Samsung reboot excerpt ended at line 390 in a 383-line file. The specification was corrected to end at 383; `20261111T052635064672Z-phase2-source-trace-range-final` passed with no invalid ranges.

Regression reproduction `20261111T052456419500Z-phase2-source-trace-boundary-reproduction` failed exit 1: three tests produced four failures. Reindexed oversized reports were decoded before their 512 KiB boundary was enforced; oversized retained FDTs reached reconstruction rather than being rejected at the 2 MiB read boundary; positive/negative overflowing float tokens decoded as infinities. Path-specific retained read limits and finite-float parsing now reject these before the relevant decode/reconstruction. The failed output and pre-fix scripts remain retained.

Final `20261111T052634880992Z-phase2-source-trace-guards-final-windows` passed **35 tests in 16.388 seconds**; `20261111T052634758695Z-phase2-source-trace-guards-final-wsl` passed **35 in 191.313 seconds**. These are unittest durations, not wrapper elapsed times. Fixtures cover original/retained source drift, reindexed source/excerpt/config/FDT claims, wrong JSON types, missing/extra files, traversal/index bounds, source/spec/report/FDT limits, pin/tool changes, duplicate/nonfinite JSON, absent configuration, exact excerpt endings and FDT cells/strings. They establish host behavior only.

Script review `20261111T053604393393Z-phase2-source-trace-final-script-review` confirmed eight current source/audit/recorder scripts match both final suites' recorded snapshots. No executable script changed after those suites. The later correction changes only the excerpt specification, so a new capture and both host replays validate that change without repeating the unchanged code tests.

The [earlier verified capture](PUBLICATION.md), SHA-256 `5f994ae063f04be021e1b0912e0bb07ca1cfaf465420e7af75f5b94ef80e8bda`, remains retained. Its machine-restart excerpt began at line 171, omitting the preceding callback condition and including unrelated later code. Review `20261111T054151064229Z-phase2-source-trace-return-excerpt-review-corrected` read the retained full file. The final specification now selects lines 143–179, including the complete condition and failure path; final capture/replay records are listed above. This corrects evidence presentation without modifying Linux or claiming a tested reset. An earlier review script failed with `KeyError: 'path'` in `20261111T054134383687Z-phase2-source-trace-return-excerpt-review`; the corrected read used the nested input record. That read failure changed no input or pointer.

Bundle preservation `20261111T054549619394Z-phase2-source-trace-phase1-bundle-preservation` checked all 264 Phase 1 files unchanged, exit 0. The original Android images, both historical roadmap copies, accepted build/QEMU artifacts and upstream HakiOS sources remain preserved. WSL's known nested-virtualization warning appeared, while capture and replay completed successfully. No dependency installation, rebuild, new guest run or phone query/write occurred.

After documentation/state synchronization, `20261111T060317154487Z-phase2-source-trace-final-phase1-live-integrity` passed exit 0: 13 selected runs, four artifacts, two retained transcripts, nine pins, SDK/three archives, 19 historical queries and 80 hashes/eight reference groups. This revalidated the accepted Phase 1 host inputs and current completion documentation without rebuilding or running a guest/device.

Final documentation/state consistency `20261111T061551865578Z-phase2-source-trace-final-documentation-state-check` passed exit 0. It verified 140 local links/20 documents, 67 selected references/42 successful timed runs at check time, all 82 indexed files (1,681,166 bytes), exact numbered excerpts, current report/specification/pointer pins, configuration/base-FDT/recorded-lineage provenance, 35 recorded guards/eight unchanged executable snapshots per host and retained failures. The earlier checker is referenced by a SHA-256 pin and retains the boot/libfdt/layout, raw UTC/IST and false device-gate checks. Selecting the completed run gives 68 references/43 successful timed runs. STATE.md and P2-008 record completion of this host source-trace/documentation milestone; the Phase 2 device gate remains false.

## Capture, replay and recovery

Run from `C:\Users\Ankit\Desktop\A51\hakios-a51`. [BUILD.md](BUILD.md) also lists these commands. Both replays require the original Android inputs and WSL source root. Windows maps logical `/opt/` paths through `\\wsl.localhost\A51-KernelBuilder`; Linux maps Windows paths through `/mnt/c/`.

```powershell
python ./scripts/run.py --label source-trace-readback -- python ./scripts/trace-loader-sources.py --verify-trace evidence/phase-2/source-trace/20261111T054315892562Z/report.json
python ./scripts/run.py --label source-trace-readback-wsl -- wsl -d A51-KernelBuilder -u root -- python3 /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/trace-loader-sources.py --verify-trace evidence/phase-2/source-trace/20261111T054315892562Z/report.json
```

When deliberately changing trace code or inputs, use a new logged capture and replays; run the guards when executable behavior changes:

```powershell
python ./scripts/run.py --label source-trace-guards -- python ./scripts/test-source-trace.py
python ./scripts/run.py --label source-trace-guards-wsl -- wsl -d A51-KernelBuilder -u root -- python3 /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/test-source-trace.py
python ./scripts/run.py --label source-trace-capture -- wsl -d A51-KernelBuilder -u root -- python3 /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/trace-loader-sources.py --capture
```

`--capture --spec manifests/<new-spec>.json` selects another reviewed specification. Inspect the emitted TRACE path/hash and verify that exact new path on both hosts before updating state/documentation. Timestamped captures never overwrite an existing folder. Capture exit 0 means original-byte reconstruction succeeded; it cannot pass the device gate.

For a missing/hash-changed source, image, configuration or tool, restore access to the pinned original or investigate actual drift. Do not replace the expected hash to silence an error. A tool revision change intentionally invalidates replay with different current tools; use a recorded revision in a compatible project root, not the nested `project-scripts/` folder as a standalone project. Older captures retain their own specification, so a corrected current excerpt range does not invalidate them.

Rollback: restore a specific script revision from a retained run, or restore the previous specification from its retained capture, documenting the reason. Recheck its original inputs and exact report with matching tools before deliberately restoring a current pointer. Preserve every failed run/capture and the Phase 1 bundle. These host changes require no phone restoration, kernel rebuild or QEMU rerun when those inputs are unchanged.

## . engineering milestone

The next work is read-only live observation when access exists: actual Samsung entry route/state, selected/merged FDT and fixups, dynamic/secure/runtime ownership, a usable log route and a return mechanism. Current ADB root access and bootloader acceptance remain unverified. The source trace explains why saved registers, configured exports, static reservations and reset/log declarations cannot replace these observations.

A future runtime importer and bounded probe need their own source, provenance, tests, owned extents, state-transition design and retrieval/return evidence. Phase 2 passes only when the A51 executes a loader/minimal payload, produces retrievable records and demonstrably returns to Android/recovery. Host compilation, parser agreement and source tracing cannot pass that gate; XNU, GPU acceleration, Apple services and Safari remain unverified or unavailable as recorded in [STATE.md](STATE.md).

## Subsequent privileged observations

The separate [live collector](LIVE-OBSERVATIONS.md) now verifies Shell root, an unchanged Linux-exported FDT, real iomem addresses, existing Android logs and matching partition hashes. Its 41 guards/replay per host and independent 1,087-node/91-property libfdt comparison passed. This does not modify this trace's historical phone/live flags or original-byte source associations.

Original firmware arguments/fixups, exact overlay selection, owned usable memory and a new payload's log/return path remain unresolved. The runtime ownership importer and device probe remain unimplemented. Host probe source can begin with simulated inputs; no unknown physical range becomes usable merely because it is present in the live tree.
