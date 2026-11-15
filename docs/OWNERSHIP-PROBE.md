> Publication note: this is a historical workspace document. Current completion decisions are in [PUBLIC-STATUS.md](PUBLIC-STATUS.md); raw local evidence is described in [PUBLICATION.md](PUBLICATION.md).

# Android allocation lifetime and fixed plan binding (P2-016)

Date: 11 November 2026. The A51 executed this diagnostic successfully. It checks that a small memory plan belongs to the allocation held by the running Android module. An old request cannot bind after release or module reload. This completes an internal diagnostic binding step; Phase 2 and standalone HakiOS launch remain in progress.

The module holds one 65,536-byte allocation at a time. Three bindings succeeded, seven invalid requests were rejected, and all three sequential allocations were cleared and freed. All 23 rooted commands and one file transfer succeeded. Ten status observations, two module Live observations and 21 ordered kernel messages were retrieved. Android kept the same boot; the module and temporary file are absent. Root context was `u:r:su:s0`, SELinux was Enforcing, and existing out-of-tree taint stayed 4096.

## What the binding means

The kernel owns the allocation and checks its pointer, complete offset partition, active state and full-region patterns while holding one mutex. The request supplies the fixed plan digest, a fresh 128-bit kernel-generated allocation identity and the exact next request number. Successful requests alone advance the number. Explicit release revokes active/bound state before clearing and freeing. Later requests cannot revive that allocation.

The random token is a public identity, not a password or authentication credential. A status or successful receipt is a historical observation once its callback returns. It grants no external memory lease, executable destination or permission to write through a physical address. Every saved result has `active_owned_interval=false`, `safe_for_loader_placement=false` and `phase_2_device_gate_passed=false`. The existing layout version 1 still accepts synthetic host assumptions only; no runtime loader-layout acceptance was added.

The diagnostic binds the exact six-region budget from [arena-probe-budget.json](PUBLICATION.md), SHA-256 `30fb6aab6df7e405591b53105f0b1a22f5011c7b8636926ced2c8c06952e4e13`. Input/image/BSS/stack/log/spare allowances are 4/16/8/16/4/16 KiB. These are fixed diagnostic allowances. Patterns fill them; no payload bytes, QEMU binary or XNU image were copied or executed.

## Interfaces and lifetime

| Interface | Contract |
|---|---|
| `run_id` module parameter | Required 16 lowercase hexadecimal characters for host/log correlation |
| `fail_after_alloc` parameter | Clear/free after initialization checks, then return `-ECANCELED`; no sysfs group published |
| `/sys/module/hakios_ownership_probe/ownership/status` | Root-readable snapshot: run, token, plan, active, bound, last_seq and bytes; released bytes are zero, no address exported |
| `.../ownership/command` | Root-writable bounded request: `bind:TOKEN:PLAN:SEQ` or `release:TOKEN:PLAN:SEQ` |

Commands contain at most 128 bytes, an exact 32-character token and 64-character plan digest, and a sequence from 1 through 65535 without leading zeros. One optional final newline is accepted. Explicit sysfs byte counts reject embedded NULs, trailing bytes, extra whitespace and oversized inputs. A wrong identity/digest/malformed request returns `-EINVAL`; a stale/skipped sequence returns `-ESTALE`; a released instance returns `-ENODEV`. Identity/digest checks precede active-state checks. Rejected requests leave sequence and binding state unchanged.

The sysfs group uses the installed kernel's `struct module_attribute` callback signatures. It is published after initialization without holding the callback mutex, avoiding deadlock if partial creation fails and drains a reader. Unload removes/drains callbacks before taking the mutex and releasing memory. The callbacks are ordinary module code, never discarded init code.

Allocator flags remain `GFP_NOWAIT | __GFP_ZERO | __GFP_NOWARN | __GFP_NOMEMALLOC`, order 4 with 4096-byte pages. This allocation avoids direct reclaim and emergency reserves; NOWAIT can wake kswapd. Ordinary module loading and sysfs infrastructure have their own allocations. The module starts no thread, timer, DMA/MMIO operation or CPU/MMU/cache/interrupt transition.

## Executed tests and evidence

The first instance rejected wrong token, wrong digest, malformed number and skipped number; accepted bind 1; rejected replay 1; accepted bind 2; held across a one-second sleep; accepted release 3; then rejected bind 4. The second instance rejected the first token, accepted its own bind 1 and released on normal unload. The third exercised failed-init cleanup. All three lifetimes reused historical `[0x88ad0000,0x88ae0000)` with different tokens. That address is now released and must never be reused as a future destination.

Native Clang 18 ASan/UBSan tests use the exact C core compiled into the module: 1,408 assertions, 801 parser cases, 115 state cases and 51 layout cases. They cover byte-length/NUL/truncation grammar, token/plan identity, sequence limits and skipped/replayed requests, released states, unchanged validation state and complete partition arithmetic/alignment/overflow. Successful state transitions in the native test are modeled; kernel mutex serialization, sysfs teardown and randomness are not established by those host tests. Actual device commands exercise ordinary callback/load/unload paths, not concurrent stress or fault injection.

The isolated build matched exact vermagic and all 17 imported CRCs. Original Android source/output metadata and ten pinned build inputs stayed unchanged. The accepted upstream and previous diagnostic/prototype sources were preserved. New kernel code lives only in this diagnostic; no upstream adaptation patch was needed.

| Selected record | Purpose |
|---|---|
| `evidence/phase-2/ownership-probe-build/20261111T141326924789Z/result.json` | Isolated build, native guards, ABI and original-file preservation |
| `evidence/phase-2/ownership-probe-device/20261111T141913580938Z/result.json` | Exact device capture, closed lifetimes and diagnostic flags |
| `evidence/phase-2/ownership-probe-bindings/3171cddc46f338d4175cbb8b55ff55ac.json` | External historical capture/source association with recorder snapshots and original host packet |
| `runs/20261111T141321024873Z-phase2-ownership-build/metadata.json` | Exact build command and timed output |
| `runs/20261111T141913031415Z-phase2-ownership-device/metadata.json` | Exact device command, captured script revisions and timed output |

Module SHA-256: `631a54504a13c00fab22d80cd092ec1be78d15a54715b6542a653f83b658ebbb`. Replay verifies packet roles/pins, exact commands/remote framing/exit types, transfer roles, UTC/IST timing, canonical boot UUID, unchanged boot/release, globally ordered transaction observations and kernel messages, monotonic kernel timestamps, binding states and cleanup. The external source association prevents repinning a modified helper or module/host pair inside a copied packet. This is reproducibility evidence, never a live allocation certificate. Current replay revisions can differ from the frozen capture revision; both are retained and selected separately.

## Failure and review history

Static review corrected two issues before the selected build: kobject attributes were changed to the module dispatcher callback types, and sysfs publication moved outside the callback mutex to make failed-creation drainage safe. No phone ran either earlier revision. Builder derivation and generated budget header have retained provenance; completed page/arena/prototype inputs were not edited.

The first offline corruption suite, `runs/20261111T142356179678Z-phase2-ownership-evidence-corruption-guards-windows/metadata.json`, failed: 38 of 44 mutations were rejected, but six repinned-source/module or timestamp/number mutations were accepted. The failed fixtures remain. Replay was tightened with an external recorder/source association, original host/module comparisons, one ordered transaction trace, monotonic kernel timestamps and canonical status numbers/boot identities. The interleaving mutation was corrected to preserve each separate list while moving observations across actions. These changes only affect offline verification; the original phone packet is unchanged. WSL nested-virtualization warnings are preserved.

Cross-boot rejection follows the fresh random identity design and host state tests; no reboot or actual cross-boot phone experiment occurred. The token's collision resistance depends on the kernel random source. No arbitrary runtime plan, standalone entry mechanism, physical handoff, persistent payload/fault logs, fault containment or Android/recovery return after leaving Android is implemented or verified here. Kexec remains disabled.

## Rebuild, replay and recovery

Run from `C:\Users\Ankit\Desktop\A51\hakios-a51`. Use the recorder for consequential commands:

```powershell
python scripts/run.py --label ownership-build -- wsl -d A51-KernelBuilder -u root -- python3 /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/build-ownership-probe.py
python scripts/run.py --label ownership-replay -- python scripts/test-ownership-probe-device.py --verify evidence/phase-2/ownership-probe-device/20261111T141913580938Z
python scripts/run.py --label ownership-corruption -- python scripts/test-ownership-probe-evidence.py --packet evidence/phase-2/ownership-probe-device/20261111T141913580938Z
python scripts/run.py --label ownership-handoff -- python scripts/check-ownership-probe-handoff.py
```

The builder creates a fresh `/opt/a51-hakios/diagnostics/ownership-probe/<UTC>` copy, removes copied Git pointer files and rejects symlinks escaping that copy. It never builds in `/opt/a51-everline`. Do not rerun either one-time preparation script or the one-time pilot registration. A fresh device capture uses `--build <new evidence directory> --serial A51_SERIAL_HERE` through the recorder; preflight checks current root/kernel/config/boot/modules/path before transfer. Its capture/source association is automatically registered from the running recorder snapshots. Allocation failure is a reported failure, never a reason to force loading or expand allocation flags.

The normal script trap and fallback remove the module and its unique temporary file. If a transport failure interrupts a future test, inspect the retained result and query `/proc/modules` and the exact recorded path; ordinary `rmmod hakios_ownership_probe` releases memory, then remove only that file. Never force unload. No firmware restore is needed for this completed capture. Existing taint 4096 remains until a normal reboot; none was requested.

Documentation rollback copies, original paths, UTF-8 synchronization source and after hashes are retained in `evidence/phase-2/ownership-probe-docs/20261111-p2-016/`. Restore those exact originals to roll back documentation/state, and revert the separate new diagnostic/scripts if desired. Preserve frozen evidence/runs and all 264 Phase 1 bundle files. Isolated WSL copies can be retained for reproduction; removal must target only an explicitly verified HakiOS path.

Final offline checks: Windows and WSL both rejected all 44 mutations. Selected replay/guard runs are recorded in state.json and the P2-016 implementation-log entry.


P2-016 documentation/state handoff `runs/20261111T144752379875Z-phase2-ownership-final-handoff-marker-corrected/metadata.json` passed exit 0 and is selected in `state.json`: the 33-file host and 76-file device packets, exact source/module/ABI associations, both replays, 44 corruption rejections per host, three released allocations, 12 original documentation rollback copies, all historical milestone selections and all 264 Phase 1 bundle files verified. The Android allocation/plan diagnostic milestone is complete. Phase 2 remains in progress; standalone entry, CPU/MMU/cache/DMA/interrupt transitions, recoverable payload/fault logs and demonstrated return remain unresolved.
