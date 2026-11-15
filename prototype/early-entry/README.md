# Host-only pre-Linux diagnostic candidate

Implemented and host verified on 11 November 2026. This candidate has not run
on the A51. It is a small trusted diagnostic in an experimental Android kernel
Image, followed by the original Linux boot path. It is not XNU, a standalone
operating system, an EFI loader or a no-flash launch mechanism. Phase 2's A51
execution/log/return gate remains false.

`hakios_early_entry.S` is the exact assembly tested by the synthetic harness.
`hakios_early_entry.h` defines its 256-byte record. `hakios_early_report.c` reads
the retained record at the start of `setup_arch()`. `prepare.py` writes a local
adaptation only into an isolated source clone under `/opt/a51-hakios` and retains
the exact original files and a complete generated patch. It does not edit a
configuration, compile, package, contact a phone or operate on partitions.

## Entry and execution contract

The pinned `head.S` begins `ENTRY(stext)` with `bl preserve_boot_args`. The
adaptation inserts `b hakios_early_entry` before that call and exports
`hakios_early_entry_continue` immediately before the original instruction.
The payload ends by branching to this continuation. Direct branches preserve
incoming x30; no Linux routine is called inside the diagnostic. Linux's own
boot-argument preservation and EL/MMU setup continue afterward.

The diagnostic uses x4–x12 and x17 as scratch. It preserves x0–x3 exactly,
x18–x30, SP and NZCV. x13–x16 are also untouched by this source. It does not
require a valid incoming stack. The native Linux boot ABI does not promise a
return address or meaningful incoming scratch-register values; complete
conservation of arbitrary incoming registers is outside this contract.

The record contains original x0–x3, raw CurrentEL, physical `stext`, payload and
continuation labels, incoming SP/LR/NZCV, DAIF, CNTFRQ_EL0, MIDR_EL1, the active
SCTLR_EL1 or SCTLR_EL2, raw CTR_EL0 and the derived minimum data-cache line size.
These are observations at the hook. They do not measure secure firmware state,
other CPUs, DMA, device ownership, a full memory map or an exception return PC.

1. Read CurrentEL and select SCTLR_EL1 at EL1 or SCTLR_EL2 at EL2.
2. Skip all record addressing, writes and cache maintenance if EL is unsupported
   or the active SCTLR M/C bit is set. Read CTR and similarly skip if DminLine
   denotes a line larger than 256 bytes.
3. With accepted EL, MMU off and data cache off, record entry state. If all four
   DAIF masks are not set, commit invalid status and skip the arithmetic payload.
4. Otherwise execute fixed XOR/rotate arithmetic over x0–x3, CNTFRQ and MIDR;
   store its value and completion marker. No input bytes, callback or copied
   image are executed.
5. Commit status, issue `dmb sy`, invalidate the record's complete cache lines
   with `dc ivac`, issue `dsb sy`, then branch to the original kernel path.

The initialized record is `.mmuoff.data.write` **PROGBITS**, not BSS. The pinned
linker keeps this supported section in a separate 2 KB Cache Writeback Granule
area, before `_edata` and the BSS which `__primary_switched` clears. Alignment is
256 bytes. Accepted CTR DminLine values 0–6 give line sizes 4–256 bytes and exactly
`64 >> DminLine` operations, bounded to 1–64. Every invalidated line lies wholly
inside the record. This avoids the partial-line clean/invalidate branch used by
Linux's more general `__inval_dcache_area`; the barrier and full-line invalidation
semantics come directly from `preserve_boot_args` and that helper. I-cache state
is neither changed nor assumed off.

This contract relies on the firmware's native Image protocol, including the
image range being cleaned to PoC and CPU/system-cache coherency. An MMU-off
SCTLR observation alone cannot prove those obligations. The diagnostic does not
reconfigure MMUs, caches, ELs, interrupts, timers, devices or system registers.
Its `DC` instruction is limited cache maintenance, not a cache enable/disable.

For a freshly loaded Image, unsupported entries leave initialized status zero. Later output therefore says
`unobserved-or-skipped`; it cannot identify which guard rejected the entry.
Writing a failure record under an unknown translation/cache contract would
defeat the guard. A supported EL with unmasked DAIF records invalid status two;
the original kernel still continues. Unexpected entry does not establish that
Linux can safely boot. EL0 system-register access, higher-EL traps, memory faults
or asynchronous faults can still prevent execution: this diagnostic has no
exception vectors, watchdog or independent reset/fault logger.

The record has no boot epoch or authentication. If a caller reuses the image's
memory without reloading its initialized data, an unsafe skipped re-entry could
leave a prior executed record. A later reporter alone cannot distinguish that
case. Any device evidence must associate logs with the exact candidate Image,
a fresh boot and its demonstrated load/entry route. A valid safe re-entry runs
the payload again and overwrites the capture; this is not a first-entry-only
or persistent cross-boot record.

## Record format

All fields are 64-bit little-endian in the tested/native AArch64 build.

| Byte offset | Field |
|---:|---|
| 0, 8, 16 | Magic `0x31454c5241494b48`, version 1, size 256 |
| 24, 32 | Status and reason |
| 40–64 | Original x0, x1, x2, x3 |
| 72 | Raw CurrentEL (`4` = EL1, `8` = EL2) |
| 80, 88, 96 | Physical stext entry, payload and continuation labels |
| 104, 112 | Incoming SP and DAIF |
| 120, 128 | CNTFRQ_EL0 and MIDR_EL1 |
| 136, 144, 152 | Active SCTLR, CTR_EL0, line bytes |
| 160, 168 | Arithmetic result and marker `0x3143455845494b48` |
| 176, 184 | Incoming x30 and NZCV |
| 192–255 | Eight zero reserved words |

Status 0 means no retained accepted capture; status 1/reason 0 means arithmetic
payload completed; status 2/reason 1 means DAIF violated the boot contract and
the arithmetic payload was skipped. `setup_arch()` checks the header and
recomputes the payload value before reporting a consistent executed result.

Example future kernel lines:

```text
HAKIOS_EARLY_V1 status=1 reason=0 setup_arch=reached standalone_os=0
HAKIOS_EARLY_V1 x0=... x1=... x2=... x3=...
HAKIOS_EARLY_V1 el=... entry_pc=... payload_pc=... continue_pc=... sp=...
HAKIOS_EARLY_V1 daif=... cntfrq=... midr=... sctlr=... ctr=... line=...
HAKIOS_EARLY_V1 payload=executed record=consistent value=... continuation=setup_arch_reached
```

The reporter running is evidence of Linux reaching `setup_arch`, not Android
userspace success. Retrieving matching lines from an actual experimental boot
would establish this tiny pre-Linux payload and Linux continuation only. Kernel
log retention through that boot, persistent fault evidence, a demonstrated
Android/recovery procedure and standalone HakiOS execution remain unverified.

## Exact source preparation

Inspected Android lineage is
`468ab8343364e4d3a267e670fa6a22fd4197a805`; the original source has no Git HEAD.
`prepare.py` rejects changed bytes before writing:

| Original file | SHA-256 |
|---|---|
| `arch/arm64/kernel/head.S` | `fcf3c3937a06b1bb5a31a9b92d852f340dad3ea505ca50b4f1e9dfcef8292cf1` |
| `arch/arm64/kernel/setup.c` | `eafab4dca1a22c24bd1c26fb0976eed77d639e96ceff6c6692f205911ce68b7b` |
| `arch/arm64/kernel/Makefile` | `a628d655b96f4cff1432a39bf0d79cf2ff8d0d6d1545700f37064f5dcdbb834d` |

Before changing a different clone, read its applicable `AGENTS.md` files.
The read-only original-source audit found no such files in that checkout.
The script validates resolved target paths and regular files, requires a fresh
evidence directory outside the source, refuses already installed candidate
files, retains original bytes, and checks the source-root configuration unchanged
if one exists. An out-of-tree configuration is the build orchestrator's separate
pinning obligation.

After a separate orchestrator creates a fresh complete source clone, run from
Windows with the real unique stamp substituted:

```powershell
python hakios-a51/scripts/run.py --label phase2-early-entry-prepare -- wsl -d A51-KernelBuilder -- python3 /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/prototype/early-entry/prepare.py --source /opt/a51-hakios/experimental/early-entry/STAMP/src --evidence /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/evidence/phase-2/early-entry-prepare/STAMP
```

It installs three candidate files under `arch/arm64/kernel` and changes only
the pinned head/setup/Makefile integration points. The generated
`early-entry.patch` includes all six changes, and `result.json` records before/
after hashes, provenance and false device/gate flags. Keep the original
`/opt/a51-everline/{src,out}` untouched. A kernel compile and Samsung boot-image
assembly require separate build/format validation; this script does neither.

## Host verification and recovery

```powershell
python hakios-a51/scripts/run.py --label phase2-early-entry-host-harness -- wsl -d A51-KernelBuilder -- python3 /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/prototype/early-entry/host_test.py
```

The accepted run is
`runs/20261111T162527080829Z-phase2-early-entry-host-harness`, exit 0; its selected
result is `evidence/phase-2/early-entry-host/20261111T162536291908Z/result.json`.
Five QEMU `virt`/Cortex-A53 cases passed 228 C integration checks, with independent
Python decoding of raw register and record packets:

| Synthetic case | Checks | Verified result |
|---|---:|---|
| EL1 with M/C off and masked DAIF | 43 | Payload completed, preserved entry registers |
| EL2 with M/C off and masked DAIF | 43 | Active SCTLR_EL2 capture and payload completion |
| EL1 with IRQ unmasked | 42 | Invalid DAIF capture, no payload marker/value |
| EL1 with data cache enabled | 50 | All 256 initialized record bytes unchanged |
| EL1 with MMU enabled and fixture identity map | 50 | All 256 initialized record bytes unchanged |

Every case verifies exact x0–x3 and x18–x30, SP=0 and chosen NZCV. Nonzero x1–x3
show that capture does not replace unexpected firmware arguments with zeros.
Valid cases check physical labels against linked symbols, the arithmetic result,
EL/cache state and reserved bytes. Object disassembly retains the 316-byte
payload and confirms no MSR, BL, MMIO, stack access or flags-changing instruction;
section output proves the 256-byte initialized PROGBITS record/alignment.
QEMU PSCI shutdown exited zero at both EL1 and EL2. QEMU addresses, page tables,
UART and setup/teardown MSR instructions exist only in the synthetic fixture.

The first harness build/run passed; no failed payload harness attempt was
discarded. WSL emitted a nested-virtualization detection warning; QEMU runs still
passed. Each build/link/run command has exact arguments, timestamps, a bounded
timeout, output and exit status in the result/logs. Compiler/linker/tool version
outputs, source snapshots and linked ELFs are retained. The harness does not
model Exynos caches, Samsung firmware, KASLR relocation, traps, DMA or recovery.
Oversized CTR lines and unsupported ELs have source/disassembly guard evidence,
not executed synthetic coverage.

To recover from a host failure, preserve its result/logs and create a new unique
build/evidence directory; correct the candidate and rerun through `run.py`.
`prepare.py` is intentionally not idempotent on an already patched clone.
Rollback in that isolated clone restores the three exact `original/` copies and
removes only its three added candidate files. Rebuilding a fresh clone is the
preferred rollback. Retain all evidence and Phase 1 files. No phone restoration
is required for these host-only commands; none installs, flashes or reboots.
