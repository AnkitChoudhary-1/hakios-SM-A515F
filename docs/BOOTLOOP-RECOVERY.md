> Publication note: this is a historical workspace document. Current completion decisions are in [PUBLIC-STATUS.md](PUBLIC-STATUS.md); raw local evidence is described in [PUBLICATION.md](PUBLICATION.md).

# Android boot-loop incident and reversible recovery

Date: 12 November 2026, Asia/Calcutta. Device: Samsung Galaxy A51
SM-A515F, serial `A51_SERIAL_HERE`.

## Current post-reset KernelSU restoration: passed

The user confirmed a factory reset/data wipe only, enabled USB debugging and
authorized ADB. The recorded inventory identifies SM-A515F and the surviving
`4.14.357-Everline-KSUN-A51` kernel. Android reports release 16, SDK 36 and build
`BP4A.251205.006`; its reported fingerprint still names Samsung Android 13, so
that property alone does not establish the exact custom-ROM release label.
Both KernelSU managers were initially absent.

Installed `kernel-work/artifacts/KernelSU-Next-v3.0.0.apk` (SHA-256
`3390c3e6511b31923637dc32587d5c63b3c7cfa50c7de05eb297d1703a7b749f`). Its verified
certificate matches the retained KernelSU-Next default
`79e590113c4c4c0c222978e413a5faa801666957b1212a328e46c00c69821bf7`.
The manager displays Working/LEGACY, v3.0.0 (32857), kernel Unknown (32942),
hook mode Unknown and zero modules. Successful `su -c id`, including after
reboot, is the effective root evidence; the unknown UI fields remain recorded.

The rooted partition reads match the retained images:

| Partition | Installed SHA-256 |
|---|---|
| boot | `eb30609a62999e3282ac81e0a5e56411ef12ec1a39c107171bf3e01209c7cb67` |
| recovery | `12412e2008d950260cda627ac7a6b8eac954b49ef9db5573a297f67e4fc85999` |
| dtbo | `41662c61ff3158448935025477a4e29d445823dab2cddafb18ea649c8ea925d6` |

The installed boot matches the saved KernelSU boot image; no flashing was
necessary. Root returned `uid=0(root) ... context=u:r:su:s0`. SELinux was
Enforcing and kernel taint was 0. Both `/data/adb/modules` and
`/data/adb/modules_update` were absent before and after reboot.

Run `20261112T152001082721Z-android-reroot-reboot-stability` passed one controlled
reboot and 18 polls over 181.25 seconds. New boot ID
`05f4e2c3-3fcd-4ad1-aaf7-23144d33b8a4` stayed constant; uptime increased from
24.82 to 204.83 seconds. All observation polls reported Android boot completed
and root available. No unexpected reset occurred. The phone ended in Android;
no recovery return was needed. This is a bounded check, not a long-term
stability claim or identification of the historical panic's exact cause.

Installation run: `20261112T150342545100Z-android-reroot-install-next-manager`.
Root/partition/module inventory:
`20261112T151912658075Z-android-reroot-root-and-module-inventory`.
The restoration changed manager app/data and removed its temporary UI XML,
then rebooted Android. No partition image, further data wipe, application-patch
module or HakiOS candidate was installed. The old flash helper was not run.
Phase 2 host code work resumes; its device execution and return gates stay false.

Rollback for the manager installation is uninstalling `com.rifsxd.ksunext`
through Android; that removes manager access while retaining the existing
KernelSU kernel. Keep the retained Android artifacts and logs. The module
disable-marker instructions below apply to the historical pre-reset incident;
those module directories do not currently exist.

## Historical outcome before the reported reset

The phone ended in TWRP after a bounded Android test. Two existing
KernelSU application-patch modules were disabled with reversible zero-byte
`disable` markers. A subsequent Android boot retained one boot ID from uptime
14.10 seconds through 194.25 seconds, completed Android startup, produced 52
successful state polls, retained both disable markers in every poll and showed
no spontaneous reset. The host then returned the phone to TWRP.

No boot, recovery, DTBO or other partition was written. Nothing was wiped. The
P2-018/P2-019 HakiOS candidate was not flashed or executed and must remain
unflashed while the Android baseline has only this bounded stability result.
Final read-only handoff run
`20261112T025314766767Z-phase2-bootloop-final-adb-recovery-readback` reported TWRP
`3.7.1_12-Galaxieo`, confirming that the phone still ended in recovery.

## Observed failure and corrected interpretation

Android had reached the UI but reset again after roughly 5–10 seconds. Two
spontaneous reset cycles were retained. The second retained Samsung record says
`RESET CAUSE - TIMA_RKP_VMM_PANIC` in
`evidence/phase-2/bootloop-crash/20261112T020120887081Z/last_kmsg` (2,097,152
bytes, SHA-256
`9cd96570dfe457c8d687641511fa24601f49d58deee19f3e1130579071768ce8`).
This identifies a Samsung TIMA/RKP EL2-hypervisor panic class. It does not
identify the exact triggering process, module or kernel defect.

The incident is not evidence of an F2FS, `/data` or `vold` failure. Android
mounted encrypted `/data`; the earlier observed `vold` termination coincided
with the deliberate host request to reboot back into recovery. It is also not
evidence that the unflashed HakiOS image ran or caused the reset.

Privacy: `pmsg-ramoops-0` in the crash folder contains account email addresses.
Retain it locally as evidence, but do not quote or publish it.

## Bounded inventory before mutation

Run `20261112T022244252722Z-phase2-bootloop-bounded-android-inventory` booted
Android only long enough to obtain root state and then returned to TWRP. Its
selected report is
`evidence/phase-2/bootloop-live/20261112T022244604836Z/report.json` (SHA-256
`e16e1fb0e7f4a3df9378daaee13ad1ec87acb9786547c12e9142a570f9a7b0fa`).
It found two enabled KernelSU modules and no disable/remove markers:

- `music-morphe-jhc-arm64`, Music Morphe v9.30.53.
- `youtube-morphe-jhc`, YouTube Morphe v21.30.216. Its metadata reported an
  installed/module version mismatch.

KernelSU root grants for `com.android.shell` and `com.franco.kernel` were also
observed. `/proc/modules` was empty. These are observations, not proof that any
one item caused the TIMA/RKP panic.

## Reversible isolation

`scripts/capture-bootloop-window.py` starts only when TWRP is detected. With
`--disable-modules`, it reboots into a bounded Android window, creates a
`disable` marker for each enabled KernelSU module before collecting the longer
inventory, calls `sync`, verifies that no module remains active and immediately
requests recovery.

Run `20261112T022714562314Z-phase2-bootloop-disable-modules` passed. Selected
report:
`evidence/phase-2/bootloop-live/20261112T022714879077Z/report.json`, 6,054
bytes, SHA-256
`df282528e9810f0cdbf4177ec7dc4486e5574989f71edf501dd2ccbd135f113b`.
It created and verified:

- `/data/adb/modules/music-morphe-jhc-arm64/disable`
- `/data/adb/modules/youtube-morphe-jhc/disable`

The report recorded `MODULE_DISABLE_COUNT 2`, `MODULE_ACTIVE_COUNT 0`, no
partition writes and a successful return to TWRP. The data change is limited to
those two reversible markers.

## Stability validation

`scripts/capture-android-stability.py` starts only in TWRP. It follows
`logcat -b all`, captures rooted `dmesg` at the beginning and end, polls boot
ID, uptime, boot/power properties and module markers, and requests recovery only
after the observation window or after detecting an unexpected reset.

Run `20261112T023112401618Z-phase2-bootloop-post-module-stability` passed.
Selected report:
`evidence/phase-2/bootloop-stability/20261112T023112668665Z/report.json`, 86,391
bytes, SHA-256
`c7123590b9a5e8eaf1cdfbe11758660b9fddbadd75d3f0ff8981c7f524064086`.
The evidence records:

- one boot ID, `97fb1b61-ca83-4250-9a4c-7a3758b2c934`;
- uptime increasing from 14.10 to 194.25 seconds;
- 52 successful polls across the requested 180-second window;
- both modules disabled in all 52 polls and zero active-module observations;
- Android `sys.boot_completed=1` by the final poll;
- continuous logcat remaining connected until the host ended the observation;
- rooted start/end dmesg captures;
- no `TIMA_RKP_VMM_PANIC`, kernel-panic, watchdog-bite, kernel-oops or hard-lockup
  signature in the current boot's selected searches; and
- a successful host-requested return to TWRP after the observation.

The all-buffer logcat is retained for local diagnosis and may contain personal
application data. Do not quote it publicly.

## What this does and does not establish

The simultaneous module isolation correlates with a stable three-minute boot.
It does not prove which module, if either, was the exact cause. A longer normal
use session has not yet been observed, and Franco Kernel Manager's root grant
has not been isolated because the first reversible step stabilized the bounded
test.

This incident work validates only the existing Android baseline and its return
to recovery. It does not validate Samsung acceptance of the HakiOS candidate,
standalone payload entry, owned physical handoff, persistent payload fault
logging, exception recovery or return from a new payload. The Phase 2 device
gate therefore remains false.

## Recovery and rollback

Keep both disable markers in place while diagnosing the baseline. KernelSU can
re-enable a module by deleting its corresponding `disable` marker, but doing so
may restore the boot loop. Re-enable only one item at a time during a separately
bounded test if exact causality is needed. If Android instability returns with
both markers present, the next reversible isolation target is Franco Kernel
Manager; restoring `everline-ksu/backups/a51-pixelos-original-boot.img` requires
an explicit user decision because it writes the boot partition.

The capture helpers and documentation can be rolled back by removing their
project-owned files, but retain the incident evidence and run logs. Removing a
disable marker is the device-state rollback; no partition-image rollback was
performed or is currently required.

