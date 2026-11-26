# Galaxy A51: successful iOS 16.5 first boot

On 21 November 2026, the Galaxy A51 SM-A515F (RZ8N2032ZXE, Exynos 9611) booted the experimental HakiOS port using the owner's iOS 16.5 / 20F66 IPSW. Captured frames independently show iOS Control Center and the Phone app keypad. The owner confirmed: **“Yes, home screen and touch worked.”** The home screen app-icon grid was not captured; its confirmation comes from direct on-device observation.

## Test outcome

The test ran from approximately **16:52:39 to 16:57:48 IST** (11:22:39–11:27:48 UTC). The boot recipe requested 300 seconds of kernel runtime. The host observed `returned 1441823 0` at approximately 307 seconds. The first numeric field is the returned kernel log length in bytes, not an error number. No kernel panic was found in the saved logs. Long-session stability has not been established.

The phone was left in the diagnostic loader after the timed return. No stop, reboot, or additional partition write was sent during collection. **This installation currently provides a five-minute test session; it does not automatically keep iOS running indefinitely.**

| Approximate elapsed time | Captured display | Evidence |
| --- | --- | --- |
| 0 s | Loader console, `usb: started` | [Initial frame](boot-tests/20261121T112239-072980Z/screen-000.png) |
| 61 s | Apple logo | [Boot logo](boot-tests/20261121T112239-072980Z/screen-004.png) |
| 123 s | iOS Control Center | [Control Center](boot-tests/20261121T112239-072980Z/screen-008.png) |
| 184 s | iOS Phone app keypad | [Phone keypad](boot-tests/20261121T112239-072980Z/screen-012.png) |
| 246 s | Expanded connectivity controls | [Connectivity panel](boot-tests/20261121T112239-072980Z/screen-016.png) |
| 307 s | Kernel returned to loader | [Command transcript](boot-tests/20261121T112239-072980Z/fastboot-transcript.txt) |

SpringBoard and backboardd launch successfully in the logs. Backboardd reports touch contacts and routes gestures to SpringBoard. The Phone app launch is also logged. A visible dialer is evidence of UI/app rendering; cellular calling was not tested and is unsupported in this configuration.

## Installed and retained

- Apple system region: 8,365,539,328 bytes written to the existing `darwin` partition; full read-back SHA-256 passed.
- Diagnostic recovery: 25,749,504 bytes written to `recovery`; full read-back SHA-256 passed.
- Android boot and both GPT regions were checked unchanged after installation. No repartitioning was performed.
- Original boot, recovery, darwin and GPT backups remain in `backups/RZ8N2032ZXE/`.
- Windows now binds xnuloader to Android Bootloader Interface 11.0.0.0 with problem code 0.

## Exact first-run recipe

```text
root_apfs=ufs_darwin ufs=2 ufs_write=0 var_store=0 bootcpu=4 cpus=7 small_cores_after=0 touchscreen=1 a51gpu=0 wifi=0 fb_threads=1 fb_decon_trig=1 fb_decon_double=1 fb_decon_second=0xcaa00000 fb_decon_third=0xcb400000 loader_return_after=300 sb_delay=8 epoch=1795260159
```

The verified RAM payload SHA-256 was `b9647de4c04022dae1dac60de3846ad02b2fcb701bb28fb168413375aa2b1e97`. Component hashes are preserved in the [original collection manifest](boot-tests/20261121T112239-072980Z/test-manifest.json). Its `ios_home_screen_verified: false` is the collector's unassessed default; the subsequent [boot assessment](boot-tests/20261121T112239-072980Z/boot-assessment.json) records screenshot review and the owner's confirmation. The collector does not automatically interpret screen contents.

## Remaining work

Software rendering and touch worked during this run. GPU acceleration and Wi-Fi are disabled. Cellular, calls, Bluetooth, camera, and hardware audio are unavailable in the selected configuration. The battery/PMIC driver is unavailable, so the on-screen low-battery icon does not verify the actual battery level. The connectivity controls likewise do not establish working radios.

UFS writes and variable persistence are disabled; saved iOS settings and data are not established across reboots. A longer session, broader app checks, hardware drivers, and a tested return to Android remain future work. Any subsequent kernel attempt needs a fresh recovery boot because this port has CPU-off limitations. No further system flash is needed merely to change a RAM payload's boot arguments.

The final screenshot attempt encountered empty geometry after the kernel returned. All five live screenshots succeeded. `run_diagnostic.py` now skips screenshots when the kernel is no longer running; this small collector change was checked locally but has not been exercised in another phone test.

See the [boot guide](A51-first-boot-guide.md) for a fresh diagnostic run and returning to Android, and the [build notes](A51-iOS16.5-build-notes.md) for preparation, exact image checksums and rollback.

## Return-to-Android follow-up

At the owner's request, sent a software reboot after the test. It returned to xnuloader rather than Android. A button restart and power cycle also selected UEFI. The owner restored the saved recovery using the verified recovery-only Odin archive. Android is now running: ADB serial/model and `sys.boot_completed=1` were independently verified. Rooted partition hashes confirm restored recovery exactly matches the original backup and Android boot remains unchanged. Diagnostic recovery is no longer installed; any future iOS test needs it reinstalled. The iOS system, Android boot and userdata are not targets of that rollback. See `return-to-android.json` for current observations.
