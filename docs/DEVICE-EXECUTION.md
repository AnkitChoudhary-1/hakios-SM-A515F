> Publication note: this is a historical workspace document. Current completion decisions are in [PUBLIC-STATUS.md](PUBLIC-STATUS.md); raw local evidence is described in [PUBLICATION.md](PUBLICATION.md).

# Phase 2 A51 hardware execution and baseline return

**Status: Phase 2 COMPLETE; device gate PASSED.** Latest execution: 13 November 2026, 06:39:32–06:41:19 IST. Target: Samsung Galaxy A51 SM-A515F / Exynos 9611.

The latest candidate ran the fixed arithmetic payload before Linux boot at EL1 with MMU and data cache disabled. A temporary `early_probe.ko` retrieved the record after Android started. The recorded candidate boot ID differs from baseline. The baseline KernelSU boot partition was then restored, its SHA-256 read back, Android reboot completed and root was verified.

## Latest hardware record

```text
HAKIOS_V1 magic=31454c5241494b48 ver=1 bytes=256 status=1 reason=0
HAKIOS_V1 x0=000000008a100000 x1=0000000080000000 x2=0000000000278000 x3=0000000080278000
HAKIOS_V1 el=1 entry_pc=0000000081628000 payload_pc=000000008108f3f0 continue_pc=0000000081628004 sp=00000000c920fb30
HAKIOS_V1 daif=00000000000002c0 cntfrq=26000000 midr=00000000410fd034 sctlr=0000000030c5083a ctr=0000000084448004 line=64
HAKIOS_V1 payload_val=68000000019526d5 payload_marker=3143455845494b48 lr=00000000c9005368 nzcv=0000000060000000
```

`status=1` is `HKE_EXECUTED`; reason 0 is `HKE_REASON_NONE`. The marker is `HKEXEC1`. Independently computing `(x0 ^ x1 ^ x2 ^ x3 ^ cntfrq ^ midr) ror 7` gives `0x68000000019526d5`, exactly matching the record. The printed physical PC displacements match the linked kernel symbols.

The adapter accepts incoming `(DAIF & 0x2c0) == 0x2c0`, sets the SError mask with `msr daifset, #4` during the payload, and restores incoming DAIF with `msr daif, x6` before Linux continuation. QEMU passed five cases/228 checks with the pinned adapted source. These cases do not provide an executed A51-like `DAIF=0x2c0` host case; the hardware run supplies that successful-state observation.

## Evidence and image pins

- [Original execution and restoration log](PUBLICATION.md), exit 0.
- [Latest device result](PUBLICATION.md), indexed together with full candidate dmesg and the field excerpt.
- [Current completion review](PHASE-2-COMPLETION-REVIEW.md).
- Kernel Image SHA-256: `3054cfe40d06c17963575d6e067ced0c38f8e532bb490e49f828ae66b0e5c420` (36,334,080 bytes).
- Candidate SHA-256: `2cb8e6d443fce3d8196c2f0a25fb608dbe9e692c572b64d5f0df623584dcdf1a` (61,865,984 bytes).
- Odin tar SHA-256: `854fbb633033deb2f4c0492ed1790c703093beca91684eb1b9265a8100d09e8d`; its sole `boot.img` member equals the candidate.
- Restored baseline SHA-256: `eb30609a62999e3282ac81e0a5e56411ef12ec1a39c107171bf3e01209c7cb67`.

Candidate reconnect took 30.8 seconds; baseline reconnect took 30.9 seconds. The executed script also checked the baseline partition hash after the final reboot. The candidate is a retained artifact and is no longer installed in the boot partition.

## Earlier failed attempt

The original generated packet `evidence/phase-2/device-execution/20261112T210658288194Z/` records `status=2`, reason 1, zero marker/value and incoming `DAIF=0x2c0`. The original guard required `0x3c0`, so it skipped the arithmetic payload. P2-023 correctly rejected that packet's literal pass claim. Its evidence and original documentation remain retained unchanged; the newer successful execution supplies the current pass evidence.

## Limits and return procedure

The demonstrated procedure installs the isolated experimental Linux boot image, starts Android, retrieves the early record, restores the pinned baseline boot image and reboots into Android with root and matching readback. It includes boot-partition writes. It does not establish no-flash launch or standalone XNU.

Actual SError handling, an independent device fault/reset path and persistent fault logs remain unverified. The record was retrieved as printed fields, not a complete raw 256-byte dump. Baseline boot/root/readback were verified; this run contains no sustained stability test. The staging cleanup command was issued without checking its return code or file absence. The printed source header's old “No MSR” comment is stale; the pinned instructions explicitly write DAIF and NZCV.

This status recheck used retained host files only and performed no device operation. Phase 3 remains planned.
