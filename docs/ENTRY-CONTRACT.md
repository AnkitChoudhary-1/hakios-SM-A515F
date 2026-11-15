> Publication note: this is a historical workspace document. Current completion decisions are in [PUBLIC-STATUS.md](PUBLIC-STATUS.md); raw local evidence is described in [PUBLICATION.md](PUBLICATION.md).

# A51 entry-route source review

Date: 11 November 2026. Status: inspected source, retained configuration and Image facts, followed by bounded CPU-state and host early-entry diagnostics; actual firmware/launch behavior remains unverified. The original entry-route review changed no Android/upstream source and contacted no phone. P2-017 later used a temporary Android module, while P2-018 changed only an isolated WSL source copy and linked an experimental Image on the host. Phase 2 remains `in_progress`.

The [live observations](LIVE-OBSERVATIONS.md), [offline map](RUNTIME-MAP.md), [host/QEMU prototype](LOADER-PROTOTYPE.md), [CPU-STATE.md](CPU-STATE.md) diagnostic and [EARLY-ENTRY.md](EARLY-ENTRY.md) candidate establish useful but different inputs. They do not supply a working A51 entry adapter, owned executable destination, persistent fault log or return path.

## Native Samsung/Linux Image

In `/opt/a51-everline/src`, `arch/arm64/kernel/head.S:74–111` emits the raw ARM64 header. Lines 97–101 write `.quad 0xecefecef` in the `CONFIG_PROCA` alternative. The retained installed configuration does not contain `CONFIG_PROCA`; absence is not an explicit `n`. This vendor word is explained by the inspected Samsung source and is not a compression signature. `arch/arm64/boot/Makefile:19,31–44` uses objcopy for raw Image and separate gzip/lz4 targets. `Documentation/arm64/booting.txt:61–65` requires external decompression when using a compressed Image.

| Retained Image | Stored kernel slice | Header effective image_size | Additional execution extent |
|---|---:|---:|---:|
| Installed KernelSU boot | 36,333,584 | 47,362,048 | 11,028,464 |
| Original boot backup | 36,313,128 | 47,259,648 | 10,946,520 |
| Recovery backup | 43,745,292 | 49,958,912 | 6,213,620 |

All three have `text_offset=524288`, `flags=10`, vendor word `0xecefecef` and `pe_header_offset=0`. Installed kernel-slice SHA-256 is `f9ccca797b1114600f935f7398fa14425c09a21c639951f7d94a376bd57bf57d`. Stored size alone cannot bound execution memory: `arch/arm64/kernel/image.h:75–79` defines `_end - _text`; `vmlinux.lds.S:232–255` places BSS/page tables before `_end`. This is a Linux Image extent finding, not an XNU extent parser or a selected A51 load address.

`booting.txt:73–130` describes effective image size and text offset from a usable aligned base. Lines 144–210 specify x0 as physical FDT, x1–x3 zero, masked DAIF, EL1/EL2 entry, MMU disabled, timers, coherency and DMA requirements. These are protocol expectations. Android container addresses, Image offsets or the high-bank declarations cannot identify Samsung's actual PC, relocation, accepted wrapper or usable allocation. `head.S:128–141` preserves arguments before EL setup; KASLR lines 155–156 replace saved x1–x3 with zeros, so Linux's saved values cannot recover the original firmware registers.

## Linux-to-payload candidate

The installed configuration has `CONFIG_KEXEC=n` (line 573). ARM64 `Kconfig:802–810` selects `KEXEC_CORE` and depends on `PM_SLEEP_SMP`; `arch/arm64/kernel/Makefile:53–54` conditionally builds kexec/relocation/reset objects. `kernel/sys_ni.c:27–29` provides the unavailable syscall fallback. Shell root alone does not add these missing objects.

Enabling kexec would still require a payload-specific trampoline and platform contract. `arch/arm64/kernel/relocate_kernel.S:109–114` clears x0–x3 before branching to x17; a payload expecting x0=FDT cannot assume it receives that ABI. `machine_kexec.c:156` rejects the ordinary path with stuck CPUs or more than one online CPU; lines 199–212 mask DAIF and use soft restart. `arch/arm64/kernel/cpu-reset.h:19–31` defines a nonreturning physical helper, and `arch/arm64/include/asm/mmu_context.h:122–128` installs an identity map.

`kernel/kexec_core.c:1159–1174` takes the ordinary path through device shutdown, CPU migration and machine shutdown into a nonreturning handoff. `drivers/base/core.c:2901–2987` invokes only available bus/driver callbacks (2956–2969); it does not independently prove every DMA agent has stopped. PSCI CPU_OFF may be missing, denied or time out. Configuration for hotplug/PSCI does not establish observed quiescing or current firmware capability. `kernel/kexec.c:195–203` checks `CAP_SYS_BOOT` and `kexec_load_disabled` when built. No capability query or shutdown was run in this continuation.

KernelSU's retained `KernelSU-Next/kernel/supercalls.c:680–825` reboot hook handles FD/manager/log/version/uname management. The inspected kernel-subtree loader/handoff search found no implementation. Module support/signature configuration also does not establish a module launch route: `kernel/module.c:3639–3644` checks `CAP_SYS_MODULE` and `modules_disabled`, and KernelSU `KernelSU-Next/kernel/app_profile.c:290–318` derives profile capabilities. Searches found no conventional exports of the inspected kexec/soft-restart/CPU-shutdown/device-shutdown/restart helpers. A custom implementation remains possible but is unimplemented and would need separate ownership/quiescing/entry/log/return evidence. This review made no Android configuration change.

## Upstream EFI candidate

The pinned upstream HakiOS loader is an AArch64 PE/COFF EFI application (`xnuloader/build.sh:8–12`). `loader.c:4311–4321` receives a real EFI handle/system table, reads `st->bs` and calls Boot Services. `choose_window:2773–2811` needs `GetMemoryMap`, conventional EFI memory and `AllocatePages`. Native Linux x0=FDT/x1=0 cannot supply this entry ABI; direct branching would misinterpret the arguments.

The installed config has `CONFIG_EFI=n` (611), and the retained Image has no PE header offset. `CONFIG_EFI_PARTITION=y` (375) enables partition parsing and supplies no Boot Services evidence. These facts do not prove the phone firmware has no possible EFI interface; they show that the retained native route does not establish one.

The concrete retained loader path at `3468–3488` keeps UEFI resident for return, consistent with the context-restoration discussion at `603–612`. Its introductory comment mentions ExitBootServices, but that comment does not describe this executed path. A51 return cannot be inferred from the upstream EFI/QEMU harness.

## Remaining contract and provenance

| Required contract | Current evidence | What remains |
|---|---|---|
| Launch mechanism / accepted wrapper | Native Image/header/config/source and EFI ABI | Actual accepted A51 loader entry |
| Physical allocations and lifetime | Historical DRAM/resources/reservations | Owned loader/control/payload/BSS/stack/FDT/log extents |
| Entry and transitions | Source protocol/trampoline/shutdown requirements; P2-017 Linux callback state; P2-018 synthetic early-entry behavior and host linkage | Samsung firmware/pre-Linux EL/PC/SP/registers/timer state, actual A51 execution and bounded CPU/DMA/cache/MMU/interrupt transitions |
| Logs and return | Existing Android logs, temporary diagnostic records and synthetic QEMU continuation | New-payload persistent/retrievable fault/reset logs and demonstrated Android/recovery return |

The first device gate is still a tiny payload executing on the A51, producing retrievable evidence and returning through a demonstrated procedure. No-flash launch remains a research branch. The next work is an exact Samsung packaging/entry route plus exception, watchdog, persistent fault-log, platform-transition and recovery/return contracts. A Samsung-packaged experimental image and device execution are unimplemented.

Source-review runs, all exit 0 unless stated: `20261111T111559032115Z-phase2-loader-native-image-entry-source-review`, `20261111T111711465665Z-phase2-loader-image-extent-efi-source-review-corrected`, `20261111T112050573703Z-phase2-loader-header-symbol-and-efi-contract-review`, `20261111T112129934143Z-phase2-loader-retained-image-extent-readback`; Linux route runs `20261111T111528747843Z-phase2-linux-payload-route-source-map`, `20261111T111637978502Z-phase2-linux-payload-route-source-detail`, `20261111T111801445839Z-phase2-linux-payload-route-capability-cpu-inspection`, `20261111T112057149656Z-phase2-linux-payload-route-shutdown-ksu`, `20261111T112237426739Z-phase2-linux-payload-route-api-contract`, `20261111T112406726405Z-phase2-linux-payload-route-retained-config`. Metadata/output and exact arguments are under `runs/`.

Failed `20261111T111648136735Z-phase2-loader-image-extent-efi-source-review` requested nonexistent `asm/image.h`; the corrected run used `arch/arm64/kernel/image.h`. The capability-inspection source-root `.config` read was unavailable and recovered using the retained installed configuration; deliberate no-match search exit codes remain visible inside successful review commands. Preserve these observations rather than interpreting absent files/searches as runtime proof.

Android commit `468ab8343364e4d3a267e670fa6a22fd4197a805` is recorded lineage; the source root lacks Git metadata. File hashes pin inspected bytes. Upstream HakiOS HEAD `63fc2b4633bac3af8e57dadab9f5a8d4cb940438` was verified; `loader.c` SHA-256 `8796088683fcd6f2a28232e1623e4915cb2e1fe1ab10c6ce78a3a613c8440099`, `build.sh` `7d5cd24a8a153dde804ba8d139ec5c60405f476e3233870c2768e1e0c31296f7`. This review creates no patch against either source project. Reproduce the recorded read-only commands against matching files; preserve the full source pins, logs and historical Image inputs. Documentation rollback uses the 14-file runtime-map documentation baseline; no device rollback is required.

Retained source packet: `evidence/phase-2/entry-route/20261111T112915805884Z/summary.json`, 24,032 bytes, SHA-256 `af9e7c84bad96f91f3ffda3d5ce3e3ca8a5e5a9707711cabb473c31c0f4354e5`; 29 complete source/config copies, 24 facts with checked inclusive citation ranges and 11 review records. The 30-file index totals 833,430 bytes; index SHA-256 `2167397e5e4448b9254d60168f3cfab92bfc03bf89dfd057d622452c20cc41c3`. Retention run `20261111T112907412756Z-phase2-entry-route-source-retention` passed. Original Image bytes remain in their existing retained Android inputs rather than being duplicated. The summary retains their container/slice pins and reported execution sizes.


## Executed lifetime-bound plan diagnostic (P2-016)

The [allocation/plan diagnostic](OWNERSHIP-PROBE.md) passed on the A51: three fixed 64 KB plan bindings, seven rejected wrong/stale/released requests, ten state observations and 21 ordered kernel messages. All 23 rooted commands and the transfer succeeded. All three sequential allocations were cleared and released; Android kept the same boot and the module/file are absent. SELinux was Enforcing and existing taint stayed 4096. Native ASan/UBSan checks passed 1,408 assertions; all 17 import CRCs and exact vermagic matched. Windows/WSL replay and all 44 corruption guards per host passed.

Selected host result: `evidence/phase-2/ownership-probe-build/20261111T141326924789Z/result.json`. Selected device result: `evidence/phase-2/ownership-probe-device/20261111T141913580938Z/result.json`. The fixed plan is checked inside the allocation owner under one mutex; a receipt is historical once its callback returns. No external allocation certificate, loader-layout acceptance, copied payload or standalone execution is established. Current released addresses cannot authorize future placement. Phase 1 remains complete, Phase 2 in progress, and standalone launch/platform/fault-log/return gates remain false.

Next: define the bounded A51 diagnostic adapter execution/fault contract, then resolve standalone entry, CPU/MMU/cache/DMA/interrupt transitions, recoverable payload/fault logs and demonstrated return. See the new guide for exact commands, source provenance, failed offline checks and rollback.

## Android Linux callback CPU-state diagnostic (P2-017)

The temporary [CPU-STATE.md](CPU-STATE.md) diagnostic captured eight `on_each_cpu()` callbacks, one on each online CPU 0–7. All eight records reported EL1. Their common `SCTLR_EL1=0x34d5d91d` has the MMU, data cache and instruction cache enabled, and `CNTFRQ_EL0=26000000` records a 26 MHz counter. MIDR identified CPUs 0–3 as Cortex-A53 and CPUs 4–7 as Cortex-A73.

Selected device result: `evidence/phase-2/cpu-state-device/20261111T155948363876Z/result.json`, SHA-256 `6b6bcae092f51def03aa8b252e529eac644d59fb686798fec14c19fbc0078099`. The result establishes only normal Android Linux callback state. It does not establish Samsung firmware entry, pre-Linux or MMU-off state, standalone execution or a physical handoff, and it supplies no persistent fault log or demonstrated Android/recovery return.

## Host-only early-entry candidate and Image linkage (P2-018)

The [EARLY-ENTRY.md](EARLY-ENTRY.md) candidate passed five synthetic QEMU cases totaling 228 checks. Its isolated Android-source adaptation changed six paths; the retained 8,757-byte patch has SHA-256 `bb958f092d82f5b1d5b81761d5198d2a8bf0e80657ecc48a02d27b6e207f409f`. The host build linked a 36,334,080-byte Linux `Image` with SHA-256 `87c0401361d4503afb0b266b15ff0caf1e64f505d61d53be700e8b6c6d8e9cf6`.

Selected final verifier runs were `20261111T172248699374Z-phase2-early-entry-evidence-final-windows`, `20261111T172248517634Z-phase2-early-entry-corruption-final-windows`, `20261111T172248928798Z-phase2-early-entry-evidence-final-wsl` and `20261111T172249251195Z-phase2-early-entry-corruption-final-wsl`. The Image was not Samsung-packaged, flashed, booted or executed on the A51. Exception vectors, a device watchdog, persistent reset/fault logging, platform transitions and Android/recovery return remain unavailable. A51 execution, standalone HakiOS execution, return and the Phase 2 device gate remain false.

## P2-019 packaging result versus entry contract

The host-only [SAMSUNG-BOOT-DRY-RUN.md](SAMSUNG-BOOT-DRY-RUN.md) result proves that the P2-018 kernel can be represented inside one pinned Android v2 template while preserving all bytes outside four declared regions. The calculated full-sequence SHA-256 is `73d88c699dda238238b7b2b1105caea248b9ef3aef282a3f01b566f0fd894a58`, but the sequence was never emitted or retained.

P2-019 does not resolve this contract's firmware side: it supplies no accepted Odin/container path, bootloader policy result, pre-Linux register state, physical destination ownership, exception vectors, watchdog/reset path, platform transition, persistent fault evidence or return demonstration. Packaging-layout consistency is verified host-only while actual Samsung entry and every A51 execution/log/return gate remain false.
