> Publication note: this is a historical workspace document. Current completion decisions are in [PUBLIC-STATUS.md](PUBLIC-STATUS.md); raw local evidence is described in [PUBLICATION.md](PUBLICATION.md).

# Host payload-layout validator and evidence replay

Date: 11 November 2026. Status: version 1 implemented and verified on Windows and WSL. All 92 guard tests passed on each host; one synthetic demonstration passed and all 21 retained-A51 demonstrations were rejected as expected. Both demonstration records replayed successfully on both hosts.

This is a host consistency check. Version 1 accepts only `synthetic-host` assumptions and has no A51 runtime-evidence importer. The `a51-retained-host` target diagnoses historical inputs and always rejects an executable layout. No A51 destination, loader, decompressor, experimental boot image or device execution is implemented. Every result retains `safe_for_loader_placement=false` and `phase_2_device_gate_passed=false`.

Read [loader requirements](LOADER-DESIGN.md) for the entry, live FDT, ownership, logging and return evidence still required. The [retained-image audit](PHASE-2-HOST-AUDIT.md) supplies source declarations, not an available-memory map.

## Files and responsibilities

| File | Responsibility |
|---|---|
| [payload_layout.py](../scripts/payload_layout.py) | Strict JSON contract, provenance, bounded input reads, original-byte audit import, arithmetic, extents, overlaps and diagnostics |
| [validate-payload-layout.py](../scripts/validate-payload-layout.py) | Candidate capture, demonstrations, indexed evidence, reconstruction/replay and current pointer |
| [test-payload-layout.py](../scripts/test-payload-layout.py) | 92 meaningful host arithmetic, integrity, ownership, entry and replay guards |
| `evidence/phase-2/layout/<UTC>/` | Exact case manifests, result and checksum index; the synthetic demonstration also retains its generated inputs |
| [payload-layout-current.json](PUBLICATION.md) | Latest completed check, operation, outcome, counts and result hash; historical selections use explicit timestamped paths |

The module reuses `boot_formats.py` for FDT/Linux Image parsing and `audit-boot-inputs.py` for original-image report verification. It reads existing Android/source inputs without modifying them. No additional dependency or upstream adaptation was needed.

## Version 1 manifest contract

The exact passing example is [synthetic-host-example.json](PUBLICATION.md). Its text input is deliberately nonexecutable; its FDT is an empty synthetic tree. Copying its address or evidence labels cannot establish A51 support.

All fields below are required. Unknown fields, unsupported versions, duplicate JSON keys, nonfinite numbers, duplicate list identifiers and undefined evidence references are rejected.

| Top-level field | Meaning |
|---|---|
| `format`, `schema_version` | Exactly `hakios.payload-layout` and integer `1` |
| `target` | `synthetic-host` or `a51-retained-host`; no runtime A51 target exists |
| `purpose` | Explicit description of the host diagnostic or synthetic assumptions |
| `evidence` | Records with `id`, `path`, positive whole-file `size` and lowercase `sha256` |
| `retained_audit` | `null` for synthetic targets; A51 binding with `evidence`, `image`, `section` and `entry_index` |
| `memory` | `allowed`, `excluded` and `dynamic` lists |
| `prerequisites` | Provenance records for `entry_route`, `cpu_state`, `live_fdt`, `memory_ownership`, `log_retrieval` and `return_path` |
| `entry` | Loader component `component`, byte `offset`, `alignment` and descriptive `abi` |
| `components` | Separate records covering loader, kernel, payload, FDT, BSS, stack, page tables, scratch and logs |

Every provenance record has `state`, `basis`, `evidence` and `note`. States are `observed`, `conditional` and `unknown`. Bases are `synthetic`, `retained_bytes`, `source_declaration`, `runtime_observation` and `unavailable`. Observed/conditional assertions require defined hash-pinned evidence; unavailable evidence must remain unknown. These labels describe an assertion's basis, not an independent certification.

Version 1 trusts available intervals and entry/CPU/FDT/ownership/log/return prerequisites only for an observed synthetic assumption on the synthetic target. Caller-supplied `runtime_observation` labels cannot turn retained bytes, a declared bank or a static gap into verified ownership. Conditional or unknown prerequisites prevent acceptance.

`memory.allowed` records contain `id`, `start`, `size` and `provenance`. Exclusions add `owner`. Dynamic records contain `id`, `owner`, `size`, `alignment`, `alloc_ranges`, `placement`, `declaration` and `placement_provenance`. Allocation constraints contain `start` and `size`; a placement is such an interval or `null`. An unresolved placement or alignment prevents acceptance even when a proposed component appears to avoid known fixed reservations. A synthetic placed allocation must cover its full declared size, obey alignment/allocation constraints, fit one supported interval and avoid other dynamic allocations and exclusions.

Each component contains `id`, `role`, nullable `start` and `execution_bytes`, `alignment`, `reserve_alignment`, `prefix_bytes`, `suffix_bytes`, `format`, nullable `image` and `extent_provenance`. File-backed loader/kernel/payload/FDT records require an image slice with `evidence`, `offset`, positive `size` and `sha256`. BSS, stack, page tables, scratch and logs use separate `zeroed` extents with no file content. This describes future touched memory; the host validator does not zero or copy physical memory.

## Bounds, integrity and effective extents

Addresses and sizes accept unsigned 64-bit JSON integers or `0x` hexadecimal strings of at most 16 digits. Booleans, floats, negatives and oversized integers are rejected. Sizes are positive where required; additions, prefixes, suffixes and alignment rounding must remain representable. An exclusive interval end equal to `2**64` is rejected. Alignments must be positive powers of two.

The JSON manifest and each generated evidence/index/result/case file are limited to 2 MiB. Evidence replay checks file size before allocating and bounds the subsequent read. Manifest evidence is limited to 64 pins with a combined 256 MiB input budget; the checked-byte cache is limited to 128 MiB. Component lists are limited to 64 records and ordinary interval lists to 256. Whole-file size/hash and slice bounds/hash must match before format-specific checks.

`raw` inputs prove byte identity and a stated extent, not executable code or a CPU ABI. `arm64-image` parsing requires a valid bounded Linux Image and a nonzero declared image size; its minimum execution extent is the greater of stored slice size and Image size. `fdt` slices require bounded parsing and exact `totalsize`, rejecting trailing bytes. `expanded` is accepted only as a synthetic extent assertion; no actual decompressor or XNU/Mach-O execution-extent parser is implemented.

The entire component reservation includes full execution size, prefix/suffix bytes and reservation alignment:

~~~text
touch_end = start + execution_bytes
reserved_start = align_down(start - prefix_bytes, reserve_alignment)
reserved_end = align_up(touch_end + suffix_bytes, reserve_alignment)
~~~

That complete half-open reservation must fit within one supported owned interval. A component cannot bridge a hole or combine adjacent intervals into an unsupported larger interval. Pairwise component checks and reservation/dynamic checks include all padding. Adjacent nonoverlapping ranges may meet at an exclusive boundary. Overlapping allowed intervals are rejected as ambiguous.

Entry must select a file-backed loader with `raw` or `expanded` format, lie within its execution extent and satisfy entry alignment. A raw loader entry must also lie within stored bytes rather than zero extension. The `abi` description is retained but no Samsung or XNU entry ABI is validated.

## Importing retained A51 declarations

The A51 diagnostic selects `original-boot`, section `dtb`, entry `0` from the final original-byte report. Import first verifies the report's index, original image/source hashes and reconstructed tree summaries. Unapplied overlays cannot supply base RAM.

Imported RAM stays in `memory.declared`. Every imported fixed exclusion, FDT header reservation and unresolved dynamic allocation is added independently of caller lists. Empty or substituted caller lists cannot remove the modem reservation or resolve a dynamic owner. Diagnostic FDT and Linux Image slices must match the selected retained original.

The retained base has three separate 2 GiB banks, 15 fixed spans and three unplaced dynamic allocations. **QEMU's `0xF0000000` address is inside modem memory `[0xED000000, 0xF5A00000)`.** It must not be reused for the A51. Neither high-bank declarations nor mathematical static gaps establish live usable RAM; all retained-A51 evaluations include `a51_runtime_evidence_unavailable`.

The diagnostic kernel is retained Android Linux, not a HakiOS/XNU implementation. No loader/payload implementation exists in these manifests, and their absent addresses/extents remain explicit unknowns. Probe addresses in rejected cases are host test inputs; none is a selected destination.

## Selected results and verification history

| Demonstration | Retained result | Counts |
|---|---|---|
| Synthetic arithmetic/integrity example | [20261111T033005872222Z/result.json](PUBLICATION.md) | 1 accepted synthetic case; 4 indexed files |
| Retained A51 rejection diagnostics | [20261111T033104768751Z/result.json](PUBLICATION.md) | 21 rejected cases; 22 indexed files; 3 banks/15 fixed/3 dynamic declarations |

Synthetic result: 7,527 bytes, SHA-256 `50bfea1d913d1cc9addaa0b037d5925362361755d2e4201215b6baa83194647b`. A51 result: 514,441 bytes, SHA-256 `4cc79e0d7750ed47ad172fb75fc5f78fe54dc498452e60aaff57ec1a4a43a199`. Both have `all_expectations_met=true` and false device/placement/destination/write flags. The current pointer selects the A51 demonstration.

The 21 A51 cases comprise one unplaced-input case, the QEMU/modem conflict, all 15 fixed reservations, both high banks, a static gap and an attempt to promote retained inputs with caller runtime labels. Expected issue codes/locations are checked as well as rejection; a generic unrelated rejection cannot substitute for the required modem/reservation diagnosis.

| Check | Successful run |
|---|---|
| 92 guards, Windows | `20261111T032831861807Z-phase2-payload-layout-guards-final-windows` |
| 92 guards, WSL | `20261111T032831997257Z-phase2-payload-layout-guards-final-wsl` |
| Synthetic capture | `20261111T033005541735Z-phase2-payload-layout-synthetic-demo` |
| A51 diagnostic capture | `20261111T033104412655Z-phase2-payload-layout-a51-demo` |
| Synthetic replay, Windows / WSL | `20261111T033146422553Z-phase2-layout-synthetic-readback-windows` / `20261111T033146581036Z-phase2-layout-synthetic-readback-wsl` |
| A51 replay, Windows / WSL | `20261111T033146721006Z-phase2-layout-a51-readback-windows` / `20261111T033146935109Z-phase2-layout-a51-readback-wsl` |
| Unchanged Phase 1 bundle, 264 files | `20261111T033147159696Z-phase2-layout-phase1-bundle-preservation` |
| Continuation review of records, hashes and script snapshots | `20261111T033534236362Z-phase2-layout-continuation-evidence-review` |
| Final Phase 1 live integrity against updated documentation | `20261111T034920443881Z-phase2-layout-final-phase1-live-integrity` |
| Final documentation/state/evidence consistency | `20261111T035322188207Z-phase2-layout-final-documentation-state-check` |

Final handoff checks passed exit 0. Phase 1 live integrity reverified 13 selected runs, four artifacts, two transcripts, nine pins, SDK/three archives, 19 historical queries and 80 input hashes. Documentation consistency checked 108 local links across 19 documents, selected successful timed runs, report/result/current-pointer identities and counts, all 26 indexed layout files and eight unchanged script snapshots per host. No guard suite, build, QEMU run or device query was repeated for documentation synchronization.

Earlier guard suites passed 85 and then 89 cases. Additional review reproduced three replay defects in `20261111T032721500888Z-phase2-layout-replay-boundary-reproduction`, exit 1: Python's equality let a boolean replace an empty candidate size, the index limit was checked after reading, and an oversized case could pass evidence replay. The correction enforces JSON value types and bounds index/case reads before allocation. All three regressions are included in the final 92-test suites. The failing run and its script snapshot remain retained; it is not completion evidence.

The guards also cover integer/overflow/alignment boundaries, >4 GiB addresses, discontiguous banks, full expanded/padded extents, each required component, corrupted/truncated files and FDTs, entry bounds, unknown ownership, every prerequisite, original-byte audit substitution and reindexed evidence tampering. Continuation review confirmed eight current scripts match each final host's retained snapshots, with no code change after those tests.

## Run, capture and replay

Run from `C:\Users\Ankit\Desktop\A51\hakios-a51` in PowerShell. All consequential commands use the recorder; run creation commands sequentially because they update a shared current pointer.

~~~powershell
python ./scripts/run.py --label payload-layout-guards -- python ./scripts/test-payload-layout.py
python ./scripts/run.py --label payload-layout-guards-wsl -- wsl -d A51-KernelBuilder -u root -- python3 /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/test-payload-layout.py
python ./scripts/run.py --label layout-synthetic-readback -- python ./scripts/validate-payload-layout.py --verify-result evidence/phase-2/layout/20261111T033005872222Z/result.json
python ./scripts/run.py --label layout-a51-readback -- python ./scripts/validate-payload-layout.py --verify-result evidence/phase-2/layout/20261111T033104768751Z/result.json
~~~

Either readback can run in WSL by replacing the child Python command with `wsl -d A51-KernelBuilder -u root -- python3 /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/validate-payload-layout.py` and keeping its arguments. A51 replay needs the original boot/audit/source inputs; Windows maps logical `/opt/` inputs through `\\wsl.localhost\A51-KernelBuilder`, and WSL maps Windows paths through `/mnt/c/`. No phone access is needed.

For an intentional fresh capture:

~~~powershell
python ./scripts/run.py --label layout-synthetic-demo -- python ./scripts/validate-payload-layout.py --demonstrate-synthetic
python ./scripts/run.py --label layout-a51-demo -- python ./scripts/validate-payload-layout.py --demonstrate-a51 --report evidence/phase-2/boot-audit/20261111T022538476271Z/report.json
~~~

`--demonstrate-a51` without `--report` selects and checks the current boot-audit pointer. To evaluate an existing manifest, use `--manifest`. For example, evaluating the retained unplaced case returns the expected exit 1 and retains a new candidate record:

~~~powershell
python ./scripts/run.py --label layout-unplaced-candidate -- python ./scripts/validate-payload-layout.py --manifest evidence/phase-2/layout/20261111T033104768751Z/cases/unplaced-retained-inputs.json
~~~

## Outcome interpretation and recovery

`--manifest` returns 0 for an accepted synthetic host layout and 1 for a rejected candidate. Demonstrations return 0 only when all expected outcomes and required diagnostics match. A51 demonstration exit 0 therefore means its 21 rejection checks passed. `--verify-result` returns 0 when retained evidence reconstructs correctly, including a retained rejected candidate; inspect `assessment.host_validation_passed` and `status` for the layout outcome.

Capture uses a new UTC folder and exact manifest bytes, then independently replays with a fresh input resolver before publishing the current pointer. A completed rejected candidate may update the pointer with `expected_checks_passed=false`. `host_check_completed=true` is not acceptance. Preflight/replay errors do not publish a successful check; preserve any partial evidence and the run's output.

Replay checks index containment, bounds, file identities and the exact expected file set. Demonstrations are regenerated from pinned originals or exact synthetic fixtures; candidate replay uses the copied original manifest and retained source-manifest identity. Assessments, counts and JSON types are recomputed, preventing a rehashed result from silently changing its outcome or device claims. The original standalone candidate manifest need not remain present, but its pinned component/audit inputs must.

For checksum/access failures, restore access to the exact original input or investigate drift; do not replace its accepted digest. If validator semantics change, preserve old results and replay them using the matching script revisions in a compatible project root. Scripts derive their project root from their location, so a nested `runs/<id>/project-scripts` directory is a revision source, not a standalone checkout. Record deliberate script restoration or pointer changes in IMPLEMENTATION-LOG.md and create new evidence for new semantics.

Rollback is limited to a specific host script/document revision or deliberately verified pointer. Preserve all runs, original Android inputs and the Phase 1 completion bundle. No phone restoration or host kernel rebuild is required for this validator/documentation work.

Hashes establish local integrity, not authenticity, physical ownership or execution. Source tracing, privileged Linux-exported FDT observations, the host/QEMU prototype and the [historical runtime-observation map](RUNTIME-MAP.md) are now verified. The [entry-route review](ENTRY-CONTRACT.md) documents pinned source requirements; actual A51 entry, owned memory, platform transitions, payload/fault logs and demonstrated Android/recovery return remain the next milestone. Version 1's ownership-certification importer remains unimplemented, and the observation map cannot approve placement. Phase 2's device gate remains unpassed.


## Executed lifetime-bound plan diagnostic (P2-016)

The [allocation/plan diagnostic](OWNERSHIP-PROBE.md) passed on the A51: three fixed 64 KB plan bindings, seven rejected wrong/stale/released requests, ten state observations and 21 ordered kernel messages. All 23 rooted commands and the transfer succeeded. All three sequential allocations were cleared and released; Android kept the same boot and the module/file are absent. SELinux was Enforcing and existing taint stayed 4096. Native ASan/UBSan checks passed 1,408 assertions; all 17 import CRCs and exact vermagic matched. Windows/WSL replay and all 44 corruption guards per host passed.

Selected host result: `evidence/phase-2/ownership-probe-build/20261111T141326924789Z/result.json`. Selected device result: `evidence/phase-2/ownership-probe-device/20261111T141913580938Z/result.json`. The fixed plan is checked inside the allocation owner under one mutex; a receipt is historical once its callback returns. No external allocation certificate, loader-layout acceptance, copied payload or standalone execution is established. Current released addresses cannot authorize future placement. Phase 1 remains complete, Phase 2 in progress, and standalone launch/platform/fault-log/return gates remain false.

Next: define the bounded A51 diagnostic adapter execution/fault contract, then resolve standalone entry, CPU/MMU/cache/DMA/interrupt transitions, recoverable payload/fault logs and demonstrated return. See the new guide for exact commands, source provenance, failed offline checks and rollback.
