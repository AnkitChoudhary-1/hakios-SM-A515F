> Publication note: this is a historical workspace document. Current completion decisions are in [PUBLIC-STATUS.md](PUBLIC-STATUS.md); raw local evidence is described in [PUBLICATION.md](PUBLICATION.md).

# A51 Android page diagnostic

11 November 2026. Implemented, built and executed on SM-A515F `A51_SERIAL_HERE`. The normal module load/unload and controlled failed-initialization cleanup passed. Android stayed in the same boot. Phase 2 remains in progress: this diagnostic supplies Android allocation and log evidence, while the standalone A51 loader, physical handoff, payload fault logs and demonstrated return still need implementation.

## What ran and what it proves

`diagnostics/page-probe/hakios_page_probe.c` requests exactly one order-zero page using `GFP_KERNEL | __GFP_ZERO | __GFP_NOWARN | __GFP_NORETRY`. It validates a required 16-character hexadecimal run ID, reports the page's physical address, checks all 4,096 initial zero bytes, writes/checks an `0xa5` pattern, and holds that page until ordinary module unload. Every post-allocation initialization error releases the page. A second run with `fail_after_alloc=1` releases its page and deliberately returns `-ECANCELED`; it does not cause a CPU fault or panic. No thread, timer, device, ioctl, MMIO access or execution from allocated memory is involved.

| Device evidence | Observed result |
|---|---|
| Normal run `6ae70c7469287f4e` | Acquired `[0x93894b000, 0x93894c000)`, zero/pattern checks passed, module listed Live with reference count 0, ordinary unload returned 0 and released the same page |
| Failed-init run `061dd84761e2da52` | Acquired `[0x89e06000, 0x89e07000)`, checks passed, released it with `requested_init_failure`, then insmod returned 1 / Operation Canceled |
| Identity and acceptance | Root domain `u:r:su:s0`; SELinux Enforcing; current boot hash and decompressed configuration matched the installed build before transfer |
| End state | Same boot ID and kernel release, no page-probe module record, temporary module file absent |
| Kernel taint | 0 before, 4096 after: the expected out-of-tree module flag remains after unload. No reboot was requested to clear it. |

These two intervals were owned only between their acquire/release events. Both are now released and must never be selected as future payload destinations from this record. A one-page success establishes no large contiguous allocation, DMA isolation, executable mapping, device shutdown or standalone entry state. Same-boot Android responsiveness is not a return after leaving Android. The controlled init error is cleanup evidence, not CPU fault or persistent reset-log evidence.

## Matching build inputs and isolation

The retained installed configuration exactly matches `/opt/a51-everline/out/.config`: SHA-256 `9862a2b3ca684c08a0423681e77bf8503c2b7c2e18bd182ca3c1370681f8adb1`. The saved Image hash is `f9ccca797b1114600f935f7398fa14425c09a21c639951f7d94a376bd57bf57d`; the installed boot hash is `eb30609a62999e3282ac81e0a5e56411ef12ec1a39c107171bf3e01209c7cb67`. Current phone reads matched the boot/configuration association. The exact compiler/linker are Ubuntu clang 18.1.3 (1ubuntu1) and LLD 18.1.3. Source commit `468ab8343364e4d3a267e670fa6a22fd4197a805` is recorded lineage, not a verified Git HEAD.

`scripts/build-page-probe.py` copies the existing source, generated generic/ARM64 headers and build tools into `/opt/a51-hakios/diagnostics/page-probe/<timestamp>`, detaches copied KernelSU Git metadata pointers and rejects symlinks resolving outside the isolated tree. It never invokes make in the existing Android output. Copied ABI inputs are checked before/after make, and original source/output metadata plus ten critical content hashes are checked unchanged. The original 9,666-row Module.symvers has SHA-256 `fdaef95baeed06a37e9e2b1fa9da8ff8d5ec322f33cba46ebd723b0faf22c2d4`.

The ELF is an AArch64 relocatable module with exact vermagic `4.14.357-Everline-KSUN-A51 SMP preempt mod_unload modversions aarch64`. All nine imported CRCs match the original pinned symbol table: module_layout, param_ops_bool, param_ops_charp, __free_pages, memset, printk, memstart_addr, __alloc_pages_nodemask and strlen. Undefined-symbol inspection finds no unversioned import. Kernel acceptance was then observed through ordinary insmod. No forced loading/unloading or SELinux change was used.

## Selected evidence and verification

Host packet: `evidence/phase-2/page-probe-build/20261111T124258280383Z/result.json`. Device packet: `evidence/phase-2/page-probe-device/20261111T124942840876Z/result.json`. The built/transferred/retained module is 157,784 bytes, SHA-256 `9ea0e37ed7fd44aa9b711030241a5fa21f3befa078cbd77bb518dcb8b3c08f73`.

The successful host build is `20261111T124252597230Z-phase2-page-probe-isolated-build-headers-corrected`. Device execution is `20261111T124942248455Z-phase2-page-probe-device-normal-and-failed-init`; all 20 rooted commands succeeded, plus one successful ADB transfer. The intentional init failure is retained inside the successful transaction, with its nonzero insmod status checked explicitly. Seven nonce-associated lifecycle messages were retrieved. Windows replay `20261111T125232911703Z-phase2-page-probe-device-evidence-replay-windows` and WSL replay `20261111T125233140396Z-phase2-page-probe-device-evidence-replay-wsl` passed without phone access; WSL's known virtualization warning was retained.

The capture script revision is frozen both inside the device packet and the run's project-scripts directory. After capture, replay gained explicit copied-host-result/module binding checks and fallback cleanup gained explicit absence checks. Both host replays used that stronger verifier. Those fallback paths were reviewed but were not exercised on the phone; both normal cleanup paths were exercised. The new handoff checker verifies selected packet pins, exact command roles, both revisions and preservation of historical evidence.

From the Windows project root, repeat only the needed action:

```powershell
# Offline readback; no phone access.
python scripts/run.py --label page-probe-readback -- python scripts/test-page-probe-device.py --verify evidence/phase-2/page-probe-device/20261111T124942840876Z
python scripts/run.py --label page-probe-handoff -- python scripts/check-page-probe-handoff.py
# A new isolated host build; leaves existing Android projects untouched.
python scripts/run.py --label page-probe-build -- wsl -d A51-KernelBuilder -u root -- python3 /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/build-page-probe.py
# An authorized new device diagnostic; writes/loads then cleans its unique temporary .ko.
python scripts/run.py --label page-probe-device -- python scripts/test-page-probe-device.py --build evidence/phase-2/page-probe-build/20261111T124258280383Z --serial A51_SERIAL_HERE
```

Keep the exact current-build checks before every later device run. `--verify` never loads a retained module. Logs retain true remote status, transport status, command bytes and timing. The shell exit trap removes the temporary file and unloads a probe if needed; fallback cleanup uses ordinary rmmod and verifies absence. A transport failure cannot itself prove remote cleanup, so any failed run requires inspecting its retained cleanup/absence evidence before continuing.

## Failed attempts, recovery and next work

The first isolated build `20261111T123933989703Z-phase2-page-probe-isolated-build` failed because ARM64 generated headers were omitted from the copied header set (`asm/errno.h` absent). Adding that existing header directory fixed the build; no upstream code was patched. Original metadata before the failed and corrected attempts is unchanged. The first wrapper syntax command `20261111T124818783340Z-phase2-page-probe-device-wrapper-compile` used a project-prefixed path despite run.py already selecting the project cwd; corrected relative paths passed in `20261111T124829418899Z-phase2-page-probe-device-wrapper-compile-path-corrected`. Both failed attempts remain retained.

No device restoration is needed: the module and temporary file are absent, the owned pages were released and Android kept running. For an interrupted future run, inspect `/proc/modules` and the packet's exact temporary path, unload only the owned `hakios_page_probe` instance with ordinary `rmmod`, then remove only its unique file. Do not force unload or change the boot image to recover this test. Documentation/state rollback copies and their original paths are indexed in `evidence/phase-2/page-probe-docs/20261111T1255Z/before/index.json`; revert the new diagnostics/scripts/guide/checker while preserving evidence and run history. Isolated WSL build directories may remain for reproduction.

Next: define the payload memory budget and an allocator that retains ownership for the whole proposed run, then connect lifetime-bound evidence to the layout validator. Larger/contiguous allocation, low-memory placement, CPU/DMA/cache/MMU/interrupt transitions, loader entry, persistent fault logs and demonstrated Android/recovery return remain unverified. Kexec remains disabled. Phase 1 stays complete; Phase 2's device gate stays false; Phases 3–10 remain planned.

P2-014 documentation completion: `20261111T125844179465Z-phase2-page-probe-final-handoff-utf8-corrected` passed exit 0, verifying both selected packets, the build/device/replay command roles, 11 original rollback copies, 212 links across 26 documents and all 264 Phase 1 bundle files. The completed record and its original counts are selected in state.json; the Android diagnostic and documentation milestone is verified. Phase 2 remains in progress and its standalone device gate remains false. No additional phone test, reboot or build was performed for this bookkeeping.

P2-015 supersedes the next-memory-work statement above: [64 KB arena diagnostic](ARENA-PROBE.md) now verifies a non-final 64 KB allowance and ownership until unload. Both tested arenas are released; active loader-placement certification and standalone launch remain pending.
