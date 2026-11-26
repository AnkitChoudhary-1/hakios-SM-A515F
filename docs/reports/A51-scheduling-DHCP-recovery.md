# A51 scheduling and DHCP recovery candidate — 22 November 2026

The tested full-quality parent improved smoothness by the owner's report, but the owner estimates 20–25 FPS and requests 40–50 FPS. Its initial DHCP lease and web probes succeeded; after hours of use, iOS showed 169.254.136.237 with no router. This candidate targets CPU placement and persistent lease failure while preserving 1125×2436 rendering, scale 3, wallpaper, blur, animations, and iPhone X navigation. It does not implement Metal, audio or apps. Charging indication remains unresolved.

## Implementation

`fb_cpu=0` binds the single priority-92 display presenter to logical boot CPU 0, which is physical A73 core 4 in the verified `bootcpu=4` configuration. The thread yields once to apply the binding. Only boot CPU 0 is accepted; absent/other values retain normal scheduling. Each retained copy trace now records its beginning/end CPU. This is a scheduling experiment, not a guarantee of 40–50 FPS.

`gl_cpu=1 enable_skstb=1` asks only backboardd's GL-calling threads to bind to separate logical A73 CPU 1. backboardd runs as mobile, so the stock root-only binding sysctl cannot serve this caller. A DEVELOPMENT/DEBUG-only self-binding sysctl accepts only CPU 1 or unbinding, requires both boot gates, and cannot change another task's threads. It uses the existing checked scheduler helper and records thread ID, request, actual binding and result in the loader log. The stock sysctl and its guard remain intact. Default builds/boot settings do not enable the experiment. Concentrating compositor work on one core may hurt under contention; runtime evidence decides whether to retain it.

The fake-SMT `NO_SMT` policy was inspected and is not used as a claim of reliable big-core placement. GPU/CPU supported clock requests and existing verification/thermal guards are unchanged. The long parent run reached cumulative maxima 66/86/71°C and made three reductions/restorations, so additional clock increases are not part of this candidate.

An indefinite `net_test recover en0` process samples every ten seconds with an autorelease pool per iteration. It refreshes the existing configd DHCP service after 60 continuous seconds of a joined/up interface lacking usable IPv4 and router. A 120-second attempt cooldown includes failed notifications. Healthy IPv4, an existing router, non-link-local IPv6, manual/static configuration, absent DHCP service, unknown state and offline interfaces suppress the request and reset persistence. Apple80211 state is read from the driver, rather than trusting the Settings toggle. No extra DHCP service, disassociation, firmware reset or fixed IP is introduced.

Recovery notifies `State:/Network/Interface/en0/RefreshConfiguration` through `SCDynamicStoreNotifyValue`, matching Apple's `_SCNetworkInterfaceForceConfigurationRefresh` and bootp's `link_refresh` renewal handler. References: [configd SCNetworkInterface.c](https://github.com/apple-oss-distributions/configd/blob/main/SystemConfiguration.fproj/SCNetworkInterface.c), [bootp ipconfigd.c](https://github.com/apple-oss-distributions/bootp/blob/main/IPConfiguration.bproj/ipconfigd.c). A notification is a renewal request, not proof that the radio can exchange DHCP packets. Retained minute-level IP/router/DNS and radio phase/error/queue/drop/panic statistics support diagnosis if it fails.

The radio's existing event log is now also retained immediately, so an early full event-summary buffer cannot conceal a later disconnect. Busy block counts are read under the pool lock. A small root-only logging sysctl accepts bounded single-line diagnostics into the loader's retained ring. `waitaddr` no longer treats a 169.254 address as a usable IPv4 configuration.

Triple buffers, scaler math, texture reuse, GPU fences and rendering effects remain as in the tested parent. The unsettled-frame path needs a fuller buffer-ownership review before changing it. Hardware DPP1 scaling, GPU scaling into display-owned buffers and direct scanout remain unimplemented.

## Provenance and validation

Candidate: `outputs/full-quality-recovery`. Tested parent artifacts remain in `outputs/full-quality`. The new candidate contains exact parent source copies, their hashes, and copies of the parent's source/package/runtime manifests. `source-changes.json` records every candidate source hash, including the new shared DHCP policy header. The original recovery backup and Odin rollback archive remain unchanged.

Host tests passed: actual renderer/scaler/clock helpers under ASan/UBSan, 3,000 scaler rows, ARM64 general-register store checks, twelve clock guard policy cases, and actual DHCP policy cases for the reported link-local IP, initial private IP, persistence, cooldown, recovery, disconnect/down, manual/unknown state, IPv6 and existing routes. The actual restricted self-binding handler also passed boot-gate, wrong-core/request, read, bind/unbind and copy/scheduler failure cases with mocked sysctl/scheduler calls under ASan/UBSan. Kernel and userland compiled/linked; actual active XNU source copies match. The first kernel attempt caught a missing IOKit-exported declaration for `thread_bind`; a matching internal declaration fixed it, and the failed log is preserved. No new compile/link failure is accepted; the project's pre-existing kext symbol-set check exclusions still apply.

APFS checks read back every generated entry. Independent package verification passed component, payload, recovery image, Odin archive, firmware and rollback hashes. Both profiles keep `loader_return_after=0`; the boot line uses at most 590/607 bytes including conservative loader prefixes. Re-check the final manifest after any rebuild.

Final package verification completed on 22 November 2026 at 03:23:51 UTC. WSL build verification passed active source copies, explicit framebuffer compilation, kernel link, firmware and packaged artifacts. Windows verification passed all component/archive/rollback checks, host test provenance, full-quality geometry/effects and disabled timed return. Host-only traced RAM preparation is saved at `full-quality-recovery/boot-tests/20261122T032357-718150Z`; it issued no phone commands. The current verified diagnostic recovery is 29,605,888 bytes.

Final SHA-256 values:

| Artifact | SHA-256 |
| --- | --- |
| Kernel | `5c5a63cb7e214ff218ccb1b6157e0116105d10ff09459b5091cdbc1075cf5c55` |
| root.apfs | `e3d8ac89cba5e49b80c1c8c7a9cf32332f970d7d3657ea091572e3daa8abbc4e` |
| flashboot.apfs | `f3e4e7029d03b17e90122a83daa2144147b08f7b7a314ce5dfa14a017584a0d7` |
| Diagnostic recovery image | `4f5c0ed5f86c9c6bb3a29d576289ba930a11d2e7d80cffb59e8bf25a8be82e29` |
| Diagnostic Odin archive | `0ca2e8966962769e13a759eeee9f2915d5039e3fbd2635f33a61852c0dbef115` |
| Original recovery rollback archive | `b19b680469b04d82622c22e27f29e4ede226256418cceab1c1934740b84274e5` |

## Hardware test pending

Preparation issued no phone commands. After the owner returned to Android, the read-only device/backup check passed at 03:26:59 UTC on 22 November 2026. The guarded recovery-only install completed at 03:28:05 UTC (08:58 IST), writing 29,605,888 bytes with the matching diagnostic image SHA-256 above. Local backups, GPT, Android boot and the existing iOS system region were checked; recovery read-back passed. A single ADB reboot into fresh diagnostic recovery was then requested. CPU binding, performance and DHCP recovery are awaiting hardware assessment. Fresh RAM payload preparation retains full-quality arguments and manual return. A bounded host log collection never stops iOS.

Compare repeated Settings scrolling after warm-up, Home and top-right Control Center gestures, rendering artifacts and temperature. Check retained `tl: render` and `tl: display presenter` lines plus copy CPU IDs; binding failure means the requested placement did not apply. Copy completions or pending-buffer replacements are not distinct panel presentations and must not be reported as FPS. Owner smoothness feedback remains separate from instrumented measurements.

Confirm a private DHCP address, nonempty router and DNS, and Safari Apple Success over the unchanged open `OPPO K13 5G B93C` hotspot. An initial working connection does not prove recovery: observe beyond the original one-hour lease and retain renewal/failure lines. No disruptive forced outage or manual/static changes are required for a normal test.

## Reproduction and manual return

Do not rerun the one-time source mutation/fix scripts. Build the saved source with `build-a51-scheduling-recovery-kernel.sh` and `build-a51-scheduling-recovery.sh`. Set `A51_PROFILE=full-quality-recovery` for `test-a51-full-quality.py` and `verify-a51-full-quality-build.py`. Run `test-a51-net-recovery.py`, `test-a51-render-binding.py`, `test-a51-clock-guard.py` and `prepare_boot.py --profile full-quality-recovery`. The kernel helper recompiles the framebuffer explicitly so the final log proves compilation of that source as well as the kernel link. On Windows run `verify-a51-full-quality.py --profile full-quality-recovery`; then use the existing installer/diagnostic scripts with `--package-dir outputs/full-quality-recovery` and diagnostic `--trace-frames --manual-return`.

Return to Android with Odin `D:\Odin3_v3.14.4\Odin3_v3.14.4\Odin3_v3.14.4.exe`, AP only `C:\Users\Ankit\Documents\Codex\2026-11-21\hi-2\outputs\restore-current-recovery-RZ8N2032ZXE.tar.md5`. Leave BL/CP/CSC empty, Re-Partition OFF, no PIT, Auto Reboot ON. If recovery opens, choose Reboot → System without wiping. The manual return is necessary because ADB is unavailable during iOS and the new package requires a fresh boot.


## Later intermittent internet report — 22 November 2026

Read-only capture at wifi-investigation/20261122T152915-950361Z shows a nonzero Wi-Fi firmware panic record, stalled receive/firmware queue counters and accumulating transmit blocks while DHCP still has valid IP/router/DNS. This differs from the prior link-local lease failure and is not addressed by DHCP refresh alone. A later Wi-Fi toggle produced an unanswered DEL-VIF confirmation. See A51-WiFi-stability-investigation.md for source references, limitations and a targeted firmware/transport recovery direction. No changes were applied; iOS remained running.

## Firmware recovery successor — 23 November 2026

`wifi-stability-recovery` now contains a compiled, host-verified kernel recovery candidate. It preserves the actual current `full-quality-recovery` component bytes and every non-epoch boot setting. The hashes/profile descriptions earlier in this historical document must not be substituted for the newer manifests or evidence. See `A51-WiFi-firmware-recovery.md` for current hashes, tests, implementation and device-test status. The successor is not installed yet; current logs/screenshots were collected read-only.
