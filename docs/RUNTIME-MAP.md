> Publication note: this is a historical workspace document. Current completion decisions are in [PUBLIC-STATUS.md](PUBLIC-STATUS.md); raw local evidence is described in [PUBLICATION.md](PUBLICATION.md).

# Offline runtime-observation map

Date: 11 November 2026. Status: implemented and verified; import passed on Windows; 80 guards and original-source replay passed on Windows/native WSL. This guide describes historical Linux observations. Executable ownership and the Phase 2 device gate remain unproved.

`scripts/runtime_observations.py` normalizes a fully verified schema-2 [live capture](LIVE-OBSERVATIONS.md). `scripts/import-runtime-map.py` creates an indexed packet or replays an explicit result. Neither operation contacts the phone, executes a payload, modifies Android inputs or changes the version 1 [payload-layout contract](PAYLOAD-LAYOUT.md). The placement/ownership-certification importer is still unimplemented.

## Observations and meaning

The selected source is `evidence/phase-2/live-loader/20261111T071559056361Z/report.json`, SHA-256 `771929edd98643aed7c7ecb50fec5354510bae39cfb8f7b1d56fd938c59bd9fd`. Its historical 153-file capture retains 49 queries, including five true remote failures. Import calls the current trusted live-capture verifier, which reconstructs the complete capture, pinned source-trace/base-FDT dependencies and original Android inputs before normalization. Copied report/index files alone are insufficient for replay.

| Observation | Normalized fact | Limit |
|---|---|---|
| Linux-exported FDT DRAM | Five ranges, 6,327,107,584 bytes | Declarations do not establish payload ownership |
| Root `/proc/iomem` System RAM | Four ranges; their union agrees with the five FDT ranges | Linux resource membership does not establish free memory |
| Live fixed reservations | 20 spans, versus 15 retained base spans | Every span remains an exclusion, including reusable reservations |
| Dynamic reservations | Video 75,497,472 bytes; crypto 25,165,824 bytes; Wi-Fi/Bluetooth 16,777,216 bytes | Their actual placements are unresolved |
| `/proc/iomem` resources | 95 records, including kernel code/data | Parent/child extents are checked; non-RAM records remain conservative exclusions |
| Initrd declaration | `[2298478592, 2299803648)`, 1,325,056 bytes | The exported declaration is historical; it does not prove current allocation lifetime |
| `MemFree` / `MemAvailable` | Retained counts in KiB | Counts cannot identify physical intervals |

Additional live reservations include `camera_contig`, `el2_code`, `el2_earlymem` and `kaslr`. Both initrd addresses use one 32-bit cell even though the root has `#address-cells=2`. The importer decodes each initrd address independently as one or two cells; it does not impose the root width on these properties.

The normalized map has 112 observed exclusions, three unplaced dynamic reservations and zero verified owned intervals. Overlapping resource/reservation descriptions are deliberately retained with their owners and basis. Counts of exclusions are records, not a sum of distinct occupied bytes.

## Interfaces and invariants

`normalize(report)` requires a complete, stable privileged capture, enabled DRAM declarations, valid fixed/dynamic ranges and false ownership/placement/device gates. Enabled DRAM ranges cannot overlap; adjacent ranges merge when comparing unions. Unsupported untranslated reservations, alignment-cell mismatches and invalid iomem hierarchy are rejected. Redacted iomem records retain their names without becoming physical intervals or supporting child records. Dynamic size/alignment/allocation restrictions remain observations with `placement=null`.

`interval(start, size)`, `checked_range(record)` and `union_ranges(records)` use exclusive ends. Addresses and sizes are exact integers, excluding booleans. Sizes are positive and `start + size < 2**64`; an end equal to `2**64` is deliberately rejected to match layout version 1. `address_cells(values)` accepts exactly one or two unsigned 32-bit cells.

`diagnose_span(map, start, size)` reports DRAM/System RAM coverage, overlapping exclusions and unresolved dynamic owners. Every candidate has `decision=rejected_ownership_unproved` and `usable_for_loader=false`, including a declared high-bank interval or a static gap with no known conflict. Demonstrations cover all 20 fixed reservations, kernel code/data, initrd, the modem/QEMU address, a low-bank gap, a high-bank interval and an interval outside declared DRAM: 27 required rejections. `0xF0000000` remains inside the modem reservation.

No caller can turn this map into a placement approval. All eight ownership/placement/destination/device/log/return/acceptance/no-flash flags remain false, `verified_owned_intervals=[]`, and the map explicitly records historical scope and no phone query/write by the importer.

## Commands and packet

Run from `C:\Users\Ankit\Desktop\A51\hakios-a51`; retain consequential commands through `run.py`:

```powershell
python scripts/run.py --label runtime-map-guards -- python scripts/test-runtime-map.py
python scripts/run.py --label runtime-map-import -- python scripts/import-runtime-map.py --import-report evidence/phase-2/live-loader/20261111T071559056361Z/report.json
python scripts/run.py --label runtime-map-readback -- python scripts/import-runtime-map.py --verify-result evidence/phase-2/runtime-map/<UTC>/result.json
python scripts/run.py --label runtime-map-readback-wsl -- wsl -d A51-KernelBuilder -u root -- python3 /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/import-runtime-map.py --verify-result /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/evidence/phase-2/runtime-map/<UTC>/result.json
```

Import/replay actions are mutually exclusive. Exit 0 means the historical projection/rejection diagnostics reconstruct; it approves no executable placement. `manifests/runtime-map-current.json` changes only after successful packet self-verification. Historical selections must use explicit timestamped paths and hashes. No new package or source dependency is installed.

Each packet has ten indexed files plus `index.json`: `result.json`, `map.json`, `diagnostics.json`, `inputs/live-report.json`, `inputs/live-index.json`, and five exact tool copies (`runtime_observations.py`, `import-runtime-map.py`, `test-runtime-map.py`, `capture-live-loader.py`, `boot_formats.py`). Replay checks exact roles/file set, original-source associations, report/index pins and copies, matching current tools, completed-capture-before-import timestamps, rederived maps/diagnostics/counts and false gates. The source is checked again after its verifier returns, and the returned report must match the pinned report bytes semantically.

JSON rejects duplicate keys, nonfinite constants/overflowing floats, invalid UTF-8 and depth above 64. A file is limited to 2 MiB before read and the ten indexed files to 8 MiB in aggregate before packet reads. Paths are canonical contained relative paths and symlinks are rejected. Replay imports the current trusted verifier; it never executes a retained script. Checks support local integrity and reconstruction, without authenticating a coherently replaced evidence set.

## Verification, failures and recovery

First Windows suite `20261111T112731837773Z-phase2-runtime-map-guards-first-windows` retained four failures: overflowing JSON float, original report mutation during verification, nested FDT placement promotion and boolean redacted addresses. The implementation now checks finite floats, source report/index after verification, nested placement false and exact integer redacted addresses. These failures are historical evidence and must remain preserved. The normalization preflight `20261111T112741636645Z-phase2-runtime-map-normalization-preflight` checked the expected counts/initrd/union agreement from the retained JSON; it did not substitute for complete source verification.

Guard fixtures use small synthetic reports and temporary packets with exact current tools/report/index bytes. Only complete source verification is mocked for packet tests; file/index/path/hash/pin/reconstruction checks run normally. Explicit selected-result replay must separately exercise the real original source verifier on both hosts. Native WSL guards use a hash-checked isolated mirror under `/opt/a51-hakios/validation/runtime-map` to avoid repeatedly copying large Android backups across DrvFS.

If replay fails, inspect the exact run metadata/output, file identities and current-versus-retained tools. Restore matching revisions into a compatible project root with its original inputs; the retained `tools/` directory is a revision source, not a standalone project. For intentional changes run meaningful guards on both hosts, create a new packet and replay its explicit result on both hosts. Preserve failed/partial packets; a failed import cannot publish a verified pointer.

Fourteen pre-change documentation/state/roadmap files are indexed under `evidence/phase-2/runtime-map-docs/20261111T111836955101Z`. Rollback restores those copies to their original locations (the `assessment/ROADMAP.md` copy belongs to `hakios-assessment/ROADMAP.md`), reverts the new importer scripts and selects a previously verified pointer if applicable. Preserve the new evidence/run history and the 264-file Phase 1 bundle. No device restoration is needed for this host-only milestone.

Next work: establish allocator/firmware-owned physical intervals and their lifetime, an actual launch mechanism, CPU/DMA/cache/MMU transitions and retrievable payload logs with demonstrated Android/recovery return. The [entry-route review](ENTRY-CONTRACT.md) narrows the source requirements; those requirements remain separate from measured Samsung behavior.

Selected verified result: `evidence/phase-2/runtime-map/20261111T113849417244Z/result.json`, 2,155 bytes, SHA-256 `eab0d48a1838a92b4dd0ec5cbac8e3738c86e90f72fd44458c8af7e27ef4f9d9`; 10 indexed files / 413,086 bytes; 80 guards per host. Counts are 5 banks / 6,327,107,584 bytes / 20 fixed reservations / 112 exclusions / 3 unplaced dynamics / 0 owned intervals / 27 rejections. Import run `20261111T113847571712Z-phase2-runtime-map-import-final` and explicit replays `20261111T113905433824Z-phase2-runtime-map-readback-final-windows`, `20261111T113905604263Z-phase2-runtime-map-readback-final-wsl` passed. Final guards: `20261111T113734339024Z-phase2-runtime-map-guards-resource-final-windows`, `20261111T114116349509Z-phase2-runtime-map-guards-resource-final-wsl-native`. Native preparation `20261111T114018269312Z-phase2-runtime-map-native-guard-preparation-final` retained five exact files / 120,431 bytes at `/opt/a51-hakios/validation/runtime-map/20261111T1138Z`; stage-manifest SHA-256 `dba59a0dd4f44718b1fa7664d5e921ea13d166334b81b3249054640b612f8e11`.

The independent amplification review `20261111T113057431706Z-review-runtime-map-amplification` reproduced a 20,994-byte input expanding beyond 5 MiB; extra-directory review `20261111T113223514525Z-review-runtime-map-extra-directory` reproduced an accepted unindexed empty tree. The implementation now caps normalized exclusions at 512, diagnostic cases at 256 and accumulated conflict copies at 1,024. Bounded incremental encoding rejects output above 2 MiB, and both map/diagnostics are encoded before a packet directory or input copies are created. Replay enumerates exactly the root, inputs and tools entries with per-directory count/type/name checks, without recursive traversal. Final guards cover exact limits, early consumption stop, repeated exclusions, directory substitutions and rejection before writes. Both reproductions and intermediate 66/67-case passing suites remain historical records; final tool identities are pinned by the 80-case suites and accepted packet.

Final offline-map/entry-review handoff `20261111T115352367308Z-phase2-runtime-map-final-documentation-state-check-corrected-output` passed exit 0 and is selected in `state.json`. At check time it verified 132 references/90 successful timed runs, 195 local links/24 documents, 80 guards per host, both original-source replays, exact tool/run roles and native staging, 24 citations from 29 source/config files, 14 documentation rollback copies and all 264 Phase 1 bundle files. The host-only observation/source-review and documentation milestone is complete. Phase 2 remains in progress: actual A51 entry, owned allocations, physical transitions, payload/fault logs and demonstrated Android/recovery return remain unresolved. No phone query/write/reboot/payload execution occurred in this continuation.
