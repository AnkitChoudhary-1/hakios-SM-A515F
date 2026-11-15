> Publication note: this is a historical workspace document. Current completion decisions are in [PUBLIC-STATUS.md](PUBLIC-STATUS.md); raw local evidence is described in [PUBLICATION.md](PUBLICATION.md).

# Where everything is and how to view it

## Windows workspace

Open `C:\Users\Ankit\Desktop\A51\hakios-a51` in an editor. Start with README.md, docs/STATE.md and docs/INDEX.md.

| Location | Purpose | How to use it |
|---|---|---|
| `C:\Users\Ankit\Desktop\A51\AGENTS.md` | Instructions for future AI agents | Read before modifying project files |
| `hakios-a51\docs\` | Architecture, baseline, commands, editing, audit, history, handoff | Read the index in order; update with every change |
| `hakios-a51\scripts\` | Recorded execution, inventories, setup, build, validation | Follow BUILD.md; Windows Python scripts and WSL scripts are labeled |
| `hakios-a51\manifests\` | Current machine-readable inventories, dependency hashes, versions | JSON/TSV files; values are evidence with capture times |
| `hakios-a51\manifests\inventory-snapshots\` | Historical device/input inventories | UTC-named JSON; current manifest can change without losing these |
| `hakios-a51\runs\` | Exact command arrays, working directories, stdout/stderr, statuses | Select a timestamped run and read metadata.json and output.log |
| `hakios-a51\evidence\build-snapshots\` | Nested logs and source/artifact identities | Needed because upstream inner logs are overwritten on the next build |
| `hakios-a51\evidence\phase-2\boot-audit\<UTC>\` | Retained-image report, checksum index, extracted `dt/` blobs and `references/` copies | Inspect the timestamped report; verify against original image/source bytes with `audit-boot-inputs.py --verify-report` |
| `hakios-a51\evidence\phase-2\libfdt\<UTC>\` | Independent FDT cross-check, command records/output and checksum index | `check-boot-audit-libfdt.py --verify-result` reads existing evidence; a fresh cross-check runs in WSL |
| `hakios-a51\manifests\boot-audit-current.json`, `libfdt-check-current.json` | Latest successful Phase 2 host evidence pointers | Historical claims use explicit report/result paths and hashes rather than these replaceable pointers |
| `hakios-a51\docs\PHASE-2-HOST-AUDIT.md`, `LOADER-DESIGN.md` | Host findings, failure history and pending loader requirements | Read before choosing any A51 address or entry route |
| `hakios-a51\scripts\payload_layout.py`, `validate-payload-layout.py`, `test-payload-layout.py` | Implemented host manifest contract, capture/replay and 92 guards | Use PAYLOAD-LAYOUT.md and recorded BUILD.md commands; synthetic acceptance does not establish A51 ownership |
| `hakios-a51\evidence\phase-2\layout\<UTC>\` | Exact manifests, result, checksum index and synthetic inputs | Selected demonstrations have 4/22 indexed files; `validate-payload-layout.py --verify-result` reconstructs their outcomes |
| `hakios-a51\manifests\payload-layout-current.json` | Latest completed layout check, outcome/counts and result hash | May select a rejected candidate; inspect operation and `expected_checks_passed`, and use timestamped paths for historical claims |
| `hakios-a51\docs\PAYLOAD-LAYOUT.md` | Contract fields, bounds, provenance, evidence semantics, failures and recovery | Read alongside LOADER-DESIGN.md; no runtime ownership importer or device destination is implemented |
| `hakios-a51\scripts\source_trace.py`, `trace-loader-sources.py`, `test-source-trace.py` | Retained-source/config/FDT capture, original-byte reconstruction and 35 guards per host | Use SOURCE-TRACE.md and BUILD.md; mutually exclusive `--capture` / `--verify-trace` never contact the phone |
| `hakios-a51\manifests\loader-source-trace.json`, `loader-source-trace-current.json` | Reviewed source/excerpt/config specification and latest verified report pointer | Historical replay uses each capture's retained specification; pin the explicit report path/hash for claims |
| `hakios-a51\evidence\phase-2\source-trace\<UTC>\` | Report/index, specification, three inputs, full sources, numbered excerpts, base FDTs and tools | Selected capture has 28 sources/40 excerpts/three FDTs/22 symbols/six tools/82 indexed files; replay also requires original inputs |
| `hakios-a51\docs\SOURCE-TRACE.md` | Entry/FDT/memory/log/reset findings, provenance, bounds, failures, commands and rollback | Recorded Android lineage is not a verified Git HEAD; runtime ownership/log retrieval/return remain unknown |
| `hakios-a51\docs\CPU-STATE.md` | P2-017 matching-ABI Android Linux callback-state diagnostic | Review eight per-CPU EL/register records, cleanup, selected evidence and the firmware/pre-Linux claim boundary |
| `hakios-a51\docs\EARLY-ENTRY.md` | P2-018 host-only early-entry candidate and isolated Linux Image link | Review five QEMU cases, 228 checks, the experimental Image identity, packet limitations and recovery |
| `hakios-a51\patches\` | Local adaptations to pinned upstream, when needed | Read each patch's purpose before applying |
| `hakios-a51\state.json` | Machine-readable phase status, gates and evidence | Keep consistent with docs/STATE.md and roadmap |
| `hakios-assessment\` | Initial feasibility, effort assessment and ten-phase roadmap | Historical assessment plus roadmap; execution evidence lives in hakios-a51 |
| `hakios-assessment\sources\` | Selected research files and complete GitHub tree listings | A research snapshot, not a buildable source checkout |
| `kernel-work\source\` | Retained Samsung/Exynos Linux driver and DTS references | Read and cite; avoid editing this Android project for HakiOS work |
| `everline-ksu\backups\` | Original Android boot, DTBO and TWRP recovery images | Preserve originals and their hashes |
| `everline-ksu\artifacts\` | Existing Linux kernel/configuration and repack validation | Separate Android Linux project; Shell root is verified, while A51 HakiOS execution remains unproved |

Paths in the first column below are inside the `A51-KernelBuilder` WSL distribution. In Windows Explorer, paste `\\wsl.localhost\A51-KernelBuilder\opt\a51-hakios` to view them. In PowerShell, `Get-Content -LiteralPath` can read a file via that UNC path. Compile on the WSL filesystem to preserve Unix behavior and avoid Windows filesystem overhead.

## Linux project

The completed Phase 1 bundle is `C:\Users\Ankit\Desktop\A51\hakios-a51\evidence\phase-1\20261111-final`. Its `index.json` lists checksum-covered copies and `verification.json` records gate verification. The explicit selection is `manifests/phase-1-evidence.json`; `scripts/verify-phase1.py` validates live inputs or an existing bundle. Preserve both archived roadmap copies: `evidence/phase-1-reference/ROADMAP-20261110.md` retains the original inventory-hashed bytes, and `ROADMAP-20261111.md` retains the Phase 1 completion document. The current roadmap now records Phase 2 progress and is intentionally different. Commands and limits are in BUILD.md and REVIEW-20261111.md.

Current Phase 2 selections: `evidence/phase-2/boot-audit/20261111T022538476271Z/report.json` (25 indexed files, including 11 FDTs and 13 references) and `evidence/phase-2/libfdt/20261111T022902468010Z/result.json` (73 indexed files, 1,380 compared properties). Reports keep original Windows image paths and logical WSL source paths; `audit-boot-inputs.py` maps them to `/mnt/c` on Linux or `\\wsl.localhost\A51-KernelBuilder` on Windows. The full Android checkout `/opt/a51-everline/src` was read only. SoC DTS/reservations are under `arch/arm64/boot/dts/exynos/exynos9610*`; A51 board/revision definitions are under `arch/arm64/boot/dts/samsung/exynos9611-a51*`.

Host scripts: `boot_formats.py` parses bounded boot/table/FDT/Image structures; `audit-boot-inputs.py` creates or verifies original-byte reports; `test-boot-formats.py` and `test-boot-audit.py` exercise parser and evidence rejection behavior; `check-boot-audit-libfdt.py` performs WSL cross-validation or checksum readback. `payload_layout.py` reuses the bounded parser and original-byte report verifier; `validate-payload-layout.py` captures and reconstructs indexed cases, and `test-payload-layout.py` supplies 92 guards. Host/QEMU loader source now lives in `prototype/loader/`; an A51 adapter, runtime ownership importer and experimental XNU checkout remain absent.

Selected layout records: `evidence/phase-2/layout/20261111T033005872222Z/result.json` (one accepted synthetic case/four indexed files) and `evidence/phase-2/layout/20261111T033104768751Z/result.json` (21 expected A51 rejections/22 indexed files). The current layout pointer selects the latter. The validator maps logical `/opt/` inputs through WSL UNC paths on Windows and Windows inputs through `/mnt/c/` on Linux; both results replayed on both hosts. Version 1 accepts synthetic assumptions only and retains false device/placement/destination flags. [PAYLOAD-LAYOUT.md](PAYLOAD-LAYOUT.md) retains exact hashes and run IDs.

| WSL path | Contents |
|---|---|
| `/opt/a51-hakios/src/hakios-xnu-kernel` | Full pinned HakiOS checkout |
| `/opt/a51-hakios/theos/toolchain/linux/iphone/bin` | Dedicated Mach-O toolchain; system clang remains the XNU compiler |
| `/opt/a51-hakios/theos/sdks-git` | Pinned, sparse SDK checkout |
| `/opt/a51-hakios/theos/sdks/iPhoneOS16.5.sdk` | Symlink to the selected SDK |
| `/opt/a51-hakios/downloads` | Retained original toolchain and SDK archives, checksum file |
| `/mnt/c/Users/Ankit/Desktop/A51/hakios-a51` | This documentation/evidence project as seen in Linux |
| `/opt/a51-everline` | Separate existing Android build; preserve it |

## Upstream checkout file map

All paths here are relative to `/opt/a51-hakios/src/hakios-xnu-kernel`.

| Path | Role and modification guidance |
|---|---|
| `Makefile` | Public target list; do not run phone targets for a QEMU baseline |
| `configs/`, `.config` | Input fragments and generated chosen configuration; edit fragments for durable behavior |
| `tools/hakios-config.py` | Configuration parsing, kernel selection and boot arguments |
| `devices/`, device manifest and `tools/hakios-device.py` | External device/SoC source organization; no A51 entry exists at the pin |
| `drivers/` | Common XNU drivers and overlays; durable driver edits originate here |
| `xnu/patches/`, `xnu/files/` | HakiOS changes applied to Apple XNU |
| `xnu/apply.sh`, `xnu/sync-drivers.sh` | Generated source preparation and driver synchronization |
| `xnu-src/xnu-8796.121.2/` | Generated patched XNU tree; retain changes as source patches before regeneration |
| `xnu-src/xnu-8796.121.2/BUILD/` | Rebuildable headers, objects and kernel intermediates |
| `xnu-deps/setup.sh`, `xnu-deps/host/bin/` | Dependency preparation and wrappers/host tools |
| `xnu-deps/sdk/iPhoneOS16.5.xnu.sdk` | Generated SDK overlay |
| `xnu-env.sh`, `xnu-build.sh`, `tools/make-kernel.sh` | Environment, compiler invocation, build failure classification |
| `xnuloader/` | EFI loader, placeholder identity and payload packer |
| `userland/src/hello.c`, `userland/hello` | Minimal source and built raw-syscall Mach-O program |
| `userland/build.sh`, `userland/src/` | Larger Darwin image integration and compatibility sources |
| `qemu/run.sh`, `qemu/esp/`, `qemu/vars.fd` | QEMU invocation, generated EFI filesystem, disposable firmware variables |
| `hakios-kernel`, `xnuloader/loader.efi`, `qemu/payload.bin` | Source-built outputs; verify freshness and hashes |
| `prebuilt/` | Retained upstream binaries; do not use as evidence of our source build |
| `docs/porting/`, `docs/uefi-boot.md`, `docs/configs.md` | Upstream design and configuration guidance; other-phone instructions need A51 review |

For search use `rg --files` and `rg -n PATTERN PATH`. WSL now has ripgrep. Prefer targeted searches: several versions of Mali and many board variants coexist in the Samsung tree.

## Privileged live observation files

| Path | Purpose |
|---|---|
| `scripts/capture-live-loader.py`, `test-live-loader.py` | Fixed 49-query read-only capture, schema-2 original-byte replay and 41 host guards |
| `manifests/live-loader-current.json` | Selects the corrected 153-file live report |
| `evidence/phase-2/live-loader/<UTC>/` | Report, index, exact response/stdout/host-stderr triples, tools and three base FDTs |
| `evidence/phase-2/live-fdt-libfdt/<UTC>/` | Independently compared live FDT, raw commands/tool identities and 14-file result |
| `evidence/phase-2/live-handoff-docs/20261111T073251238016Z/` | Indexed pre-synchronization copies of 16 current documents/state/roadmap |
| `docs/LIVE-OBSERVATIONS.md` | Scope, findings, remote failures, replays, source distinctions and rollback |

Native WSL validation copies live separately at `/opt/a51-hakios/validation/live-loader/20261111T071559056361Z`; the accepted upstream and Android projects are preserved. The host/QEMU loader prototype is separate; no A51 adapter, experimental Samsung image or A51 XNU driver exists yet.

## Host/QEMU loader prototype

| Path | Purpose |
|---|---|
| `prototype/loader/probe.h`, `probe.c` | Freestanding synthetic-arena core, entry/callback interfaces and seven CRC32 frames |
| `prototype/loader/test_probe.c` | Native sanitizer harness: 2,609 bounds, callback, memory and frame assertions |
| `prototype/loader/qemu/start.S`, `main.c`, `virt.ld` | Capture virtual entry, provide actual C stack, execute trusted payload, output PL011 frames and request QEMU shutdown |
| `scripts/build-loader-probe.py`, `test-loader-probe-evidence.py` | Isolated build/native/QEMU execution, indexed capture/replay and corruption/semantic guards |
| `scripts/check-loader-probe-handoff.py` | Read-only selected-result/state/link/run-role checks and preservation of the Phase 1 bundle and documentation rollback copies |
| `manifests/loader-probe-current.json` | Latest fully successful, self-verified result pointer |
| `evidence/phase-2/loader-probe/<UTC>/` | Seven source copies, generated identity, three binaries, identity inputs and 14 command JSON/stdout/stderr triples; result and checksum index |
| `/opt/a51-hakios/prototype/loader/<UTC>/` in WSL | Isolated native source/object/binary working directory; no upstream edit |
| `docs/LOADER-PROTOTYPE.md` | Interfaces, wire offsets, trust boundary, selected hashes, commands and recovery |
| `evidence/phase-2/loader-probe-docs/20261111T102921621458Z/` | Indexed rollback copies of 13 pre-prototype documents/state/roadmap |

The prototype's QEMU `0x40080000`/PL011/PSCI constants are virtual-machine settings, with no A51 placement or reset claim. Replay reads retained bytes and executes no artifacts. Rebuilds always create new timestamped directories; preserve the first accepted build and all failed attempts.

## Current offline observation and entry-contract milestone

The [offline runtime-observation map](RUNTIME-MAP.md) is implemented and verified: 80 guards passed on Windows/native WSL, and the selected historical Linux projection replayed against the complete original capture on both hosts. It records five DRAM declarations (6,327,107,584 bytes), 20 fixed reservation spans, 112 exclusion records, three unresolved dynamic placements and zero verified owned intervals; all 27 diagnostic candidates are rejected. The [entry-route source review](ENTRY-CONTRACT.md) retains 29 source/config files and 24 cited facts, explaining native Image extent, Linux kexec restrictions and the upstream EFI ABI. The A51 ownership-certification importer, adapter, physical transitions, new-payload logs and demonstrated return remain unresolved. No phone query/write/reboot/payload execution occurred in this host-only continuation.

New project files: `scripts/runtime_observations.py`, `import-runtime-map.py`, `test-runtime-map.py` and `check-runtime-map-handoff.py`; `docs/RUNTIME-MAP.md` and `ENTRY-CONTRACT.md`; `manifests/runtime-map-current.json`; ten indexed projection files under `evidence/phase-2/runtime-map/20261111T113849417244Z/` and 30 source/indexed files under `evidence/phase-2/entry-route/20261111T112915805884Z/`. Native guard tools are under `/opt/a51-hakios/validation/runtime-map/20261111T1138Z/`, with `stage-manifest.json` retaining all five tool identities. Replays require the complete original capture and unchanged Android/source inputs.

## Android diagnostic additions

| Location | Contents |
|---|---|
| `diagnostics/page-probe/` | Bounded one-page kernel module source and Makefile |
| `scripts/build-page-probe.py` | Isolated matching-ABI host build and import validation |
| `scripts/test-page-probe-device.py` | Serial-bound temporary module test, cleanup and offline replay |
| `scripts/check-page-probe-handoff.py` | Current diagnostic/historical evidence preservation |
| `docs/PAGE-PROBE.md` | Interfaces, observed lifetime, results, limitations and recovery |
| `evidence/phase-2/page-probe-build/` and `page-probe-device/` | Frozen build/runtime packets |
| `/opt/a51-hakios/diagnostics/page-probe/<timestamp>/` | Isolated source, headers, tools and module build |

## P2-015 arena files

- `diagnostics/arena-probe/`: fixed-size module, Makefile and generated budget header.
- `manifests/arena-probe-budget.json`: pinned diagnostic allowance.
- `scripts/arena_probe.py`, `build-arena-probe.py`, `test-arena-probe-device.py`, `test-arena-probe.py`, `test-arena-probe-evidence.py`, `check-arena-probe-handoff.py`: budget/lifetime import, isolated build, bounded capture/replay, guards and handoff.
- `evidence/phase-2/arena-probe-{preparation,build,device,corruption,docs}/`: retained inputs, packets, failed/changed fixtures, rollback and synchronization program.
- `/opt/a51-hakios/diagnostics/arena-probe/20261111T132918243669Z`: isolated WSL build; existing Android projects are separate.

Read [64 KB arena diagnostic](ARENA-PROBE.md) before a new test.


## Executed lifetime-bound plan diagnostic (P2-016)

The [allocation/plan diagnostic](OWNERSHIP-PROBE.md) passed on the A51: three fixed 64 KB plan bindings, seven rejected wrong/stale/released requests, ten state observations and 21 ordered kernel messages. All 23 rooted commands and the transfer succeeded. All three sequential allocations were cleared and released; Android kept the same boot and the module/file are absent. SELinux was Enforcing and existing taint stayed 4096. Native ASan/UBSan checks passed 1,408 assertions; all 17 import CRCs and exact vermagic matched. Windows/WSL replay and all 44 corruption guards per host passed.

Selected host result: `evidence/phase-2/ownership-probe-build/20261111T141326924789Z/result.json`. Selected device result: `evidence/phase-2/ownership-probe-device/20261111T141913580938Z/result.json`. The fixed plan is checked inside the allocation owner under one mutex; a receipt is historical once its callback returns. No external allocation certificate, loader-layout acceptance, copied payload or standalone execution is established. Current released addresses cannot authorize future placement. Phase 1 remains complete, Phase 2 in progress, and standalone launch/platform/fault-log/return gates remain false.

Next: define the bounded A51 diagnostic adapter execution/fault contract, then resolve standalone entry, CPU/MMU/cache/DMA/interrupt transitions, recoverable payload/fault logs and demonstrated return. See the new guide for exact commands, source provenance, failed offline checks and rollback.

## P2-017 CPU-state diagnostic files

| Location | Contents |
|---|---|
| `diagnostics/cpu-state/` | Capture-only AArch64 Android kernel module; it reads architectural state without writing system registers or invoking a payload |
| `scripts/build-cpu-state.py`, `test-cpu-state-device.py`, `test-cpu-state-evidence.py` | Isolated ABI build, bounded device capture/offline replay and eight corruption guards |
| `evidence/phase-2/cpu-state-build/20261111T155623575651Z/` | Selected 27-file build packet and 156,840-byte module |
| `evidence/phase-2/cpu-state-device/20261111T155948363876Z/` | Selected 75-file A51 packet; result SHA-256 `6b6bcae092f51def03aa8b252e529eac644d59fb686798fec14c19fbc0078099` |
| `docs/CPU-STATE.md` | Observed EL1/A53/A73/cache/MMU/counter facts, Linux-callback-only scope, commands and rollback |

The selected module and temporary file were removed. These records describe Android Linux callbacks, not Samsung firmware or pre-Linux entry state, and establish no reusable payload placement or physical handoff.

## P2-018 early-entry candidate files

| Location | Contents |
|---|---|
| `prototype/early-entry/` | Fixed 256-byte record, AArch64 candidate, synthetic QEMU harness, preparation source and detailed source contract |
| `scripts/build-early-entry-kernel.py`, `early_entry_evidence.py`, `test-early-entry-evidence.py` | Isolated Android kernel link, strict phone-free replay and nine focused corruption classes |
| `evidence/phase-2/early-entry-host/20261111T162536291908Z/` | Five QEMU cases and 228 checks; packet predates the indexed format |
| `evidence/phase-2/early-entry-prepare/20261111T163522918342Z/` | Pinned six-path adaptation and patch; packet predates the indexed format |
| `evidence/phase-2/early-entry-kernel/20261111T163522918342Z/` | Indexed host build and 36,334,080-byte Linux `Image`, SHA-256 `87c0401361d4503afb0b266b15ff0caf1e64f505d61d53be700e8b6c6d8e9cf6` |
| `docs/EARLY-ENTRY.md` | Evidence boundary, flow, selected identities, limitations, reproduction and rollback |

The host/preparation packets lack indexes, their QEMU `.bin` files were not retained, `vmlinux` remains external/unindexed, most original build-input bytes are not packet-retained, and the kernel build reused copied output rather than starting clean. Unsupported-EL and oversized-CTR paths lack executed coverage, and the nine corruption classes are focused rather than exhaustive. The Image was never Samsung-packaged, installed or executed on the A51. Phase 2 remains `in_progress`; exception vectors, watchdog/persistent fault logging, bounded platform transitions and demonstrated return remain unresolved.

## P2-019 Samsung boot dry-run files

| Location | Contents |
|---|---|
| `docs/SAMSUNG-BOOT-DRY-RUN.md` | P2-019 input pins, four-region transformation, candidate-digest semantics, verification, failures, recovery and rollback |
| `scripts/samsung_boot_dry_run.py` | Strict Android v2/ARM64/unsigned-AVB parser and in-memory reconstruction logic |
| `scripts/capture-samsung-boot-dry-run.py` | Report-only capture; deliberately emits no candidate bytes |
| `scripts/verify-samsung-boot-dry-run.py`, `test-samsung-boot-dry-run.py`, `test-samsung-boot-dry-run-evidence.py` | Semantic replay, 11 core cases per host and 30 evidence guards per host |
| `scripts/check-samsung-boot-dry-run-handoff.py` | Aggregate P2-019 documentation/evidence/state and P2-017/P2-018 regression checker |
| `evidence/phase-2/samsung-boot-dry-run/20261112T010401492946Z/` | Seven indexed report/source records totaling 58,533 bytes; no `.img` or candidate byte range |

The calculated 61,865,984-byte in-memory candidate has SHA-256 `73d88c699dda238238b7b2b1105caea248b9ef3aef282a3f01b566f0fd894a58`. It is an identity, not a retained or installable image. Existing Android/upstream projects, backups and the 264-file Phase 1 bundle remain separate and unchanged.
