# A51 Wi-Fi firmware recovery candidate — 23 November 2026

Status: installed and device-tested; **Wi-Fi remains unstable**. Installed from TWRP on 23 November at 01:03:16 UTC (06:33:16 IST). Recovery-partition read-back verified SHA-256 `c5be9c8bf3ba9ec2000ecb551b04d668c40a5e553a1add83d53ceb21ab4a8150`. The guarded installer verified backups and live phone checks, then wrote only the recovery image. Installation evidence is `last-device-check.json`; preparation manifests retain their historical no-write flags. This candidate changes only the kernel and preparation epoch relative to the current `full-quality-recovery` package. Loader, UEFI, DTB, APFS userland, app files and all other boot settings are byte-identical to that parent. It does not change resolution, blur, animations, audio or charging.

Host-verified follow-up: `wifi-ordering-recovery`; see `A51-WiFi-ordering-recovery.md`. It corrects missing compiler memory barriers and adds bounded live panic/stack records. It is not installed or proven to resolve the recurrent panics. The current iOS run has been left active.

## Sustained device result — 23 November 2026

Capture: `wifi-stability-recovery/device-tests/20261123T011048-027970Z`. iOS began around 01:06:16 UTC. The owner confirmed Safari worked initially; Instagram still displayed the loading circle after “Do not save account info.” The 900-second host collector completed without requesting a stop or reboot. The owner subsequently reported disconnection from the unchanged hotspot.

| Kernel timeline | Observed event | TX / RX before failure | Evidence |
| --- | --- | --- | --- |
| 753 s | Validated firmware panic, restart 1; sequencer reset confirmed `0x80` | 18213 / 34134 | `snapshot-009.txt`, lines 11588 and 11591 |
| 910 s | Validated firmware panic, restart 2; reset confirmed | 18330 / 34276 | `snapshot-013.txt`, lines 10125 and 10128 |
| 997 s | Validated firmware panic, restart 3; reset confirmed | 18432 / 34345 | `snapshot-015.txt`, lines 9724 and 9727 |
| 1095 s | Fourth validated firmware panic; three-restart limit exhausted | 18535 / 34416 | `snapshot-017.txt`, lines 9200 and 9201 |

RX progressed after the first three resets (34274 at 880 s, 34345 at 983 s, 34416 at 1074 s). This establishes successful hardware resets and resumed packet traffic, but not durable internet or successful completion of Instagram feed requests. Final DHCP state has `joined=0`, no address/router/DNS. The wifid “SystemSleep” label alone does not explain the independently captured firmware crashes.

An early assessment missed the resets by looking only at periodic counter lines; the full-log assessment above supersedes it. Logs contain NUL bytes: search with `rg -a` or decode bytes explicitly, and examine recovery events as well as counters. Overlapping snapshots repeat events and must be deduplicated. Complete panic dump contents have not yet been recovered from these live logs, so the current fault ID must not be assumed to equal an earlier capture. The next work is to identify the recurrent fault and retain its full record through an observable diagnostic path. Raising the restart limit alone is not a stability fix.

## Evidence and scope

The 22 November investigation found a nonzero firmware panic record, frozen firmware queue/receive counters, and accumulating transmit buffers while DHCP remained configured. See `A51-WiFi-stability-investigation.md` for that evidence. The new 23 November capture reproduces this condition: at 390/450/510/570 seconds RX remains 24,075, busy data buffers rise 17/24/28/31, and the firmware queue vector remains `04 50 53 32 a8 9d`. Panic words are again `b50ff/25002a02`. The initial connection and much larger packet totals indicate that networking worked earlier in this boot. The exact panic cause remains undecoded.

New captures: `instagram-investigation/20261123T005333-post-login` and `instagram-investigation/20261123T005613-reopened`. Instagram is alive on a white loading-circle screen and logs a network request timeout after reopening. This establishes a network failure during the app's hang, not proof that Wi-Fi is its only remaining problem.

Local source defects addressed here: the long-running Wi-Fi service did not consume configured management/debug/log streams; panic records only produced logging; logical power toggles did not reset failed firmware; receive-buffer returns could overwrite a full return ring. Management-stream read/write indices also shared a noncoherent cache line. These findings support transport hardening and bounded recovery, but do not identify the firmware panic ID.

## Implementation

- Consume configured to-host management, R4/M4 debug and binary log rings, acknowledge interrupts, and retain a small log tail for a failure dump. Seven management/debug/log stream index pairs now occupy separate 64-byte cache lines referenced through `mxconf`.
- Validate Samsung version-2 panic records with length, bounds and XOR checksum before recovery. Also detect outstanding HIP queues with no firmware index progress for 15 seconds; idle/no incoming traffic alone does not trigger a restart.
- Respect the HIP return-ring full condition and preserve unreturned descriptors. Limit per-poll receives so auxiliary servicing and failure checks get time.
- Gate sends and pool reclamation under the producer lock; stop the station worker and drain active operations/state readers before shared-memory reuse. Keep the requested network, pending join/leave and Wi-Fi power state. Explicit leave/power-off/newer joins take precedence; a failed join's existing fallback becomes the reconnect target.
- Publish link-down, retain panic/log diagnostics, then apply Samsung Exynos9610's case-2 PMU reset sequence. Rebuild and reuse firmware memory only after sequencer status `0x80` confirms reset. A reset timeout retains memory and leaves the radio unavailable.
- Reload checked firmware, rebuild HIP/mxconf, restart and rejoin through the existing station path. Do not re-read `wifi.conf` on every restart. Existing link/DHCP handling reacts to the down/up events. Cap recovery at three restarts per boot, with 5/10/15-second delays. Exhaustion is logged and requires reboot; it does not loop indefinitely.

Canonical source: `devices/a51/drivers/wifi/hakios.a51wifi.c`, `drivers/wifi/hakios.sta.c`, `xnu/files/bsd/sys/hakios.sta.h`. Active XNU copies match. Before/after source snapshots, hashes and the scoped patch are in `wifi-stability-recovery/`. Existing unrelated checkout changes were preserved.

Reference: Samsung `drivers/misc/samsung/scsc/platform_mif_9610.c`, `mif_reg_S5E9610.h`, `fw_panic_record.c`, `mxman.c`, and wireless `hip4.c` under `/opt/a51/src`.

## Verification and artifacts

`test-a51-wifi-recovery.py` passed actual extracted driver functions and the actual station source under Clang AddressSanitizer/UndefinedBehaviorSanitizer. Cases cover queue wrap/full preservation, firmware freeing a slot, pending-queue timeout versus idle/progress, panic checksum/bounds, auxiliary wrap/invalid indices, reset register order/timeout, network/power/request preservation and real pthread quiescence waits. These fixtures cannot establish electrical behavior, firmware compatibility with the new index layout, on-device cache ordering, reconnection or internet stability.

The latest kernel linked successfully. The final incremental log explicitly recompiles the station source; the preceding build compiled the Wi-Fi driver. The project's existing unsupported kext symbol-set checks still return make status 2, which `tools/make-kernel.sh` accepts only after a successful kernel build. No new C compile/link error was accepted. Final canonical/active source hashes and the linked output were checked.

`package-a51-wifi-recovery.py` preserves the parent's Android recovery header and every non-kernel component. Only the embedded XNU payload kernel/epoch, enclosing length and Android boot-image ID change. `verify-a51-wifi-recovery.py` independently verifies component and payload comparisons, source/test provenance, Android v2 header/body/ID, recovery capacity, Odin recovery-only member/checksum and the saved Android rollback. The conservative boot line occupies 590/607 bytes. `loader_return_after=0` remains in effect: host log collection can end without stopping iOS.

| Artifact | SHA-256 |
| --- | --- |
| Kernel | `1132aa9bfab298ab698cbeda562d527787e4604ac5fda79740327525b6e58b07` |
| Diagnostic recovery image | `c5be9c8bf3ba9ec2000ecb551b04d668c40a5e553a1add83d53ceb21ab4a8150` |
| Diagnostic Odin archive | `32ac889693247afa5cc41ca8bc3efbc8fa31edfcab41a3bf3e6138148aaeb920` |
| Saved Android recovery image | `12412e2008d950260cda627ac7a6b8eac954b49ef9db5573a297f67e4fc85999` |

Recovery image size: 29,671,424 bytes, within the verified 71,106,560-byte recovery partition. Candidate folder: `outputs/wifi-stability-recovery`. Manifest/static-verification/host-tests/source-changes records distinguish host preparation from device installation and testing.

## Reproduction

Do not rerun the one-time implementation script. The final scoped patch is `wifi-stability-recovery/wifi-recovery.patch`; `source-after/` contains exact final source copies. In WSL, sync `xnu/files/bsd/sys/hakios.sta.h` to `xnu-src/xnu-8796.121.2/bsd/sys/hakios.sta.h`, then run `tools/make-kernel.sh -j8` in the repo. The build helper syncs the two driver sources. Run the host fault-injection tests under WSL, then the component-preserving packager. Run the independent verifier on Windows or WSL after recording source hashes. Repackaging regenerates the epoch and therefore changes payload/image/archive hashes.

## Device test and Android return

Device testing must verify initial join, a private DHCP IP/router/DNS, repeated Safari HTTPS access and sustained traffic beyond the observed 6–15-minute stalls. If firmware fails, verify a captured failure, confirmed reset, rejoin, resumed RX counters and successful web traffic. Check Wi-Fi off/on and selected-network behavior. Recovery may briefly disconnect active connections; host fixture success is not a claim of stable internet. Preserve iOS app/login data and test Instagram again after networking is known to work.

Return to Android via Odin at `D:\Odin3_v3.14.4\Odin3_v3.14.4\Odin3_v3.14.4.exe`, AP only `C:\Users\Ankit\Documents\Codex\2026-11-21\hi-2\outputs\restore-current-recovery-RZ8N2032ZXE.tar.md5`. BL/CP/CSC empty, Re-Partition OFF, no PIT, Auto Reboot ON; if recovery opens, Reboot → System without wiping. This manual transition is necessary because ADB is unavailable during iOS. Once Android is connected, use the existing guarded recovery-only installer with the candidate package directory; never reinstall the system or overwrite app data for this change.
