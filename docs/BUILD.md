> Publication note: this is a historical workspace document. Current completion decisions are in [PUBLIC-STATUS.md](PUBLIC-STATUS.md); raw local evidence is described in [PUBLICATION.md](PUBLICATION.md).

# Build, run and rebuild

This runbook covers Phase 1's QEMU baseline and Phase 2's retained-image audit, host payload-layout checks, retained-source tracing, live observation replay, host/QEMU loader prototype, CPU-state evidence replay and host-only early-entry evidence replay. Run Windows commands in PowerShell from `C:\Users\Ankit\Desktop\A51\hakios-a51`. WSL commands run as root in `A51-KernelBuilder`. The commands added for P2-017/P2-018 below replay retained evidence only and do not contact the phone.

## Setup on this host

Windows requires Python 3, Git, WSL and ADB for device inventory. The existing WSL distribution is Ubuntu 24.04. Keep the Linux source under `/opt/a51-hakios` and the evidence under this Windows project. The scripts currently contain these absolute paths; when moving to another machine, update all occurrences together and record the change.

```powershell
Set-Location C:\Users\Ankit\Desktop\A51\hakios-a51
python .\scripts\run.py --label host-inventory -- wsl -d A51-KernelBuilder -u root -- bash /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/inspect-host.sh
python .\scripts\run.py --label source-bootstrap -- wsl -d A51-KernelBuilder -u root -- bash /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/bootstrap-source.sh
python .\scripts\run.py --label install-host -- wsl -d A51-KernelBuilder -u root -- bash /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/install-host.sh
python .\scripts\run.py --label acquire-deps -- wsl -d A51-KernelBuilder -u root -- python3 /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/acquire-deps.py
```

The main source pin is `63fc2b4633bac3af8e57dadab9f5a8d4cb940438`. The SDK pin and archive hashes are in `manifests/dependencies.json`. Source identities are checked by `verify-sources.py` after upstream dependency setup. A different commit or unexpected modification fails verification. The generated XNU tree intentionally contains HakiOS's overlay; its dirty status is captured rather than rejected.

Ubuntu's package repository supplies host tools. `manifests/ubuntu-packages.tsv` records installed versions; rerunning apt later is not guaranteed to install the identical package set. Keep the recorded versions when reproducing an issue. The toolchain archive's initial hash is local provenance; the macOS SDK archive was checked against its release checksum. SDKs are build inputs, not the Darwin runtime.

## Build and execute

```powershell
python .\scripts\run.py --label build-open -- wsl -d A51-KernelBuilder -u root -- bash /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/build-open.sh
python .\scripts\run.py --label qemu-open -- wsl -d A51-KernelBuilder -u root -- python3 /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/qemu-open.py --seconds 180
```

Run these sequentially. The build sets a dedicated THEOS directory, requests two jobs, overrides XNU's recursive `MAKEJOBS`, and uses Bash for make recipes because `xnu-env.sh` uses Bash syntax. It writes `.config`, applies the source if absent, prepares headers/support libraries, validates source pins, builds the named kernel and placeholder EFI loader, compiles hello and packs the RAM payload. Default config includes 25 common drivers in the binary; their phone-specific runtime switches are not enabled by `cpus=1`. Their presence is not hardware support.

The kernel build has an upstream exception for kext symbol-set/export checks. `tools/make-kernel.sh` accepts only those known failures and verifies a final kernel exists. Compiler/link/debug-symbol errors still fail. Keep this classification intact.

Outputs in `/opt/a51-hakios/src/hakios-xnu-kernel`:

| Output | Meaning |
|---|---|
| `hakios-kernel` | Source-built ARM64 Mach-O kernel |
| `xnuloader/loader.efi` | Source-built ARM64 UEFI application with placeholder identity |
| `userland/hello` | Static Mach-O, raw system calls, no dyld/libc |
| `qemu/payload.bin` | Packed kernel, hello, boot arguments and kernel version |

Build snapshots preserve their sizes, hashes, file identification, configuration, nested logs and source/tool identities. An EXIT trap captures a failed build too. Artifact existence alone is not success. QEMU preflight checks captured hashes and requires all four local outputs, preventing the upstream missing-loader fallback to `prebuilt/`.

`qemu-open.py` records raw serial bytes under `evidence/qemu/<UTC>/serial.log` and a structured `result.json`. Its own exit 0 means acceptance checks passed. `runner_exit_code` records the upstream runner's real exit, including timeout 124. Read the markers and panic reason, not just the exit status. QEMU uses `virt`, GICv3, Cortex-A76, one CPU, 6 GiB guest RAM, TCG with a 384 MiB translation cache and Ubuntu AAVMF. This configuration does not emulate Exynos 9611.

The parser requires the user program's matching kernel-version sysctl result before the first panic; the loader banner alone is insufficient. Its false-acceptance guards use a retained real transcript:

```powershell
python .\scripts\run.py --label qemu-acceptance-guards -- python .\scripts\test-qemu-acceptance.py
```

The fixture `evidence/qemu/20261110T163402791610Z/serial.log` must remain available for this check. It tests rejection of missing/wrong user output, earlier/unrelated panic, failed exit and abnormal runner termination; it is not a hardware test. Final Phase 1 observations, elapsed time and immutable artifact/log identities are in [PHASE-1-RESULTS.md](PHASE-1-RESULTS.md).

## Verify and retain completed Phase 1 evidence

The explicit historical selections are in `manifests/phase-1-evidence.json`. Verification checks retained successful run metadata, build/QEMU identities and raw serial acceptance, current `/opt` artifacts/source/SDK/archive identities, the original read-only inventory and hardware/research hashes, and current completion-state markers. It does not rebuild or contact the phone. Run it in WSL:

```powershell
python .\scripts\run.py --label verify-phase1 -- wsl -d A51-KernelBuilder -u root -- python3 /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/verify-phase1.py
python .\scripts\run.py --label phase1-bundle-guards -- python .\scripts\test-phase1-bundle.py
python .\scripts\run.py --label verify-phase1-bundle -- wsl -d A51-KernelBuilder -u root -- python3 /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/verify-phase1.py --verify-bundle evidence/phase-1/20261111-final
```

To retain a new bundle after successful verification, add `--bundle evidence/phase-1/<new-name>` to the first command. Existing directories are rejected. The completed bundle is `evidence/phase-1/20261111-final`; `index.json` covers copied documentation/manifests/scripts, selected runs, build/QEMU logs and immutable inventory. `verification.json` records scope/counts. Verification of an existing bundle only checks its copied files and does not require live `/opt` artifacts. Four guard cases verify valid copies and rejection of same-size corruption, missing files and path escape.

The historical inventory hashed the old roadmap. Its original bytes are now retained under `evidence/phase-1-reference/ROADMAP-20261110.md`; the verifier checks that explicit archived input. Android backup/source inputs keep their original identities. All later evidence selections must be deliberate, with matching new build/QEMU records; do not silently redirect a historical claim to a current manifest.

`evidence/phase-1-reference/ROADMAP-20261111.md` also preserves the Phase 1 completion roadmap. Phase 2 updates the current roadmap; neither archived copy nor the 264-file completion bundle should be overwritten or required to equal current documentation.

The checksum index is local integrity evidence, not independent authentication. The large `/opt` artifacts and external Android backups remain at recorded paths. The run creating a bundle finalizes after the ledger snapshot, so its metadata must be read from the main `runs/` directory. See [review findings](REVIEW-20261111.md).

## Clean rebuild acceptance

```powershell
python .\scripts\run.py --label clean-rebuild-open -- wsl -d A51-KernelBuilder -u root -- bash /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/clean-rebuild.sh
python .\scripts\run.py --label qemu-after-clean -- wsl -d A51-KernelBuilder -u root -- python3 /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/qemu-open.py --seconds 180
```

The clean script first preserves evidence, checks the resolved project path, and removes only named generated outputs: XNU BUILD, loader object/EFI/identity, hello, named kernel, payload, QEMU ESP and variable file. It then rebuilds exported headers and the two support libraries with `--rebuild-libs`, plus all kernel/loader/hello outputs. It retains source, host tools, downloaded inputs, logs and every Android project. This is a clean output rebuild with cached pinned dependencies, not a new Ubuntu installation or byte-identical build. Kernel version timestamps and PE timestamps can change hashes between runs.

Do not run builds concurrently against this checkout, edit scripts mid-run, or use upstream `make clean` as an undocumented substitute. If a fresh source regeneration is needed, preserve/export edits and use a separate checkout; `xnu/apply.sh` refuses an existing tree.

## Phase 2 host audit and evidence readback

The [host audit](PHASE-2-HOST-AUDIT.md) documents verified retained Android v2 images, DT table v0/FDT v17 parsing, Linux Image extents and declared memory. The [loader requirements](LOADER-DESIGN.md) record unresolved entry, ownership, log and return work. These commands read existing inputs and do not contact the phone:

```powershell
python .\scripts\run.py --label boot-format-guards -- python .\scripts\test-boot-formats.py
python .\scripts\run.py --label boot-audit-guards -- python .\scripts\test-boot-audit.py
python .\scripts\run.py --label retained-boot-readback -- python .\scripts\audit-boot-inputs.py --verify-report evidence/phase-2/boot-audit/20261111T022538476271Z/report.json
python .\scripts\run.py --label libfdt-readback -- python .\scripts\check-boot-audit-libfdt.py --verify-result evidence/phase-2/libfdt/20261111T022902468010Z/result.json
```

The 36 parser guards and 13 audit-integrity guards passed. Report readback checks 25 indexed files, 18 original hashes and reconstructs all 11 FDT summaries from original image bytes. It needs the original Android images/config/repack record and recorded Linux files at their Windows/WSL paths. Libfdt readback checks 73 indexed files plus linked report/blob hashes; it does not rerun libfdt or replace original-image verification.

When intentionally generating new host evidence, run sequentially:

```powershell
python .\scripts\run.py --label retained-boot-audit -- python .\scripts\audit-boot-inputs.py
python .\scripts\run.py --label libfdt-crosscheck -- wsl -d A51-KernelBuilder -u root -- python3 /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/check-boot-audit-libfdt.py
```

The cross-check defaults to `manifests/boot-audit-current.json`; pass `--report evidence/phase-2/boot-audit/<UTC>/report.json` to select a particular report. Each successful creation retains a new timestamped folder and then updates its current pointer. Preserve failed/draft runs and use each historical run's `project-scripts/` for its parser version; the final parser rejects superseded semantic summaries.

The cross-check used existing WSL `fdtget` and `fdtdump`, DTC 1.7.0 (`device-tree-compiler`/`libfdt1` `1.7.0-2build1`). It retained all 36 tool commands, output and tool identities; 11 FDTs and 1,380 properties matched. No host dependency was installed for this work. No overlays are applied. Declared reservation gaps are not a loader allowlist; `safe_for_loader_placement` remains false. In particular, the QEMU address `0xF0000000` is within declared modem memory.

## Phase 2 host payload-layout checks

The [payload-layout guide](PAYLOAD-LAYOUT.md) documents the implemented version 1 contract, limits, input provenance, selected hashes, failure history and recovery. All 92 guards passed on each host. Version 1 accepts synthetic host assumptions only; the A51 runtime ownership importer, adapter and device probe remain unimplemented. The separate host/QEMU prototype below does not select a device layout.

```powershell
python ./scripts/run.py --label payload-layout-guards -- python ./scripts/test-payload-layout.py
python ./scripts/run.py --label payload-layout-guards-wsl -- wsl -d A51-KernelBuilder -u root -- python3 /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/test-payload-layout.py
python ./scripts/run.py --label layout-synthetic-readback -- python ./scripts/validate-payload-layout.py --verify-result evidence/phase-2/layout/20261111T033005872222Z/result.json
python ./scripts/run.py --label layout-a51-readback -- python ./scripts/validate-payload-layout.py --verify-result evidence/phase-2/layout/20261111T033104768751Z/result.json
```

The selected synthetic result contains one accepted case/four indexed files; the selected A51 result contains 21 expected rejections/22 indexed files. Both replayed on Windows and WSL. Replay verifies bounded indexed files and reconstructs outcomes from pinned inputs; it creates no new layout result and does not contact the phone. A51 input resolution requires the recorded Android images and WSL source files. The guide explains both host path mappings and intentional fresh captures.

`--manifest` exits 1 for a rejected candidate. A51 demonstration exit 0 means all expected rejections and required diagnostics matched. `--verify-result` exits 0 when evidence reconstructs, including rejected layouts. `manifests/payload-layout-current.json` selects the A51 rejection demonstration; a later completed rejected candidate can replace it with `expected_checks_passed=false`. Read the result's assessment, operation and counts. Every device/placement/destination flag remains false, and `0xF0000000` remains excluded by the declared modem reservation.

## Phase 2 retained-source capture and replay

The [source-trace guide](SOURCE-TRACE.md) documents the implemented contract, source/configuration findings, limits, provenance, failures and rollback. The selected report is `evidence/phase-2/source-trace/20261111T054315892562Z/report.json`, 84,557 bytes, SHA-256 `a6f9211b459ef8309c53b6e39403a0ebad792cf013b904d7a2771b218c9a86b9`: 28 sources, 40 excerpts, three base FDTs, 22 symbols, six tools and 82 indexed files. Both host replays and 35 guards per host passed.

```powershell
python ./scripts/run.py --label source-trace-readback -- python ./scripts/trace-loader-sources.py --verify-trace evidence/phase-2/source-trace/20261111T054315892562Z/report.json
python ./scripts/run.py --label source-trace-readback-wsl -- wsl -d A51-KernelBuilder -u root -- python3 /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/trace-loader-sources.py --verify-trace evidence/phase-2/source-trace/20261111T054315892562Z/report.json
```

Replay uses the retained specification, checks every indexed file, reconstructs source/excerpt/config/FDT facts and tool identities from original inputs, and revalidates the pinned boot report against original image bytes. It does not change the report or pointer. Original Windows Android inputs and `/opt/a51-everline/src` in WSL must be accessible with matching bytes; Windows maps `/opt/` through `\\wsl.localhost\A51-KernelBuilder`, while Linux maps Windows paths through `/mnt/c/`. The Android source root has no Git metadata; its recorded commit is lineage from repack metadata, not a verified checkout HEAD.

When intentionally changing executable trace behavior, run guards on both hosts. A specification-only correction needs a fresh capture and exact-path replays; unchanged code does not require repeating its passed guards.

```powershell
python ./scripts/run.py --label source-trace-guards -- python ./scripts/test-source-trace.py
python ./scripts/run.py --label source-trace-guards-wsl -- wsl -d A51-KernelBuilder -u root -- python3 /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/test-source-trace.py
python ./scripts/run.py --label source-trace-capture -- wsl -d A51-KernelBuilder -u root -- python3 /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/trace-loader-sources.py --capture
```

Capture defaults to `manifests/loader-source-trace.json`; `--capture --spec manifests/<reviewed-spec>.json` selects another project-relative specification. It creates a new timestamped evidence folder, verifies reconstruction, then replaces `manifests/loader-source-trace-current.json`. Verify the emitted new report path on both hosts before selecting it in state/documentation. Failed preflight cannot publish a successful report; retain any partial folder from a later failure. JSON is bounded at 512 KiB, source/excerpt/config/tool files at 4 MiB, FDTs at 2 MiB, indexed bytes at 32 MiB and indexed files at 256.

No source is modified and no phone is contacted. Saved entry arguments, conditional FDT/log exports and reset declarations cannot supply live ownership, retrievable payload logs or a demonstrated return. Every trace phone/device/placement/live-FDT/ownership/log-retrieval/return flag stays false. Preserve the 264-file Phase 1 bundle, original Android inputs, failed attempts and older captures; use matching recorded tool revisions in a compatible project root for historical replay.

## Inventory and viewing logs

```powershell
python .\scripts\run.py --label device-inventory -- python .\scripts\inventory.py
python .\scripts\run.py --label hardware-trace -- python .\scripts\trace-hardware.py
python .\scripts\run.py --label source-audit -- python .\scripts\audit-research.py
Get-ChildItem .\runs | Sort-Object Name
Get-Content .\manifests\qemu-current.json
Get-Content .\manifests\source-lock.json
```

Inventory is read-only. A script may complete while a particular phone query fails; query-level exit codes and output preserve these distinctions. `inventory-snapshots/` and `hardware-snapshots/` retain history. Open a run's `metadata.json` for exact argument arrays, directory and times; `output.log` contains merged stdout/stderr. Use `Get-Content -Tail 30 -Wait` to follow an active run, then Ctrl+C to stop viewing. That does not stop the build.

Check physical Windows C: free space with `Get-PSDrive C`. WSL's virtual free capacity overstates available physical disk. The host currently has about 6.3 GiB WSL RAM and 2 GiB swap; two build jobs were selected for this environment. Use the captured timings as machine-specific observations.

## Privileged live evidence replay

The [live-observation guide](LIVE-OBSERVATIONS.md) contains the fixed read-only capture contract, 41 passed guards per host, corrected remote-status handling, independent libfdt check and failure/rollback history. Offline replay passed on Windows/WSL:

```powershell
python ./scripts/run.py --label live-loader-readback -- python ./scripts/capture-live-loader.py --verify evidence/phase-2/live-loader/20261111T071559056361Z/report.json
python ./scripts/run.py --label live-loader-readback-wsl -- wsl -d A51-KernelBuilder -u root -- python3 /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/capture-live-loader.py --verify evidence/phase-2/live-loader/20261111T071559056361Z/report.json
```

Replay verifies 153 indexed files/current tools, raw remote status, pinned base-FDT/source-trace associations and unchanged local Android inputs without contacting the phone. The 14-file independent live-FDT result and exact logged inline checker are documented separately; the existing historical libfdt script remains unchanged. No rebuild or QEMU run is needed for unchanged tools and documentation.

## Host/QEMU loader prototype build and replay

Read [LOADER-PROTOTYPE.md](LOADER-PROTOTYPE.md) for C interfaces, trust assumptions, entry/frame fields, artifacts and failures. The selected final build passed 2,609 ASan/UBSan assertions, a freestanding AArch64 link with no undefined symbols and a seven-frame QEMU execution/shutdown. All 93 evidence guards passed on Windows/native WSL. The prototype uses existing Clang/LLD/LLVM 18.1.3 and QEMU 8.2.2; its result retains complete versions, tool binary hashes, seven source hashes and 14 exact command records. It is independent of Phase 1's EFI/XNU build.

```powershell
python ./scripts/run.py --label loader-probe-build -- wsl -d A51-KernelBuilder -u root -- python3 /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/build-loader-probe.py --build
python ./scripts/run.py --label loader-probe-readback -- python ./scripts/build-loader-probe.py --verify-result evidence/phase-2/loader-probe/20261111T105317947466Z/result.json
python ./scripts/run.py --label loader-probe-readback-wsl -- wsl -d A51-KernelBuilder -u root -- python3 /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/build-loader-probe.py --verify-result /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/evidence/phase-2/loader-probe/20261111T105317947466Z/result.json
python ./scripts/run.py --label loader-probe-evidence-guards -- python ./scripts/test-loader-probe-evidence.py
python ./scripts/run.py --label loader-probe-evidence-guards-wsl -- wsl -d A51-KernelBuilder -u root -- python3 /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/test-loader-probe-evidence.py
python ./scripts/run.py --label loader-probe-handoff -- python ./scripts/check-loader-probe-handoff.py
```

Run builds sequentially; replay/guard checks read disposable or retained host evidence and contact no phone. A fresh build creates `/opt/a51-hakios/prototype/loader/<UTC>/` and `evidence/phase-2/loader-probe/<UTC>/`, then updates `manifests/loader-probe-current.json` only after native/QEMU/decoder success and self-verification. Preserve prior folders. The default guard fixture uses that pointer; native WSL copies of matching scripts/pointer/evidence under `/opt/a51-hakios/validation/loader-probe/` make disposable-copy checks faster than DrvFS. Exact preparation paths, 59 copied-file hashes and arguments are retained in the final guard runs; these copies do not change the accepted upstream.

Final explicit-path readbacks `20261111T105601972017Z-phase2-loader-probe-evidence-readback-final-windows` and `20261111T105602069992Z-phase2-loader-probe-evidence-readback-final-wsl` passed: 55 files/1,986,789 bytes/2,609 native checks/seven frames. Strict replay executes no binary/QEMU, checks contained indexed roles and all 14 ordered commands, and reconstructs identities/frames/timing. It supports local integrity/rebuild, without independently proving compiler derivation. Native/QEMU timeout 30/20 seconds is a failure; cooperative payload fuel cannot interrupt CPU faults or hangs. An A51 entry/reset/log adapter, owned-runtime ownership importer and experimental Samsung image remain unimplemented. Neither virtual addresses nor QEMU shutdown establish phone placement or return. For a failure, inspect the exact command outputs, restore a recorded source/environment revision and rebuild into a new timestamp; preserve the failed result.

## Current offline observation and entry-contract milestone

The [offline runtime-observation map](RUNTIME-MAP.md) is implemented and verified: 80 guards passed on Windows/native WSL, and the selected historical Linux projection replayed against the complete original capture on both hosts. It records five DRAM declarations (6,327,107,584 bytes), 20 fixed reservation spans, 112 exclusion records, three unresolved dynamic placements and zero verified owned intervals; all 27 diagnostic candidates are rejected. The [entry-route source review](ENTRY-CONTRACT.md) retains 29 source/config files and 24 cited facts, explaining native Image extent, Linux kexec restrictions and the upstream EFI ABI. The A51 ownership-certification importer, adapter, physical transitions, new-payload logs and demonstrated return remain unresolved. No phone query/write/reboot/payload execution occurred in this host-only continuation.

```powershell
python scripts/run.py --label runtime-map-readback -- python scripts/import-runtime-map.py --verify-result evidence/phase-2/runtime-map/20261111T113849417244Z/result.json
python scripts/run.py --label runtime-map-readback-wsl -- wsl -d A51-KernelBuilder -u root -- python3 /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/import-runtime-map.py --verify-result /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/evidence/phase-2/runtime-map/20261111T113849417244Z/result.json
python scripts/run.py --label runtime-map-handoff -- python scripts/check-runtime-map-handoff.py
```

Import/fresh guards/native staging and historical-revision recovery are documented in RUNTIME-MAP.md. Run only the relevant checks after new code or unresolved failures; unchanged prototype/build sources need no new native/QEMU execution.

## Executed Android module diagnostic

See [PAGE-PROBE.md](PAGE-PROBE.md) for isolated matching-kernel builds, exact device preflight, the temporary-file/load/unload boundary, both cleanup tests, offline verification and interrupted-run recovery. Use `scripts/check-page-probe-handoff.py` for the current aggregate handoff. Native/QEMU prototype sources did not change and need no repeated execution for this diagnostic.

## Android 64 KB arena diagnostic

See [64 KB arena diagnostic](ARENA-PROBE.md) for exact build/capture/replay commands, budget, ABI pins and cleanup. Current aggregate handoff: `scripts/check-arena-probe-handoff.py`. Use `--verify` to replay existing packets without a phone; one-time preparation/checkpoint/sync programs must not be rerun. Existing native/QEMU sources are unchanged.


## Executed lifetime-bound plan diagnostic (P2-016)

The [allocation/plan diagnostic](OWNERSHIP-PROBE.md) passed on the A51: three fixed 64 KB plan bindings, seven rejected wrong/stale/released requests, ten state observations and 21 ordered kernel messages. All 23 rooted commands and the transfer succeeded. All three sequential allocations were cleared and released; Android kept the same boot and the module/file are absent. SELinux was Enforcing and existing taint stayed 4096. Native ASan/UBSan checks passed 1,408 assertions; all 17 import CRCs and exact vermagic matched. Windows/WSL replay and all 44 corruption guards per host passed.

Selected host result: `evidence/phase-2/ownership-probe-build/20261111T141326924789Z/result.json`. Selected device result: `evidence/phase-2/ownership-probe-device/20261111T141913580938Z/result.json`. The fixed plan is checked inside the allocation owner under one mutex; a receipt is historical once its callback returns. No external allocation certificate, loader-layout acceptance, copied payload or standalone execution is established. Current released addresses cannot authorize future placement. Phase 1 remains complete, Phase 2 in progress, and standalone launch/platform/fault-log/return gates remain false.

Next: define the bounded A51 diagnostic adapter execution/fault contract, then resolve standalone entry, CPU/MMU/cache/DMA/interrupt transitions, recoverable payload/fault logs and demonstrated return. See the new guide for exact commands, source provenance, failed offline checks and rollback.

## P2-017 CPU-state evidence replay

Read [CPU-STATE.md](CPU-STATE.md) before interpreting the results. The selected packet records eight Android Linux `on_each_cpu()` callbacks at EL1, not Samsung firmware or pre-Linux entry state. These commands are phone-free:

```powershell
python scripts/run.py --label phase2-cpu-state-final-replay-windows -- python scripts/test-cpu-state-device.py --verify evidence/phase-2/cpu-state-device/20261111T155948363876Z
python scripts/run.py --label phase2-cpu-state-evidence-guards -- python scripts/test-cpu-state-evidence.py --packet evidence/phase-2/cpu-state-device/20261111T155948363876Z
```

Selected result SHA-256: `6b6bcae092f51def03aa8b252e529eac644d59fb686798fec14c19fbc0078099`. Do not use the replay commands as authorization for a new module build, transfer or capture; those are separate temporary device mutations and require an explicitly scoped run.

## P2-018 host-only early-entry evidence replay

Read [EARLY-ENTRY.md](EARLY-ENTRY.md). The retained evidence has five synthetic QEMU cases/228 checks and a host-linked 36,334,080-byte Linux `Image`, SHA-256 `87c0401361d4503afb0b266b15ff0caf1e64f505d61d53be700e8b6c6d8e9cf6`. The Image was never Samsung-packaged, installed or executed on the A51. These checks invoke no compiler, QEMU, WSL, ADB or phone:

```powershell
python scripts/run.py --label phase2-early-entry-evidence-final-windows -- python -B scripts/early_entry_evidence.py verify-all
python scripts/run.py --label phase2-early-entry-corruption-final-windows -- python -B scripts/test-early-entry-evidence.py
python scripts/run.py --label phase2-entry-final-handoff -- python -B scripts/check-phase2-entry-handoff.py
```

The host/preparation packets lack indexes, QEMU `.bin` files were not retained, `vmlinux` is external/unindexed, most original build inputs are not packet-retained, and the kernel build reused copied output. Unsupported-EL and oversized-CTR paths lack executed coverage; nine mutation classes are focused rather than exhaustive. Exception vectors, an independent watchdog, persistent fault/reset logging, platform handoff and Android/recovery return remain unverified. Phase 2 remains `in_progress` and its device gate remains false.

## P2-019 Samsung boot-image dry-run replay

Read [SAMSUNG-BOOT-DRY-RUN.md](SAMSUNG-BOOT-DRY-RUN.md). The selected host-only packet reconstructs the pinned Android v2 layout in memory and calculates candidate SHA-256 `73d88c699dda238238b7b2b1105caea248b9ef3aef282a3f01b566f0fd894a58`. It does not emit a candidate image. Run the read-only checks from `hakios-a51/` through the recorder:

```powershell
python .\scripts\run.py --label phase2-samsung-dry-run-core-windows -- python .\scripts\test-samsung-boot-dry-run.py
python .\scripts\run.py --label phase2-samsung-dry-run-replay-windows -- python .\scripts\verify-samsung-boot-dry-run.py .\evidence\phase-2\samsung-boot-dry-run\20261112T010401492946Z
python .\scripts\run.py --label phase2-samsung-dry-run-guards-windows -- python .\scripts\test-samsung-boot-dry-run-evidence.py .\evidence\phase-2\samsung-boot-dry-run\20261112T010401492946Z
python .\scripts\run.py --label phase2-samsung-boot-dry-run-handoff -- python scripts/check-samsung-boot-dry-run-handoff.py
```

Windows and native WSL passed 11 core cases and 30 packet guards per host. Replay reads the separately pinned template/kernel/repack inputs but does not contact the phone. Preserve the four retained failed runs and never modify capture code to write candidate bytes. Samsung firmware acceptance, A51 execution, fault logging and return remain outside this verification.
