# A51 audio and frame performance

21 November 2026. Work in progress. The owner verified smoother UI and working Wi-Fi in the preceding GPU/Wi-Fi test and requested audible audio and sustained 50–60 FPS. Neither requested result is verified yet. Preserve the tested package in `gpu-wifi/` and the original backups.

## Phone state and hardware evidence

Android was restored using the original recovery in Odin. ADB serial `RZ8N2032ZXE` reports `sys.boot_completed=1`. The audio inventory and firmware extraction used read-only ADB commands.

**Correction:** this phone's revision-07 live device tree enables a TI TAS2562 at I2C address 0x4c on HSI2C3 (`0x11D10000`). Android has bound its driver. The RT5510 at 0x34 in the generic DTS is disabled on this phone. RT5665 at 0x1b serves other analog audio paths. Speaker playback routes through ABOX UAIF2, 48 kHz, stereo, 16-bit. See `audio-performance/live-codecs.txt`, `live-fdt.dtb`, `live-fdt.dts`, and the mixer XML inventory.

The ABOX register region is `0x14A50000`, sysreg `0x14810000`, SRAM `0x14B00000`; reserved DRAM is `0xE9400000` for 40 MiB, also reserved by the existing UEFI memory map. Its GIC distributor and CPU interface are `0x14AF1000` and `0x14AF2000`. Exynos PMU and CMU_DISPAUD are `0x11860000` and `0x14980000`. Samsung's revision-07 DTS, CAL tables and ABOX/TAS2562 drivers are the source of register definitions.

Calliope SRAM/DRAM/IVA, `spkamp.bin`, `param_ti.bin`, and the three available SLSI extension binaries were extracted from this phone and independently hash-checked against Android. The manifest is `audio-performance/audio-firmware/manifest.json`. APTV is absent even in the working Android audio boot and is not treated as a prerequisite. Firmware availability alone does not establish DSP startup or playback.

## Performance implementation

The new isolated profile retains Panfrost, three DECON buffers and **one** framebuffer copy worker. The port's own recorded hardware measurements found simultaneous writes by three workers to write-combined display memory much slower. This profile does not repeat that setting.

ACPM FVP and TMU plugins from the owner's existing Samsung source are size-checked, recorded under `audio-performance/firmware/`, and staged in `hakios/fw-acpm` (relative to the repository root). Requested rates are exact supported levels: A53 1638 MHz, A73 2080 MHz and GPU 572 MHz. Memory/interface bus overrides are zero. The driver checks original rates and all temperature sensors before requesting a boost, verifies the requested rates by FREQ_GET, and watches temperature each second. Sensor loss or a reading above 100°C disables boosting for that domain and restores its verified original rate. Normal thermal reduction starts above 81°C for A53 or 83°C for A73/GPU; recovery below 75°C is limited to one level per five seconds. This is a bounded experiment, not a sustained performance guarantee.

Low-rate GPU reports now enter the loader log as whole lines, including jobs/failures/resets, timings, temperatures and actual rate queries. The source patch and hashes are `audio-performance/a51-performance.patch` and `performance-source-manifest.json`. Twelve tests compiled from the actual thermal policy passed. Kernel compilation and linking passed; only the repository's documented kext export/symbol-set checks failed and its build judge accepted those failures.

The diagnostic job list runs a small triangle/readback, CPU observations, a delayed network check, repeated left/right swipes and a late HTTPS check. It uses init's direct job syntax; shell subshells are unsupported and were removed before packaging. Command lines, including trace arguments, must fit XNU's 607-byte capacity.

## Audio implementation and remaining work

`enable-a51-audio-probe.py` adds the separate opt-in A51AUDIO driver. `a51audio=1` records PMU state and reads CMU only while DISPAUD is powered. Stage 1 performs no register writes and does not touch gated ABOX/I2C peripherals. It deliberately leaves the audio sink unregistered. Generic Qualcomm SOUND/ADSP/SPEAKER drivers stay disabled.

Audible output still requires proving clocks and peripheral access, TAS2562 identity and safe configuration, Exynos DMA/IOMMU routing through UAIF2 (and Calliope IPC if that path is used), then integrating the 48 kHz PCM sink and volume/mute/fault handling. Neither HAL enumeration nor captured PCM counts as speaker playback. An audible test and owner confirmation are required.

## Reproduction and test boundaries

1. WSL: run `enable-a51-performance.py`, `test-a51-clock-guard.py`, and `enable-a51-audio-probe.py` from `outputs/scripts/` via their `/mnt/c/...` paths.
2. In the existing checkout: `KERNEL_LOG=xnu-a51-audio-performance-build.log tools/make-kernel.sh -j8`.
3. WSL: `bash .../outputs/scripts/build-a51-audio-performance.sh`.
4. WSL: `python3 .../outputs/scripts/prepare_boot.py --profile audio-performance`.
5. Windows: prepare and run using `run_diagnostic.py --package-dir outputs/audio-performance --trace-frames`, after the corresponding diagnostic recovery is installed.

Per the owner's latest request, this profile now uses `loader_return_after=0`: no normal timed return. Keep `ufs_write=0 var_store=0`, a fresh firmware session and recovery-only installation. Host collection is independent of runtime; it sends no stop/reboot when it finishes. The hang watchdog remains unchanged. Return to Android with the original `outputs/restore-current-recovery-RZ8N2032ZXE.tar.md5` in Odin AP only, with Re-Partition off, no PIT, and no wipe. Record each package hash, run folder and physical observations as work proceeds.

## First packaged build (historical, superseded)

The isolated final package passed static validation. Kernel: 15,065,568 bytes, SHA-256 `b1f88fd51f82d0786db6bbac66bce94442032df4b040c9d57977a1e6f2ed3eb4`. Root APFS: 8,024,064 bytes, SHA-256 `2f21567b20493c707950e4f4fcfc6fb3da858b56b86f8d6fa201721603fcf734`. Diagnostic recovery: 29,597,696 bytes, SHA-256 `ff9146cfc2e19d27a5afec54a74c86a4876171a1290d04fdb0c9b731521439be`. The flashboot hash remains identical to the working GPU/Wi-Fi package. Root verification read all 497 entries back against staging. This first package was subsequently installed and tested, as recorded below; its firmware omission is corrected in the current package.

## First audio/performance test: packaging correction

Recovery installation and read-back passed. Run `audio-performance/boot-tests/20261121T131314-488672Z` booted iOS. The PMU/CMU audio baseline completed without a hang. DISPAUD status `0x0003000f`; ABOX CPU configuration `1`, option `0`; UAIF2 and ABOX gate readings `0x00200000`. No playback was attempted.

Hardware logging exposed an ACPM staging path error: userland/build.sh changes directory into userland, so its `../fw-acpm` is **hakios/fw-acpm**, not the parent of hakios. The first package lacked the plugin files; at 120 seconds the clock worker rejected the missing FVP file, so no boost was applied. Measured initial CPU rates were A53 1053 MHz/A73 1456 MHz. Corrected staging and added mandatory source/staging comparisons. Earlier claims that the plugins were in the first root image were incorrect. This run must not be treated as a higher-clock benchmark.

## Corrected firmware and manual return package

The owner reported that the first run worked but still needed greater smoothness, and explicitly requested removal of the five-minute run limit. `run_diagnostic.py --manual-return` sets `loader_return_after=0`; the audio-performance profile now also embeds zero. XNU `osfmk/arm64/loader_return.c` returns without scheduling its timer when this argument is absent or zero. No host stop/reboot is sent after collection. A manual Android return still uses the saved original recovery in Odin.

Corrected root: 8,040,448 bytes, SHA-256 `32663211ab49336b088ed29d142d89e299d0b6f07227c9a4c4b1bcebbd171f93`. Both 5,120-byte ACPM plugins are verified against staging, and all 499 APFS entries were read back. Current recovery SHA-256 `a9b9c30adc597b23d221542c2eeafcc764e3a770e7c0e651c5e4c27980bb308d`. Kernel is unchanged. Clock boost activation and its effect on frame pacing remain to be measured in the next run. Historical filenames containing `timed-boot` are retained by the packaging script, but this profile's actual command line disables the timer. Each new RAM run preserves its exact package manifest.

First-run gesture measurements: 3,524 moving frame intervals, 59% above 18 ms and 29% above 34.5 ms. This does not demonstrate sustained 50–60 FPS; workload differences prevent treating it as a controlled comparison. The stock frame parser's big/small core split does not match the A51's interleaved logical CPU map; core attribution must be corrected before use.

## Completed manual-return test and follow-up

Run `audio-performance/boot-tests/20261121T132911-695294Z` collected 354 seconds, finished normally with `running 0 0`, and sent no stop command. Its command line explicitly used `loader_return_after=0`. The package is now recorded as phone-tested in `integration-readiness.json`; the exact home-screen observation was not captured for this run and that flag remains false. ACPM FREQ_GET returned zero for A53, A73 and GPU. Rate guards refused boosting; plugin presence did not establish successful DVFS initialization.

Moving-frame measurements for this run: 2,382 intervals, about 59% above 18 ms and 29% above 34.5 ms. Mean draw duration was about 12.8 ms on big and 20.3 ms on small cores, using the corrected small logical CPU set 2/4/6. These are uncontrolled workload observations and establish no FPS improvement or sustained target.

The owner returned to Android by restoring the original recovery in Odin, then confirmed speaker playback for read-only capture. Charging, battery reporting, powered audio access and reduced-resolution rendering are being developed in the isolated `device-services/` profile. See `A51-device-services.md` for exact scope, validation and reproduction. This preserved package and its logs remain available as the baseline.
