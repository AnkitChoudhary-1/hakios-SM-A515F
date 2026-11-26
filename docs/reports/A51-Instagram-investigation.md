# Instagram 418.2.0 investigation — 22 November 2026

Performance, audio and charging work are paused. This investigation inspected host files and collected existing phone logs/screenshots. It did not alter the port, install an app, flash a partition, reboot or stop iOS. The host inspection script and these records are new documentation artifacts.

## Reported behavior

The user reports that an earlier build reached Instagram login, then crashed after selecting “Don't save info”. In the current build it stays on the Instagram logo. The user closed and reopened Instagram for the latest collection.

## IPA and staged application

- File: `D:\com.burbn.instagram-418.2.0-Decrypted.ipa`, 281,777,870 bytes.
- SHA-256: `28577f6827a2978aba118fb2a99bf56ea9436001cf4c7829cf301fb0ac1ca39b`.
- Bundle: `com.burbn.instagram`, version 418.2.0, build 893787717.
- Main executable: ARM64, Mach-O minimum iOS 16.3, SDK 26.2, encryption flag `cryptid=0`.
- The five embedded frameworks are ARM64, have `cryptid=0`, and declare minimum versions no later than 16.3.
- The main executable in the local `outputs/apps/instagram.apfs` is byte-identical to the IPA executable: SHA-256 `2edf2c80421805a477b92d6dd599c8a9fb37ebd1fa09be29a77798e27e956667`. Its staged Info.plist also identifies 418.2.0. This verifies the local staged image, not an independently read-back copy from the running phone.
- Two optional camera extensions require iOS 18.0. The lock-screen camera extension under `Extensions/` remains marked encrypted (`cryptid=1`). These extensions are not iOS 16.5 candidates; their presence alone does not explain a hang in the main app.

iOS 16.5 meets the main app's declared OS minimum. A newer SDK alone is not proof of incompatibility. Encryption flags and headers do not establish package integrity, successful entitlement handling, or availability of every runtime API.

## Runtime evidence

Collection: `full-quality-recovery/boot-tests/20261122T145258-498568Z`, after the user replied “opened”. Commands were limited to loader status, log export and screenshot export. The collector ended with `running 0 0`; no stop/reboot command was sent. Its freshly prepared host payload was not staged and does not prove which package booted.

- The screenshot captures Instagram's launch logo.
- At 14:52:42 UTC, the previous Instagram process, PID 215, was terminated with `0x8BADF00D`: “failed to terminate gracefully after 5.0s”. This followed the user's manual close; it is not evidence of a five-second startup watchdog deadline.
- A new Instagram process, PID 426, launched immediately afterward. CPU samples show 7% and then 40%; they do not identify the blocked thread or prove a busy loop.
- The capture does not contain Instagram's intended injected startup, signal-stack or uncaught-exception messages.
- An earlier saved `current_live_log.txt` records Instagram PIDs 177 and 250 exiting due to SIGTRAP. Those lines confirm earlier crashes, but do not identify the failing instruction or establish which user action caused them.
- Current DHCP logs show `172.28.223.196`, router `172.28.223.8` and populated DNS. The earlier link-local address is not present in these selected current samples. This does not verify Instagram server access or rule out a network-related wait.

Running kernel log identifies `2.3.4-hakios-darwin22.5-exynos9611-gae617cf3-dirty`. Do not substitute earlier performance candidates or their conclusions for this session.

## Confirmed diagnostic defect in local packaged userland

`userland/src/inject_app.c` has `__attribute__((constructor))` before a typedef and exception-handler declarations rather than attached to `hakios_app_init`.

Inspection of both the local build and the library extracted from the current local package confirms:

- `libhakios.app.dylib` is 66,304 bytes; SHA-256 `e78c9fc9fc30a1488d1c964e762b8223742e4a5181374fb87d6a67abf0458a6a`.
- There is no `__mod_init_func` or `__init_offsets` section, and no compiled `hakios_app_init` or uncaught-handler symbol. LLVM independently confirms the missing initializer sections.
- The compiled library retains its `posix_spawn` interpose. Its intended startup-driven signal, exception and Objective-C method tracing is absent.
- The running log declares injection of `/redwood/lib/libhakios.app.dylib` into Sileo and Instagram, and lists the same library size. Its running bytes have not been independently hashed.

This explains missing intended tracing in the inspected package. It does not prove the cause of Instagram's hang or earlier SIGTRAP.

## Metal hypothesis checked against artifacts

The modified `HakiosMetalCA.m` source explicitly permits Instagram to see an experimental device. However, the current local packaged Metal binary is the other plugin built from `HakiosMetal.m`, not that CA implementation. Its SHA-256 is `534d23d19f2c8b2ffcb189a43b95aaeb45ee011488a0adaab0dcde4652018251`, size 90,536 bytes. This matches the local build; the running log lists that size.

The packaged binary lacks the CA-specific Instagram allowlist and `metal_all=1` strings. The bundle has no `HakiosMetal.clients` file. The other plugin normally gates exposure using `metal=` and a clients file; the captured boot arguments do not include `metal=`. No Instagram Metal-device initialization was observed. The CA source edit therefore cannot be presented as an established cause of this running failure.

## Next diagnostic work, not applied

1. Correctly attach the diagnostic initializer and verify the rebuilt Mach-O actually registers it, before another device test.
2. Preserve the IPA, app data and login state. Reproduce startup with working stderr/exception tracing; collect a thread sample if the app hangs without an exception.
3. Verify the running app's installation path, writable data container, app groups/keychain behavior, network requests and any Metal calls using that evidence. Compare with the earlier build under the same app/data conditions.
4. Apply only the fix supported by a failing stack, exception or resource error. No evidence currently justifies deleting app data, stripping extensions, changing graphics, or claiming Instagram is fixed.

## Saved artifacts

- `instagram-investigation/ipa-inspection.json`: binary headers, dependencies, encryption flags, entitlements and hashes.
- `instagram-investigation/current-app-hook.json` and `current-metal-hook.json`: local compiled library inspection.
- `instagram-investigation/staged-artifacts.json`: local APFS app/package file hashes.
- `instagram-investigation/runtime-evidence.json`: selected runtime lines with source line numbers/hashes; URLs redacted.
- `instagram-investigation/packaged-libhakios.app.dylib` and `packaged-HakiosMetal`: host copies extracted for inspection; originals preserved.
- `scripts/inspect-instagram-ipa.py`: host-only IPA/Mach-O inspector. It does not execute app binaries or modify the IPA.

The startup hang remains unresolved. No phone or port changes were made in this investigation.

## Follow-up log check — 22 November 2026, 15:18 UTC (20:48 IST)

At the user's request, collected current logs into `full-quality-recovery/boot-tests/20261122T151849-216136Z`. The collection completed with loader result `running 0 0`, with no stop, flash, installation or reboot commands. No port changes were made by this investigation.

This is a later boot session: its launchd initialization timestamps start at approximately 15:16 UTC. Earlier statements about absent startup tracing apply to the previously inspected package/session, not this newer runtime.

- Instagram PID 179 was spawned at 15:17:04 UTC.
- At 15:17:16, it logged `hakios: Instagram: started as uid 501 (effective 501), watching for what kills it`. Diagnostic startup tracing is now active.
- At 15:17:17.818–17.825, Instagram logged five `OSStatus error: [-34018] Security error has occurred.` messages. In `log-001.txt`, the first occurs at line 11412.
- `-34018` is `errSecMissingEntitlement`, a missing-entitlement error commonly returned by Keychain operations. The port's existing `userland/src/keychain_test.c` also documents this code. These log messages do not specify the exact SecItem operation, access group or denied entitlement.
- CPU samples include Instagram at 7% and 41%. No new Instagram signal stack, uncaught exception, missing-library error or missing-symbol error was observed in this capture.

App signing, `application-identifier`, `keychain-access-groups` and the port's entitlement handling are now the leading area to investigate. Compare the entitlements available to the running process with its actual Keychain requests and capture the thread that remains blocked. Do not conclude that every Keychain error causes a hang, grant permissions globally, bypass Keychain isolation, delete login data, or claim the problem is fixed based on these five messages alone. Metal remains unproven as a cause.

Selected lines and the source log hash are preserved in `instagram-investigation/runtime-evidence-20261122T151849Z.json`.

## Solution assessment — follow-up source inspection, 22 November 2026

The inspected IPA already contains application-identifier and keychain-access-groups entitlements. Their presence in the file does not establish that Security.framework sees them on the running process. The team identifier and App ID prefix differ in this IPA; that difference alone is not proof of a defect, because legacy App ID prefixes can differ from team identifiers.

The current local port source includes xnu/files/libkern/amfi/miniamfi_entitlements.cpp, which obtains a process entitlement blob through cs_entitlements_blob_get and parses it for entitlement queries. This identifies another point to check, but does not prove the current running kernel has that implementation or that it is failing. userland/build.sh signs its standalone Keychain test with ldid when available; this is not evidence that Instagram was re-signed or lost its entitlements.

A targeted solution requires comparing the running process's effective application identifier and Keychain access groups with the access group used by the failing SecItem request. If installation/signing dropped or altered the required entitlements, correct that app's signing/install path. If the signed blob is correct but the port fails to expose it to Security.framework/securityd, correct that entitlement delivery path. Preserve existing app data and Keychain isolation. Confirm successful Keychain operations and reproduce launch/login before claiming this resolves the logo hang. If the hang remains, obtain a thread sample to identify the actual blocking call. No port or device changes were applied in this source inspection.

## Post-login loading-circle investigation — 23 November 2026

The latest report differs from the old logo hang: login completes, then selecting “Do not save account info” leaves a white loading-circle screen instead of the main feed. Read-only captures are `instagram-investigation/20261123T005333-post-login` and `instagram-investigation/20261123T005613-reopened`. Both have screenshots; the second followed the owner's reply “done” to the reopen/Safari request. That reply does not establish whether Safari loaded.

The first screenshot confirms the circle with the Home indicator, rather than Instagram's launch logo. At 390/450/510/570 seconds, Wi-Fi RX stays 24,075 and firmware indices are frozen while TX/busy buffers increase; the panic record is again `b50ff/25002a02`. DHCP still has IP/router/DNS, so a connected Wi-Fi icon is not evidence of usable internet.

After reopening, Instagram PID 339 runs, initiates URL session tasks and receives `NSURLErrorDomain Code=-1001`, “The request timed out”, while loading server configuration at 00:55:49 UTC (reopened.txt line 10541). Background task requests return IDs rather than remaining blocked in the captured calls. No new Instagram fatal signal or uncaught exception was observed. CPU samples alone do not identify its waiting thread.

This newer runtime also logs a persistent Keychain fallback. Several original SecItem calls return `-34018`, followed by successful fallback results for stored authentication/persistent-account items and updates. Thus the raw entitlement status is not the final result of all those calls and cannot alone establish the cause of this capture. The prior document's entitlement investigation remains a separate unresolved issue; the fallback is pre-existing in this session and was not introduced or altered by this work. Do not output its stored item data, grant app permissions globally, delete login data or assume its semantics match the native Keychain.

The demonstrated Wi-Fi failure is the first blocker to remove before assessing feed loading. The new kernel-only Wi-Fi candidate preserves the current userland/app bytes; see `A51-WiFi-firmware-recovery.md`. After a working sustained connection is verified, reopen Instagram and repeat the login/“Do not save” path if needed. If the circle remains with successful networking, capture completion/error evidence for feed requests and a thread sample; investigate app service/API/Keychain behavior from those results. Current captures do not prove Wi-Fi is the only cause or that Instagram is fixed. No Instagram installation, binary, app-data or phone change was made here.

## Wi-Fi candidate device follow-up — 23 November 2026

The kernel-only candidate was installed at 01:03:16 UTC. The owner confirmed Safari loaded initially, while Instagram still showed the post-login circle. This is evidence that the app hang can persist while at least one Safari request succeeds; it does not establish successful Instagram server/API responses. The subsequent sustained capture recorded three firmware panics with confirmed resets and resumed packet traffic, then a fourth panic exhausting recovery at kernel time 1095 seconds. The owner now reports hotspot disconnection. Networking remains an active blocker, and the app's independent completion/thread diagnosis is still required. No app/account data has been cleared or replaced. Original app hooks and Keychain fallback remain unchanged.

The next kernel-only candidate, `wifi-ordering-recovery`, is host-verified and awaits the owner's Android transition for installation. It corrects compiler ordering around shared Wi-Fi memory and adds bounded live panic/stack records; see `A51-WiFi-ordering-recovery.md`. Its effect on the radio crashes remains untested. This candidate changes no app/userland bytes and makes no claim that Instagram is fixed.
