> Publication note: this is a historical workspace document. Current completion decisions are in [PUBLIC-STATUS.md](PUBLIC-STATUS.md); raw local evidence is described in [PUBLICATION.md](PUBLICATION.md).

# Samsung boot-image packaging dry-run (P2-019)

Date: 12 November 2026. Status: implemented and verified on Windows and native WSL as a host-only, in-memory reconstruction. No candidate boot image was emitted, retained, installed or executed.

This milestone answers one narrow question left by [EARLY-ENTRY.md](EARLY-ENTRY.md): can the retained 36,334,080-byte experimental Linux `Image` fit into the retained A51 Android boot-partition layout without moving the ramdisk, DTB or AVB boundary? The answer is yes for the pinned bytes and the four-region transformation below. It does not establish Odin packaging, Samsung firmware acceptance, standalone HakiOS execution, fault recovery or return to Android/recovery.

## Selected evidence and exact inputs

The selected packet is `evidence/phase-2/samsung-boot-dry-run/20261112T010401492946Z/`. It contains seven indexed files totaling 58,533 bytes. Its report is 5,281 bytes with SHA-256 `ab636baa11543a6da7fce252baa835547f72eb39c3c863cebee251a2607bfd02`; its index is 1,349 bytes with SHA-256 `34007a50202a11667e0646875f6baf8de3a68f9fb53388764d78a3083f79ffbd`.

| Role | Pinned path | Bytes | SHA-256 |
|---|---|---:|---|
| Retained Android v2 template | `everline-ksu/artifacts/A51-PixelOS-Everline-KernelSU-Next-boot.img` | 61,865,984 | `eb30609a62999e3282ac81e0a5e56411ef12ec1a39c107171bf3e01209c7cb67` |
| P2-018 kernel | `hakios-a51/evidence/phase-2/early-entry-kernel/20261111T163522918342Z/Image` | 36,334,080 | `87c0401361d4503afb0b266b15ff0caf1e64f505d61d53be700e8b6c6d8e9cf6` |
| Prior Android repack record | `everline-ksu/artifacts/repack-validation.json` | 1,911 | `2ced1959920eb5a1daf1343c89b36c40caf1a3d7d419a73957385597c8e8712b` |

The prior repack record associates the template with an Android kernel that was previously boot-tested and read back. That historical device result applies only to that prior Android kernel. It is not evidence that the P2-018 kernel, the in-memory candidate or HakiOS boots on the phone.

The retained template is Android boot header version 2 with a 2,048-byte page. Its kernel starts at offset 2,048. The old 36,333,584-byte kernel and zero padding occupy a fixed 36,335,616-byte slot. The new kernel is 496 bytes larger but remains in that same slot, leaving 1,536 zero-padding bytes. The ramdisk remains at offset 36,337,664, the DTB at 37,662,720, the payload/AVB boundary at 37,797,888 and the full partition length at 61,865,984 bytes.

## Exact in-memory transformation

`scripts/samsung_boot_dry_run.py` first validates the Android header, ARM64 `Image` header, unsigned AVB metadata, current legacy boot ID, fixed section layout and zero kernel padding. It then copies the template into memory and permits changes in exactly four regions:

| Region | Offset | Bytes | Meaning |
|---|---:|---:|---|
| `header.kernel_size` | 8 | 4 | Store the new 36,334,080-byte kernel size as little-endian Android header data. |
| `header.id` | 576 | 32 | Recompute the Android v2 legacy SHA-1 identifier into the first 20 bytes and keep the final 12 bytes zero. |
| `kernel.slot` | 2,048 | 36,335,616 | Zero the fixed slot, copy the new kernel and retain zero padding; no later section moves. |
| `avb.boot_digest` | 37,798,312 | 32 | Recompute the retained SHA-256 boot hash descriptor over its salt and the 37,797,888-byte original-image span. |

The legacy Android identifier is SHA-1 over each retained section followed by its four-byte little-endian size: kernel, ramdisk, zero-length second, zero-length recovery DTBO and DTB. The resulting identifier is `e8c00ec632687d9a8ba6099dc847448220ee9155`.

The AVB footer and vbmeta stay at their retained offsets. The retained metadata requires libavb 1.0, uses algorithm type 0 with zero authentication bytes, has flags 0 and contains a SHA-256 boot hash descriptor. Algorithm type 0 means this record is unsigned; recalculating its descriptor is a byte-layout consistency check, not proof of the phone's complete verified-boot policy.

The reconstruction checks that the full partition length, ramdisk, second, recovery DTBO, DTB and every byte outside the four declared regions remain unchanged. The report records before/after hashes for each changed region.

## Candidate digest semantics

The full 61,865,984-byte in-memory result hashes to SHA-256 `73d88c699dda238238b7b2b1105caea248b9ef3aef282a3f01b566f0fd894a58`. This is a reproducible identity for the calculated byte sequence, not a retained artifact:

- `generate_report()` deletes its internal candidate reference after calculating the report.
- The capture writes only JSON, source snapshots and the prior 1,911-byte repack record.
- The packet contains no `.img`, no candidate byte range and no installable Odin archive.
- Reproducing the digest requires the separately pinned live template, kernel, source and report semantics.

Do not rename this digest as a built, packaged, flashed or boot-tested image. `full_image_emitted`, `candidate_bytes_retained`, `installable_image_created`, all phone-operation flags and every Phase 2 execution/log/return gate are false.

## Verification

The selected capture run is `20261112T010359925342Z-phase2-samsung-boot-dry-run-capture-hardened-3`. Exact semantic replay passed in:

- Windows: `20261112T010409189329Z-phase2-samsung-boot-dry-run-replay-final-windows`
- WSL: `20261112T010514159526Z-phase2-samsung-boot-dry-run-replay-final-wsl`

The core reconstruction suite passed 11 cases on each host:

- Windows: `20261112T005453932895Z-phase2-samsung-boot-dry-run-tests-hardened-windows`
- WSL: `20261112T005748242395Z-phase2-samsung-boot-dry-run-tests-hardened-wsl`

It covers retained/identity reconstruction and rejects bad boot magic, unsupported header version, stale legacy ID, invalid AVB footer, signed AVB, verification-disabled flags, stale AVB hash, invalid ARM64 magic and kernel-slot growth.

The packet verifier passed 30 evidence guards on each host:

- Windows: `20261112T010456977064Z-phase2-samsung-boot-dry-run-evidence-guards-final-windows`
- WSL: `20261112T010532637885Z-phase2-samsung-boot-dry-run-evidence-guards-final-wsl`

It enforces the exact seven roles, bounded strict JSON/source reads, tree containment/depth/count limits, symlink/reparse rejection, exact size/hash pins, live/retained repack identity, current/retained source identity, typed semantic replay, the stable candidate digest and the four-region contract.

The completed documentation/state handoff is selected from
`20261112T013706260574Z-phase2-samsung-boot-dry-run-final-handoff`; the
post-selection readback `20261112T013737722609Z-phase2-samsung-boot-dry-run-final-handoff-selected`
also passed. Phase 1 preservation run
`20261112T013759515235Z-phase2-samsung-boot-dry-run-phase1-preservation`
reverified all 264 files in `evidence/phase-1/20261111-final`.

## Failed attempts retained

Failed runs and their partial evidence are intentionally preserved:

- `20261111T180424005604Z-phase2-samsung-boot-dry-run-tests-windows` exposed an incorrect legacy boot-ID formula that omitted required zero-length section size words.
- `20261111T180515402338Z-phase2-samsung-boot-dry-run-tests-windows-2` exposed a reversed AVB test expectation: replacing the kernel should make the old descriptor stale before recomputation.
- `20261112T005524061821Z-phase2-samsung-boot-dry-run-evidence-guards-windows` showed that the Windows depth fixture reached the directory-set guard first.
- `20261112T005822893860Z-phase2-samsung-boot-dry-run-evidence-guards-wsl` exposed recursion in a mocked `lstat` predicate that called `resolve()` under the same mock.

The fixes corrected the formula, expectation and test fixtures. They did not weaken the production verifier. Preserve the failed run folders and the earlier timestamped packets for audit and regression diagnosis.

## Reproduction

Run consequential commands from `hakios-a51/` through `scripts/run.py` so their arguments, output, timestamps and exit status are retained. Choose new labels; do not overwrite the selected packet.

```powershell
python .\scripts\run.py --label phase2-samsung-dry-run-core-windows -- python .\scripts\test-samsung-boot-dry-run.py
python .\scripts\run.py --label phase2-samsung-dry-run-replay-windows -- python .\scripts\verify-samsung-boot-dry-run.py .\evidence\phase-2\samsung-boot-dry-run\20261112T010401492946Z
python .\scripts\run.py --label phase2-samsung-dry-run-guards-windows -- python .\scripts\test-samsung-boot-dry-run-evidence.py .\evidence\phase-2\samsung-boot-dry-run\20261112T010401492946Z
```

```powershell
python .\scripts\run.py --label phase2-samsung-dry-run-core-wsl -- wsl.exe -d A51-KernelBuilder -- python3 -B /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/test-samsung-boot-dry-run.py
python .\scripts\run.py --label phase2-samsung-dry-run-replay-wsl -- wsl.exe -d A51-KernelBuilder -- python3 -B /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/verify-samsung-boot-dry-run.py /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/evidence/phase-2/samsung-boot-dry-run/20261112T010401492946Z
python .\scripts\run.py --label phase2-samsung-dry-run-guards-wsl -- wsl.exe -d A51-KernelBuilder -- python3 -B /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/test-samsung-boot-dry-run-evidence.py /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/evidence/phase-2/samsung-boot-dry-run/20261112T010401492946Z
```

`capture-samsung-boot-dry-run.py` creates a new timestamped report packet only after validating all input pins. It still must be run through `run.py`. Do not modify it to write the returned test-only candidate bytes.

## Recovery and rollback

Replay is read-only. If an input pin, source snapshot, report field or packet role differs, stop and retain the failure; do not edit the selected packet to make it pass. Determine whether the live template/kernel/repack source changed, restore the intended separately backed-up input if appropriate, or create a new timestamped packet and document the new provenance. Never substitute a different boot image under an old hash.

Rollback for P2-019 is deletion of newly created project-owned reports or code changes only after their paths have been reviewed and the evidence is no longer needed. The selected and failed packets and run logs should normally be preserved. There is no phone rollback because this milestone made no phone query, write, flash, partition, reboot, boot/recovery or DTBO change. Existing Android kernel projects and artifacts remain separate and unchanged.

## Remaining gate

P2-019 verifies a host-only byte-layout hypothesis. It does not create an installable image or prove Samsung bootloader acceptance, firmware entry state, exception vectors, independent watchdog/reset behavior, persistent fault retrieval, CPU/MMU/cache/DMA/interrupt transitions, standalone A51 execution or demonstrated return. Phase 2 therefore remains `in_progress`; the A51 payload-execution, standalone-execution, persistent-fault-log, fault-return, A51-return and Phase 2 device gates remain false.
