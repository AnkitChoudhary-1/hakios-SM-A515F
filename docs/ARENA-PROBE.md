> Publication note: this is a historical workspace document. Current completion decisions are in [PUBLIC-STATUS.md](PUBLIC-STATUS.md); raw local evidence is described in [PUBLICATION.md](PUBLICATION.md).

# A51 Android 64 KB arena diagnostic — P2-015

The A51 successfully held, checked, cleared and released one contiguous 65,536-byte Android allocation. Normal load/unload and controlled canceled-init cleanup both passed. This establishes an Android allocator lifetime and retrievable diagnostic logs. It does not establish standalone HakiOS entry, XNU execution or return after leaving Android.

## Implemented and verified scope

- `diagnostics/arena-probe/hakios_arena_probe.c`: one order-4 allocation, partition/alignment/zero checks, six complete region patterns, ownership until ordinary unload, final integrity check, zeroing and release. `fail_after_alloc=1` clears/releases then returns `-ECANCELED`.
- `scripts/arena_probe.py`: fixed budget, pinned reference measurements, generated-header validation and offline closed-lifetime reconstruction. Released evidence always has `active_owned_interval=false` and `safe_for_loader_placement=false`.
- `scripts/build-arena-probe.py`: timestamped isolated kernel/header/module build, exact vermagic/import CRC checks, retained source/ABI/tool provenance and unchanged original metadata/content checks.
- `scripts/test-arena-probe-device.py`: explicitly selected phone, current installed-kernel/config/boot checks, one unique temporary module file, normal hold/unload, canceled init, bounded logs and post-test absence/boot checks. `--verify` reconstructs saved evidence without phone access.
- `scripts/test-arena-probe.py` and `scripts/test-arena-probe-evidence.py`: budget/lifetime guards and retained corrupted-packet rejections. `scripts/check-arena-probe-handoff.py` checks selection, command roles, compiled source/ABI, historical preservation and documentation.

The module allocates with `GFP_NOWAIT | __GFP_ZERO | __GFP_NOWARN | __GFP_NOMEMALLOC`. This allocation requests neither direct reclaim nor emergency reserves; GFP_NOWAIT may wake kswapd. Module-loader allocations have separate behavior. The module has no worker/thread/timer, DMA/MMIO, CPU-state transition or arena execution. Byte checks use READ_ONCE. Module code executes as an ordinary Android kernel module; arena data contains patterns only.

## Fixed diagnostic allowance

| Role | Offset | Bytes | Pattern |
|---|---:|---:|---:|
| Input | 0 | 4,096 | 0x11 |
| Image allowance | 4,096 | 16,384 | 0x22 |
| BSS allowance | 20,480 | 8,192 | 0x33 |
| Stack allowance | 28,672 | 16,384 | 0x44 |
| Logs allowance | 45,056 | 4,096 | 0x55 |
| Spare | 49,152 | 16,384 | 0x66 |

The total is 65,536 bytes, 16 pages of 4,096 bytes, order four. The entire generated partition is validated before allocation/writes. Manifest `manifests/arena-probe-budget.json` is 1,691 bytes, SHA-256 `30fb6aab6df7e405591b53105f0b1a22f5011c7b8636926ced2c8c06952e4e13`.

This is a non-final diagnostic allowance. The retained QEMU sizing reference `evidence/phase-2/loader-probe/20261111T105317947466Z/` has a 7,248-byte probe.bin, 4,100-byte ELF BSS and 16,384-byte linker stack; its seven log frames are 256 bytes each. Binary SHA-256 `bdb3754a8856c412661a31dae53d46bce59cc0d12407f7a807c1bb346cc1958e`; ELF `dedf47cfa9dd5438dd53c46b8a7915677239df310f55c7d68471895c4886a187`; result `d34df32b8ec8f95d62453dec4021a6f59577e72ddefb7fc2bdac4b8bb16b8351`. The QEMU adapter is not an A51 executable. No reference binary was copied to the phone or executed by this diagnostic. A final standalone/XNU memory budget remains unknown.

## Selected build and actual phone execution

Host: `evidence/phase-2/arena-probe-build/20261111T132918243669Z/result.json` (29 indexed files / 20,079,977 bytes). Build directory: `/opt/a51-hakios/diagnostics/arena-probe/20261111T132918243669Z`. The builder copied existing `/opt/a51-everline/src` and required generated output inputs into this separate directory. Original metadata before/after and ten content pins are unchanged. Android source commit `468ab8343364e4d3a267e670fa6a22fd4197a805` is recorded lineage; there is no verified Git HEAD. Clang/LLD 18.1.3 versions and build commands are retained in the host packet.

Module `hakios_arena_probe.ko`: 161,448 bytes, SHA-256 `713462b3bb484ca1b40c2fbf72ac060941df3fd0c9f546762425a35aeb1542b5`. Exact vermagic: `4.14.357-Everline-KSUN-A51 SMP preempt mod_unload modversions aarch64`. All nine imported CRCs match the original Module.symvers:

| Import | CRC |
|---|---|
| module_layout | 0x90ff6c0e |
| param_ops_bool | 0xe617b1eb |
| param_ops_charp | 0xebf248ac |
| __free_pages | 0xa2c47224 |
| memset | 0xdcb764ad |
| printk | 0x985558a1 |
| memstart_addr | 0xfadf2436 |
| __alloc_pages_nodemask | 0xe3bf81a1 |
| strlen | 0x98cf60b3 |

Device: `evidence/phase-2/arena-probe-device/20261111T133447277112Z/result.json` (75 indexed files / 303,799 bytes), Samsung SM-A515F serial `A51_SERIAL_HERE`. Tests ran 19:04:47–19:04:56 IST on 11 November 2026. All 23 rooted queries and one ADB transfer succeeded. Root domain was `u:r:su:s0`; SELinux was Enforcing. Current config SHA-256 `9862a2b3ca684c08a0423681e77bf8503c2b7c2e18bd182ca3c1370681f8adb1` and installed boot SHA-256 `eb30609a62999e3282ac81e0a5e56411ef12ec1a39c107171bf3e01209c7cb67` matched the build association before transfer.

Normal run `262ed7b1bc4275dd`: acquire → selfcheck → loaded → release. Two module Live observations bracketed a one-second sleep; unload rechecked all patterns, cleared the arena and freed it. Failed-init run `0f6ae7b969d461be`: acquire → selfcheck → release, followed by the expected `Operation Canceled`/insmod exit 1. The allocation address was sequentially reused; both historical intervals `[0x81980000, 0x81990000)` are now **released**. They are never a current executable destination or reusable authorization.

Seven lifecycle logs were retrieved. Android boot ID and kernel release stayed unchanged; `/proc/modules` and the exact unique `/data/local/tmp/hakios-arena-probe-262ed7b1bc4275dd.ko` absence check confirm cleanup. Taint stayed 4096 from the earlier out-of-tree diagnostic; unloading does not clear that flag. MemFree/available observations vary while Android runs and do not prove leak freedom or ownership. Actual release evidence comes from the diagnostic lifecycle plus successful unload/absence checks.

## Reproduction and offline verification

Run from `C:\Users\Ankit\Desktop\A51\hakios-a51`:

```powershell
# Offline; does not contact the phone or load a module.
python scripts/run.py --label arena-readback -- python scripts/test-arena-probe-device.py --verify evidence/phase-2/arena-probe-device/20261111T133447277112Z
python scripts/run.py --label arena-budget-guards -- python scripts/test-arena-probe.py
python scripts/run.py --label arena-packet-guards -- python scripts/test-arena-probe-evidence.py --packet evidence/phase-2/arena-probe-device/20261111T133447277112Z
python scripts/run.py --label arena-handoff -- python scripts/check-arena-probe-handoff.py
# Fresh isolated build; preserve previous directories.
python scripts/run.py --label arena-build -- wsl -d A51-KernelBuilder -u root -- python3 /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/build-arena-probe.py
# Authorized new Android diagnostic; retains exact current-build checks.
python scripts/run.py --label arena-device -- python scripts/test-arena-probe-device.py --build evidence/phase-2/arena-probe-build/20261111T132918243669Z --serial A51_SERIAL_HERE
```

Windows/WSL final offline replay passed; ten budget mutations and nine lifetime rejections passed on each host. The packet guard retains 24 expected rejections on Windows, including altered/reframed commands, transfer destinations, serials, status/types, released ownership, lifecycle order/clear/address/integrity, transaction-marker suffixes, timestamps, module/budget pins and oversized configuration expansion. The verifier limits JSON/file/config bytes, verifies exact roles, remote footer status, globally ordered lifetime logs and equivalent chronological UTC/IST command timing. External state/result/index pins anchor packet integrity; this is not cryptographic attestation of a compiler or kernel.

The capture wrapper/helper are frozen in the packet and original timed-run snapshot. Subsequent replay refinements are independently pinned in final replay runs/state. First WSL replay `20261111T133530906584Z-phase2-arena-device-evidence-replay-wsl` failed on interpreting Windows ADB paths; normalization corrected only replay, preserving the original result. WSL virtualization warnings were retained. One initial preparation apply_patch failed validation without writing files; corrected preparation succeeded. Failed and intermediate outputs remain preserved.

## Recovery, rollback and next gate

The successful test needs no phone restoration. Future exceptions have an exit trap and ordinary fallback unload/file removal; fallback exception paths were reviewed but not exercised on this phone. A transport failure alone cannot prove cleanup. Inspect retained boot/module/path evidence before continuing; unload only the owned `hakios_arena_probe` with ordinary rmmod and remove only that run's exact unique temporary path, then verify absence. Do not force unload/load, expand the allocation on failure or reuse released physical addresses.

Ten pre-change documentation/state/roadmap copies, exact original paths and hashes: `evidence/phase-2/arena-probe-docs/20261111-p2-015/before/index.json`. The retained sync.py/changes.json and completion-before copies document bookkeeping. Restore only those indexed copies and revert new files as needed while preserving all evidence/runs and the 264-file Phase 1 bundle. Keep isolated WSL outputs for reproduction. `prepare-arena-probe.py` and checkpoint/sync/completion mutations are one-time programs; do not rerun them. Existing Android projects, backups and upstream remain separate.

The active lifetime-bound ownership certificate, loader-plan/layout-v1 binding, actual A51 entry adapter, CPU/MMU/cache/DMA/interrupt transitions, fault/persistent payload logs and demonstrated return after standalone execution are **unimplemented or unverified**. Linux kexec remains disabled. Phase 1 is complete, Phase 2 in progress, its standalone device gate false, and Phases 3–10 planned. Android diagnostic cleanup does not complete the Phase 2 execution/log/return gate.


## Executed lifetime-bound plan diagnostic (P2-016)

The [allocation/plan diagnostic](OWNERSHIP-PROBE.md) passed on the A51: three fixed 64 KB plan bindings, seven rejected wrong/stale/released requests, ten state observations and 21 ordered kernel messages. All 23 rooted commands and the transfer succeeded. All three sequential allocations were cleared and released; Android kept the same boot and the module/file are absent. SELinux was Enforcing and existing taint stayed 4096. Native ASan/UBSan checks passed 1,408 assertions; all 17 import CRCs and exact vermagic matched. Windows/WSL replay and all 44 corruption guards per host passed.

Selected host result: `evidence/phase-2/ownership-probe-build/20261111T141326924789Z/result.json`. Selected device result: `evidence/phase-2/ownership-probe-device/20261111T141913580938Z/result.json`. The fixed plan is checked inside the allocation owner under one mutex; a receipt is historical once its callback returns. No external allocation certificate, loader-layout acceptance, copied payload or standalone execution is established. Current released addresses cannot authorize future placement. Phase 1 remains complete, Phase 2 in progress, and standalone launch/platform/fault-log/return gates remain false.

Next: define the bounded A51 diagnostic adapter execution/fault contract, then resolve standalone entry, CPU/MMU/cache/DMA/interrupt transitions, recoverable payload/fault logs and demonstrated return. See the new guide for exact commands, source provenance, failed offline checks and rollback.
