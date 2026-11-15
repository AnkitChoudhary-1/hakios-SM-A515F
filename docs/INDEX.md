> Publication note: this is a historical workspace document. Current completion decisions are in [PUBLIC-STATUS.md](PUBLIC-STATUS.md); raw local evidence is described in [PUBLICATION.md](PUBLICATION.md).

# Documentation index and reading order

## Current Phase 4 hardware investigation

Exception vectors, stack, cleared BSS and saved entry context now precede cache changes. Matching 63-case QEMU execution and cycle-model validation are pending; the previous passing 60-case suite predates these entry changes. An injected pre-cache-transition exception with I-cache enabled is checked at all three placements; hardware entry and persistence remain separate gates. The last watchdog trial `evidence/phase-4/device-cycle/20261114T224503780422Z/result.json` returned to recovery after 55.719 seconds but produced no attributable Phase 4 envelope. Loader entry, watchdog reset and persistent-record survival remain unverified. The pinned Android baseline was restored and verified, with unchanged recovery/DTBO and no staging files. Subsequent rooted inventory `evidence/phase-4/live-inventory/20261114T231927713848Z/result.json` passed (Android UUID `302e4e3f-b785-4b0d-85fe-5c9cfd9359af`), and ADB is connected in `20261114T233545114739Z-phase4-resume-authorized-adb`. The trial's restored Android UUID `1e8256ad-99af-4884-9669-e64ae465f32c` is retained separately. The original successful entry probe measured Image base `0x800d0000`; the corrected loader accepts that placement alongside `0x80080000` and `0x80278000`. An envelope is emitted before C validation, so the old placement rejection does not by itself explain the absent log. Actual display/brightness, physical touch/keys, UFS DMA/image loading and read-only submission gates remain unpassed. See [device path and recovery](PHASE-4-DEVICE-PATH.md).

Phase 1 and Phase 2 remain COMPLETE. Phase 3 has three retained A51 PID 1/timer/return runs in `evidence/phase-3/repeatability/20261114T132905926137Z/consecutive_runs_summary.json`. Phase 4 is **IN PROGRESS**; its device gate is **UNPASSED**. Phase 5 remains planned.

The previous Phase 4 completion decision is superseded by a source review: the test used a local framebuffer, absent DSIM MMIO, synthetic touch/key events and fabricated storage bytes. Actual display output/brightness, physical input, UFS reads against independent image bytes, larger-image loading and a read-only hardware submission path still require verification. The original files/results are preserved in `evidence/phase-4/completion-correction/20261114T145419130432Z/before/`. See [Phase 4 review](PHASE-4-COMPLETION-REVIEW.md).

1. `README.md`: project entry point and objective.
2. `docs/STATE.md` and `state.json`: verified progress, blockers and next action.
3. `../hakios-assessment/ROADMAP.md`: ten phases and acceptance criteria; its older Phase 2 status paragraph is historical. Current status is in the review and state above.
4. `docs/IMPLEMENTATION-LOG.md`: every implementation change and its evidence.
5. `runs/`: exact command metadata and complete output logs.
6. `manifests/`: device/host inventory and source/dependency provenance.
7. `scripts/`: repeatable capture/build/verification entry points.
8. `patches/`: explained adaptations to pinned upstream code.

Current Phase 3 audit: [review](PHASE-3-COMPLETION-REVIEW.md); retained result and documentation rollback copies are in `evidence/phase-3/completion-review/20261114-gate-audit/`.

Current Phase 3 platform build, timer diagnostics and rebuild/recovery guide: [PHASE-3-PLATFORM.md](PHASE-3-PLATFORM.md).

## Guides by task

| Task | Read |
|---|---|
| See verified progress and the next action | [Current state](STATE.md) and [machine-readable gates](../state.json) |
| Check the Phase 2 gate against original records and source | [Completion review](PHASE-2-COMPLETION-REVIEW.md) |
| Review the Phase 1 completion decision, logs and artifact hashes | [Acceptance report](PHASE-1-RESULTS.md) |
| Review continuation findings and verify the completion bundle | [11 November review](REVIEW-20261111.md) and [verification commands](BUILD.md) |
| Review retained Android boot/DT structure, declared RAM/reservations and libfdt validation | [Phase 2 host audit](PHASE-2-HOST-AUDIT.md) |
| Understand loader entry, layout, logging and return requirements still pending | [Loader design requirements](LOADER-DESIGN.md) |
| Inspect the implemented host layout contract, 92 guards, retained-A51 rejections and replay commands | [Payload-layout validator](PAYLOAD-LAYOUT.md) |
| Inspect retained entry/FDT/memory/log/reset sources, configuration limits, 35 guards per host and original-byte replay | [Retained source trace](SOURCE-TRACE.md) |
| Inspect verified Shell root, live Linux-exported FDT/memory/logs/partition hashes, 41 guards per host, true remote failures and offline replay | [Privileged live observations](LIVE-OBSERVATIONS.md) |
| Build/replay the native and AArch64 QEMU loader prototype; inspect C interfaces, entry capture, seven CRC frames, trust limits and recovery | [Loader/test-payload prototype](LOADER-PROTOTYPE.md) |
| Review the eight-CPU Android Linux callback capture, ABI association, cleanup and firmware-entry claim boundary | [CPU-STATE.md](CPU-STATE.md) |
| Review the synthetic early-entry harness, isolated Linux Image link, retained limitations and recovery | [EARLY-ENTRY.md](EARLY-ENTRY.md) |
| Inspect the stackless exception vector prototype, 34 cases across EL1/EL2 in QEMU, 538 checks, and register save structures | [Stackless fault envelope](FAULT-ENVELOPE.md) |
| Review the Samsung boot candidate packaging, Odin tarball generation, and four-region transformation | [Samsung boot packaging](SAMSUNG-BOOT-DRY-RUN.md) |
| Review latest minimal payload execution, earlier rejection and verified baseline restoration | [Device execution record](DEVICE-EXECUTION.md) and [completion review](PHASE-2-COMPLETION-REVIEW.md) |
| Find source, outputs, references and logs; view WSL files from Windows | [File map](FILE-MAP.md) |
| Understand source preparation, compilation and runtime handoff | [Architecture](ARCHITECTURE.md) |
| Install inputs, build, run QEMU or rebuild from clean outputs | [Build runbook](BUILD.md) |
| Change configuration, drivers, loader, scripts or source pins | [Modification guide](MODIFICATION-GUIDE.md) |
| Document a newly implemented driver or loader thoroughly | [Subsystem documentation template](DRIVER-DOCUMENTATION-TEMPLATE.md) |
| Inspect phone facts, backup layouts and Linux/firmware references | [Device baseline](DEVICE-BASELINE.md) |
| Understand missing runtime, Mali integration and Safari dependencies | [Dependency gaps](DEPENDENCY-GAPS.md) |
| Diagnose known failures and preserve evidence | [Troubleshooting](TROUBLESHOOTING.md) |
| Review the TIMA/RKP Android boot-loop evidence, reversible module isolation, stability test and rollback | [Android boot-loop recovery](BOOTLOOP-RECOVERY.md) |
| Review each implementation and configuration change | [Implementation log](IMPLEMENTATION-LOG.md) |
| Resume with another AI | [Handoff](HANDOFF.md), then [workspace instructions](../AGENTS.md) |
| See the complete ten-phase plan | [Roadmap](ROADMAP.md) |

Phase 2 remains **IN PROGRESS**; its device gate is **UNPASSED**. The P2-022 hardware record verifies Samsung acceptance, early-entry state capture at EL1 and successful baseline restoration, but `status=2` (`HKE_INVALID_DAIF`), `reason=1` and a zero payload marker prove that the minimal arithmetic payload was skipped. The earlier completion claim is superseded by the [completion review](PHASE-2-COMPLETION-REVIEW.md).

The documentation records verified host/QEMU work, Samsung packaging, early-entry observation and baseline restoration. Historical milestone sections below retain their original dates; current completion authority is the [completion review](PHASE-2-COMPLETION-REVIEW.md).

Windows root: `C:\Users\Ankit\Desktop\A51\hakios-a51`.
Linux root: `/opt/a51-hakios` inside the `A51-KernelBuilder` WSL distribution.
Windows project as seen from Linux: `/mnt/c/Users/Ankit/Desktop/A51/hakios-a51`.

Commands in logs are argument arrays rather than shell strings. Use the supplied scripts to avoid quoting differences between PowerShell and Bash.

## Current offline observation and entry-contract milestone

The [offline runtime-observation map](RUNTIME-MAP.md) is implemented and verified: 80 guards passed on Windows/native WSL, and the selected historical Linux projection replayed against the complete original capture on both hosts. It records five DRAM declarations (6,327,107,584 bytes), 20 fixed reservation spans, 112 exclusion records, three unresolved dynamic placements and zero verified owned intervals; all 27 diagnostic candidates are rejected. The [entry-route source review](ENTRY-CONTRACT.md) retains 29 source/config files and 24 cited facts, explaining native Image extent, Linux kexec restrictions and the upstream EFI ABI. The A51 ownership-certification importer, adapter, physical transitions, new-payload logs and demonstrated return remain unresolved. No phone query/write/reboot/payload execution occurred in this host-only continuation.

| Task | Guide |
|---|---|
| Import/replay historical Linux resources and inspect bounds, 80 guards, failures and rollback | [offline runtime-observation map](RUNTIME-MAP.md) |
| Inspect pinned native Image/Linux/EFI entry requirements and remaining device contracts | [entry-route source review](ENTRY-CONTRACT.md) |

## Read-only prerequisite milestone (P2-013)

The [connected A51 tests](DEVICE-PREREQUISITES.md) passed 33 of 35 read-only queries, with two true remote failures retained. Root, boot ID, Linux-exported FDT and kernel configuration were stable and matched the earlier Android capture. All eight CPUs were online. Module support and the rooted child’s module-loading capability are verified observations; exact module ABI and successful module execution remain unverified. Kexec remains disabled. Windows/WSL replay and three corruption checks passed. Current-session phone-query status is true; historical host/source/runtime flags remain unchanged. No phone write/reboot/module/payload execution occurred.

Selected supplement: `evidence/phase-2/device-prerequisites/20261111T121643948118Z/report.json`. Next: verify the exact installed module ABI and design a small allocation/logging diagnostic; actual A51 handoff, owned payload memory, physical transitions, payload/fault logs and Android/recovery return still require implementation and execution. Phase 2 remains in progress.

## Executed Android page diagnostic (P2-014)

The [one-page diagnostic](PAGE-PROBE.md) built against the matching installed kernel and passed actual A51 module load/unload, 4 KB zero/pattern checks and controlled failed-init cleanup. Seven lifecycle messages were retrieved, Android kept the same boot, both pages were released and the temporary module file was removed. All 20 rooted commands plus the transfer succeeded. Exact vermagic and nine imported CRCs matched; original Android source/output files remained unchanged. Windows/WSL offline replay passed. The out-of-tree taint flag changed from 0 to 4096 and remains after unload.

Selected host result: `evidence/phase-2/page-probe-build/20261111T124258280383Z/result.json`. Selected device result: `evidence/phase-2/page-probe-device/20261111T124942840876Z/result.json`. Current session phone-query/write flags are true for this temporary Android diagnostic; historical read-only/prototype/map/source records retain their original flags. Neither released page is a usable current payload destination. Standalone A51 loader execution, CPU/DMA/cache/MMU/interrupt handoff, persistent fault logs and demonstrated return remain unresolved. Phase 1 remains complete, Phase 2 in progress and its device gate false; Phases 3–10 remain planned. Next: define the payload memory budget and ownership/lifetime contract before implementing physical handoff.

| Task | Guide |
|---|---|
| Rebuild/replay the executed Android module, review one-page ownership lifetime and cleanup | [A51 page diagnostic](PAGE-PROBE.md) |

## Executed Android 64 KB arena diagnostic (P2-015)

The [64 KB arena diagnostic](ARENA-PROBE.md) passed actual A51 normal load/hold/unload and controlled failed-init cleanup. One 65,536-byte order-4 allocation was held with six region patterns, rechecked, cleared and released; two module Live records bracketed a one-second sleep. Seven lifecycle logs, all 23 rooted queries and one transfer succeeded. Android kept the same boot; the module and unique temporary file are absent. SELinux was Enforcing; existing taint stayed 4096. Both sequential lifetimes are released and cannot authorize current loader placement. The budget is a diagnostic allowance, not a final XNU memory budget.

Selected host result: `evidence/phase-2/arena-probe-build/20261111T132918243669Z/result.json`. Selected device result: `evidence/phase-2/arena-probe-device/20261111T133447277112Z/result.json`. Windows/WSL final replay and 10 budget mutations/nine lifetime rejections per host passed; 24 packet corruption cases were rejected on Windows. Exact vermagic and nine import CRCs matched, and original Android source/output metadata and pinned bytes remained unchanged. Phase 1 remains complete, Phase 2 in progress and every standalone launch/placement/handoff/fault-log/return gate false.

Next: implement a live lifetime-bound ownership certificate and loader-plan binding, then resolve actual A51 entry, CPU/MMU/cache/DMA/interrupt transitions, recoverable payload/fault logs and the demonstrated return procedure. No standalone payload or copied QEMU binary ran on the phone.


## Executed lifetime-bound plan diagnostic (P2-016)

The [allocation/plan diagnostic](OWNERSHIP-PROBE.md) passed on the A51: three fixed 64 KB plan bindings, seven rejected wrong/stale/released requests, ten state observations and 21 ordered kernel messages. All 23 rooted commands and the transfer succeeded. All three sequential allocations were cleared and released; Android kept the same boot and the module/file are absent. SELinux was Enforcing and existing taint stayed 4096. Native ASan/UBSan checks passed 1,408 assertions; all 17 import CRCs and exact vermagic matched. Windows/WSL replay and all 44 corruption guards per host passed.

Selected host result: `evidence/phase-2/ownership-probe-build/20261111T141326924789Z/result.json`. Selected device result: `evidence/phase-2/ownership-probe-device/20261111T141913580938Z/result.json`. The fixed plan is checked inside the allocation owner under one mutex; a receipt is historical once its callback returns. No external allocation certificate, loader-layout acceptance, copied payload or standalone execution is established. Current released addresses cannot authorize future placement. Phase 1 remains complete, Phase 2 in progress, and standalone launch/platform/fault-log/return gates remain false.

Next: define the bounded A51 diagnostic adapter execution/fault contract, then resolve standalone entry, CPU/MMU/cache/DMA/interrupt transitions, recoverable payload/fault logs and demonstrated return. See the new guide for exact commands, source provenance, failed offline checks and rollback.

## Android Linux callback CPU state (P2-017)

[CPU-STATE.md](CPU-STATE.md) records the matching-ABI module build, temporary A51 load/unload and eight reconstructed Linux callback records. All callbacks observed EL1, enabled MMU/data/instruction caches and a 26 MHz counter; CPUs 0–3 were Cortex-A53 and CPUs 4–7 Cortex-A73. Selected result: `evidence/phase-2/cpu-state-device/20261111T155948363876Z/result.json`, SHA-256 `6b6bcae092f51def03aa8b252e529eac644d59fb686798fec14c19fbc0078099`. This narrows Linux runtime state only; Samsung firmware/pre-Linux entry state and physical handoff remain unknown.

## Host-only early-entry candidate (P2-018)

[EARLY-ENTRY.md](EARLY-ENTRY.md) documents five synthetic QEMU cases/228 checks and the isolated link of a 36,334,080-byte Android Linux `Image`. Kernel result: `evidence/phase-2/early-entry-kernel/20261111T163522918342Z/result.json`; Image SHA-256 `87c0401361d4503afb0b266b15ff0caf1e64f505d61d53be700e8b6c6d8e9cf6`. The Image was never Samsung-packaged, installed or executed on the A51. No standalone HakiOS/XNU launch, exception-vector recovery, independent watchdog, persistent fault logger or Android/recovery return is verified. Phase 2 remains `in_progress` with its device gate false.

## Samsung boot-image packaging dry-run (P2-019)

Read [SAMSUNG-BOOT-DRY-RUN.md](SAMSUNG-BOOT-DRY-RUN.md) for the pinned Android v2 template/kernel inputs, four-region in-memory transformation, Windows/WSL tests, failed attempts, recovery and rollback. The calculated candidate SHA-256 is `73d88c699dda238238b7b2b1105caea248b9ef3aef282a3f01b566f0fd894a58`, but no candidate bytes or installable image were retained. This is host packaging evidence only; Samsung acceptance, A51 execution, persistent fault logging and demonstrated return remain unverified.

## Android baseline boot-loop recovery

[BOOTLOOP-RECOVERY.md](BOOTLOOP-RECOVERY.md) records the retained `TIMA_RKP_VMM_PANIC`, corrected `/data`/`vold` interpretation, two existing KernelSU modules, reversible disable markers, 52-poll/180-second same-boot stability result, privacy limits and rollback.

## Stackless fault envelope prototype (P2-020)

[FAULT-ENVELOPE.md](FAULT-ENVELOPE.md) documents the freestanding stackless exception vector implementation. It intercepted 34 exception vector cases (538 checks) across EL1 and EL2, SP0 and SPx, in QEMU without stack or heap allocation. Result SHA-256: `70e6a79858bcde7db56867c8b38735480633851f95b107216011982cd28c2f7a`; offline replay passed on Windows and native WSL.

## Samsung boot candidate and Odin packaging (P2-021)

Emitted and verified the 61,865,984-byte boot candidate (`A51-HakiOS-P2-018-Early-Entry-boot.img`, SHA-256 `73d88c699dda238238b7b2b1105caea248b9ef3aef282a3f01b566f0fd894a58`) and the 61,870,080-byte POSIX ustar Odin archive (`A51-HakiOS-P2-018-Early-Entry-boot.tar`, SHA-256 `5d6baadac5be7b94b292f4dcccc964e2be0c40744cbfb2d990aa70d087cc4f09`). Verification runs passed on Windows and native WSL exit 0, confirming all four changed regions and four rollback images.

## Hardware entry observation and baseline restoration (P2-022)

Phase 2 remains **IN PROGRESS**; its device gate is **UNPASSED**. The P2-022 hardware record verifies Samsung acceptance, early-entry state capture at EL1 and successful baseline restoration, but `status=2` (`HKE_INVALID_DAIF`), `reason=1` and a zero payload marker prove that the minimal arithmetic payload was skipped. The earlier completion claim is superseded by the [completion review](PHASE-2-COMPLETION-REVIEW.md).

The review script checks retained hashes, exact record correspondence to original output, linked source pins, failed execution predicates and restoration records. Run through `scripts/run.py`; audit exit 0 reports a completed review, while its structured device gate remains false.

Phase 4 platform diagnostics/SPI and corrected C loader have host/QEMU evidence; silicon execution and real peripheral drivers remain pending. See docs/PHASE-4-DEVICE-PATH.md.
