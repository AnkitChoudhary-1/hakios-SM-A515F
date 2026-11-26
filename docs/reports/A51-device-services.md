# Galaxy A51 device services

Updated 21 November 2026. Owner device SM-A515F, Exynos9611, serial RZ8N2032ZXE. This follow-up targets frame pacing, truthful battery reporting, charging and speaker playback. The build reached iOS Settings on hardware; the owner reported a navigation/status-bar regression from the XR layout override. Charging control and speaker playback are not implemented; neither is claimed working.

## Preserved baseline and current package

`audio-performance/` retains the prior tested package. Its manual-return run `boot-tests/20261121T132911-695294Z` collected 354 seconds and remained `running 0 0` when collection ended. ACPM FREQ_GET returned zero for all three requested domains, so the driver refused boosts. The owner restored Android through the saved recovery in Odin before the hardware reference capture. Earlier owner feedback confirmed working Wi-Fi and improved but insufficient smoothness.

The isolated follow-up is `device-services/`. Kernel SHA-256: `fc2ac0a6b55af8eb650af999f80992948655bd5111911aa7f26bd98d52e9e1f6` (15,072,832 bytes). Diagnostic recovery SHA-256: `44aafd0957c02964473080ff30f3ccbf8166e8275afeea3958019c11a05dd3df` (29,620,224 bytes). Root APFS, flashboot, loader, UEFI and DTB hashes independently match the preserved profile. Consult `boot-package-manifest.json` for all artifacts and `integration-readiness.json` for current validation state.

Every payload embeds `loader_return_after=0`. Host log collection ends without stopping iOS. The inherited hang watchdog still exists. Recovery-only installation verifies saved backups, GPT, Android boot, original recovery, staged image and read-back; the existing Darwin system prefix is checked before installation. No repartitioning is part of this follow-up.

## Battery monitor and charging investigation

The dedicated legacy I2C controller is at 0x13840000; SM5713 charger address is 0x49 and fuel gauge address is 0x71. `a51battery=1` logs diagnostics; `=2` also publishes Darwin battery state. Identity is checked before polling every five seconds. SOC, voltage, signed current, gauge internal temperature, cycle count, charger status, watchdog and current-limit registers are read. Invalid readings withdraw external/charging/full flags and mark data stale while retaining the last SOC.

The bridge preserves the existing ADSP entry point. It omits unknown adapter measurements and learned capacity. Design capacity 4,000,000 uAh comes from the live DT. Full status requires the hardware top-off state rather than a percentage rounded to 100. Gauge internal temperature is never substituted for battery thermistor temperature.

The Exynos ADC v3 monitor uses CMGP at 0x11c00000, sysreg at 0x11c10000 and ADC at 0x11c30000. It arbitrates with CHUB, restores temporary clock settings and bounds arbitration/conversion waits. Five samples per thermistor use a trimmed mean; revision-07 DT tables convert channel 1 (battery) and channel 3 (charger). Values outside the tables are invalid. This test verified ADC conversions with interrupts disabled: battery approximately 25–26 C and charger approximately 28–33 C, with plausible trends.

No charger enable, watchdog servicing, calibration, boost or current-limit writes are present. Android showed USB input limit 475 mA, charge limit 550 mA, float setting 4350 mV and watchdog register 0x05. Watchdog expiry was observed in iOS: WDTCNTL changed from 0x05 to 0x04, STATUS2 gained bit 7 (0x80), and battery current became negative while USB was connected. The charger was not serviced by this read-only build. Do not enable charging until reliable battery/charger temperatures, status/fault checks and bounded servicing/protection behavior are proven. The normal Android battery policy stops above 50 C or below 0 C, with recovery below 48 C or above 2 C.

## Speaker investigation

The live revision-07 hardware uses TAS2562 at 0x4c, HSI2C3 0x11d10000, CMGP gpm2-0 SCL/gpm3-0 SDA and gpm0-0 reset. Android speaker playback was captured while the owner played music. Active PCM streams were 48 kHz, stereo S16_LE; main period/buffer 960/3840 frames, second 480/1920. Logs include I2S/IV-slot setup, active power register 2 = 0, and amplifier status. They are partial observations, not a complete initialization recipe or calibration.

`a51audio=2` adds powered/gated ABOX version, route and UAIF2 reads. `=3` adds a bounded open-drain GPIO amplifier probe, skipping when reset is asserted. It saves/restores GPIO and book/page selectors and does not drive high, reset, unmute or configure boost/gain. Audible output still needs verified clocks, UAIF2 DMA/IOMMU routing, Calliope IPC if used, amplifier initialization/calibration/fault handling and a real PCM sink. No discard sink is registered.

## Frame pacing

Panfrost, triple DECON buffering and one copy worker are retained. ACPM SRAM/channel/plugin validation is tightened and low-rate request/reply diagnostics added. Measured-rate and thermal guards remain; no guessed rate is seeded to bypass the zero-rate blocker.

The rejected `device-services` command line requests 828 x 1792 at scale 2 with XR layout/artwork. This reduces rendered pixel count about 46% from 1125 x 2436, trading sharpness for lower render load. `fb_ca_hz=120` uses the port's existing CoreAnimation pacing setting. The owner reported Control Center opening from the bottom, loss of the home gesture and an unfamiliar status bar. Screenshot screen-008.png also showed black rectangular labels/icons. This layout is rejected; sustained 50–60 FPS remains unverified. Frame intervals require controlled gestures, workload matching and correct A51 logical CPU mapping before comparisons. The command line plus tracing is 504 bytes, below the 607-byte XNU limit.

## Validation and reproduction

Kernel compilation/linking passed. The known kext export/symbol-set checks still fail and `make-kernel.sh` accepts them for this configuration. Decoder checks compile actual code with UBSan, exercise all 65,536 gauge words, eight charger cases, thermistor knots/bounds/monotonicity, two Android temperature references and eight actual ACPM SRAM bounds cases. They passed; they do not verify hardware access.

Use the existing prepared checkout `/opt/a51-hakios/upstream-a51/hakios` in WSL `A51-KernelBuilder`. From Windows, paths below are accessed in WSL through `/mnt/c/Users/Ankit/Documents/Codex/2026-11-21/hi-2/outputs/scripts/`:

1. Apply `enable-a51-device-services.py` to the preserved audio/performance source. It embeds decoder and ADC sources, synchronizes the built XNU input header, and records before/source files, a patch and hashes. For baseline reproduction only, the older performance/audio-probe scripts precede this step; do not reapply the old audio-probe script over the extended driver.
2. Run `test-a51-device-services.py`.
3. Build in the checkout: `KERNEL_LOG=xnu-a51-device-services-build.log tools/make-kernel.sh -j8`.
4. Package with `python3 .../prepare_boot.py --profile device-services`. The existing validated root APFS is reused.
5. Windows: `python outputs/scripts/install_a51.py --install-recovery --package-dir outputs/device-services`, then enter recovery in a fresh firmware session.
6. Windows: `python outputs/scripts/run_diagnostic.py --run --package-dir outputs/device-services --trace-frames --manual-return --seconds 360`. Six minutes bounds host collection only.

Android references are under `device-services/android-reference/`; `capture-provenance.json` records hashes, times and retained command provenance, including where exact supplementary invocations were not saved. Source provenance is `device-services/source-manifest.json`.

## Android return

Use `outputs/restore-current-recovery-RZ8N2032ZXE.tar.md5`, SHA-256 `b19b680469b04d82622c22e27f29e4ede226256418cceab1c1934740b84274e5`, in Odin AP only. Leave BL/CP/CSC empty, Re-Partition off, no PIT, Auto Reboot on. If recovery opens, choose Reboot → System without wiping. Odin executable: `D:\Odin3_v3.14.4\Odin3_v3.14.4\Odin3_v3.14.4.exe`.

## 14:18 UTC hardware test and layout correction

Run `device-services/boot-tests/20261121T141837-455212Z/` reached Settings and returned SM5713/thermistor diagnostics. TAS2562 was held in reset, so its I2C probe was skipped; ABOX/UAIF register reads succeeded. ACPM sequence-matched replies erased domain/opcode and returned zero rates; boosts were refused. No frame trace events were recovered, so this run cannot substantiate an FPS improvement. Host `getvar result` timed out after the last successful 296-second poll; no host stop/reboot was sent. The owner subsequently restored Android, after which the corrected recovery was installed. Exact evidence and log hashes are in `hardware-evidence.json`.

The isolated `device-services-layout-fix/` package removes all five framebuffer/layout/pacing overrides and preserves the exact tested kernel, battery monitor, Wi-Fi, GPU, root APFS and other firmware components. Diagnostic recovery SHA-256: `c3dbd6cd35fa3b28b62479b295a7991a855db142451059f3d8592d3c24f84cde`. Original iPhone X defaults are selected, and `loader_return_after=0` is retained. Independent component/payload/header/cmdline checks passed. Recovery installation completed at 14:30:40 UTC with a matching read-back SHA-256. The manual-return hardware test started at 14:32 UTC in `device-services-layout-fix/boot-tests/20261121T143245-555261Z/`; gesture verification is in progress. Reproduce with `prepare_boot.py --profile device-services-layout-fix`.

## 14:32 UTC layout-fix test and rendering follow-up

The corrected layout run completed host collection with `running 0 0` at 359 seconds; iOS was left running. Screenshot `screen-008.png` shows the iPhone X status bar and home indicator. The owner still reported intermittent black boxes, unsmooth UI and no sound; exact home/Control Center gesture confirmation remains pending. Frame tracing recovered 114 gestures and 3,609 displayed frames. Logs show the 256-entry IOSurface texture binding table filled and 54 distinct attachment texture IDs failed. Full evidence is in `device-services-layout-fix/boot-tests/20261121T143245-555261Z/hardware-evidence.json`.

The isolated `render-fix` package grows that binding table, preserves the iPhone X layout and tests CA pacing at an advertised 120 Hz. Host lifetime/sanitizer tests, userland rebuild, APFS read-back and independent package checks passed. Its completed hardware run recorded 125 gestures and 4,041 frame copies; the owner still reported lag. No binding exhaustion was observed in the captured snapshots, but sustained 50–60 FPS and complete elimination of black boxes remain unverified. Charging control and speaker playback are still unimplemented. See [A51-render-fix.md](A51-render-fix.md) for the evidence.

The lower-resolution follow-up completed collection with the owner reporting "still laggy"; its tracing argument was truncated by the loader's command-line prefix, so no valid FPS comparison is available. See [A51-UI-performance.md](A51-UI-performance.md). The owner has stopped resolution, blur and animation experiments and now requests only a Metal feasibility explanation, documented in [A51-Metal-feasibility.md](A51-Metal-feasibility.md). Speaker, charging and app development remain paused. No new rendering implementation or device changes were made for this assessment.
