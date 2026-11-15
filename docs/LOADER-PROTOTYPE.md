> Publication note: this is a historical workspace document. Current completion decisions are in [PUBLIC-STATUS.md](PUBLIC-STATUS.md); raw local evidence is described in [PUBLICATION.md](PUBLICATION.md).

# Bounded loader/test-payload prototype

Updated 11 November 2026, Asia/Calcutta. Status: implemented and verified in native WSL and QEMU virt. A51 device execution remains unconfigured and unverified; Phase 2 is in progress.

The first actual loader prototype source is under `prototype/loader/`. Its freestanding C core validates a synthetic arena, prepares test data, records entry and stage information, invokes a compiled test payload and requests return through a trusted callback. A separate AArch64 QEMU adapter captures virtual CPU registers, prints those records through PL011 and shuts down QEMU after the result is checked. This milestone supplies executable prototype code; the [A51 loader requirements](LOADER-DESIGN.md) still govern future hardware work.

## Files and build boundary

| File | Responsibility |
|---|---|
| `prototype/loader/probe.h` | Version 1 C interfaces, status/stage values, entry fields and limits |
| `prototype/loader/probe.c` | Validate spans before writes, copy/zero arena extents, callback flow, little-endian frame encoding and CRC32 |
| `prototype/loader/test_probe.c` | Native adversarial checks for bounds, untouched invalid input, callbacks, memory footprint and frame bytes |
| `prototype/loader/qemu/start.S` | Capture x0–x3, PC, initial SP and CPU state before BSS clearing and stack setup |
| `prototype/loader/qemu/main.c` | QEMU virt PL011 output, 16-byte test payload, simulated return and PSCI HVC SYSTEM_OFF |
| `prototype/loader/qemu/virt.ld` | QEMU direct-kernel load layout and separate 16 KiB C stack |
| `scripts/build-loader-probe.py` | Native sanitizer build, freestanding cross-build, bounded subprocess timeouts, source/tool/artifact capture and offline result verification |
| `scripts/test-loader-probe-evidence.py` | Independent transcript semantic/corruption guards |
| `manifests/loader-probe-current.json` | Latest fully successful prototype result and its SHA-256 |

Each fresh build copies sources into a new `/opt/a51-hakios/prototype/loader/<UTC>/source` directory and writes outputs alongside it. Retained evidence is copied to `evidence/phase-2/loader-probe/<UTC>/` in the Windows project. These are project-owned sources; no upstream adaptation patch is needed. The accepted HakiOS/XNU baseline and Android sources are separate.

The builder uses existing Ubuntu Clang/LLD 18.1.3, LLVM tools and QEMU 8.2.2. Tool paths, full versions and binary hashes, exact flags/arguments, UTC/IST timestamps, exit codes and separate stdout/stderr files are retained. No dependency was downloaded or installed for this milestone. The native binary uses AddressSanitizer and UndefinedBehaviorSanitizer; the AArch64 build uses freestanding code, no builtins, no stack protector and general registers only. The final ELF must have no undefined symbols.

## C interface and trust contract

`hp_validate(plan, arena_size)` performs no arena write. `hp_run(arena, arena_size, plan, callbacks)` returns a structured result containing status, frame count, callback invocation flags, signed callback outcomes and remaining fuel. Only modes `HP_HOST_SIMULATION=1` and `HP_QEMU_VIRT=2` are accepted. These names identify this prototype's adapters; caller labels cannot establish hardware evidence or create an A51 launch path.

The trusted caller must supply a valid allocation of the stated size, accessible plan/callback structures outside the arena and a captured entry record. C cannot infer whether a supplied pointer or allocation length is truthful. Callbacks are trusted compiled code and must preserve the plan, callback table, layout and log bytes. There is no sandbox for an arbitrary callback and no branch to copied input data.

The plan contains five spans with unsigned 64-bit offsets and sizes relative to one arena: input, payload destination, BSS, stack and logs. Every span must have positive size, 16-byte aligned offset/size, remain within the stated arena and be disjoint from every other span. Subtraction checks containment before addition or pointer arithmetic, including overflow cases. Arenas are limited to 1 MiB. The destination must hold the entire input, and the log span must hold all seven 256-byte frames, or 1,792 bytes. Adjacent spans and exact-end containment are allowed.

Invalid plan values, a null arena pointer or missing callbacks produce a structured error before any arena write or callback. Non-null pointers must satisfy the caller's accessibility/allocation contract above; the core cannot detect a dangling pointer or inaccessible structure. A rejected run emits no arena frame because its log destination has not been authorized by validation. The caller's external command/result record is the available rejection evidence.

On acceptance, the core copies input to the destination, zeros its remaining padding, zeros the BSS/stack spans and writes stage frames. The core leaves input and bytes outside these extents unchanged; callback side effects depend on the trusted-callback contract. The stack span is a modeled test extent; the core does not switch SP to it. The QEMU adapter separately provides its actual C stack through the linker script.

The payload view exposes copied input as read-only bytes, a writable BSS span and fuel. The payload callback can return an error. Zero fuel or increasing fuel beyond its initial value produces `HP_BUDGET_EXHAUSTED`; a nonzero payload result otherwise produces `HP_PAYLOAD_FAILED`. Return is requested once even for these outcomes. A nonzero return callback produces `HP_RETURN_FAILED` while preserving the earlier payload result in frames/result fields.

Fuel is cooperative work accounting, with an initial range of 1–1,048,576. It cannot interrupt a hung callback or a CPU exception. The host runner separately bounds native execution at 30 seconds and QEMU at 20 seconds, and marks timeouts as failures. CPU exception vectors, crash-safe fault records, watchdog enforcement, physical cache/MMU/interrupt transitions, DMA quiescing and a device reset/restoration implementation remain planned.

## Entry and log format

Entry fields in order are x0, x1, x2, x3, PC, SP, CurrentEL as level 1–3, CNTFRQ, SCTLR, DAIF, TCR, TTBR0, TTBR1 and VBAR. `entry_flags` bit *i* marks field *i* valid; zero flags and unknown bits are rejected. An enabled CurrentEL must be 1–3 and enabled CNTFRQ must be nonzero. Native tests supply synthetic values. A field with its bit clear is unknown even if its stored value is zero or nonzero.

In QEMU, assembly captures all 14 fields before clearing BSS, selecting the C stack or entering C. The accepted adapter requires EL1 and reads EL1 control registers only at EL1. This is measured QEMU entry evidence. It describes the virtual machine's direct-kernel entry, including its initial SP of zero, rather than Samsung firmware entry. The recorded PC is the adapter's `_start` address. The adapter does not use or hash the supplied FDT; its FDT identity is zero and `fdt_consumed=false` is explicit.

Every frame is exactly 256 bytes, encoded byte-by-byte in little-endian order. No native packed-structure cast defines the wire ABI.

| Byte offset | Length | Value |
|---|---|---|
| 0 | 8 | ASCII `HAKIPRB1` |
| 8 | 4 | Version 1 |
| 12 | 4 | Zero-based sequence |
| 16 | 4 | Stage 1–7 |
| 20 | 4 | Current unsigned `hp_status` |
| 24 | 4 | Adapter mode |
| 28 | 4 | Entry validity flags |
| 32 | 32 | Build identity SHA-256 |
| 64 | 32 | Input SHA-256 |
| 96 | 32 | FDT SHA-256; all zero when unused |
| 128 | 112 | Fourteen 64-bit entry fields in the order above |
| 240 | 8 | Remaining fuel |
| 248 | 4 | Signed callback result encoded as its 32-bit bit pattern; payload result from stage 5, return result at stage 7 |
| 252 | 4 | IEEE CRC32 over bytes 0–251 |

The build identity hashes canonical retained JSON containing source hashes, tool identities, compile/QEMU flags, exact input and unused-FDT status. The host computes the SHA-256 of the actual 16-byte input and generates `identity.h`. The C core carries caller-provided identity bytes; it contains no SHA-256 implementation or cryptographic authentication. General C callers' identities are assertions. The QEMU test checks each copied input byte against its built-in fixture, and the independent Python decoder checks emitted identities against retained build/input identities.

`hp_frame_valid` verifies frame size, magic, version, sequence, corresponding stage and CRC. It is an envelope check. The independent decoder additionally requires successful status, QEMU mode, complete entry flags, expected PC/EL/nonzero frequency, unchanged entry across frames, exact identities and budgets, zero callback results and the complete transcript. A re-CRC'd false mode or identity cannot satisfy its semantic acceptance.

Stages are entry captured, validation complete, data prepared, payload entered, payload exited, return requested and return result. All seven slots are reserved before writing the first frame. A successful tiny payload consumes 16 of 64 fuel units for its input-byte checks and leaves 48. Its BSS scan, logging and return are finite but uncharged, so the fuel number does not measure total runtime. Return success is recorded before the QEMU adapter requests SYSTEM_OFF. The return callback means ordinary control returned to the QEMU harness. QEMU shutdown is recorded separately by emulator exit 0. Neither outcome demonstrates return to Android/recovery.

## QEMU platform boundary

The demonstration uses QEMU `virt`, Cortex-A53, one CPU, 64 MiB RAM, direct raw-kernel loading at `0x40080000`, PL011 at `0x09000000` and the virtual PSCI HVC SYSTEM_OFF call. These constants are confined to `qemu/`; none selects an A51 executable address or identifies an Exynos UART/reset route. The test does not boot XNU or use the Phase 1 EFI/XNU artifacts.

The serial transcript retains seven hexadecimal frames and an exact success marker. The host decoder uses Python `struct` and `zlib.crc32`, independently of the C frame reader. It rejects extra/missing/reordered frames and incompatible fields. The guest checks the payload/return result and every frame before printing success; the host requires emulator exit 0 and reconstructs every frame before publishing the current pointer.

## Selected execution evidence

Selected final build: `20261111T105314457724Z-phase2-loader-probe-build-final`, exit 0. Native sanitizer checks: 2,609 assertions. Freestanding link: no undefined symbols. QEMU: seven valid frames, EL1, 62,500,000 Hz CNTFRQ, payload return success and emulator exit 0. This fresh execution followed the completed evidence-reader fixes and 93 passed guards on Windows/native WSL.

Selected result: `evidence/phase-2/loader-probe/20261111T105317947466Z/result.json`, 14,283 bytes, SHA-256 `d34df32b8ec8f95d62453dec4021a6f59577e72ddefb7fc2bdac4b8bb16b8351`. Its checksum index contains 55 files/1,986,789 bytes. Fourteen exact command records cover tools, compilation, native tests, linking, undefined-symbol check, binary conversion and QEMU. Build identity: `2c11080b3dbde2c21382f2eb42fe1402c66574720d1bde461af2691f340a116e`.

| Artifact | Size | SHA-256 |
|---|---|---|
| `probe.bin` | 7,248 | `bdb3754a8856c412661a31dae53d46bce59cc0d12407f7a807c1bb346cc1958e` |
| `probe.elf` | 74,216 | `dedf47cfa9dd5438dd53c46b8a7915677239df310f55c7d68471895c4886a187` |
| `test-probe` | 1,822,952 | `3557ba7dbc2800b46c7f49c36f55d68f720e5044e05891a3374b910dc3ed356f` |

Offline `--verify-result` checks the exact 55-file role set, contained indexed references and hashes/sizes; exactly seven source and five tool identities; regenerated `identity.h`; all 14 commands in order with reconstructed arguments/flags, correct native/QEMU stdout links, record/type equality and exit status; UTC/IST agreement and time ordering; artifact ELF roles; native success/count and independent serial reconstruction. Strict UTF-8 JSON rejects duplicate keys, nonfinite values, unknown fields, boolean/numeric substitutions and nesting beyond 64 levels. JSON roles are limited to 512 KiB and test/serial outputs to 4 KiB before reading. Other indexed files are limited to 16 MiB and aggregate bytes to 64 MiB. It executes neither artifacts nor QEMU and contacts no phone. Local checksum integrity is not external authentication; supplied files and compiler outputs are trusted project evidence, rather than a hostile-input execution service.

Final guard runs: `20261111T105214757357Z-phase2-loader-probe-evidence-guards-role-bounds-final-windows` (93, 21.163 seconds) and `20261111T105214866426Z-phase2-loader-probe-evidence-guards-role-bounds-final-wsl-native` (93, 1.683 seconds), both exit 0. The suite mutates disposable transcript/evidence copies, including re-CRC'd false fields, reindexed command/config/type/scope/timing/reference changes and pre-read resource limits. The 31-failure boundary reproduction and both failed 86-test nesting suites remain preserved. Final builder SHA-256 is `821de15feff559aa5b74b1e84b8981116713762e231343fbf9f0eb2532e94067`; guard script SHA-256 is `e035f71f558ebdb098c4a295b5c2fa2fa2cd2df890954039cc2ff546570a9542`.

The first accepted build `20261111T102810381957Z-phase2-loader-probe-build-first` and result `evidence/phase-2/loader-probe/20261111T102815217132Z/result.json` remain unchanged (SHA-256 `f386bc859f0419866f2475a70218f2fe11544703e915917f40a6ef000d95dcd4`, 55 files/1,975,386 bytes). Strict replay still passes for it; its older builder hash explains its different identity and binary bytes. The current pointer selects the fresh final execution above.

## Run, modify and recover

Run PowerShell from `C:\Users\Ankit\Desktop\A51\hakios-a51`:

```powershell
python ./scripts/run.py --label loader-probe-build -- wsl -d A51-KernelBuilder -u root -- python3 /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/build-loader-probe.py --build
python ./scripts/run.py --label loader-probe-readback -- python ./scripts/build-loader-probe.py --verify-result evidence/phase-2/loader-probe/20261111T105317947466Z/result.json
python ./scripts/run.py --label loader-probe-readback-wsl -- wsl -d A51-KernelBuilder -u root -- python3 /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/build-loader-probe.py --verify-result /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/evidence/phase-2/loader-probe/20261111T105317947466Z/result.json
python ./scripts/run.py --label loader-probe-evidence-guards -- python ./scripts/test-loader-probe-evidence.py
python ./scripts/run.py --label loader-probe-evidence-guards-wsl -- wsl -d A51-KernelBuilder -u root -- python3 /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/test-loader-probe-evidence.py
python ./scripts/run.py --label loader-probe-handoff -- python ./scripts/check-loader-probe-handoff.py
```

A fresh build always creates new Windows evidence and native WSL directories. It preserves earlier successful/failed builds and updates the current pointer only after full success and self-verification. If a compiler, test, link, emulator or decoder fails, inspect the failed result, exact command JSON and stdout/stderr. A timeout keeps available output, marks `timed_out=true` and exit 124, and cannot become a pass. Resolve the source/environment issue and run a fresh build; preserve the failed folder. Do not weaken a check to accept a partial transcript.

Core or QEMU adapter changes require native guards and a fresh freestanding QEMU run. Decoder changes require semantic guards and replay; changes to build identity/build execution require a fresh build. Documentation-only changes require state/link/evidence consistency checks. Retained source copies, exact commands and matching tool versions permit inspection and a historical rebuild. Replay checks the retained relationships and bytes; it does not independently prove that a compiler produced an artifact from those sources. Use the matching runner/tool versions when reproducing older behavior.

Rollback: restore a specific retained source revision from the result's `source/` directory, record why and rebuild into a new timestamp. A current pointer may deliberately select an earlier verified result after a recorded rollback, while preserving both histories. Thirteen pre-change documents/state/roadmap copies are retained under `evidence/phase-2/loader-probe-docs/20261111T102921621458Z`; no phone restoration is needed for this host milestone.

Final documentation/state handoff check `20261111T110651772420Z-phase2-loader-probe-final-documentation-state-check` passed exit 0 and is selected in `state.json`. It verified 102 references/66 successful timed runs, 163 links/22 documents, result/pointer/counts/identities, exact build/guard/replay roles and native preparation, unchanged tested sources/scripts, both accepted-result replays, 13 rollback copies and all 264 Phase 1 bundle files. The host/QEMU implementation and documentation milestone is complete; Phase 2's A51 device gate remains false.

Next port work is an A51-specific adapter backed by an actual entry route, verified owned memory, platform transitions, recoverable payload logs and demonstrated return. The [live observations](LIVE-OBSERVATIONS.md) and [source trace](SOURCE-TRACE.md) supply references but cannot fill those missing execution facts. A runtime ownership importer and Samsung experimental image remain unimplemented. Phase 3 XNU entry/timer/interrupt work and all hardware drivers await their gates.
