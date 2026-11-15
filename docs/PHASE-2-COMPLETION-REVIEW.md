> Publication note: this is a historical workspace document. Current completion decisions are in [PUBLIC-STATUS.md](PUBLIC-STATUS.md); raw local evidence is described in [PUBLICATION.md](PUBLICATION.md).

# Phase 2 completion review — 13 November 2026

**Decision: Phase 2 COMPLETE; A51 device gate PASSED. Phase 3 remains planned.**

The newer hardware run executed the fixed minimal arithmetic payload, retrieved its record and restored baseline Android. The earlier P2-023 incomplete decision remains correct for the old skipped-payload run. Current state now selects the newer successful run, rather than reinterpreting the failed evidence.

## Gate and evidence

The [roadmap pass gate](ROADMAP.md) requires the loader to execute a minimal payload on the A51, produce retrievable evidence and demonstrate return to Android/recovery. Compilation alone does not satisfy it. The external assessment roadmap still contains its earlier in-progress status paragraph; use this review and STATE.md for current completion status.

| Gate requirement | Verified latest result |
|---|---|
| Minimal payload execution on the A51 | `status=1`, reason 0, marker `0x3143455845494b48`, arithmetic value `0x68000000019526d5` |
| Retrievable evidence | Full candidate dmesg plus five record field lines, matching the original timed hardware log |
| Demonstrated return | Android continuation, baseline boot-partition restoration/readback, subsequent reboot completion and root |
| Host/image validation | Five QEMU cases/228 checks, pinned isolated kernel, exact candidate reconstruction and matching tar member |

The hardware record reports EL1, incoming DAIF `0x2c0`, 26 MHz timer, Cortex-A53 MIDR `0x410fd034`, MMU/data cache off, and 64-byte cache lines. The independent XOR/rotate calculation matches the printed value. Source pins, kernel symbols and hardware PC displacements agree. All eight execution predicates in the retained completion review are true.

## Adaptation and successful run

The initial guard rejected Samsung's incoming `0x2c0` because it required all four DAIF masks (`0x3c0`). The adapted source requires IRQ/FIQ/Debug masks (`0x2c0`), temporarily masks SError with `msr daifset, #4`, and restores incoming DAIF with `msr daif, x6` before Linux continuation. It preserves NZCV as implemented in the pinned assembly. This successful hardware run observes the accepted incoming state; it does not test an actual SError exception.

The original timed run was 06:39:32–06:41:19 IST on 13 November. Candidate and baseline reconnects took 30.8 and 30.9 seconds. Candidate readback matched the experimental image, its boot ID changed, and after restoration the executed script required baseline readback, boot completion and `uid=0(root)`.

- Host/QEMU: `runs/20261113T004001253454Z-early-entry-host-tests/`, exit 0.
- Isolated build: `runs/20261113T004218150818Z-build-early-entry-kernel/`, exit 0.
- Packaging: `runs/20261113T010750141773Z-package-samsung-boot-candidate/`, exit 0.
- [Original hardware log](PUBLICATION.md), exit 0.
- [Hardware result](PUBLICATION.md).
- [Retained completion audit](PUBLICATION.md), `reviewed_complete`; run `20261113T012258446372Z-phase2-final-completion-review`, exit 0.
- [Independent recheck](PUBLICATION.md), `verified_complete`; run `20261113T013047142864Z-phase2-completion-recheck-independent`, exit 0.

## Independent integrity check and reproduction

The independent recheck verified all 35 indexed device/review/kernel files, the review's original input pins (using before copies for documents), current source/build/QEMU associations, original run exits, exact record correspondence, arithmetic and execution-state checks. Reconstructing the new candidate from the pinned baseline plus adapted Image reproduces every candidate byte while limiting changes to the four permitted boot-image regions. The tar's sole `boot.img` member matches that candidate. No image or phone experiment was repeated.

From `C:\Users\Ankit\Desktop\A51\hakios-a51`:

```powershell
python scripts/run.py --label phase2-completion-recheck-independent -- python scripts/recheck-phase2-completion.py
python scripts/run.py --label phase2-completion-recheck-current-status -- python scripts/recheck-phase2-completion.py --check-documentation
```

These commands only inspect retained files and write a new indexed host review packet. Exit 0 means the selected successful evidence and requested current-document checks pass. The legacy `verify-samsung-boot-candidate.py` is tied to the older candidate; use the independent checker for this new Image/candidate pair.

## History and limits

The old hardware packet `evidence/phase-2/device-execution/20261112T210658288194Z/` records `status=2`, reason 1 and zero payload value/marker. P2-023 correctly marked Phase 2 incomplete from that evidence. Its review packet at `evidence/phase-2/completion-review/20261113T001731211609Z/` remains unchanged, including audit source and original document copies. The unsupported literal pass flag in the old assembler remains historical.

P2-024 selects the newer successful evidence and reconciles README, STATE, INDEX, HANDOFF, device/review guides and state.json, while retaining immediate before copies under `evidence/phase-2/completion-reconciliation/20261113-p2-024/before/`. Older milestone state objects retain their capture scope; current authority is `phase_2_completion_review`, `phase_2_device_execution_validation` and the top-level gate.

This gate proves a fixed payload in an experimental Linux Image and its normal Android/rollback path. Standalone XNU, no-flash launch, actual fault/reset handling, persistent fault evidence, general payload memory ownership and sustained Android stability remain unverified. Hardware evidence consists of printed fields rather than a raw 256-byte dump. Temporary staging cleanup was issued but not independently verified. The build reused copied incremental outputs; this check does not claim a clean rebuild. QEMU's five cases do not include a successful incoming `DAIF=0x2c0` case, although the A51 run does. The assembly's old “No MSR” comment is stale and has been left untouched to preserve source/build hashes.

The status recheck performed no phone query, write, reboot or flash. No Phase 3 implementation was started.
