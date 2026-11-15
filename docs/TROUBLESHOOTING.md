> Publication note: this is a historical workspace document. Current completion decisions are in [PUBLIC-STATUS.md](PUBLIC-STATUS.md); raw local evidence is described in [PUBLICATION.md](PUBLICATION.md).

# Observed failures and recovery

Keep the failing run and nested logs before retrying. Read BUILD.md for recorded commands. Each recovery below was prompted by an actual failure in this workspace.

| Symptom | Cause | Recovery and limit |
|---|---|---|
| Android reaches the UI for 5–10 seconds and resets; retained reset cause is `TIMA_RKP_VMM_PANIC` | Samsung TIMA/RKP EL2-hypervisor panic; exact trigger remains unproved. Two enabled KernelSU application-patch modules were present | Keep the HakiOS candidate unflashed. Use [BOOTLOOP-RECOVERY.md](BOOTLOOP-RECOVERY.md): both existing modules now have reversible `disable` markers, and a 180-second/52-poll same-boot test passed before controlled TWRP return. Do not publish `pmsg-ramoops-0`; it contains account addresses. Re-enabling either module may restore the loop |
| Windows recorder crashes on U+2192 | Default cp1252 output cannot print Ubuntu Unicode | `run.py` configures UTF-8 with replacement; original interrupted run is annotated, child result remains unknown |
| `uuid/uuid.h` absent compiling MIG | Missing host UUID development headers | Add `uuid-dev` to installer and rerun setup/build |
| `bash: --minimize: command not found` at DSYMUTIL | Upstream xcrun cannot find unversioned dsymutil | Install Ubuntu `llvm` meta package providing generic tools; retain version; no success classification bypass |
| `/usr/bin/env: python: No such file` in LLDB macro installation | XNU invokes generic python, Ubuntu has only python3 | Install `python-is-python3`; no Python 2 assumed |
| `/bin/sh: ./xnu-env.sh: Bad substitution` during hello | Make defaults to dash while environment script uses Bash | Pass `SHELL=/bin/bash` via MAKEFLAGS; rebuild hello. Earlier command exit 0 with this diagnostic is not clean evidence |
| Recursive make says `-j13` despite JOBS=2 | XNU derives recursive MAKEJOBS from nproc+1 | Pass `MAKEJOBS=--jobs=2`; current logs show -j2. Jobserver reset warnings are separate from build errors |
| Clean build links kernel then fails `/scripts/verify-sources.py: No such file or directory` | Earlier wrapper resolved an incomplete verification-script path | Current `build-open.sh` uses the full `/mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/verify-sources.py` path before kernel compilation. Retain the failed clean run, then rerun the complete clean build and QEMU; kernel existence alone does not pass |
| `failed to find romfile efi-virtio.rom` | `--no-install-recommends` omitted iPXE QEMU ROM | Install `ipxe-qemu`, then rerun QEMU |
| QEMU outputs hello then `initproc failed to start` panic with exit status 0 | Raw hello exits without launchd's spawn handshake; XNU's prefix uses initproc_spawned | Accept only with successful hello/process-1/root/version/normal-exit markers preceding first panic and zero signal/status; any earlier/different panic fails |
| QEMU runner returns 124 | Bounded timeout expired | Marker and panic checks determine result; timeout alone is not evidence of success |
| Kernel make exits 2 on `.symbolset` / check_all_exports | Upstream machine configuration lacks some kext-only exports | Existing `tools/make-kernel.sh` narrowly classifies these. Never ignore unrelated failures |
| ADB says su inaccessible/not found | ADB shell lacks a usable su entry point | Runtime KernelSU access remains unverified; preserve result, continue host work. Do not infer missing hooks |
| `/proc/iomem`, DT or partition-size reads denied | Ordinary Android shell permission restriction | Record unknown values; retained images are historical evidence, not substitute for live map |
| Boot-state properties say locked/green despite custom kernel history | Conflicting evidence from current ROM versus prior boot records | Keep actual unlock state unresolved; Phase 2 needs independent evidence |
| WSL nested-virtualization warning | WSL startup warning on this host | Linux commands still execute; QEMU uses TCG, not nested KVM. Capture actual child result |
| Retained-image audit rejects two-cell reserved-memory alignment | Initial parser incorrectly used root size cells for alignment | Linux `of_reserved_mem.c` uses root address cells for alignment; the corrected parser and guard cover address/size inversion. Preserve failed run `20261111T015706864973Z-phase2-retained-boot-audit` and the encoding probe |
| Current report reader rejects the first successful draft summary | Later review corrected unapplied-overlay memory and local-fixup fragment semantics | Use the final `20261111T022538476271Z` report. Historical draft replay requires its recorded `project-scripts/`; never overwrite a draft or weaken the reader to promote it |
| Reindexed candidate replay accepted a boolean in zero-size metadata | Python equality treated `False` and `0` alike | Replay now checks JSON value types as well as values; the failed reproduction and final regression guard are retained |
| Layout replay read an index before rejecting its excessive size | Limit was checked after allocation | The reader now checks size first and bounds the subsequent read; preserve failed run `20261111T032721500888Z-phase2-layout-replay-boundary-reproduction` |
| Oversized case JSON could pass layout replay | Candidate/case read lacked the shared pre-read bound | The corrected reader applies the 2 MiB limit before reading cases; all three reproduced defects are covered by the 92 guards on both hosts |
| Source-trace range preflight rejects Samsung reboot excerpt ending at 390 | Inspected file contains only 383 lines | Corrected specification ends at 383; preserve failed `20261111T052044501035Z-phase2-source-trace-range-preflight` and passed final range check |
| Reindexed oversized source-trace report/FDT reached decoding or reconstruction | Path-specific 512 KiB JSON / 2 MiB FDT limits were not enforced early enough | Retained reads now check those bounds before allocation/decoding; failed three-test/four-failure reproduction and final 35 guards per host remain retained |
| Positive/negative `1e309` JSON tokens decoded as infinity | Standard float parsing did not reject overflow | Finite-float parsing rejects overflow as well as nonfinite literals; failed `20261111T052456419500Z-phase2-source-trace-boundary-reproduction` is preserved |
| Exploratory trace reader raises `KeyError: 'path'` | Reader assumed a flat source record; trace inputs are nested | Corrected read `20261111T054151064229Z-phase2-source-trace-return-excerpt-review-corrected` passed; failed `20261111T054134383687Z-phase2-source-trace-return-excerpt-review` changed no input/pointer |

## Evidence that must stay distinct

`runs/metadata.json` reports a whole command's outcome. An inventory script can pass while individual queries fail. `build-current.json` contains outputs and build status, but QEMU evidence is separate. A QEMU marker is not phone evidence. No UI, Wi-Fi, audio, charging or GPU support is established by a driver name in a binary.

The first ROM-failure QEMU run never started the guest. The later guest reached hello, but the first validator rejected the wording of the expected panic. That failed validator result is retained; it is not rewritten after the check was corrected. Later fresh acceptance records demonstrate the corrected behavior.

## If a future rebuild fails

For completion-review failures, use `verify-phase1.py` through the BUILD.md commands. It distinguishes a missing/changed live artifact, source or archive from a copied bundle checksum failure. A historical roadmap hash is checked against the explicit original copy, because current documentation has advanced. Do not change an accepted hash to silence an error. Rebuild missing outputs, execute fresh QEMU and record a new selection if the evidence truly changes. PowerShell's parsed JSON display may convert date strings to local dates; inspect raw metadata or parse with Python to verify the original UTC/IST labels before claiming timestamp corruption.

Locate the first compiler/tool error in the full output rather than the final recursive make summaries. Inspect the snapshot's `xnu-build.log`, MIG, tcsh and export-header logs. Check source pins, environment/tool versions, archive hashes, disk space and the script versions used. Fix a concrete dependency or source issue, record it, then rerun the affected check. A stale `hakios-kernel` can coexist with a failed build; QEMU preflight requires a captured successful build and matching hashes.

Interrupted recordings from before script snapshots were added retain argument arrays and output, with changes explained in IMPLEMENTATION-LOG.md. New recorded runs also preserve `project-scripts/`; do not edit wrappers while they execute.

## Phase 2 host evidence diagnostics

Use the BUILD.md report/result readback commands. `audit-boot-inputs.py --verify-report` checks indexed files, original image/source hashes and reconstructed summaries. `check-boot-audit-libfdt.py --verify-result` checks retained command/result files and linked report/blob hashes without rerunning tools; it does not replace the original-byte report check. A missing `/opt/a51-everline/src` reference or unavailable WSL path is an input-access problem, not a phone result. Keep the original pin and restore access to the recorded file; do not change the hash to make verification pass.

A fresh libfdt cross-check must run in WSL with `fdtget`/`fdtdump`; the successful run retained DTC 1.7.0 and package/binary identities. Creation updates current pointers only after success, and all older reports remain available. Report semantics, original hashes, copied-file integrity and device execution are separate evidence scopes. No loader was executed and no phone restoration is needed for host audit changes.

Current roadmap updates are intentional: Phase 2 is in progress. Preserve `ROADMAP-20261110.md` and `ROADMAP-20261111.md` under `evidence/phase-1-reference/`; they retain the original input and completion decision. Their equality with today's roadmap was a historical Phase 1 check, not a continuing requirement.

## Payload-layout outcomes and replay

Use the [payload-layout guide](PAYLOAD-LAYOUT.md) and BUILD.md commands. All 92 guards passed on Windows and WSL; the selected synthetic record has one accepted case, while the A51 record has 21 expected rejections. A51 demonstration exit 0 means required rejection diagnostics matched. `--manifest` exits 1 for a rejected candidate; `--verify-result` exits 0 when retained evidence reconstructs correctly, even for a rejected layout. Inspect `assessment.host_validation_passed`, `status` and result counts for the actual outcome.

A completed rejected candidate can update the layout pointer with `expected_checks_passed=false`; `host_check_completed=true` does not mean acceptance. Preflight/replay errors retain their failed run and do not publish a successful check. Preserve all timestamped results and any partial evidence.

`a51_runtime_evidence_unavailable` is the current version 1 result for retained A51 layouts. It accepts synthetic host assumptions only and has no runtime ownership importer. Caller runtime labels, high-bank declarations and static gaps cannot resolve ownership. QEMU's `0xF0000000` overlaps modem memory; no replacement address is selected. Resolve entry/live FDT/ownership/log/return facts through retained source tracing and read-only observations before extending this contract.

For replay hash/access failures, restore the exact pinned image/source input or investigate drift. Windows maps logical `/opt/` inputs through `\\wsl.localhost\A51-KernelBuilder`; WSL maps Windows paths through `/mnt/c/`. No phone query is needed. Do not substitute a new digest to silence an error. Historical script snapshots must be integrated into a compatible project root before replay, because scripts derive paths from their location. Restore a specific host revision or deliberately checked pointer, retain the failure history and record the change. No phone restoration, kernel rebuild or new QEMU run is needed for unchanged validator inputs and documentation.

## Retained-source trace diagnostics

Use [SOURCE-TRACE.md](SOURCE-TRACE.md) and BUILD.md for capture/replay commands. The selected 82-file report and original-byte replay passed on both hosts; 35 guards per host cover bounds, types, path/index integrity, source/config/FDT drift and exact excerpts. Replay uses the retained specification and also reconstructs the boot audit against original inputs. A changed default specification does not rewrite an old capture; changed current tools or original bytes deliberately fail reconstruction. Investigate the specific mismatch and use matching recorded revisions in a compatible project root.

The earlier verified capture retained `machine_restart` lines 171–215, omitting its preceding callback condition. The final specification captures the complete lines 143–179 and was followed by new capture and both host replays. No Linux or executable trace script changed; no reset behavior was tested. Preserve both reports, their specifications and the exploratory read failure.

The inspected Android source root has no Git metadata; the recorded lineage commit is not a verified HEAD. Missing Git metadata is a provenance limitation recorded by the report, rather than a reason to invent a source identity. Individual hashes bind inspected bytes but do not authenticate a remote commit.

For later live observations, an absent or denied `/sys/firmware/fdt` must retain its actual access result. SYSFS export is conditional, mode 0400, and may reflect removal of `rng-seed`. The retained kernel disables DEBUG_FS, so mounting debugfs cannot expose the inspected memblock/memsize code. Saved x1–x3 under KASLR, log file modes, a pstore persistence flag and reset registrations cannot establish original entry state, owned RAM, new-payload log retrieval or return. All trace device gates remain false; no phone restoration is required for these host changes.

## Current live capture status

Shell root now works after the user's KernelSU grant. The [schema-2 live evidence](LIVE-OBSERVATIONS.md) records five actual remote failures despite ADB transport exit 0; dynamic `reg`, debugfs and kexec_loaded absence cannot be treated as successful reads. Preserve raw response/status footers and use `--verify` for offline reconstruction. Schema-1 evidence is superseded and deliberately rejected by current replay.

The slow DrvFS guard run was interrupted after identical native WSL tests passed; retain its exit 15 and possible partial fixture. Neither these failures nor root access establish a usable execution destination, new-payload logs, reset/return or no-flash boot.

## Loader prototype evidence and execution

Read [LOADER-PROTOTYPE.md](LOADER-PROTOTYPE.md). The first 42 evidence guards passed, but expanded review reproduced 31 accepted substitutions in the original replay reader: missing/changed command roles, reindexed metadata/type/scope/timing changes and unindexed references. Failed run `20261111T103949959209Z-phase2-loader-probe-evidence-boundary-reproduction` is preserved. The corrected reader requires strict JSON/types, contained indexed references, the exact source/tool/file roles and full ordered 14-command chain with stdout associations and timestamps. Re-CRC'd false frame semantics remain rejected by independent decoding.

A compiler/native test/link/undefined-symbol/QEMU/decoder failure cannot publish a successful current pointer. Inspect the timestamped result and exact command JSON/stdout/stderr. Native/QEMU process timeouts retain available output and record exit 124/`timed_out=true`; they are failures. Fix the specific source/environment issue and rebuild into a fresh folder, keeping earlier results. Invalid synthetic plans emit no arena frames because validation has not authorized the log destination; the external harness/result supplies rejection evidence.

Replay runs on Windows or WSL and executes no retained binary. Restore exact missing bytes or use a matching historical runner/tool set for a recorded rollback, then retain a new verification result. Do not edit old evidence or weaken the decoder to accept a partial transcript. QEMU success does not resolve A51 ownership, hardware exceptions/watchdog, log persistence or Android/recovery return. No phone restoration is needed for this host-only milestone.

## Current offline observation and entry-contract milestone

The [offline runtime-observation map](RUNTIME-MAP.md) is implemented and verified: 80 guards passed on Windows/native WSL, and the selected historical Linux projection replayed against the complete original capture on both hosts. It records five DRAM declarations (6,327,107,584 bytes), 20 fixed reservation spans, 112 exclusion records, three unresolved dynamic placements and zero verified owned intervals; all 27 diagnostic candidates are rejected. The [entry-route source review](ENTRY-CONTRACT.md) retains 29 source/config files and 24 cited facts, explaining native Image extent, Linux kexec restrictions and the upstream EFI ABI. The A51 ownership-certification importer, adapter, physical transitions, new-payload logs and demonstrated return remain unresolved. No phone query/write/reboot/payload execution occurred in this host-only continuation.

The first 65-case Windows suite retained four failures (overflowing float, original report mutation, ignored nested placement flag and boolean redacted addresses). Independent reviews then reproduced diagnostic amplification and accepted extra empty directories. Final 80-case guards cover the fixes, precise output/conflict/case boundaries, rejection before writes and bounded exact packet traversal. Oversized derived output or unexpected packet entries are failures; inspect retained run output rather than weakening limits. Both real-source replays passed.
