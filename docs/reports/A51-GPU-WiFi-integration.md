# Galaxy A51 GPU and Wi-Fi integration

Status: tested on the phone on 21 November 2026. Mali/Panfrost acceleration and open-hotspot association/DHCP verified; owner reports smoother UI and working Wi-Fi. Steady 50–60 FPS and long-term stability remain unverified.

The owner reported a very laggy UI, no Wi-Fi and no apparent charging during the first iOS 16.5 boot. Physical charging was not measured. On 21 November 2026 the owner requested integrating GPU acceleration and Wi-Fi first. Charging and third-party app installation are outside this change.

## Approach

- Preserve the first successful software-rendered package and all its test evidence.
- Build Mesa 25.0.7 with `softpipe,panfrost`, including the repository's Darwin patches and HakiosMali bridge.
- Enable `GL=1` in the helper userland and `a51gpu=8 a51gpu_keep=1` in the timed RAM test.
- Start without frequency changes (`a51gpu_clock=0`). CPU/GPU clock tuning is a separate step after actual acceleration is verified.
- Extract and hash Samsung WLBT firmware from this phone's Android. Extract the keep-alive patch from the owner's existing Samsung kernel source.
- Enable `a51wifi=8` for the A51 driver. The generic Qualcomm `wifi` argument remains disabled.
- Verify scan, association, DHCP and traffic separately. A Wi-Fi icon alone is insufficient.
- Keep `ufs_write=0 var_store=0`, a 300-second kernel runtime and the known recovery-only Android restoration procedure.

## Current observations

Android ADB is available on `RZ8N2032ZXE`, with `sys.boot_completed=1`. All four expected `/vendor/etc/wifi/mx140*` firmware/configuration files exist. Kernel configuration already includes `HAKIOS_A51GPU`, `HAKIOS_A51WIFI`, and `HAKIOS_WIFI_STATION`; the first test disabled their runtime paths and omitted the corresponding userland dependencies.

Source GPU and Wi-Fi results describe other tests and are not verification of this owner's new package. Test results and exact hashes will be added as work proceeds.

## Build completed on 21 November 2026

The owner's test network is `OPPO K13 5G B93C`, an open hotspot. Android confirms security type 0, association at 5180 MHz, an IPv4 address and usable Internet before the experimental test.

The A51 service supported open association, but `fw/wifi.conf` required credentials and its standing join unconditionally selected WPA2. The local driver patch adds explicit `security=open`; a missing security field keeps the existing WPA2 interpretation, and an unknown security type is rejected. The legacy step-7 WPA2 diagnostic rejects open configurations. `gpu-wifi/open-network.patch` records the change. The actual parser was compiled on the host and passed 12 configuration cases, including open SSIDs with spaces, CRLF, missing credentials, existing WPA2 passphrase/PMK configurations, invalid security and oversized SSIDs. This validates parsing, not hardware association.

Samsung's four firmware files were extracted with binary-safe ADB reads and their SHA-256 values matched the phone. The existing Samsung source supplied the keep-alive array: 58 little-endian words / 232 bytes. Sources, sizes and hashes are recorded in `gpu-wifi/firmware-manifest.json`.

Mesa 25.0.7 was built with `softpipe,panfrost`. The helper was rebuilt with `GL=1`; the GL bridge and Mesa library are present in its RAM filesystem. The new root APFS image has 497 entries, all read back against the staging tree, and passed `apfsck -cw`. The unchanged 4 MiB flashboot image also passed both checks. Kernel driver source synchronized into XNU matches the local patch byte for byte. Kernel compilation/linking completed; the repository's build judge accepted only its documented, existing kext symbol-set/export-check failures. Logs and artifact hashes are saved under `gpu-wifi/`.

The diagnostic jobs use a small GL triangle/read-back test, CPU observation at 10-second intervals, DHCP/DNS/TCP/HTTPS checks and two scripted swipes. The original CPU stress job is omitted. CPU/GPU frequency overrides are omitted. Runtime GPU acceleration still requires proof from the renderer, real GPU job counts and frame timings.

## Reproduction and rollback

Run the scripts with the existing WSL builder and extraction described in the main build notes:

1. Windows: `python.exe outputs/scripts/extract-a51-wifi.py` (reads phone firmware only).
2. WSL: `python3 outputs/scripts/enable-a51-open-wifi.py` using its `/mnt/c/...` path (one-time exact source patch), then `test-a51-wifi-conf.py`.
3. WSL: `bash .../outputs/scripts/build-a51-mesa.sh`, then `build-a51-gpu-wifi.sh` and `build-a51-wifi-kernel.sh`.
4. WSL: `python3 .../outputs/scripts/prepare_boot.py --profile gpu-wifi`.
5. Windows: `python.exe outputs/scripts/run_diagnostic.py --prepare --package-dir outputs/gpu-wifi`.

The original package stays in `outputs/`; the new package is in `outputs/gpu-wifi/`. The installer and diagnostic runner now accept `--package-dir`, with their existing defaults preserved. Host preparation commands do not flash the phone. Installing this test replaces recovery only; the Apple system is already present in darwin.

Returning from the first test to Android required Odin restoration of the original recovery. Normal reboot/button attempts did not return to Android. Keep `outputs/restore-current-recovery-RZ8N2032ZXE.tar.md5` available, use it in Odin AP only, leave Re-Partition off and do not supply a PIT. No wiping or repartitioning is part of this test. A new diagnostic run needs a fresh recovery session.

## Live test result, 21 November 2026

The test ran from 12:20:44 UTC (17:50:44 IST) and returned to the diagnostic loader as intended; collection ended at 12:25:57 UTC. Only recovery was replaced, read-back verified at SHA-256 `92bc63ad533e44ddfb485b0a13a7f5dd7e36843960c58f3dae96ecf905f31913`. The Apple system region was reused. The RAM payload retains `ufs_write=0 var_store=0`; collection issued no stop/reboot. See `gpu-wifi/boot-tests/20261121T122043-999029Z/` for the actual manifest, screenshots, frame analysis and GPU/network evidence.

- GL renderer: `Mali-G72 (Panfrost)`, OpenGL ES 3.1 Mesa 25.0.7. The 320×240 triangle drew in 44 ms, read back in 9 ms, GL error 0, with exactly the expected pixel coverage. CoreAnimation opened this renderer and the window server selected acceleration. The triangle tool's message about no display service refers to its HakiosGPU presentation lookup; the A51 uses HakiosMali. Later screenshots show a rendered iOS interface. A black capture at about 62 seconds was temporary; its cause was not established.
- Wi-Fi: joined `OPPO K13 5G B93C`, channel 36 / 5180 MHz, BSSID `3a:bf:9d:d0:78:d7`; DHCP assigned `172.28.223.196`, gateway `172.28.223.8`, with IPv6 and service DNS configuration. The owner twice confirmed working Wi-Fi. The one early automated DNS/TCP/HTTPS probe failed while global configuration was incomplete; no later automatic retry ran. The exact Safari Success page was not explicitly confirmed, so the automated Internet check remains unresolved.
- Owner feedback: “it is smoother then previous test, wifi is also working”.
- Saved frame traces contain 3,896 displayed frames and 107 gestures. The repository analyzer reports 69% of 2,170 sampled moving frame intervals over its 18 ms threshold and 39% over 34.5 ms. Individual gesture segments vary, with one scripted swipe near 59 FPS and many slower segments. This is not sustained 60 FPS, and no equivalent traced baseline exists for a numerical speedup claim. Its draw/GPU/idle attribution produces negative idle values with overlapping work; use the actual display intervals as evidence rather than treating that attribution as a serial breakdown. The display's advertised 60 Hz capability alone is not a performance measurement.
- Repeated host logs reach their capture cap and omit the kernel GPU status lines. Therefore this run does not establish cumulative GPU job failure/reset counters or temperatures. The normal timed return and absence of a visible crash do not establish long-term stability.

## Next authorized work

The owner requested speaker/audio support and a UI stable at 50–60 FPS. Android restoration through the saved recovery in Odin completed; ADB confirms Android running. The live revision-07 DT and bound Android driver identify TAS2562/UAIF2 as the speaker path. The new isolated performance profile retains one framebuffer copy worker and adds guarded supported ACPM rate requests, complete GPU logging and repeated gestures. Details and remaining audio work are in `A51-audio-performance.md`. Charging remains outside scope.
