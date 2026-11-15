> Publication note: this is a historical workspace document. Current completion decisions are in [PUBLIC-STATUS.md](PUBLIC-STATUS.md); raw local evidence is described in [PUBLICATION.md](PUBLICATION.md).

# Historical host-only early-entry diagnostic candidate (P2-018)

This guide describes the original 11 November revision. The adapted 13 November revision executed the minimal payload on the A51 and passed Phase 2; see the [current review](PHASE-2-COMPLETION-REVIEW.md). Original source and build pins below remain historical.

Date: 11 November 2026. Status: implemented and verified in a synthetic QEMU
harness, then linked into an isolated Android kernel `Image` on the host. The
candidate has not been packaged into a Samsung boot image, flashed, booted or
executed on the Galaxy A51. It is not XNU, EFI, a standalone operating system or
a no-flash loader. Phase 2 remains in progress and its A51 device gate remains
false.

## Result and evidence boundary

| Classification | Result |
|---|---|
| Implemented | Fixed AArch64 early-entry diagnostic, 256-byte record, Linux reporter, QEMU harness, pinned isolated-source adaptation and kernel build |
| Executed | Five synthetic QEMU `virt`/Cortex-A53 cases at EL1/EL2, totaling 228 C checks |
| Host-linked | Experimental Linux `Image`, 36,334,080 stored bytes, SHA-256 `87c0401361d4503afb0b266b15ff0caf1e64f505d61d53be700e8b6c6d8e9cf6` |
| Not executed | The experimental `Image` on the A51, Samsung firmware entry, a standalone payload, physical platform handoff or return to Android/recovery |
| Still unavailable | Exception vectors, device watchdog, independent persistent fault/reset log and a demonstrated restoration path |

QEMU execution proves the candidate's synthetic entry/guard/record/continuation
behavior. The kernel build proves that a pinned isolated Android source copy can
link the same candidate. Neither fact predicts how Samsung firmware enters the
Image or whether that Image can safely boot on the phone.

The detailed source-level contract is also retained in
`prototype/early-entry/README.md`. This guide records the Phase 2 milestone,
selected evidence and handoff limits.

## Candidate flow

The isolated adaptation changes the local clone's native arm64 path as follows:

1. `stext` branches to `hakios_early_entry` before Linux
   `preserve_boot_args`.
2. The candidate preserves x0-x3, x18-x30, SP and NZCV. It uses x4-x12 and x17
   as scratch and does not require a valid incoming stack.
3. It accepts only raw `CurrentEL` values 4 or 8 (EL1 or EL2).
4. It reads the active `SCTLR_EL1` or `SCTLR_EL2` and skips all record
   addressing if either the MMU bit M or data-cache bit C is set.
5. It accepts CTR DminLine values 0-6, corresponding to complete 4-256-byte
   cache lines inside the aligned record. Larger/unsupported values skip.
6. Under accepted EL/MMU/cache conditions it records entry registers and state.
   If all DAIF masks are set, a fixed XOR/rotate arithmetic payload executes.
   Otherwise it records invalid-DAIF status without executing the arithmetic.
7. It commits status, performs `dmb sy`, bounded `dc ivac` operations over the
   complete 256-byte record, then `dsb sy`.
8. It branches to `hakios_early_entry_continue`, which resumes the original
   Linux path at `preserve_boot_args`.
9. At the start of `setup_arch()`, `hakios_early_report()` validates and reports
   the retained record.

The arithmetic payload consumes only x0-x3, `CNTFRQ_EL0` and `MIDR_EL1`. It
does not execute copied bytes, call an input-provided callback, touch MMIO or
become a standalone OS. The reporter reaching `setup_arch()` would prove Linux
continuation only; it would not prove Android userspace success or a recovery
procedure.

## Record and source adaptation

`hakios_early_entry.h` defines a 256-byte little-endian record with magic,
version and size; status/reason; original x0-x3; raw EL; entry/payload/continuation
addresses; SP, LR and NZCV; DAIF, counter frequency, MIDR, active SCTLR and CTR;
derived cache-line size; arithmetic value/marker; and eight reserved words.

The record is an initialized, 256-byte-aligned `.mmuoff.data.write` PROGBITS
object, not BSS. Accepted cache-line sizes divide and fit the record, so every
invalidation lies wholly inside it. This relies on the native Image protocol's
coherency and clean-to-PoC obligations; the candidate cannot prove firmware met
them.

The pinned preparation changed six paths in only the timestamped clone:

- modified `arch/arm64/kernel/head.S`, `setup.c` and `Makefile`;
- added `hakios_early_entry.S`, `hakios_early_entry.h` and
  `hakios_early_report.c` beneath `arch/arm64/kernel`.

The exact patch is 8,757 bytes with SHA-256
`bb958f092d82f5b1d5b81761d5198d2a8bf0e80657ecc48a02d27b6e207f409f`.
The original three files are retained by the preparation packet. The source
lineage `468ab8343364e4d3a267e670fa6a22fd4197a805` is recorded but remains not a
verified Git HEAD. The original `/opt/a51-everline` tree and output were not
modified.

## Synthetic QEMU verification

The accepted host run was
`20261111T162527080829Z-phase2-early-entry-host-harness`, exit 0. Five cases
passed 228 checks:

| Case | EL | Checks | Verified behavior |
|---|---:|---:|---|
| Valid entry | 1 | 43 | Record and arithmetic payload completed; original register set preserved |
| Valid entry | 2 | 43 | EL2 path selected `SCTLR_EL2`; record and payload completed |
| Invalid DAIF | 1 | 42 | Failure status/reason committed; no payload value or marker |
| Data cache enabled | 1 | 50 | Candidate skipped; all 256 initialized record bytes unchanged |
| MMU enabled | 1 | 50 | Candidate skipped under the fixture identity map; all record bytes unchanged |

The harness independently decodes raw register/record packets, verifies exact
x0-x3 and x18-x30 preservation, SP and NZCV, linked labels, result arithmetic,
reserved bytes and QEMU PSCI shutdown. Object review retains a 316-byte payload
and finds no `MSR`, `BL`, MMIO, stack access or flags-changing instruction in
the candidate. Harness setup/teardown system-register writes, UART and page
tables are fixture code, not candidate behavior.

QEMU does not model Exynos9611 firmware, Samsung wrappers, KASLR relocation,
system-cache behavior, traps, DMA, fitted devices or recovery.

## Isolated kernel build

The accepted build was
`20261111T163513157751Z-phase2-early-entry-isolated-kernel-build`, exit 0. It
copied source and the prior output into
`/opt/a51-hakios/experimental/early-entry/20261111T163522918342Z`, applied the
exact pinned adaptation and built `Image`. Configuration, original metadata and
pinned original input bytes were reported unchanged.

| Image fact | Value |
|---|---:|
| Stored bytes | `36,334,080` |
| SHA-256 | `87c0401361d4503afb0b266b15ff0caf1e64f505d61d53be700e8b6c6d8e9cf6` |
| Header text offset | `524,288` |
| Declared in-memory image size | `47,362,048` |
| Header flags | `10` |
| Endianness/page size | little-endian / 4 KiB |
| Placement flag | any 2 MiB-aligned base |

The build retained symbol addresses for `_text`, `_end`, `_edata`,
`__bss_start`, `stext`, the candidate entry/payload/continuation/record/reporter
and the mmu-off data bounds. The build-time `vmlinux` is 267,313,848 bytes with
recorded SHA-256
`6fe876776827c44bdf6880ab6f5caca4f21d510b911f884d685482835d5ed8b2`,
but it remains only under the external WSL build directory and is not part of
the retained packet index.

The copied output makes this an incremental isolated build, not a clean rebuild
from empty output. It establishes successful linkage against the pinned inputs;
it does not establish independent full compiler derivation.

## Selected evidence

| Role | Selected record | Integrity |
|---|---|---|
| QEMU harness | `evidence/phase-2/early-entry-host/20261111T162536291908Z/result.json` | 32,856 bytes; SHA-256 `379f5c2a450632052fcb251575277151cbfef382bf1f59b984a157e4c4c23d4c` |
| Source preparation | `evidence/phase-2/early-entry-prepare/20261111T163522918342Z/result.json` | 1,832 bytes; SHA-256 `557c6c90f306fbfc6b7219ffa5f570f4639daad12a107e364d21b3f3b14bd0ab` |
| Adaptation patch | `evidence/phase-2/early-entry-prepare/20261111T163522918342Z/early-entry.patch` | 8,757 bytes; SHA-256 `bb958f092d82f5b1d5b81761d5198d2a8bf0e80657ecc48a02d27b6e207f409f` |
| Kernel build | `evidence/phase-2/early-entry-kernel/20261111T163522918342Z/result.json` | SHA-256 `5bbe01ecdfab1364cc9a0db05753fcc986fbe9a7e053469e899d02d8f44c7049` |
| Kernel index | `evidence/phase-2/early-entry-kernel/20261111T163522918342Z/index.json` | SHA-256 `60fef1b76fff189e256528a900c4b9afa31875c152f57f7ade6dbb7d388fb4f6`; 23 indexed files / 60,298,894 bytes |

The host harness and preparation folders predate the strict indexed-packet
format and have no `index.json`. Their current directories contain 52 files /
482,974 bytes and five files / 49,310 bytes respectively, but those aggregate
counts are not index-bound selections.

## Offline verifier and its bounds

`scripts/early_entry_evidence.py` is a strict phone-free reader for the three
selected packets. It checks exact selected paths and result hashes; strict JSON
types/keys/timestamps; host source snapshots, tool/command relationships, five
cases and 228 checks; the exact source adaptation and patch; the kernel index,
prototype pins, Image header, 12 required symbols, initialized 256-byte record,
entry branches and all false device gates. `scripts/test-early-entry-evidence.py`
copies the packets to an OS temporary directory, verifies the baseline, rejects
nine tested mutation classes and verifies the restored baseline. Those classes
are a changed host check count, duplicate JSON key, non-finite JSON number,
changed preparation patch, forged device gate, Boolean substituted for an
integer symbol, reindexed initialized-record mutation, extra reindexed role and
index traversal. This is focused negative testing, not exhaustive proof. The
verifier never invokes a compiler, QEMU, WSL, ADB or a phone.

Fresh `-B` replay and corruption runs passed on both Windows and native WSL. The
replays reconstructed five cases / 228 checks, 12 required symbols, the
initialized 256-byte record and all false device gates. Each corruption run
rejected the same nine tested mutation classes, restored the copied baseline
and reported no phone query or write.

The verifier deliberately reports rather than hides these retained-evidence
limits:

- the host and preparation packets lack indexes;
- the harness result records `.bin` hashes, but the `.bin` files were not
  retained, so those hashes cannot be replayed from packet files;
- `vmlinux` is external and unindexed, so its recorded hash and linked section
  type/flags cannot be independently replayed offline from the packet;
- of the original kernel inputs, only `.config` is copied into the kernel packet;
  the other original input pins are recorded in `result.json` but absent for
  independent packet-only hashing;
- the kernel build reused copied output and is incremental;
- the invalid-DAIF path has already written the observed DAIF and other accepted
  entry fields into the record before it rejects arithmetic execution; it does
  not write the DAIF architectural register;
- unsupported EL and oversized CTR/DminLine guards have source/disassembly
  evidence but no executed QEMU case;
- no retained evidence proves A51 execution, exception recovery, a watchdog,
  persistent fault/reset logging or Android/recovery return.

These limits prevent host evidence from being promoted into a device-execution
claim.

## Recorded commands and runs

| Run | Result | Purpose |
|---|---:|---|
| `20261111T161347028843Z-phase2-early-entry-source-audit` | 0 | Read applicable instructions and pinned native entry/setup/cache sources |
| `20261111T161617358897Z-phase2-early-entry-cache-kaslr-audit` | 0 | Review cache/KASLR/native boot contract sources |
| `20261111T161653664101Z-phase2-early-entry-cache-exact-contract` | 0 | Review exact cache-maintenance and linker contract |
| `20261111T161908257886Z-phase2-early-entry-mmuoff-section-audit` | 0 | Review mmu-off data and boot-argument section use |
| `20261111T162527080829Z-phase2-early-entry-host-harness` | 0 | Build and execute all five QEMU cases |
| `20261111T163513157751Z-phase2-early-entry-isolated-kernel-build` | 0 | Prepare the isolated clone and build the experimental Image |
| `20261111T172248699374Z-phase2-early-entry-evidence-final-windows` | 0 | Windows `verify-all` replay of all three selected packets |
| `20261111T172248517634Z-phase2-early-entry-corruption-final-windows` | 0 | Windows rejection of nine tested mutation classes |
| `20261111T172248928798Z-phase2-early-entry-evidence-final-wsl` | 0 | Native WSL `verify-all` replay of all three selected packets |
| `20261111T172249251195Z-phase2-early-entry-corruption-final-wsl` | 0 | Native WSL rejection of nine tested mutation classes |

The host harness and isolated kernel build both passed on their first retained
execution; no failed candidate build or QEMU result was discarded. WSL emitted
the known nested-virtualization detection warning during the QEMU run and the
final native replay; both commands still completed successfully.

Reproduction must use new timestamped directories and retain old evidence:

```powershell
python scripts/run.py --label phase2-early-entry-host-harness -- wsl -d A51-KernelBuilder -- python3 /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/prototype/early-entry/host_test.py
python scripts/run.py --label phase2-early-entry-isolated-kernel-build -- wsl -d A51-KernelBuilder --exec python3 /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/build-early-entry-kernel.py
python scripts/run.py --label phase2-early-entry-evidence-final-windows -- python -B scripts/early_entry_evidence.py verify-all
python scripts/run.py --label phase2-early-entry-corruption-final-windows -- python -B scripts/test-early-entry-evidence.py
python scripts/run.py --label phase2-early-entry-evidence-final-wsl -- wsl -d A51-KernelBuilder -- python3 -B /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/early_entry_evidence.py verify-all
python scripts/run.py --label phase2-early-entry-corruption-final-wsl -- wsl -d A51-KernelBuilder -- python3 -B /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/test-early-entry-evidence.py
```

The native WSL replay must not invoke the external retained `vmlinux` as a
substitute for absent packet evidence.

## Recovery and rollback

`prototype/early-entry/prepare.py` rejects unexpected original bytes, an existing
candidate installation, a source-root configuration change, escaping paths and
an existing evidence destination. It is intentionally not idempotent on an
already patched clone. If preparation or compilation fails, preserve the failed
clone/evidence/run, correct the project-owned source and rebuild into a new
timestamped directory.

Rollback inside a disposable clone restores the three exact files under the
preparation packet's `original/` tree and removes only the three added candidate
files. Recreating the isolated clone is preferred. Nothing was installed on the
phone, so this milestone has no device rollback. Preserve the experimental
Image, patch, all failed or successful runs, upstream originals, Android
projects and the Phase 1 bundle.

## Remaining work and phase decision

P2-018 supplies a bounded early-entry candidate and a host-linked experimental
Image, not an A51 boot result. Before any device execution, Phase 2 still needs
an exact Samsung packaging/entry route, exception vectors, watchdog/reset and
persistent fault-log design, a recoverable boot/recovery procedure, explicit
platform-transition bounds and a demonstrated return contract. Only an actual
A51 run associated with the exact Image and fresh boot could establish pre-Linux
execution. Standalone HakiOS execution, XNU boot and the Phase 2 device gate all
remain false.

## Subsequent host packaging dry-run (P2-019)

[SAMSUNG-BOOT-DRY-RUN.md](SAMSUNG-BOOT-DRY-RUN.md) subsequently tested whether this exact 36,334,080-byte `Image` fits the retained Android v2 boot template without moving later sections. The strict in-memory reconstruction passed on Windows and native WSL, changes four declared regions and calculates candidate SHA-256 `73d88c699dda238238b7b2b1105caea248b9ef3aef282a3f01b566f0fd894a58`.

P2-019 does not alter this document's claim boundary. No candidate image bytes, Odin archive, installation, phone access or A51 execution were produced. The host-linked `Image` and calculated candidate identity still require Samsung firmware acceptance/entry evidence, exception vectors, watchdog/reset handling, persistent fault logs, bounded platform transitions and demonstrated Android/recovery return.
