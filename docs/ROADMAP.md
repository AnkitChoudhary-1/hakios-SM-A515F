> Historical plan: use PUBLIC-STATUS.md for the current evidence and completion decisions.

# Galaxy A51 HakiOS roadmap — ten phases

Created: 10 November 2026. Target device: Samsung Galaxy A51 SM-A515F, Exynos 9611, Mali-G72 MP3, 1080×2400/60 Hz panel.

**First usable release target:** sustained 60 fps in a defined interface/browser test suite, Wi-Fi, Bluetooth pairing and headset playback, speaker/headphone/microphone audio, controlled charging and working Safari browsing. Intermediate development builds will have fewer features.

**Current state (reviewed 11 November 2026, Asia/Calcutta):** Phase 1 is complete. The pinned clean host build and minimal open user program passed in QEMU; its retained inputs and completion bundle were reverified. Phase 2 is `in_progress`: the [retained boot/DT/memory host audit](PHASE-2-HOST-AUDIT.md), independent libfdt cross-check, [host payload-layout validator](PAYLOAD-LAYOUT.md) and [retained entry/memory/logging/return source trace](SOURCE-TRACE.md) passed their host checks, and [loader design requirements](LOADER-DESIGN.md) are documented. The validator accepts synthetic assumptions only; 92 guards passed on each host and all 21 retained-A51 cases were rejected as expected. The source trace preserves 28 files/40 excerpts, three base FDTs/22 symbols and 82 indexed files, with 35 guards and original-byte replay per host; Android lineage is recorded rather than a verified Git HEAD. Privileged read-only observations now verify Shell root and the Linux-exported FDT. The [host/QEMU loader prototype](LOADER-PROTOTYPE.md) is implemented: 2,609 native sanitizer assertions passed, and the freestanding AArch64 adapter executed a tiny compiled test payload with seven verified frames and QEMU exit 0. The temporary [CPU-STATE.md](CPU-STATE.md) diagnostic verified Linux runtime callback state on all eight CPUs, while the host-only [EARLY-ENTRY.md](EARLY-ENTRY.md) candidate passed five QEMU cases/228 checks and linked into an isolated Linux `Image`. Neither establishes Samsung firmware entry or standalone A51 execution. The A51 adapter, runtime ownership importer and Samsung-packaged experimental image remain unimplemented; A51 execution, persistent fault-log, return and the Phase 2 device gate remain false. Phases 3–10 remain planned. No A51 HakiOS loader, XNU kernel boot, driver or Darwin user-space behavior has been validated on the phone.

**P2-019 update (12 November 2026):** the host-only [SAMSUNG-BOOT-DRY-RUN.md](SAMSUNG-BOOT-DRY-RUN.md) reconstruction verified that the P2-018 kernel fits one pinned Android v2 boot layout through four declared in-memory changes. The calculated candidate SHA-256 is `73d88c699dda238238b7b2b1105caea248b9ef3aef282a3f01b566f0fd894a58`; no candidate bytes or installable image were emitted, and no phone operation or device execution occurred. Phase 2 remains `in_progress`.

This roadmap records work and acceptance criteria. It does not initiate flashing, repartitioning or device experiments.

## Release definition

- Display target: native 1080×2400 output with 60 Hz presentation. Record internal rendering resolution separately; any reduced-resolution release target must be explicitly documented rather than counted as native rendering.
- Performance target: in named home-screen, Settings and Safari scrolling/animation tests, at least 99% of scheduled animation frames meet their intended display refresh over a 30-minute suite. Record render times, missed refreshes and visible hitches. The 16.7 ms frame budget is a design target; unrestricted websites are outside this measurable guarantee.
- Wi-Fi target: scan, WPA2-Personal join, DHCP/DNS, HTTPS traffic, reconnect and sustained operation. Record additional security modes separately.
- Bluetooth target: device discovery, pairing, reconnect, BLE discovery and A2DP headset playback while Wi-Fi is active. Headset microphone/call profiles are separate work unless added to scope.
- Audio target: speaker and wired-headphone playback, microphone recording, volume/mute and route switching.
- Charging target: battery/temperature reporting, basic USB charging with correct current and temperature limits, attach/detach behavior and sustained operation under load. Fast charging is a separate milestone.
- Safari target: successful HTTPS navigation, JavaScript, scrolling, links/back/forward and reload on a fixed page suite, with stable browser processes. Video/DRM and every modern website are not implied by this gate.
- Reliability target: ten consecutive development boots and return-to-Android/recovery cycles, followed by sustained combined-use tests with retrievable logs and no unresolved critical driver faults.

These are proposed engineering acceptance criteria, not results already achieved. Apple services and the App Store remain outside upstream support. Calls, SMS, mobile data, cameras, fingerprint, NFC and full suspend/resume are outside this first-release scope. Session duration, battery behavior and those missing features must be documented with the release.

## Phase 1 — Establish the device baseline and reproducible upstream build

**Status:** complete; original host/QEMU evidence recorded 10 November and rechecked 11 November 2026. Basic inventory, privileged Shell root and Linux-exported FDT/memory observations are verified; original firmware entry, usable-memory ownership and fitted peripheral revisions remain explicit later-phase unknowns.

**Purpose:** prove that our inputs and build environment are usable before writing an Exynos port.

Work:

- Lock upstream repositories, branches and dependencies to examined commits; resolve the MediaTek legacy/new-layout discrepancy and identify missing Mali user-space pieces.
- Inventory existing A51 boot/recovery/DTBO backups, boot-image structure and partition dimensions. When connected for implementation, verify board revision, physical/free/reserved RAM and peripheral identities against retained sources.
- Record matching firmware locations and the Linux references for display, GPU, SCSC/WLBT, ABOX, SM5713 and UFS.
- Build and boot upstream open XNU with minimal open user space in QEMU; retain compiler versions, commands and logs.
- Audit what matching Darwin user space, SDKs and compatibility components phase 10 will require, including what is absent from the public source. Record unresolved availability issues early.

**Deliverables:** device inventory, dependency lock record, reproducible build instructions, QEMU boot log and user-space gap list.

**Pass gate:** clean rebuild reaches the minimal user program in QEMU; device-specific inputs are traceable; missing dependencies have explicit status. QEMU success establishes build readiness, not A51 bootability.

## Phase 2 — Design and prove the A51 experimental loader

**Depends on:** phase 1.

**Status:** `in_progress`, with host analysis, version 1 layout checks, retained-source trace, live observations and the host/QEMU loader prototype verified; device gate unpassed. Four retained images, five DT tables, 11 FDTs and 13 source records are checked against original bytes; libfdt matched 1,380 properties. Layout guards passed all 92 cases on Windows and WSL; one synthetic case was accepted and 21 A51 cases were rejected with required diagnostics. Both demonstrations replayed on both hosts. Source-trace guards passed 35 cases per host, preserving 28 complete sources, 40 excerpts, three base FDTs and 22 configuration symbols in 82 indexed files; capture and both host replays passed. The inspected Android root has no Git metadata: its commit is recorded lineage, with per-file hashes pinning inspected bytes. KASLR register limits, conditional FDT/log exports, DEBUG_FS-disabled memory exports and reset initialization dependencies are documented. Version 1 has no runtime ownership importer and selects no executable A51 destination. The upstream QEMU payload address `0xF0000000` overlaps declared modem memory, so it cannot be reused on the A51; the new prototype's virtual address also establishes no A51 placement. The Linux-exported live FDT is verified, but original firmware fixups/overlay index, entry state, owned dynamic/secure/runtime memory and a new payload's device logs/return remain unresolved. The prototype's freestanding C core and QEMU adapter now execute on the host; its fuel is cooperative accounting, callbacks are trusted compiled code, and CPU fault/watchdog/physical handoff/reset work remains planned. The historical host/QEMU prototype made no phone write or device payload execution. P2-014 through P2-016 subsequently executed temporary Android allocation diagnostics with verified cleanup. P2-017 observed all eight Linux callbacks at EL1 with translations and caches enabled; it does not describe firmware or pre-Linux state. P2-018 passed five host QEMU cases/228 checks and linked an isolated experimental Linux `Image`; it was not Samsung-packaged or executed on the phone. Standalone A51 execution, persistent fault/reset logging, platform transitions, demonstrated return and the Phase 2 device gate remain false.

Work:

- Derive the Samsung boot-image entry path, load addresses, reserved memory and required execution state from this phone's images and Exynos sources.
- Investigate a no-flash RAM launch or Linux-to-payload handoff. The existing kernel has kexec disabled; enabling it alone does not establish an XNU path.
- If a no-flash route cannot be established, document a separate experimental boot-image design that loads payloads into RAM and a concrete restoration path. Keep this decision visible; do not call it a no-write boot.
- Implement a minimal loader/trampoline with retrievable logs, payload bounds checks, CPU/cache/interrupt handoff and a defined reset mechanism.
- Validate image size/layout on the host before any later device execution. Preserve the existing partition layout in this design.

P2-019 satisfies the host byte-layout part of the last work item for one pinned template/kernel pair only. It does not satisfy Samsung firmware acceptance, actual entry, device execution, retrievable logs or return.

**Deliverables:** loader source, execution/memory-map notes, experimental image, host validation record and test/restore procedure.

**Pass gate:** on the A51, the loader executes a minimal payload, produces retrievable evidence and the device returns to Android/recovery through the demonstrated procedure. A compiled image alone does not pass.

**Decision point:** if execution or recovery cannot be established, resolve it before committing to downstream driver work. No-flash launch may remain an unresolved research branch.

## Phase 3 — Boot minimal XNU from RAM

**Depends on:** phase 2.

Work:

- Add the Exynos platform description and XNU boot arguments, memory mapping, interrupt/timer support and early console/logging.
- Begin with one CPU and a small RAM root filesystem; establish required basic GPIO/I2C/SPI/MMIO services as driver foundations.
- Start a minimal open user program, then expand to additional CPU cores after the single-core path is repeatable.
- Handle faults, bounded test duration, reset and log retrieval. Establish an initial memory budget before larger user-space images.

**Deliverables:** minimal A51 XNU configuration, bootable RAM payload, memory budget and kernel/user-program logs.

**Pass gate:** three consecutive device runs reach the user program with working timers, repeatable log retrieval and a demonstrated return path. Record which cores work; do not infer multicore support from the CPU count.

## Phase 4 — Add display, touch, keys and read-only storage

**Depends on:** phase 3.

Work:

- First identify whether the Samsung boot framebuffer can be preserved; then implement the Exynos DECON/DSIM/panel control required for reliable output and brightness.
- Bring up Melfas touch and power/volume keys through the matching bus/interrupt paths; expose input events to the interface layer.
- Implement Exynos UFS controller/PHY initialization and read-only block/image access. Keep writable session state in RAM initially.
- Demonstrate loading a larger test image without assuming Android encrypted userdata is directly usable by Darwin.

**Deliverables:** framebuffer/input demonstration, read-only UFS driver and verified image-loading path.

**Pass gate:** correct display dimensions and input coordinates, repeatable brightness/key behavior, and read data matching known image contents. Demonstrate that the driver does not enable storage writes. Stable 60 fps is not yet this phase's claim.

## Phase 5 — Implement charging, battery reporting and thermal controls

**Depends on:** phase 3's bus/timer foundations; phase 4 supplies a useful test interface.

Work:

- Implement SM5713 charger/fuel-gauge access and Samsung battery policy using the matching A51 definitions.
- Handle USB/cable detection, input/current limits, battery voltage/state/temperature and attach/detach events.
- Add Exynos thermal monitoring and CPU/GPU clock/power controls needed for sustained use. Preserve the hardware's documented operating limits.
- Expose battery and charging information through the Darwin interface; validate charging beyond a UI icon.

**Deliverables:** charging/power drivers, readable measurements and charging/load test records.

**Pass gate:** current/voltage/temperature readings are credible against the Android baseline and suitable external measurements where needed; charging behaves correctly on attach/detach; limits and thermal responses are verified. Extended performance sessions wait for this gate.

## Phase 6 — Bring up Mali-G72 and the accelerated graphics pipeline

**Depends on:** phases 4 and 5; uses core platform work from phase 3.

Work:

- Adapt relevant G52/Bifrost ideas while replacing MediaTek register addresses, power assumptions and clock sequencing with verified Exynos data.
- Progress through GPU identification/reset, a minimal job, GPU page tables, buffers/cache coherence, completion/error handling and repeated submissions.
- Implement/adapt the XNU/IOKit user-client interface, buffer sharing and fences required by Mesa/Panfrost and the matching graphics user space.
- Resolve the missing/publication/layout gaps in the Mali user-space path; validate the chosen Metal/compositor bridge.
- Connect rendering to 60 Hz display presentation and measure native-resolution test animations under sustained load.

**Deliverables:** G72 probe/job logs, graphics driver and user-space integration, rendered test scenes and frame-time captures.

**Pass gate:** genuine GPU rendering with correct output, repeatable memory/fence behavior and sustained 60 Hz presentation on the defined graphics tests. The final home-screen/Safari performance gate remains in phase 10.

**Decision point:** a persistent graphics or user-space gap requires revisiting the release target before investing in interface polish. Software rendering is not evidence of the requested accelerated 60 fps release.

## Phase 7 — Implement Samsung Wi-Fi

**Depends on:** phases 3 and 5; shares radio infrastructure with phase 9.

Work:

- Bring up SCSC/WLBT transport, memory/interrupt interfaces and matching firmware loading.
- Implement scanning, joining, association/authentication and required packet handling; reuse generic upstream networking only where its interface matches.
- Integrate Darwin interface configuration, DHCP/DNS and Settings controls.
- Add disconnect/reconnect behavior, useful error logs and basic sustained traffic tests.

**Deliverables:** Wi-Fi driver/service integration and connection/traffic logs.

**Pass gate:** WPA2-Personal join, DHCP/DNS and HTTPS traffic work, reconnect succeeds repeatedly, and sustained traffic is stable. Bluetooth coexistence is verified again in phase 9.

## Phase 8 — Implement audio

**Depends on:** phases 3 and 5; phase 4 helps interactive validation.

Work:

- Bring up ABOX DSP firmware, IPC, clocks and DMA; adapt matching codec/amplifier control and routing.
- Implement speaker, wired-headphone and microphone streams, volume/mute and plug/unplug handling.
- Integrate Darwin audio services and verify formats, latency, route switching and recovery after a stopped stream.

**Deliverables:** audio driver/services, playback/recording samples and route-switching test records.

**Pass gate:** sustained playback and microphone recording work with correct routing and no recurring dropouts. Test repeated start/stop and wired-headphone changes. Bluetooth headset playback is completed with phase 9.

## Phase 9 — Implement Bluetooth and radio/audio coexistence

**Depends on:** phases 7 and 8, plus core/power foundations.

Work:

- Add WLBT Bluetooth transport/HCI support and the Darwin daemon/interface integration.
- Implement discovery, pairing and reconnect; validate BLE discovery separately from classic Bluetooth.
- Complete A2DP headset playback through the audio integration. Keep headset microphone/call profiles as explicitly separate scope.
- Test simultaneous Wi-Fi browsing/traffic and Bluetooth playback, including disconnect and reconnect behavior.

**Deliverables:** Bluetooth integration, profile/status matrix and coexistence test results.

**Pass gate:** a named headset pairs, reconnects and plays audio while Wi-Fi carries traffic; discovery and BLE tests pass. A Bluetooth switch or visible device list alone does not pass this phase.

## Phase 10 — Integrate the Darwin interface, Safari and first release

**Depends on:** phases 4–9 and phase 1's matching user-space availability.

Work:

- Integrate matching, separately supplied Darwin/iOS user space and available compatibility components, launchd jobs, IPC/services, graphics, input, networking, audio and battery reporting.
- Reach the home screen and usable Settings, then bring up Safari/WebKit processes, certificates/TLS/DNS, JavaScript and RAM-backed writable state.
- Measure the defined home-screen/Settings/Safari performance suite, track memory pressure and fix missed refreshes, hangs and process crashes.
- Run combined charging, browsing, Wi-Fi and Bluetooth audio tests, followed by ten consecutive boot/return cycles.
- Package reproducible build instructions, image checksums, test results, actual boot arrangement, restore instructions and a precise supported/missing feature list.

**Deliverables:** candidate first-release build, reproducibility package, browser fixtures/frame-time results and release acceptance report.

**Pass gate:** every release criterion above has device evidence. An unavailable user-space component, broken charging path or failure to meet the performance suite means this remains a development build. Keep unresolved results visible; do not infer support from another phone's documentation.

## Effort, sequencing and working rules

The previous effort assessment (external local reference; see PUBLICATION.md) provides the rough engineering allowances: approximately 16–45+ engineer-months, with about 18–48+ calendar months budgeted for a single full-time specialist. These phase boundaries reorganize those work packages; their numbering is not a calendar estimate. The dedicated no-flash launch path remains an additional unbounded research item. Revise estimates after phases 2, 3 and 6 provide real device evidence.

The numbered order is the default implementation sequence. Phase 1 can audit user-space gaps early; phases 7 and 8 can overlap after the required platform/power work. Bluetooth headset validation follows both Wi-Fi and audio. Phase 10 integration preparation can begin earlier, but its release gate waits for every required subsystem.

For each phase, retain the tested source commit, device configuration, build identity, commands, logs, observed failures and pass/fail record. Host tests should validate parsers, memory/layout bounds and other meaningful logic; QEMU and compilation cannot replace A51 driver tests. Advance only on observed completion evidence, and revise the roadmap when hardware results change an assumption.

## Supporting records

- Initial feasibility assessment (external local reference; see PUBLICATION.md)
- Effort and RAM-boot assessment (external local reference; see PUBLICATION.md)
- Retained running kernel configuration (external local reference; see PUBLICATION.md)
- Prior Android kernel installation and backup record (external local reference; see PUBLICATION.md)
- [Phase 1 acceptance report](PHASE-1-RESULTS.md)
- [Phase 2 retained-image host audit](PHASE-2-HOST-AUDIT.md)
- [A51 loader design requirements](LOADER-DESIGN.md)
- [Retained entry, memory, logging and return source trace](SOURCE-TRACE.md)
- [Android Linux callback CPU-state diagnostic (CPU-STATE.md)](CPU-STATE.md)
- [Host-only early-entry candidate (EARLY-ENTRY.md)](EARLY-ENTRY.md)
- [Samsung boot-image packaging dry-run (SAMSUNG-BOOT-DRY-RUN.md)](SAMSUNG-BOOT-DRY-RUN.md)

## Privileged observation update, 11 November

Phase 1 remains complete; Phase 2 remains in progress. [Privileged live evidence](LIVE-OBSERVATIONS.md) now verifies KernelSU Shell root, the unchanged Linux-exported FDT, real iomem addresses, existing Android logs and matching boot/DTBO/recovery hashes. The corrected 49-query capture retains 44 successes/five actual remote failures and 153 files; 41 guards passed on Windows/native WSL and replay passed on both hosts. Independent libfdt matched 1,087 nodes/91 critical properties.

The current capture resolves Linux-exported-tree availability, superseding earlier live-FDT/root unknowns in the historical host status. Original firmware fixups, exact overlay index, entry/platform state, owned usable memory and new-payload device log/return behavior remain unproved. The host/QEMU loader core is now implemented and tested; the A51 adapter, experimental Samsung image, A51 XNU changes and drivers remain unimplemented. Next work is the actual A51 entry/memory/platform/log/return contract and adapter. Phase 2 still requires actual device execution and demonstrated return.

## Offline observation and entry-contract update, 11 November

The [offline runtime-observation map](RUNTIME-MAP.md) is implemented and verified: 80 guards passed on Windows/native WSL, and the selected historical Linux projection replayed against the complete original capture on both hosts. It records five DRAM declarations (6,327,107,584 bytes), 20 fixed reservation spans, 112 exclusion records, three unresolved dynamic placements and zero verified owned intervals; all 27 diagnostic candidates are rejected. The [entry-route source review](ENTRY-CONTRACT.md) retains 29 source/config files and 24 cited facts, explaining native Image extent, Linux kexec restrictions and the upstream EFI ABI. The A51 ownership-certification importer, adapter, physical transitions, new-payload logs and demonstrated return remain unresolved. No phone query/write/reboot/payload execution occurred in this host-only continuation.

Phase 2 still has four device-side work packages: an accepted launch/entry mechanism, owned physical memory and platform transitions, retrievable payload/fault logs, and demonstrated return to Android/recovery. The host prototype and historical map reduce implementation uncertainty; they do not provide a reliable completion percentage or schedule while launch and ownership are unresolved. Phase 1 remains complete and Phases 3–10 remain planned.

## Read-only prerequisite milestone (P2-013)

The [connected A51 tests](DEVICE-PREREQUISITES.md) passed 33 of 35 read-only queries, with two true remote failures retained. Root, boot ID, Linux-exported FDT and kernel configuration were stable and matched the earlier Android capture. All eight CPUs were online. Module support and the rooted child’s module-loading capability are verified observations; exact module ABI and successful module execution remain unverified. Kexec remains disabled. Windows/WSL replay and three corruption checks passed. Current-session phone-query status is true; historical host/source/runtime flags remain unchanged. No phone write/reboot/module/payload execution occurred.

Selected supplement: `evidence/phase-2/device-prerequisites/20261111T121643948118Z/report.json`. Next: verify the exact installed module ABI and design a small allocation/logging diagnostic; actual A51 handoff, owned payload memory, physical transitions, payload/fault logs and Android/recovery return still require implementation and execution. Phase 2 remains in progress.

## Executed Android page diagnostic (P2-014)

The [one-page diagnostic](PAGE-PROBE.md) built against the matching installed kernel and passed actual A51 module load/unload, 4 KB zero/pattern checks and controlled failed-init cleanup. Seven lifecycle messages were retrieved, Android kept the same boot, both pages were released and the temporary module file was removed. All 20 rooted commands plus the transfer succeeded. Exact vermagic and nine imported CRCs matched; original Android source/output files remained unchanged. Windows/WSL offline replay passed. The out-of-tree taint flag changed from 0 to 4096 and remains after unload.

Selected host result: `evidence/phase-2/page-probe-build/20261111T124258280383Z/result.json`. Selected device result: `evidence/phase-2/page-probe-device/20261111T124942840876Z/result.json`. Current session phone-query/write flags are true for this temporary Android diagnostic; historical read-only/prototype/map/source records retain their original flags. Neither released page is a usable current payload destination. Standalone A51 loader execution, CPU/DMA/cache/MMU/interrupt handoff, persistent fault logs and demonstrated return remain unresolved. Phase 1 remains complete, Phase 2 in progress and its device gate false; Phases 3–10 remain planned. Next: define the payload memory budget and ownership/lifetime contract before implementing physical handoff.

## Executed Android 64 KB arena diagnostic (P2-015)

The [64 KB arena diagnostic](ARENA-PROBE.md) passed actual A51 normal load/hold/unload and controlled failed-init cleanup. One 65,536-byte order-4 allocation was held with six region patterns, rechecked, cleared and released; two module Live records bracketed a one-second sleep. Seven lifecycle logs, all 23 rooted queries and one transfer succeeded. Android kept the same boot; the module and unique temporary file are absent. SELinux was Enforcing; existing taint stayed 4096. Both sequential lifetimes are released and cannot authorize current loader placement. The budget is a diagnostic allowance, not a final XNU memory budget.

Selected host result: `evidence/phase-2/arena-probe-build/20261111T132918243669Z/result.json`. Selected device result: `evidence/phase-2/arena-probe-device/20261111T133447277112Z/result.json`. Windows/WSL final replay and 10 budget mutations/nine lifetime rejections per host passed; 24 packet corruption cases were rejected on Windows. Exact vermagic and nine import CRCs matched, and original Android source/output metadata and pinned bytes remained unchanged. Phase 1 remains complete, Phase 2 in progress and every standalone launch/placement/handoff/fault-log/return gate false.

Next: implement a live lifetime-bound ownership certificate and loader-plan binding, then resolve actual A51 entry, CPU/MMU/cache/DMA/interrupt transitions, recoverable payload/fault logs and the demonstrated return procedure. No standalone payload or copied QEMU binary ran on the phone.


## Executed lifetime-bound plan diagnostic (P2-016)

The [allocation/plan diagnostic](OWNERSHIP-PROBE.md) passed on the A51: three fixed 64 KB plan bindings, seven rejected wrong/stale/released requests, ten state observations and 21 ordered kernel messages. All 23 rooted commands and the transfer succeeded. All three sequential allocations were cleared and released; Android kept the same boot and the module/file are absent. SELinux was Enforcing and existing taint stayed 4096. Native ASan/UBSan checks passed 1,408 assertions; all 17 import CRCs and exact vermagic matched. Windows/WSL replay and all 44 corruption guards per host passed.

Selected host result: `evidence/phase-2/ownership-probe-build/20261111T141326924789Z/result.json`. Selected device result: `evidence/phase-2/ownership-probe-device/20261111T141913580938Z/result.json`. The fixed plan is checked inside the allocation owner under one mutex; a receipt is historical once its callback returns. No external allocation certificate, loader-layout acceptance, copied payload or standalone execution is established. Current released addresses cannot authorize future placement. Phase 1 remains complete, Phase 2 in progress, and standalone launch/platform/fault-log/return gates remain false.

Next: define the bounded A51 diagnostic adapter execution/fault contract, then resolve standalone entry, CPU/MMU/cache/DMA/interrupt transitions, recoverable payload/fault logs and demonstrated return. See the new guide for exact commands, source provenance, failed offline checks and rollback.

## Executed Android CPU callback-state diagnostic (P2-017)

The temporary [CPU-STATE.md](CPU-STATE.md) diagnostic completed eight `on_each_cpu()` callbacks on CPUs 0–7. Every callback observed EL1; common `SCTLR_EL1=0x34d5d91d` showed the MMU, data cache and instruction cache enabled, and the architectural counter was 26 MHz. MIDR identified CPUs 0–3 as Cortex-A53 and CPUs 4–7 as Cortex-A73. The module unloaded, its temporary file was removed and Android retained the same boot.

Selected device result: `evidence/phase-2/cpu-state-device/20261111T155948363876Z/result.json`, SHA-256 `6b6bcae092f51def03aa8b252e529eac644d59fb686798fec14c19fbc0078099`. This verifies only normal Linux runtime callback state, not Samsung firmware entry, pre-Linux or MMU-off state, standalone execution or a physical handoff. It does not satisfy persistent fault-log, Android/recovery return or the Phase 2 device gate.

## Host-only early-entry candidate and isolated Image linkage (P2-018)

The [EARLY-ENTRY.md](EARLY-ENTRY.md) candidate passed five synthetic QEMU cases totaling 228 checks. Its six-path isolated source adaptation is retained as an 8,757-byte patch with SHA-256 `bb958f092d82f5b1d5b81761d5198d2a8bf0e80657ecc48a02d27b6e207f409f`. The isolated host build linked a 36,334,080-byte Linux `Image` with SHA-256 `87c0401361d4503afb0b266b15ff0caf1e64f505d61d53be700e8b6c6d8e9cf6`.

Selected final verifier runs were `20261111T172248699374Z-phase2-early-entry-evidence-final-windows`, `20261111T172248517634Z-phase2-early-entry-corruption-final-windows`, `20261111T172248928798Z-phase2-early-entry-evidence-final-wsl` and `20261111T172249251195Z-phase2-early-entry-corruption-final-wsl`. The Image was not Samsung-packaged, flashed, booted or executed on the A51. Exception vectors, a device watchdog, persistent reset/fault logging, platform transitions and Android/recovery return remain unavailable. Phase 2 remains `in_progress`; A51 execution, return and its device gate remain false, while Phases 3–10 remain planned.

## Host-only Samsung boot-image reconstruction (P2-019)

The [SAMSUNG-BOOT-DRY-RUN.md](SAMSUNG-BOOT-DRY-RUN.md) milestone verified on Windows and native WSL that the P2-018 `Image` fits the retained Android v2 template's existing kernel slot. The 61,865,984-byte in-memory sequence has calculated SHA-256 `73d88c699dda238238b7b2b1105caea248b9ef3aef282a3f01b566f0fd894a58`; only the kernel-size field, legacy boot ID, fixed kernel slot and AVB boot digest change. The selected evidence packet contains seven files/58,533 bytes, and the core/evidence suites passed 11/30 cases per host.

No candidate image, `.img`, Odin archive, installation, phone query/write, reboot, flash or execution occurred. The unsigned algorithm-0 AVB descriptor check is not proof of Samsung's complete verified-boot policy, and the prior Android kernel's device boot does not transfer to this candidate. Firmware acceptance/entry, exception vectors, watchdog/reset, owned platform transitions, persistent logs, standalone execution and demonstrated Android/recovery return remain unresolved. Phase 2 therefore stays `in_progress`; all device execution/log/return gates remain false.
