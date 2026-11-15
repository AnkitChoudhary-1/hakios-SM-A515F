> Publication note: this is a historical workspace document. Current completion decisions are in [PUBLIC-STATUS.md](PUBLIC-STATUS.md); raw local evidence is described in [PUBLICATION.md](PUBLICATION.md).

# Android Linux callback CPU-state diagnostic (P2-017)

Date: 11 November 2026. Status: implemented and verified as a temporary Android
kernel-module diagnostic. The selected module loaded on the authorized Galaxy
A51, captured one record on each of the eight online CPUs from Linux
`on_each_cpu()` callbacks, unloaded, and removed its temporary file. This is
Linux runtime state. It is not the original Samsung firmware entry state,
pre-Linux execution, CPU shutdown, a physical handoff, or standalone HakiOS
execution. Phase 2 remains in progress and its device gate remains false.

## Result and claim boundary

| Classification | Result |
|---|---|
| Implemented | Capture-only AArch64 module, isolated ABI-matched build, bounded device transaction, strict packet replay and corruption guards |
| Verified on the A51 | Module transfer/load/live/unload, eight per-CPU callbacks, matching boot/kernel/configuration, log retrieval and temporary-file cleanup |
| Observed | All eight callbacks ran at EL1 with the MMU, data cache and instruction cache enabled; counter frequency was 26 MHz |
| Not verified | Samsung's original entry EL/registers, MMU-off state, other boot stages, CPU quiescing, DMA/cache/interrupt transition, executable payload ownership, standalone payload execution, persistent fault logging or Android/recovery return |

The diagnostic answers a deliberately narrow question: what architectural state
is visible while the installed Android kernel executes a synchronous callback on
each currently online CPU? It must not be used as evidence for the state in which
firmware enters a Linux Image or any future HakiOS payload.

## Implementation

The retained source is `diagnostics/cpu-state/hakios_cpu_state.c`. It requires a
16-character lowercase hexadecimal `run_id`, holds the online-CPU set stable,
and invokes `on_each_cpu(capture_cpu, NULL, 1)`. The callback records only into a
fixed 32-entry kernel array. It makes no Linux call, emits no log line and
contains no architectural-register write. Logging occurs after every callback
has returned.

Each CPU record contains:

- raw `CurrentEL`, `MIDR_EL1`, `MPIDR_EL1`, `ID_AA64MMFR0_EL1` and
  `ID_AA64MMFR1_EL1`;
- `SCTLR_EL1`, `TCR_EL1`, `TTBR0_EL1`, `TTBR1_EL1`, `MAIR_EL1` and
  `VBAR_EL1`;
- callback PC, SP and `DAIF`;
- `CNTFRQ_EL0`, `CNTVCT_EL0` and a one-sample counter proving that the callback
  ran exactly once on that CPU.

The module accepts at most 32 online CPU identifiers. It rejects an invalid run
identifier, an out-of-range CPU identifier or any missing/duplicate callback.
On unload it clears the in-memory capture array and emits a run-associated
cleanup receipt. The source does not call a payload, reserve memory for one,
change translations, disable a CPU, write a system register or touch a boot
partition.

## Observed A51 state

The selected capture found CPUs `0-7` online and produced the following common
state inside the Linux callbacks:

| Field | Raw value | Interpretation |
|---|---:|---|
| `CurrentEL` | `0x4` | Encodes EL1 |
| `SCTLR_EL1` | `0x34d5d91d` | M=1, C=1 and I=1: MMU, data cache and instruction cache active |
| `CNTFRQ_EL0` | `26000000` | 26 MHz architectural counter frequency |
| `DAIF` | `0x1c0` | Retained raw callback observation; not an asserted firmware-entry contract |
| Online set | `0-7` | Eight callbacks and eight reconstructed records |

The CPU identity split was:

| CPUs | MIDR | Part | Interpreted core class |
|---|---:|---:|---|
| `0-3` | `0x410fd034` | `0xd03` | Arm Cortex-A53 |
| `4-7` | `0x410fd092` | `0xd09` | Arm Cortex-A73 |

The packet also retains translation bases, attributes, vector base, PC, SP,
feature registers and counter samples. These addresses and values describe one
running Android kernel boot. They do not authorize payload placement and are not
a reusable cross-boot memory contract.

## Build and ABI association

The module was built in a timestamped copy below
`/opt/a51-hakios/diagnostics/cpu-state`; `/opt/a51-everline` remained the pinned
input. The builder copied the required generated headers and metadata, detached
copied KernelSU Git metadata, rejected escaping symlinks, and checked the source
and output inventories before and after the build.

The selected module is 156,840 bytes with SHA-256
`617c830f970e21be9fa0a96b3a1e1fd67853a2f2c31dc292897aa3abbcc43280`.
Its exact vermagic is:

```text
4.14.357-Everline-KSUN-A51 SMP preempt mod_unload modversions aarch64
```

All 12 imported symbol CRCs matched the retained `Module.symvers`:
`module_layout`, `param_ops_charp`, `cpu_number`, `memset`,
`cpus_read_unlock`, `printk`, `on_each_cpu`, `cpumask_next`, `nr_cpu_ids`,
`__cpu_online_mask`, `cpus_read_lock` and `strlen`. The retained installed
configuration and Image association matched the earlier connected-device and
live-boot evidence. The Android lineage
`468ab8343364e4d3a267e670fa6a22fd4197a805` remains recorded provenance, not a
verified Git HEAD.

## Device transaction and cleanup

The capture used serial `A51_SERIAL_HERE`, 23 bounded root queries and one temporary
ADB push to `/data/local/tmp/hakios-cpu-state-f5e57eff98a070ef.ko`. Before the
load it verified root, SELinux state, boot ID, release, installed configuration,
boot hash, online CPUs, module availability, module absence and taint. The
transaction then checked the transferred hash, loaded the exact module with the
run token, observed it live, unloaded it, removed the file and checked both were
absent. Run-associated kernel lines were retrieved afterward.

The before/after boot ID, kernel release, SELinux context, SELinux mode, online
set and taint were unchanged. SELinux was Enforcing and taint was 4096 before
and after. The evidence verifies the normal cleanup path. The capture script also
contains a bounded fallback cleanup path for a failed transaction, but this
selected run did not need it.

This milestone did perform a temporary phone write and module load. It did not
flash, reboot, alter boot/recovery/DTBO, repartition, install a loader or leave a
module/file behind.

## Selected evidence

| Role | Selected record | Integrity |
|---|---|---|
| Host build | `evidence/phase-2/cpu-state-build/20261111T155623575651Z/result.json` | SHA-256 `26544601e859e4bc4aa76f0305e27f8cfe40520c5c0c2e2c5ac1305f114e6cd6` |
| Host index | `evidence/phase-2/cpu-state-build/20261111T155623575651Z/index.json` | SHA-256 `c56f5b64e2b9a91c6f9a45f401d9fd1a0d2b58d7a2abdb063acdd362c4c00974`; 27 indexed files / 20,060,266 bytes |
| Device capture | `evidence/phase-2/cpu-state-device/20261111T155948363876Z/result.json` | SHA-256 `6b6bcae092f51def03aa8b252e529eac644d59fb686798fec14c19fbc0078099` |
| Device index | `evidence/phase-2/cpu-state-device/20261111T155948363876Z/index.json` | SHA-256 `d8e663eba2d438c8b9eb732df090271e8aa4a00821205784446bb1e74abe77bc`; 75 indexed files / 330,058 bytes |
| Corruption result | `evidence/phase-2/cpu-state-corruption/20261111T161424507448Z/result.json` | SHA-256 `5f913a045013a0b3c3a59060a92f32f74ef204f8ab297e77f5003723b642d889` |
| Preparation checkpoint | `evidence/phase-2/cpu-state-preparation/20261111-p2-017/checkpoint.json` | Pre-change documentation copies and the exact builder adaptation are retained |

Strict replay reconstructs the fixed command sequence, bounded responses, host
module association, installed configuration/boot association, before/after
invariants, load/live/unload receipt, log field shapes and every CPU record. It
also requires all milestone flags to retain the narrow capture-only meaning.

Eight forged packets were rejected: Phase-gate promotion, an architectural-write
claim, Boolean CPU identifier, changed translation value, arbitrary command,
forged remote failure status, changed module and an extra file. No phone
operation occurs during replay or corruption testing.

## Recorded commands and runs

| Run | Result | Purpose |
|---|---:|---|
| `20261111T154355368729Z-phase2-cpu-state-connection-preflight` | 0 | Confirm the authorized ADB target was present |
| `20261111T154546842260Z-phase2-cpu-state-api-source-review` | 1 | First source search used an over-specific `startswith` match and ended in `StopIteration`; retained as a failed attempt |
| `20261111T155238627193Z-phase2-cpu-state-api-source-review-corrected` | 0 | Corrected exported-symbol and source review |
| `20261111T155400677152Z-phase2-cpu-state-source-preparation` | 0 | Create rollback checkpoint and builder adaptation |
| `20261111T155614723791Z-phase2-cpu-state-isolated-build` | 0 | Build and pin the ABI-matched module |
| `20261111T155902794499Z-phase2-cpu-state-disassembly-review` | 0 | Confirm the callback disassembly contains no `MSR`, `BL` or `BLR` |
| `20261111T155947563149Z-phase2-cpu-state-device-capture` | 0 | Execute the temporary Android diagnostic |
| `20261111T160015505830Z-phase2-cpu-state-translation-decode` | 0 | Decode retained register fields without changing evidence |
| `20261111T161422553413Z-phase2-cpu-state-final-replay-wsl` | 0 | Native WSL replay |
| `20261111T161422753796Z-phase2-cpu-state-final-replay-windows` | 0 | Windows replay |
| `20261111T161423017545Z-phase2-cpu-state-evidence-guards` | 0 | Reject all eight packet corruptions |

Reproduction must create new timestamped evidence and preserve the selected
records. Consequential commands are run through `scripts/run.py`:

```powershell
python scripts/run.py --label phase2-cpu-state-isolated-build -- wsl -d A51-KernelBuilder --exec python3 /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/build-cpu-state.py
python scripts/run.py --label phase2-cpu-state-device-capture -- python scripts/test-cpu-state-device.py --build evidence/phase-2/cpu-state-build/20261111T155623575651Z --serial A51_SERIAL_HERE
python scripts/run.py --label phase2-cpu-state-final-replay-windows -- python scripts/test-cpu-state-device.py --verify evidence/phase-2/cpu-state-device/20261111T155948363876Z
python scripts/run.py --label phase2-cpu-state-final-replay-wsl -- wsl -d A51-KernelBuilder --exec python3 /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/test-cpu-state-device.py --verify /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/evidence/phase-2/cpu-state-device/20261111T155948363876Z
python scripts/run.py --label phase2-cpu-state-evidence-guards -- python scripts/test-cpu-state-evidence.py --packet evidence/phase-2/cpu-state-device/20261111T155948363876Z
```

Only the replay and corruption commands are phone-free. A new capture is an
explicit temporary device mutation and must use the exact authorized serial and
retain cleanup evidence.

## Failure recovery and rollback

If a future capture fails after transfer, preserve the failed packet and run
record. The capture script attempts to unload `hakios_cpu_state`, remove only its
run-specific `/data/local/tmp` file and record the fallback response. Independently
verify that the module directory and exact temporary path are absent before any
retry. Do not overwrite an evidence folder; rebuild or capture into a new stamp.

The original Android source/output inputs were unchanged, so no upstream rollback
is required for the selected run. To remove the project implementation, delete
only the project-owned CPU-state source/scripts after restoring the retained
pre-change documents from the preparation checkpoint. Preserve all run/evidence
history and the Phase 1 bundle.

## Remaining work

P2-017 narrows one unknown: normal Android Linux callbacks execute at EL1 on all
eight online cores with translations and caches enabled. It does not establish
the state at the native Image entry point. The next entry milestone therefore
requires an independently bounded pre-Linux candidate, followed by exception and
watchdog handling, persistent fault/reset evidence, controlled platform
transitions and a demonstrated Android/recovery return before any A51 device
execution can satisfy the Phase 2 gate.
