> Publication note: this is a historical workspace document. Current completion decisions are in [PUBLIC-STATUS.md](PUBLIC-STATUS.md); raw local evidence is described in [PUBLICATION.md](PUBLICATION.md).

# Phase 1 acceptance report

Completed 10 November 2026, Asia/Calcutta. Scope: pinned inputs, host clean build, open QEMU user-program execution, read-only device/reference inventory and dependency/documentation audit. No HakiOS image was written to the A51.

Rechecked 11 November 2026: a fresh QEMU run passed using the same four clean-build artifacts; nine acceptance guard cases and nine source-pin checks passed again. Stale completion-state documents were corrected and the previously missing final bundle was created at `evidence/phase-1/20261111-final`. Its `index.json` records copied-file checksums and `verification.json` records completion checks. See the [continuation review](REVIEW-20261111.md) for exact runs, retained original roadmap hash and bundle limits.

## Completion gates and evidence

| Gate | Result | Evidence |
|---|---|---|
| Clean output rebuild | Passed; 6 minutes 18 seconds on this host | [Run metadata](PUBLICATION.md), [full output](PUBLICATION.md), [build snapshot](PUBLICATION.md) |
| QEMU reaches the minimal open user program | Passed with the final stricter validator; runner and wrapper exits 0 | [Serial log](PUBLICATION.md), [structured result](PUBLICATION.md), [run metadata](PUBLICATION.md) |
| Device-specific inputs are traceable | Passed as baseline; privileged/fitted-hardware facts remain unknown | [Immutable live inventory](PUBLICATION.md), [hardware trace](PUBLICATION.md), [baseline guide](DEVICE-BASELINE.md) |
| Source and acquired dependency identities recorded | Passed: nine source pins; archive/checksum hashes and SDK pin verified | [Source lock](../manifests/source-lock.json), [dependencies](../manifests/dependencies.json), [archive integrity run](PUBLICATION.md) |
| Missing user-space dependencies have explicit status | Passed as audit; full runtime remains unavailable locally | [Gap audit](DEPENDENCY-GAPS.md), [pinned research audit](PUBLICATION.md) |
| Handoff and modification documentation | Implemented and reviewed against scripts/source/evidence | [Documentation index](INDEX.md), [implementation log](IMPLEMENTATION-LOG.md), [handoff](HANDOFF.md) |

The read-only integrity run [20261110T163324291234Z](PUBLICATION.md) verified 80 retained device/source/research file hashes across all eight hardware-reference groups. Its exact check is retained in the argument array. Current manifests can change later; immutable inventory/build/QEMU snapshots and the final evidence bundle preserve this completion decision.

## What the successful run demonstrates

The clean procedure removed the named kernel/loader/hello/payload outputs and XNU BUILD, exported headers again, rebuilt firehose/pthread support libraries, verified nine source pins and built all four outputs. The existing upstream exception accepted only known kext symbolset/export-check failures. The complete wrapper returned 0; unrelated failures were not ignored.

QEMU started the newly built EFI application, entered XNU, opened the console, ran the static raw-syscall program as process 1/uid 0, read its kernel version through sysctl and exited with signal 0/status 0. XNU then panicked because process 1 exited. Its `initproc failed to start` wording reflects the missing launchd spawn-handshake flag, not failure to execute hello. The validator requires the successful program output before the first panic and rejects unrelated panics or abnormal runner exits. Nine acceptance-guard cases passed in [this run](PUBLICATION.md), including rejection when only the loader prints the right version.

This test ends at the expected process-1-exit panic. It does not exercise a persistent desktop, real launchd, Safari or A51 hardware drivers. Duplicate later hello/panic text in the raw log is not counted as another boot.

## Artifact identity and reproducibility limits

| WSL output relative to `/opt/a51-hakios/src/hakios-xnu-kernel` | Bytes | SHA-256 |
|---|---:|---|
| `hakios-kernel` | 15,790,992 | `6d40f498875ea131e355fdfa151822b9d5672572b2e1368d6e78d0960ea014b2` |
| `xnuloader/loader.efi` | 66,048 | `8ec3499140108bab3fbf963cd54ad40f7253b036c762d701ffadaca34b7f6f64` |
| `userland/hello` | 16,528 | `16ff0b05dd5ea107523d73640e9b3592944ec57f768e7ba74d923dcb47c77fd4` |
| `qemu/payload.bin` | 15,807,712 | `8a8782dd529bfb0430b601445c35933b550b9a6d10dac45e8fdbd998e26eadb1` |

These hashes match the captured build and QEMU inputs. Earlier kernel/EFI/payload hashes differ because build timestamps are embedded. This proves a repeatable clean output rebuild using cached pinned source/dependencies, not a byte-identical artifact or a fresh-host/package-mirror reproduction. Ubuntu package versions are recorded, and the toolchain archive hash is local provenance rather than independent vendor authentication.

## Device observations and future work

Live baseline: SM-A515F, Exynos9611, bootloader A515FXXU8HWI5, Android 16/SDK36, Linux 4.14.357-Everline-KSUN-A51, 1080×2400 and MemTotal 5,707,016 KiB. Retained original Android boot/recovery/DTBO files are hashed and their v2 image headers traced. ADB su is inaccessible; denied map/DT/firmware queries stay unknown. Current locked/green ROM properties conflict with retained custom-image history, so actual bootloader acceptance is unresolved.

Phase 2 must establish the exact DT/board variant, bootloader handoff and usable/reserved memory, retrievable logs and a demonstrated return procedure before an A51 loader can be validated. No-flash RAM launch remains unproven; retained Linux kexec is disabled. No A51 XNU boot, display/input/UFS, charging, GPU/60 fps, Wi-Fi, Bluetooth, audio or Safari behavior was implemented or validated here. Matching Darwin/iOS runtime and a complete Mali user-space path remain later-phase gaps.

Phases 2–10 remain planned. Use the [ten-phase roadmap](ROADMAP.md) for their device acceptance criteria and the [modification guide](MODIFICATION-GUIDE.md) for a separate experimental checkout. Phase 1 completion does not initiate device-write work.
