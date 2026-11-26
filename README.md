# HakiOS for Samsung Galaxy A51 (SM-A515F)

Experimental port of HakiOS (XNU / Darwin 22.5, iOS 16.5 userland) to the Samsung Galaxy A51 (`SM-A515F`, Exynos 9611 / S5E9611, Mali-G72 MP3), maintained by [AnkitChoudhary-1](https://github.com/AnkitChoudhary-1).

This repository contains the current device drivers, UEFI/loader adaptations, kernel/userland patches, host build and fastboot diagnostic scripts, and bringup documentation. Proprietary Apple userland/SDK files, vendor firmware blobs, and device partition backups are excluded.

## Current State

The Galaxy A51 boots XNU Darwin 22.5 through Mu-Silicium UEFI + `xnuloader` into iOS 16.5 `SpringBoard` and `backboardd`, with interactive touch, Wi-Fi networking, Mali-G72 GPU rendering, and persistent UFS storage.

| Subsystem | Status | Notes |
| --- | --- | --- |
| Boot / UEFI / Loader | Working | Mu-Silicium UEFI (`a51Pkg` / `S5E9611Pkg`) + `xnuloader` USB Fastboot staging (`run-payload.xnup`). |
| CPU / SMP | Working | Exynos 9611 (Cortex-A53 + Cortex-A73), GICv2, PSCI bringup across 7 cores (`bootcpu=4 cpus=7`), ACPM DVFS clock scaling. |
| Storage (UFS) | Working | Persistent APFS root/var over UFS (`ufs=2 ufs_write=1 var_store=1`, `hakios.ufs.c`), plus `ramfs` / `apfs` VFS fixes. |
| Display (DECON) | Working | DECON triple-buffered / triggered scanout (`fb_decon_trig=1 fb_decon_double=1 fb_ca_hz=120`), UEFI handoff framebuffer. |
| Touch & Buttons | Working | Melfas MSS100 touchscreen over I2C (`touchscreen=1`) and hardware power/volume keys (`hakios.a51input.c`). |
| GPU (Mali-G72 MP3) | Working | Mesa Panfrost OpenGL ES 3.1 + `HakiosMetalCA` / `eagl` translation (`a51gpu=8 a51gpu_clock=3 a51gpu_mhz=1053`). |
| Wi-Fi (`en0`) | Working | Samsung WLBT (`hakios.a51wifi.c`, `hakios.apple80211.c`, `hakios.sta.c`) with `a51wifi=8`, `wifid`, DHCP, and static IPv4 DNS fallbacks (`1.1.1.1`, `8.8.8.8`). |
| Battery & PMIC | Working | SM5713 PMIC/fuel-gauge telemetry and charging control (`hakios.a51battery.c`, `a51battery=2`). |
| App Injection / Sideloading | Partial | Decrypted `.ipa` bundling, AMFI entitlement handling, and SpringBoard/app registration (`inject_app.c`, `inject_sb.c`, `app_reg.m`). |
| Audio (Speaker / Mic) | In Progress | Early I2S/codec bringup (`hakios.a51audio.c`, `docs/a51_audio_bringup.md`); speaker output is not yet functional in system or media playback. |
| Cellular / Camera / BT / GPS | Not Implemented | No modem, camera ISP, Bluetooth, or GNSS drivers. |
| Apple SEP / iCloud / App Store | Not Available | No Apple Secure Enclave hardware; `mobileactivationd` and `fairplayd.H2` cannot activate or decrypt App Store FairPlay binaries. |

## Repository Layout

- `device/` -- Device-specific configuration, SoC definitions, and A51 drivers (`configs/`, `drivers/audio/`, `drivers/gpu/`, `drivers/input/`, `drivers/power/`, `drivers/wifi/`, `soc/`, `uefi/`, `PORTING.md`).
- `hakios-changes/` -- Diffs against upstream `hakios-xnu-kernel` and `Mu-Silicium`, plus modified/added kernel, loader, userland, and UEFI source files (`hakios-xnu-kernel.patch`, `mu-silicium.patch`, `uefi-a51/`, `xnu/`, `userland/`, `xnuloader/`, `drivers/`).
- `patches/` -- Numbered feature patches (PMIC/battery, storage capacity, DNS fallbacks, Mu-Basecore/Mu-Silicium tracked changes).
- `scripts/` -- Host-side Python and shell utilities for building, preparing boot packages, flashing recovery, staging RAM payloads via Fastboot, capturing framebuffers/logs, and running diagnostics.
- `docs/` -- Subsystem bringup status, build/boot workflow, audio bringup notes, and investigation reports (`docs/STATUS.md`, `docs/BUILD-AND-BOOT.md`, `docs/reports/`).

## Documentation

- [Subsystem Status and Limitations](docs/STATUS.md)
- [Build and Boot Workflow](docs/BUILD-AND-BOOT.md)
- [A51 Audio Bringup Notes](docs/a51_audio_bringup.md)
- [Device Porting Notes](device/PORTING.md)

## Licensing

Original host tools and standalone drivers use MIT where permitted by file notices. XNU-derived modifications retain APSL 2.0, and Linux/Android/EDK2-derived components retain their respective licenses. See `LICENSE`, `LICENSE.APSL`, `NOTICE`, and `THIRD_PARTY_LICENSES.md`.
