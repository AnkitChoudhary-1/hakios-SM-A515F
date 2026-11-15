> Publication note: this is a historical workspace document. Current completion decisions are in [PUBLIC-STATUS.md](PUBLIC-STATUS.md); raw local evidence is described in [PUBLICATION.md](PUBLICATION.md).

# Phase 2 retained boot, DT and memory audit

Date: 11 November 2026, Asia/Calcutta. Status: implemented and verified host analysis; Phase 2 device execution/return gate remains unpassed.

The continuation reviewed the completed Phase 1 evidence, then inspected existing Android images and Linux references without querying or changing the phone. No loader, experimental boot image, source rebuild or new QEMU run was created. The [loader design](LOADER-DESIGN.md) records the unresolved runtime requirements; the [implemented host layout contract](PAYLOAD-LAYOUT.md) consumes these declarations for bounded rejection diagnostics. The [retained-source trace](SOURCE-TRACE.md) now preserves the related entry/FDT/memory/log/reset code and configuration with original-byte replay on both hosts.

## Evidence and implementation

- Phase 1 integrity recheck: `20261111T014740832977Z-continuation-phase1-live-integrity`, exit 0: 13 selected runs, four artifacts, two QEMU transcripts, nine source pins, SDK pin, three archives, 19 historical queries and 80 input hashes.
- Phase 1 bundle readback: `20261111T014740571330Z-continuation-phase1-bundle-readback`, exit 0: all 264 files. Nine QEMU acceptance guards also passed in `20261111T014740683127Z-continuation-qemu-acceptance-guards`; the guest was not rerun.
- Final parser guards: `20261111T022221016941Z-phase2-boot-format-guards-final`, exit 0: 36 tests.
- Evidence reader guards: `20261111T022220919132Z-phase2-boot-audit-integrity-guards`, exit 0: 13 tests.
- Final image audit: `20261111T022533552215Z-phase2-retained-boot-audit-final`, exit 0. [Report](PUBLICATION.md) and [checksum index](PUBLICATION.md): four images, five Android DT tables, 11 extracted FDTs, 13 references and 25 indexed files. Verification checks 18 original hashes and reconstructs each image/table/summary from the original bytes.
- Independent libfdt check: `20261111T022846621274Z-phase2-libfdt-crosscheck`, exit 0. [Result](PUBLICATION.md) and [index](PUBLICATION.md): all 11 FDTs, 1,380 selected properties, 36 commands and 73 indexed files. This compared headers, node counts, root children and raw property bytes; it did not apply overlays.
- Retained-tree comparison: `20261111T023345369076Z-phase2-retained-tree-differences`, exit 0; differences described below.

Report SHA-256: `37f373bba0ea4002cb8853a09298355a8e24045c40f51853c97ebaecc50a344b`. Libfdt result SHA-256: `6e197abbf73a04418c304752cd57cea5e0cfeba809dcea1ec03bc670cc45a1f5`. Current pointers are `manifests/boot-audit-current.json` and `manifests/libfdt-check-current.json`; timestamped evidence is retained when these pointers advance.

Final readback after documentation/state synchronization: `20261111T024759188734Z-phase2-final-boot-report-readback` verified all 25 indexed files, 18 original hashes and 11 summaries; `20261111T024759461297Z-phase2-final-libfdt-result-readback` verified all 73 indexed files and linked FDTs. `20261111T024759306319Z-phase2-final-phase1-live-integrity` passed the unchanged host baseline and `20261111T024759648871Z-phase2-final-phase1-bundle-readback` verified all 264 copied files. All four exits were 0. These were evidence readbacks; libfdt comparison and QEMU execution were not repeated, and the phone was not queried.

Implemented files: `scripts/boot_formats.py`, `audit-boot-inputs.py`, `test-boot-formats.py`, `test-boot-audit.py` and `check-boot-audit-libfdt.py`. All summaries explicitly set `safe_for_loader_placement=false`. The audit verifies bounded Android boot v2, Android DT table v0 and FDT v17 structures, retains extracted blobs/source copies, and publishes its current pointer after verification. The reader rejects corrupt/missing files, path escape, inconsistent counts/revisions, substituted blobs and unsupported device/placement claims.

The cross-check used existing `fdtget`/`fdtdump` DTC 1.7.0 and Ubuntu `device-tree-compiler`/`libfdt1` version `1.7.0-2build1`. Binary paths, sizes, hashes, versions and every subprocess argument/output/exit/time are retained in its result and command files. No host package was installed for this audit.

## Original image identities and layouts

The immutable Phase 1 [inventory](PUBLICATION.md) supplies the input pins. Original images remain in the separate Android project; extracted trees are new evidence copies.

| Input | Full bytes | SHA-256 |
|---|---:|---|
| Original Android boot | 61,865,984 | `89600eb7f3bb73a26d6d8b38aa46c7cb27a5b942da84e0a3c77626ea21642e52` |
| Original DTBO | 8,388,608 | `41662c61ff3158448935025477a4e29d445823dab2cddafb18ea649c8ea925d6` |
| TWRP recovery | 71,106,560 | `12412e2008d950260cda627ac7a6b8eac954b49ef9db5573a297f67e4fc85999` |
| Installed Android boot artifact | 61,865,984 | `eb30609a62999e3282ac81e0a5e56411ef12ec1a39c107171bf3e01209c7cb67` |

All three boot containers use header v2, 2,048-byte pages and a 1,660-byte header. Their DTB sections contain Android DT tables rather than a raw FDT at the section start. Offsets below are byte offsets in the complete image.

| Image/section | File offset | Section bytes | DT table total bytes | FDT entries |
|---|---:|---:|---:|---:|
| Original boot DTB | 37,644,288 | 135,168 | 134,936 | 1 |
| Installed Android boot DTB | 37,662,720 | 135,168 | 134,936 | 1 |
| Recovery DTB | 57,759,744 | 135,216 | 135,216 | 1 |
| Original DTBO | 0 | 8,388,608 | 476,516 | 4 |
| Recovery embedded DTBO | 57,282,560 | 476,800 | 476,800 | 4 |

The report records page padding, section hashes, table fields, entry metadata, absolute blob offsets and trailing bytes. Validation is structural: it does not verify AVB signatures, vendor trailer semantics, compression or an experimental image's bootloader acceptance. Retain the entire original image; do not trim/repack it from these offsets.

## ARM64 Image and entry-address findings

| Field | Original boot | Installed Android boot | Recovery |
|---|---:|---:|---:|
| Stored kernel bytes | 36,313,128 | 36,333,584 | 43,745,292 |
| Effective `image_size` | 47,259,648 | 47,362,048 | 49,958,912 |
| `text_offset` | `0x80000` | `0x80000` | `0x80000` |
| Flags | `0xa` | `0xa` | `0xa` |

The headers describe little-endian, 4 KiB Linux images with the placement flag allowing an arbitrary suitable 2 MiB-aligned base. Effective image size exceeds stored bytes; a future layout must account for the declared execution extent. These Linux fields do not describe XNU's entry ABI or prove where Samsung placed the current kernel.

All three Android headers declare kernel `0x10008000`, ramdisk `0x11000000` and tags `0x10000100`; DTB is `0x10000000` for both boot artifacts and `0x11f00000` for recovery. These addresses lie outside the RAM banks declared by the retained base trees. They are not validated loader destinations. The generic Linux Image placement rule and these Android header fields cannot establish the actual Samsung relocation/handoff.

The retained Linux `head.S` preserves the FDT pointer from x0 and handles EL1/EL2 entry. Its `0xecefecef` PROCA-TA marker also explains the observed header word without treating every reserved field as zero. Neither the source nor the file header measures actual entry PC, CurrentEL, cache/MMU state, timer state or bootloader fixups.

## Base trees and overlay candidates

Original and installed boot contain a byte-identical base FDT: 134,872 bytes, 629 nodes, SHA-256 `6935ac20f1a8b9984ba863e918fffa192b2667d74b2c287a2cf451a32f159349`. Root compatible values are `samsung,armv8` and `samsung,exynos9610`; root hardware-revision interval is 0–255. The actual phone's Exynos 9611 identity comes from the historical live inventory, not a reinterpretation of this family-level compatible string.

Recovery's base FDT has 630 nodes and a different hash. It adds `/firmware/android/fstab/vendor`, changes properties under `/firmware/android/fstab` and `/firmware/android/vbmeta`, and retains the same declared RAM/reservation values. Recovery's overlay blob hashes also differ from original DTBO, although the revision intervals and model strings agree. The report retains each input separately.

| DTBO entry | Declared boot-revision interval | Matching Linux source candidate | Model supplied by overlay |
|---:|---|---|---|
| 0 | 0–0 | `exynos9611-a51_eur_open_00.dts` | EUR OPEN REV00 |
| 1 | 1–2 | `exynos9611-a51_eur_open_01.dts` | EUR OPEN REV00A |
| 2 | 3–6 | `exynos9611-a51_eur_open_03.dts` | EUR OPEN REV01 |
| 3 | 7–255 | `exynos9611-a51_eur_open_07.dts` | EUR OPEN REV02 |

Historical `ro.boot.revision=9` conditionally matches entry 3 in both original and recovery tables. That property is not a verified PCB identifier; actual live selection, fixups and fitted peripheral revisions remain unknown. Root-child `__overlay__` nodes are real fragments; `__local_fixups__` metadata is excluded from fragment summaries. Phandle targets remain unresolved, and `declares_memory_nodes` is only a syntactic observation. No merged tree or verified overlay effect is claimed.

## Declared memory and reservations

Root address cells are 2 and size cells are 1. Each retained base tree declares three 2 GiB RAM banks, totaling 6,442,450,944 bytes (6 GiB):

| Start | End, exclusive | Bytes |
|---|---|---:|
| `0x80000000` | `0x100000000` | 2,147,483,648 |
| `0x880000000` | `0x900000000` | 2,147,483,648 |
| `0x900000000` | `0x980000000` | 2,147,483,648 |

The high banks require 64-bit addresses; this is not one contiguous 6 GiB range. The FDT header reservation map is empty, but `/reserved-memory` declares 15 fixed spans and three dynamic reservations. The table groups the eight debug-snapshot spans; individual nodes remain in the report.

| Declared owner | Start | End, exclusive | Size |
|---|---|---|---|
| `sec_debug_magic` | `0x80000000` | `0x80001000` | 4 KiB |
| `seclog_mem` | `0xc0000000` | `0xc0080000` | 512 KiB |
| `abox_rmem` | `0xe9400000` | `0xebc00000` | 40 MiB |
| `modem_if` | `0xed000000` | `0xf5a00000` | 138 MiB |
| `cp_ram_logging` | `0xf5a00000` | `0xf7800000` | 30 MiB |
| `debug_snapshot/*` | `0xf9000000` | `0xfa710000` | 23.0625 MiB |
| `gnss_if` | `0xfb000000` | `0xfb800000` | 8 MiB |
| `chub_rmem` | `0xfd000000` | `0xfd080000` | 512 KiB |

Fixed declared spans total 251,727,872 bytes. Dynamic reservations are `ion_video_stream` (72 MiB), `ion_crypto` (24 MiB) and `wifibt_if` (16 MiB); their actual addresses are absent from the retained declarations. Both ION nodes declare 4 MiB alignment in two address cells. The video allocation range is `0x40000000`–`0x100000000`; it is an allocation constraint, not an assigned buffer address. Inspected `drivers/of/of_reserved_mem.c` reads alignment with `dt_root_addr_cells` and size with `dt_root_size_cells`, matching this encoding.

**The upstream/QEMU payload address `0xF0000000` falls within the declared modem reservation. It must not be copied into an A51 layout.** No alternative load address is selected by this audit. An absent `no-map` flag does not establish that a region is available to another kernel.

The report's `gaps_after_known_static_reservations` is a mathematical subtraction only. It does not remove dynamic/secure allocations, bootloader code, current kernel/initrd/FDT, page tables, DMA buffers or live driver ownership. Nonempty reserved-bus translations suppress that output; nested debug reservations are retained conservatively. Linux-visible MemTotal was 5,707,016 KiB, while CMA was included in Linux-visible RAM. Neither that difference nor subtracting fixed/dynamic sizes produces a verified loader allowlist.

## Source provenance and limitations

Thirteen source records are retained: the pinned Android configuration and repack record, plus 11 Linux files covering ARM64 booting/head, DTS Makefile, SoC DTS/reservations, the reserved-memory allocator, common A51 definitions and four EUR revision overlays. They were read from `/opt/a51-everline/src` in `A51-KernelBuilder` without modifying it. The Windows `kernel-work/source` snapshot does not contain `Documentation/arm64/booting.txt`; the full WSL source tree does.

Recorded Linux lineage is commit `468ab8343364e4d3a267e670fa6a22fd4197a805` of the existing Android project, as recorded in the retained repack metadata's source URL. Later source-trace inspection confirmed that `/opt/a51-everline/src` has no Git metadata: this is not a verified checkout HEAD or a remote per-file comparison. Its local adaptations predate this audit; the per-file hashes pin the inspected bytes rather than claiming a pristine upstream checkout or an exact source reconstruction of every image. This remains Linux reference material, not an XNU port.

Implemented/verified: bounded host parsing, original-byte associations, retained declared memory/reservations, conditional revision matching, libfdt cross-check, repeatable evidence readers, version 1 host payload-layout checks and retained-source tracing. Planned: loader/trampoline, runtime-ownership importer, experimental image and execution probe. The original host audit had no privileged live observations. Subsequent [live evidence](LIVE-OBSERVATIONS.md) verifies Shell root and Linux's exported FDT/memory reports. Unknown: original firmware fixups/entry state, usable/secure/dynamic ownership and a new payload's logs/return. No-flash RAM boot, A51 XNU, GPU, Darwin runtime and Safari remain unverified or absent as recorded in STATE.md.

The layout validator passed 92 guards on Windows and WSL, accepted one synthetic host case and rejected 21 retained-A51 cases with required diagnostics. Both demonstrations replayed on both hosts. Imported banks stay declarations; all 15 fixed spans and three unplaced dynamic allocations remain enforced regardless of caller lists. The modem conflict, both high banks, static-gap ownership and attempted runtime-label promotion are covered. Version 1 accepts synthetic assumptions only and has no runtime ownership importer. These checks select no A51 destination and leave the device gate false. [PAYLOAD-LAYOUT.md](PAYLOAD-LAYOUT.md) retains exact manifests, selected result hashes, commands, replay semantics and the failed regression history.

The subsequent source trace retains 28 files/40 excerpts, three base FDTs and 22 configuration symbols in 82 indexed files; 35 guards passed per host and capture/replay passed on Windows/WSL. It revalidates this original-byte audit rather than replacing it. Source limits include KASLR zeroing saved x1–x3, conditional/possibly seed-modified FDT export, DEBUG_FS-disabled memblock/memsize exports, legacy PSCI initialization without standard SYSTEM_RESET registration in the inspected path, and conditional Samsung/Exynos/watchdog/log-buffer initialization. SOURCE-TRACE.md records the exact selected report/hash, failures and recovery. These findings supply no A51 destination, measured ownership, retrievable payload logs or demonstrated return.

## Failed attempts and corrections

`20261111T015706864973Z-phase2-retained-boot-audit` failed on the original tree's two-cell alignment. The initial parser assumed alignment used size cells. The retained probe `20261111T015724677914Z-phase2-reservation-encoding-probe` exposed the encoding; source inspection established address-cell behavior. An intermediate test passed after accepting the width, but its "nonstandard" label was corrected before successful publication. Address/size inversion is now guarded explicitly.

The first successful draft report, `evidence/phase-2/boot-audit/20261111T020237181178Z/report.json`, is retained as superseded history. Review then corrected base-memory treatment for unapplied overlays, excluded local-fixup metadata from real fragments and bound stored summaries/blobs to original images. The final report linked above is authoritative. Replaying a historical parser requires that run's `project-scripts/` snapshot; the current verifier deliberately rejects stale summaries after semantic corrections. No failed record or draft evidence was overwritten.

## Repeat, verify and rollback

Run from `C:\Users\Ankit\Desktop\A51\hakios-a51`. These commands use existing inputs and do not contact the phone:

```powershell
python .\scripts\run.py --label boot-format-guards -- python .\scripts\test-boot-formats.py
python .\scripts\run.py --label boot-audit-guards -- python .\scripts\test-boot-audit.py
python .\scripts\run.py --label retained-boot-audit -- python .\scripts\audit-boot-inputs.py
python .\scripts\run.py --label retained-boot-readback -- python .\scripts\audit-boot-inputs.py --verify-report evidence/phase-2/boot-audit/20261111T022538476271Z/report.json
python .\scripts\run.py --label libfdt-crosscheck -- wsl -d A51-KernelBuilder -u root -- python3 /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/check-boot-audit-libfdt.py
python .\scripts\run.py --label libfdt-readback -- python .\scripts\check-boot-audit-libfdt.py --verify-result evidence/phase-2/libfdt/20261111T022902468010Z/result.json
```

A new audit/cross-check creates a new timestamped folder and updates the corresponding current pointer only after success. To cross-check a particular report, pass `--report evidence/phase-2/boot-audit/<timestamp>/report.json`. Report verification requires the original image/config/source files at their recorded Windows/WSL paths. Libfdt result readback checks its indexed copies and linked report/blob hashes without rerunning the tools; it does not replace original-image report verification.

Parser tests use bounded synthetic binary fixtures. Evidence-reader tests create temporary fixtures under `evidence/test-fixtures` and clean only their own generated directories. They do not test the hardware.

Rollback: restore a specific script revision from its recorded `project-scripts/` snapshot if needed, preserve all reports/runs and record the reason. Restore a previous current pointer only after deliberately checking that report with its matching parser revision; do not silently promote a superseded draft. No phone restoration is required. The Phase 1 bundle and original Android files remain unchanged; continue using BUILD.md to verify/rebuild the host baseline separately.

## Current offline observation and entry-contract milestone

The [offline runtime-observation map](RUNTIME-MAP.md) is implemented and verified: 80 guards passed on Windows/native WSL, and the selected historical Linux projection replayed against the complete original capture on both hosts. It records five DRAM declarations (6,327,107,584 bytes), 20 fixed reservation spans, 112 exclusion records, three unresolved dynamic placements and zero verified owned intervals; all 27 diagnostic candidates are rejected. The [entry-route source review](ENTRY-CONTRACT.md) retains 29 source/config files and 24 cited facts, explaining native Image extent, Linux kexec restrictions and the upstream EFI ABI. The A51 ownership-certification importer, adapter, physical transitions, new-payload logs and demonstrated return remain unresolved. No phone query/write/reboot/payload execution occurred in this host-only continuation.
