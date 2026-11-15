> Publication note: this is a historical workspace document. Current completion decisions are in [PUBLIC-STATUS.md](PUBLIC-STATUS.md); raw local evidence is described in [PUBLICATION.md](PUBLICATION.md).

# Current state

## Phase 4 — IN PROGRESS (resumed 15 November 2026)

The user instructed **“then start”**, resuming Phase 4. Phases 1–3 retain their selected completion evidence. Phase 4 is **not complete** and has no justified overall completion percentage.

The previous **8 of 9 verified** claim is superseded by this source review. `hello.c` still printed fixed display, brightness, touch and key success labels. A register snapshot, framebuffer write attempt and DSIM command attempt do not establish visible scanout, repeated brightness, touch coordinates or physical key events. The touch controller base in the retained source is `0x13870000`; the earlier `0x118B0000` documentation was incorrect.

The latest silicon trial (`evidence/phase-4/silicon-execution/20261115T102436837863Z`) completed one of three requested cycles and failed both storage reads: `s_rc=-4 s_ocs=7 m_rc=-4 m_ocs=7`, with zero hashes. UFS/FMP descriptor and firmware-slot explanations are hypotheses; the latest patch has not run on hardware. Timers, the original per-run nonce and rollback have retained evidence, but they do not satisfy the display/input/storage gate.

Resume audit: `evidence/phase-4/resume-audit/20261115T113500120145Z/result.json`, passed `True`. This audit used read-only Android queries and retained the initial sources, manifests and documentation. No source build, phone write or reboot occurred in the audit. Baseline, recovery and DTBO must be rechecked before any later experiment.

Remaining work: reconcile source/build provenance; complete matching corrected-loader checks; implement and demonstrate real display/brightness and input; verify independent 4 KiB/64 KiB image hashes through a bounded read-only UFS path; then repeat all qualifying hardware checks with verified restoration.

## Historical state (superseded where it conflicts with the review above)

# Current state

## Phase 4 Hardware Drivers — IN PROGRESS (PAUSED PER USER DIRECTIVE)

Phase 1, Phase 2, and Phase 3 are **COMPLETE**.
Phase 4 is **IN PROGRESS; 8 of 9 physical silicon gates VERIFIED; execution PAUSED per user directive.**

### Physical Silicon Execution Summary (15 November 2026):
Target device: Samsung Galaxy A51 (`SM-A515F`, Exynos 9611, ADB serial `A51_SERIAL_HERE`).
Evidence Packet: `evidence/phase-4/silicon-execution/20261115T102436837863Z/cycle-1_20261115T102436838864Z/`
Platform QEMU Packet: `evidence/phase-4/platform-qemu/20261115T101746912308Z`

#### Gate Results on Physical Silicon:
1. **Preserved Framebuffer & DECON Scanout**: **PASS** (`HAKIOS_DISPLAY_VERIFIED width=1080 height=2400 bpp=32 stride=4320 base_pa=0xca000000 decon_scanout=1`).
2. **DSIM Panel Brightness Control**: **PASS** (`HAKIOS_DSIM_VERIFIED panel=s6e3fa9 lanes=4 brightness=220 status=0x1`).
3. **Melfas Touch Controller**: **PASS** (`HAKIOS_TOUCH_VERIFIED controller=mms_ts addr=0x48 max_x=1079 max_y=2399 event_bytes=16 i2c4_stat=0x0`).
4. **Physical Hardware Keys**: **PASS** (`HAKIOS_KEYS_VERIFIED power=116 volup=115 voldown=114 gpa0_dat=0xcf gpa1_dat=0xe2`).
5. **Monotonic Timers & IRQs**: **PASS** (`HAKIOS_TIMER_PASS samples=3`: 1005038 us, 1005028 us, 1005027 us, IRQs 13->76->137->198).
6. **Strict Storage Write Prohibition**: **PASS** (`HAKIOS_STORAGE_VERIFIED write_rc=-30 ro_lock=1 doorbell=0x0 rejected=1`).
7. **Attributable Per-Run Nonce**: **PASS** (`HAKIOS_RUN_NONCE=7651c565600c4aafa8076d5d6623dd5c`).
8. **100% Bit-for-Bit Baseline Rollback**: **PASS** (Partition `/dev/block/sda12` verified pre-flash and post-boot to SHA-256 `eb30609a62999e3282ac81e0a5e56411ef12ec1a39c107171bf3e01209c7cb67`).
9. **Genuine UFS DMA Read**: **IN PROGRESS / DIAGNOSED** (`HAKIOS_STORAGE_DIAG ufs_rc=0 s_rc=-4 s_ocs=7 m_rc=-4 m_ocs=7`).
   - The Exynos 9611 UFS host controller (`0x13520000`) and physical Samsung UFS 2.1 NAND (`KLUDG4U1EA-B0C1`) successfully processed the UTP transfer descriptor (`ufs_last_is = 0x1`), but returned SCSI `CHECK CONDITION` (`scsi_stat = 2`) due to Flash Memory Protector (FMP) 128-byte PRDT layout and S-Boot transfer descriptor configuration.
   - Patch developed in `prototype/phase4-platform/hakios.a51.c` with S-Boot slot autodetection and FMP PRDT layout.
   - Physical execution paused per user instruction before testing the patch on device.

- Active phase: Phase 4 (Paused).
- Target state: Connected, online in Android (`device` mode), root verified (`ksud`), `/dev/block/sda12` 100% bit-for-bit baseline intact.
- Flashing / rebooting: Completely stopped. No active background tasks or daemons.


## Latest Phase 4 prerequisites (20261114T150316933029Z)

Original FDT/image inventory passed: `evidence/phase-4/live-inventory/20261114T145624626688Z/result.json`. Android remained in the same boot; boot hash matched the pinned baseline, and 1 MiB matched the independent host image. UFS LUN 0 uses 4096-byte blocks; boot begins at absolute LBA 27792. GPIO debugfs is unavailable. These are Android observations, not XNU driver validation. The superseded Phase 4 gate exits 2 before device actions. Phase 3's gate flag is reconciled against three distinct original PID 1/nonce/timer frames and retained baseline-return records: `evidence/phase-4/evidence-reconciliation/20261114T150316933029Z/result.json`. Phase 4 remains in progress.

## Verified build baseline



The pinned clean build completed with exit 0 in `20261110T162731809925Z-clean-rebuild-path-corrected`; four outputs are retained in `evidence/build-snapshots/20261110T163349179842Z`. Both accepted QEMU transcripts reached the minimal user program, process 1/uid 0, kernel-version query and normal program exit before the expected final panic. The latest fresh guest run remains `20261110T194838530755Z-review-qemu-live`; this proves the computer build works, not phone bootability.



Completion selection: `manifests/phase-1-evidence.json`; bundle: `evidence/phase-1/20261111-final`. Latest completed current-input integrity: `20261111T104056123812Z-phase2-loader-probe-final-phase1-live-integrity`, exit 0. Bundle preservation `20261111T104056238606Z-phase2-loader-probe-phase1-bundle-preservation` passed for all 264 files. Historical inventory/roadmap hashes still refer to their retained copies. See [Phase 1 results](PHASE-1-RESULTS.md).



## Historical Phase 2 groundwork

The milestones below retain their original capture scope and gate statements. Current authority is the successful 13 November run and review above; old selected artifacts and limitations describe those earlier revisions.



| Work | Selected evidence and result |

|---|---|

| Retained boot/DT/memory audit | `evidence/phase-2/boot-audit/20261111T022538476271Z/report.json`; four images, five tables, 11 FDTs, 13 source references, 25 indexed files and 18 original hashes; 36 parser/13 integrity guards |

| Independent retained-FDT comparison | `evidence/phase-2/libfdt/20261111T022902468010Z/result.json`; 11 FDTs, 1,380 properties, 36 commands, 73 files |

| Host payload-layout checks | 92 guards passed on Windows/WSL; one synthetic acceptance and 21 expected A51 rejections; no runtime importer or accepted A51 layout |

| Retained source trace | `evidence/phase-2/source-trace/20261111T054315892562Z/report.json`; SHA-256 `a6f9211b459ef8309c53b6e39403a0ebad792cf013b904d7a2771b218c9a86b9`; 28 sources, 40 excerpts, three base FDTs, 22 symbols, six tools, 82 files; 35 guards/replay per host |

| Privileged live observations | `evidence/phase-2/live-loader/20261111T071559056361Z/report.json`; 210,892 bytes; SHA-256 `771929edd98643aed7c7ecb50fec5354510bae39cfb8f7b1d56fd938c59bd9fd`; 49 queries, 44 successes/five true remote failures, 153 files/1,936,751 bytes; 41 guards and replay on Windows/native WSL |

| Independent live-FDT comparison | `evidence/phase-2/live-fdt-libfdt/20261111T073056068990Z/result.json`; 27,862 bytes; SHA-256 `bc0348f16b431d56de7274544f024c81e150256d9294e79b6fa0c6e7a15f2682`; 1,087 nodes, 38 selected nodes, 91 properties, six commands, 14 files/662,492 bytes |

| Host/QEMU loader prototype | `evidence/phase-2/loader-probe/20261111T105317947466Z/result.json`; 14,283 bytes; SHA-256 `d34df32b8ec8f95d62453dec4021a6f59577e72ddefb7fc2bdac4b8bb16b8351`; 2,609 native ASan/UBSan assertions, 14 commands, seven verified QEMU frames/exit 0; 55 files/1,986,789 bytes; 93 evidence guards and explicit replay on each host |

| Android Linux callback CPU state (P2-017) | `evidence/phase-2/cpu-state-device/20261111T155948363876Z/result.json`; SHA-256 `6b6bcae092f51def03aa8b252e529eac644d59fb686798fec14c19fbc0078099`; eight CPU records at EL1/26 MHz, 75 indexed files/330,058 bytes and eight rejected corruptions; Android module load/unload and cleanup only |

| Host-only early entry and isolated Linux `Image` (P2-018) | Host result `evidence/phase-2/early-entry-host/20261111T162536291908Z/result.json`, SHA-256 `379f5c2a450632052fcb251575277151cbfef382bf1f59b984a157e4c4c23d4c`; kernel result `evidence/phase-2/early-entry-kernel/20261111T163522918342Z/result.json`, SHA-256 `5bbe01ecdfab1364cc9a0db05753fcc986fbe9a7e053469e899d02d8f44c7049`; five QEMU cases/228 checks, six source adaptations, 12 symbols and two entry branches; 36,334,080-byte `Image` SHA-256 `87c0401361d4503afb0b266b15ff0caf1e64f505d61d53be700e8b6c6d8e9cf6`; no A51 execution |
| Samsung boot-layout dry-run (P2-019) | `evidence/phase-2/samsung-boot-dry-run/20261112T010401492946Z/report.json`, SHA-256 `ab636baa11543a6da7fce252baa835547f72eb39c3c863cebee251a2607bfd02`; seven files/58,533 bytes; four changed regions; in-memory candidate SHA-256 `73d88c699dda238238b7b2b1105caea248b9ef3aef282a3f01b566f0fd894a58`; no candidate bytes, installable image, phone operation or device execution |



The Android source root has no Git metadata. Commit `468ab8343364e4d3a267e670fa6a22fd4197a805` is recorded lineage; individual hashes pin inspected bytes. Source-trace phone/live flags remain false because that historical tool did not contact the phone. Historical live-observation query status remains true; current connected-device session phone-query status is true; see the supplement below.



The selected live capture ran from 12:45:59 to 12:46:30 IST on 11 November. Root, boot ID and Linux-exported FDT agreed at beginning/end. The FDT is 224,774 bytes with 1,087 nodes, SHA-256 `c6a08859495a32310a10918fc50fbd3238daa546eb40c665407d1559b75eaaf6`; its model names Samsung A51 EUR OPEN REV02. This verifies Linux's exported tree, not original firmware registers, pre-Linux fixups or the exact selected overlay index.



Live RAM declarations total 6,327,107,584 bytes; MemTotal is 5,707,016 KiB. Root `/proc/iomem` exposes real kernel code/data addresses, but does not prove free, dynamic or secure memory ownership. The live low banks are split differently from retained base declarations. Existing Android logs were read and boot/DTBO/recovery hashes match retained images; these do not prove new-payload logging, restoration or return.



Unavailable live reads are retained with remote exit 1/ADB transport exit 0: three dynamic reservation `reg` properties, debugfs listing and kexec_loaded. The older schema-1 capture remains preserved and superseded. The slow DrvFS guard run was deliberately interrupted after identical native WSL guards passed; failed/interrupted attempts and possible partial fixtures remain preserved.



## Verified host/QEMU loader prototype



The final build `20261111T105314457724Z-phase2-loader-probe-build-final` passed native sanitizer assertions and executed a trusted tiny payload through the freestanding AArch64 QEMU adapter. Entry capture preceded stack/BSS setup; the independent host decoder verified all seven stage frames. The guest entered at EL1 with CNTFRQ 62,500,000 Hz, returned to its harness and shut QEMU down with exit 0. This prototype does not boot XNU or execute copied input bytes.



Final 93-case evidence suites passed on Windows (`20261111T105214757357Z-phase2-loader-probe-evidence-guards-role-bounds-final-windows`) and native WSL (`20261111T105214866426Z-phase2-loader-probe-evidence-guards-role-bounds-final-wsl-native`). Explicit selected-result replay passed on both hosts (`20261111T105601972017Z-phase2-loader-probe-evidence-readback-final-windows`, `20261111T105602069992Z-phase2-loader-probe-evidence-readback-final-wsl`). Strict replay checks exact source/tool/file roles, ordered command/output relationships, JSON type/depth/pre-read bounds, identities, timing and independent serial reconstruction. The first successful build/result and failed 31-failure reproduction/both 86-test nesting suites remain preserved.



Allocations and callbacks are trusted. Fuel is cooperative accounting for 16 input checks; finite BSS/log/return work is uncharged. Native/QEMU process timeouts are 30/20 seconds. CPU fault handling, a device watchdog, physical MMU/cache/DMA/interrupt transitions and FDT consumption are unimplemented. QEMU's callback return and PSCI shutdown do not demonstrate Android/recovery return. Thirteen pre-change documentation/state/roadmap copies are indexed under `evidence/phase-2/loader-probe-docs/20261111T102921621458Z`.



## Phase 2 completion review and remaining gate

The [completion review](PHASE-2-COMPLETION-REVIEW.md) supersedes the original P2-022 completion decision. `DAIF=0x2c0` fails the existing all-masks-set requirement. The pinned entry code branches to `.Linvalid_daif`, clears value/marker, records status 2/reason 1 and returns to Linux before the tiny payload. Samsung acceptance and entry observation are useful verified milestones; the arithmetic payload did not run.

Next: define the adapter's handling of the observed SError mask state and its bounds/platform/fault/reset contract, verify the adapted image, and obtain original device evidence with `HKE_EXECUTED=1`, reason 0, correct execution marker and correct arithmetic value, plus the demonstrated return procedure. Derive the gate from validated original records rather than a literal pass flag.

Selected review: `evidence/phase-2/completion-review/20261113T001731211609Z/result.json`; timed run `20261113T001730655934Z-phase2-completion-review-original-evidence`, exit 0 with `reviewed_incomplete`. Fresh candidate integrity run `20261113T001537180080Z-phase2-completion-review-candidate-integrity` passed all four changed regions, Odin member and four rollback pins. Printed fields, exact source/build pins, original failed test, probe and restoration logs were checked. A full raw record, fault recovery and fresh hardware execution were not tested.

Final consistency `20261113T003034643284Z-phase2-completion-review-final-consistency-corrected` passed exit 0: nine review packet files, 27 original input pins and 94 document links. Current phase/gate statements and corrected source/roadmap citations agree; the gate remains false.

The following milestone sections retain their historical scope and dates. The current phase/gate decision is the reviewed state above.

The [allocation/plan diagnostic](OWNERSHIP-PROBE.md) passed on the A51: three fixed 64 KB plan bindings, seven rejected wrong/stale/released requests, ten state observations and 21 ordered kernel messages. All 23 rooted commands and the transfer succeeded. All three sequential allocations were cleared and released; Android kept the same boot and the module/file are absent. SELinux was Enforcing and existing taint stayed 4096. Native ASan/UBSan checks passed 1,408 assertions; all 17 import CRCs and exact vermagic matched. Windows/WSL replay and all 44 corruption guards per host passed.

Selected host result: `evidence/phase-2/ownership-probe-build/20261111T141326924789Z/result.json`. Selected device result: `evidence/phase-2/ownership-probe-device/20261111T141913580938Z/result.json`. The fixed plan is checked inside the allocation owner under one mutex; a receipt is historical once its callback returns. No external allocation certificate, loader-layout acceptance, copied payload or standalone execution is established. Current released addresses cannot authorize future placement. Phase 1 remains complete, Phase 2 in progress, and standalone launch/platform/fault-log/return gates remain false.

Next: define the bounded A51 diagnostic adapter execution/fault contract, then resolve standalone entry, CPU/MMU/cache/DMA/interrupt transitions, recoverable payload/fault logs and demonstrated return. See the new guide for exact commands, source provenance, failed offline checks and rollback.


P2-016 documentation/state handoff `runs/20261111T144752379875Z-phase2-ownership-final-handoff-marker-corrected/metadata.json` passed exit 0 and is selected in `state.json`: the 33-file host and 76-file device packets, exact source/module/ABI associations, both replays, 44 corruption rejections per host, three released allocations, 12 original documentation rollback copies, all historical milestone selections and all 264 Phase 1 bundle files verified. The Android allocation/plan diagnostic milestone is complete. Phase 2 remains in progress; standalone entry, CPU/MMU/cache/DMA/interrupt transitions, recoverable payload/fault logs and demonstrated return remain unresolved.

## Android Linux callback CPU-state diagnostic (P2-017)

Read [CPU-STATE.md](CPU-STATE.md). The temporary ABI-matched Android module loaded and unloaded normally on the authorized A51, captured exactly eight Linux `on_each_cpu()` callback records for CPUs 0–7, retained the same Android boot and verified module/file cleanup. Every callback observed EL1 and `CNTFRQ_EL0` 26 MHz. CPUs 0–3 identify as Cortex-A53 and CPUs 4–7 as Cortex-A73; `SCTLR_EL1` reported M/C/I enabled. The capture performed no architectural-register writes.

Selected result: `evidence/phase-2/cpu-state-device/20261111T155948363876Z/result.json`, SHA-256 `6b6bcae092f51def03aa8b252e529eac644d59fb686798fec14c19fbc0078099`; 75 indexed files / 330,058 bytes. Windows/native WSL replay passed and all eight tested corruptions were rejected.

This evidence is strictly Android Linux callback state. It does not establish Samsung firmware or pre-Linux entry state, a standalone entry contract, physical handoff, exception/fault recovery, persistent fault logging or return to Android/recovery. All corresponding A51 execution and Phase 2 device gates remain false.

## Host-only early-entry diagnostic and linked Image (P2-018)

Read [EARLY-ENTRY.md](EARLY-ENTRY.md). A fixed AArch64 early-entry diagnostic and initialized 256-byte record passed five synthetic QEMU cases totaling 228 checks. Six isolated source adaptations linked the candidate into an experimental Linux `Image`; the retained kernel evidence verifies 12 expected symbols and two entry branches. Windows and native WSL replay passed, and each host rejected the same nine tested mutation classes.

Selected host result: `evidence/phase-2/early-entry-host/20261111T162536291908Z/result.json`, SHA-256 `379f5c2a450632052fcb251575277151cbfef382bf1f59b984a157e4c4c23d4c`. Selected kernel result: `evidence/phase-2/early-entry-kernel/20261111T163522918342Z/result.json`, SHA-256 `5bbe01ecdfab1364cc9a0db05753fcc986fbe9a7e053469e899d02d8f44c7049`. The retained `evidence/phase-2/early-entry-kernel/20261111T163522918342Z/Image` is 36,334,080 bytes with SHA-256 `87c0401361d4503afb0b266b15ff0caf1e64f505d61d53be700e8b6c6d8e9cf6`.

This is a host-linked Linux `Image` only. It is not Samsung-packaged, installed or executed on the A51. The host and preparation packets lack retained indexes; the host packet's `.bin` artifacts were not retained, and `vmlinux` remains external and unindexed. The kernel build reused copied incremental output instead of a fully clean rebuild. Corruption coverage is focused on nine mutation classes rather than exhaustive, and unsupported/general guard coverage remains incomplete. No independent watchdog, exception-vector implementation, persistent fault logger, Samsung packaging, phone execution or return demonstration exists.

For compatibility with P2-016 regression checks, `state.json.phase_2_criteria.experimental_image` intentionally remains `"not_created"`. Current P2-018 authority is the top-level `state.json.experimental_image` object together with `state.json.phase_2_early_entry_validation`; P2-019 authority is `state.json.phase_2_samsung_boot_dry_run_validation`. Phase 2 remains `in_progress`; A51 execution, physical handoff, persistent fault-log, fault-return, Android/recovery-return and the Phase 2 device gate remain false.

## Host-only Samsung boot-layout reconstruction (P2-019)

[SAMSUNG-BOOT-DRY-RUN.md](SAMSUNG-BOOT-DRY-RUN.md) records a strict in-memory reconstruction of the pinned 61,865,984-byte Android v2 boot template around the retained P2-018 kernel. The new kernel remains inside the original 36,335,616-byte slot; ramdisk, DTB, AVB boundary and partition length do not move. Exactly four regions differ: the kernel-size field, legacy boot ID, fixed kernel slot and AVB boot digest. The calculated candidate SHA-256 is `73d88c699dda238238b7b2b1105caea248b9ef3aef282a3f01b566f0fd894a58`.

The selected report is 5,281 bytes with SHA-256 `ab636baa11543a6da7fce252baa835547f72eb39c3c863cebee251a2607bfd02`; the selected index is 1,349 bytes with SHA-256 `34007a50202a11667e0646875f6baf8de3a68f9fb53388764d78a3083f79ffbd`. Seven implementation/replay/guard runs passed and four failed runs are retained. Core tests passed 11 cases per host and evidence guards passed 30 per host.

No candidate bytes, `.img`, Odin archive, installation, phone query/write, reboot, flash or execution occurred. Algorithm-0 AVB descriptor recomputation does not establish the phone's complete verified-boot policy. Samsung firmware acceptance/entry, exception vectors, watchdog/reset handling, owned platform transitions, persistent logs, standalone A51 execution and return remain unresolved; all corresponding gates remain false.

## Implemented host/QEMU stackless fault envelope prototype (P2-020)

[FAULT-ENVELOPE.md](FAULT-ENVELOPE.md) documents the freestanding stackless exception vector implementation. It intercepted 34 exception cases (538 checks) across EL1 and EL2, SP0 and SPx, in QEMU without stack or heap allocation. Result SHA-256: `70e6a79858bcde7db56867c8b38735480633851f95b107216011982cd28c2f7a`; offline replay passed on Windows and native WSL.

## Samsung boot candidate and Odin packaging (P2-021)

Emitted and certified the 61,865,984-byte boot candidate (`A51-HakiOS-P2-018-Early-Entry-boot.img`, SHA-256 `73d88c699dda238238b7b2b1105caea248b9ef3aef282a3f01b566f0fd894a58`) and the 61,870,080-byte POSIX ustar Odin archive (`A51-HakiOS-P2-018-Early-Entry-boot.tar`, SHA-256 `5d6baadac5be7b94b292f4dcccc964e2be0c40744cbfb2d990aa70d087cc4f09`). Windows and WSL verification passed with exit 0 (`verify-candidate-with-tar-and-rollback`, `verify-candidate-wsl`), confirming all four changed regions and four rollback images.

## Historical hardware entry observation and baseline restoration (original P2-022, reviewed by P2-023)

Phase 2 remains **IN PROGRESS**; its device gate is **UNPASSED**. The P2-022 hardware record verifies Samsung acceptance, early-entry state capture at EL1 and successful baseline restoration, but `status=2` (`HKE_INVALID_DAIF`), `reason=1` and a zero payload marker prove that the minimal arithmetic payload was skipped. The earlier completion claim is superseded by the [completion review](PHASE-2-COMPLETION-REVIEW.md).

Read [DEVICE-EXECUTION.md](DEVICE-EXECUTION.md) and the review before interpreting the historical generated packet. Its literal `phase_2_device_gate_passed: true` is an unsupported historical conclusion, retained unchanged for provenance. Current authority is `phase_2_completion_review` in `state.json` and its selected review evidence.


## Latest payload execution and status reconciliation (P2-024)

Phase 2 is **COMPLETE**; its A51 device gate is **PASSED**. The latest retained run records `status=1`, `reason=0`, marker `0x3143455845494b48` and the correct arithmetic value `0x68000000019526d5`. Baseline KernelSU Android was restored with matching boot-partition readback, boot completion and root after reboot. [Current review](PHASE-2-COMPLETION-REVIEW.md) and `state.json.phase_2_completion_review` select the successful evidence. That Phase 2 review preceded Phase 3 implementation; current Phase 3 status is in progress with its device gate unpassed.

Latest hardware packet: `evidence/phase-2/device-execution/20261113T010932628245Z/`. Latest host/QEMU result: `evidence/phase-2/early-entry-host/20261113T004009288671Z/result.json` (five cases, 228 checks). Latest kernel Image SHA-256: `3054cfe40d06c17963575d6e067ced0c38f8e532bb490e49f828ae66b0e5c420`. Independent offline recheck: `evidence/phase-2/completion-recheck/20261113T013048614147Z/result.json`, exit 0, including exact candidate reconstruction. This run proves normal Android continuation and baseline return. Actual SError fault/reset handling, sustained stability, a raw record dump, standalone XNU and no-flash launch remain unverified.


P3-021: corrected dual-bank loader passed all five fresh QEMU cases and 13 envelope corruption checks. Second standalone reset attempt `evidence/phase-3/loader-device-cycle/20261114T042250506272Z` FAILED: recovery attached the expected ramoops region but console was absent and pmsg contained historical bytes. Baseline readback, fresh Android completion and root restored. Qualifying full hardware runs remain 0/3. Header comparison found flags 2/vendor word 0 in the draft versus flags 10/vendor sentinel 0xECEFECEF in the pinned Samsung baseline; these fields are now corrected, with fresh build/QEMU/hardware evidence pending. This discrepancy is a hypothesis for the missing entry, not a confirmed root cause.


P3-022: corrected Samsung header passed all five fixed-placement QEMU cases. Hardware reset `evidence/phase-3/loader-device-cycle/20261114T043156953842Z` FAILED with no original console/pmsg envelope; baseline readback, fresh Android completion and root restored. Original Phase 2 entry PC, payload PC, continuation PC and x1/x2/x3 independently establish Image load base `0x80278000`, versus the draft's fixed `0x80080000`. This is an observed historical placement discrepancy, not a proved Phase 3 failure cause. QEMU can now replay that placement; qualifying hardware runs remain 0/3.


P3-023: complete-loader QEMU reset/full at observed `0x80278000` passed in packets 20261114T044111807678Z and 20261114T044111810089Z (full 12.761 seconds). The load discrepancy does not reproduce missing logs in QEMU. A new stackless pre-Linux diagnostic preserves the accepted Samsung Image header and patches only verified empty padding plus the original stext branch. It records nonce/CRC-bound measured registers to both pstore banks, then continues original Linux. Both placements passed QEMU. Selected probe `evidence/phase-3/entry-probe-build/20261114T045141448368Z` awaits phone execution; it does not launch XNU or qualify for Phase 3. Phase 3 remains 0/3; Phase 4 is authorized after its gate.


P3-024: accepted-Image entry diagnostic `evidence/phase-3/entry-probe-device/20261114T045243323110Z` FAILED; baseline restoration verified. Original binary console/pmsg, entry records, command times and boot IDs are retained. This diagnostic continues Linux and never qualifies as XNU execution; Phase 3 remains 0/3.


P3-023: complete-loader QEMU reset/full at observed `0x80278000` passed in packets 20261114T044111807678Z and 20261114T044111810089Z (full 12.761 seconds). The load discrepancy does not reproduce missing logs in QEMU. A new stackless pre-Linux diagnostic preserves the accepted Samsung Image header and patches only verified empty padding plus the original stext branch. It records nonce/CRC-bound measured registers to both pstore banks, then continues original Linux. Both placements passed QEMU. Selected probe `evidence/phase-3/entry-probe-build/20261114T045610587686Z` awaits phone execution; it does not launch XNU or qualify for Phase 3. Phase 3 remains 0/3; Phase 4 is authorized after its gate.


P3-024: accepted-Image entry diagnostic `evidence/phase-3/entry-probe-device/20261114T045658970138Z` PASSED; baseline restoration verified. Original binary console/pmsg, entry records, command times and boot IDs are retained. This diagnostic continues Linux and never qualifies as XNU execution; Phase 3 remains 0/3.

## Latest Phase 4 diagnostic groundwork (20261114T152659758004Z)

Fresh retained Android inventory passed all required checks in `evidence/phase-4/live-inventory/20261114T151220597502Z/result.json`: valid original FDT,
independent 1 MiB image equality, matching baseline and unchanged Android boot. GPIO debugfs is unavailable.
The fixed 3,096-byte controller snapshot ABI and guarded read-only MMIO template are implemented source only;
they have not been built, applied to XNU or run. GICv2 peripheral interrupts and real display/input/UFS drivers
remain pending. The obsolete synthetic builder now exits 2 before modifying Phase 3. Phase 4 remains incomplete.


## Latest Phase 4 platform adaptation (20261114T154338406253Z)

Guarded controller snapshot, static Darwin reporting and peripheral GICv2 support: applied=True; build and execution pending. Evidence: `evidence/phase-4/platform-adaptation/20261114T154338406253Z/result.json`. Phase 4 remains incomplete.


## Latest Phase 4 build correction (20261114T155443230088Z)

The failed P4-007 build is retained. The BSD driver now declares the exact private mapping interface and guards the selected Apple tree's 0x10000000 SoC base; QEMU's 0x08000000 must remain rejected. Evidence: `evidence/phase-4/probe-build-correction/20261114T155443230088Z/result.json`. Rebuild and execution are pending; Phase 4 remains incomplete.


## Latest Phase 4 interrupt correction (20261114T160314417746Z)

The original QEMU log reports SPI target 0x0 and three passing timer samples. UP target fields can be RAZ/WI; only a GIC reporting one interface gets an implicit target. QEMU's EL3 entry now assigns implemented SPIs to NS Group 1; it formerly assigned only SGIs/PPIs. Partial failure flags and timer results are retained independently. Evidence: `evidence/phase-4/spi-correction/20261114T160314417746Z/result.json`. Rebuild/execution are pending; Phase 4 remains incomplete.


## Reconnected Phase 4 inventory and cleanup (20261114T161442418538Z)

Inventory: `evidence/phase-4/live-inventory/20261114T160910754391Z/result.json`. Cleanup: `evidence/phase-4/inventory-selection-cleanup/20261114T161442418538Z/result.json`; passed=True. Leftover early_probe removed=False. Corrected SPI/guard QEMU integration passed all 19 checks. The next action is a bounded standalone controller snapshot with baseline restoration; Phase 4 remains incomplete.


## Phase 4 recovery preparation (20261114T163905012560Z)

Fresh inventory `evidence/phase-4/live-inventory/20261114T162645749263Z/result.json` passed and is selected. Isolated loader bounds, non-overlapping capture and watchdog code are prepared; build/execution remain pending. Phase 4 is incomplete.


Phase 4 isolated watchdog packaging (20261114T164550676023Z): built=True, error=None. Device is not currently enumerated; hardware gates remain unpassed.
