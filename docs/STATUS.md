# Subsystem Status and Limitations (SM-A515F)

This document summarizes the current hardware and OS integration state of HakiOS on the Samsung Galaxy A51 (`SM-A515F`, Exynos 9611).

## Verified Working Subsystems

1. **Boot Chain (Mu-Silicium UEFI + xnuloader)**
   - Recovery-installed `xnuloader` exposes a USB Fastboot interface (`xnuloader`).
   - Host scripts stage `run-payload.xnup` (kernel, root APFS ramdisk, resident flashboot APFS, cmdline, kernel version) into RAM and boot XNU via `fastboot oem run`.

2. **CPU, Timers, and Power Management**
   - 7-core SMP bringup (`bootcpu=4 cpus=7`, Cortex-A53 + Cortex-A73) with GICv2 and PSCI trampoline.
   - ACPM DVFS clock targets (`a51cpu0_khz=1742000`, `a51cpu1_khz=2314000`, `a51gpu_mhz=1053`, `a51mif_khz=2093000`, `a51int_khz=667000`).
   - SM5713 PMIC fuel gauge and charger monitoring (`hakios.a51battery.c`, `a51battery=2`), reporting live SOC, voltage, current, and thermistor temperatures.

3. **Storage (UFS + APFS)**
   - Persistent Darwin partition over UFS (`ufs=2 ufs_write=1 var_store=1`) with `hakios.ufs.c` and `var_store.c`.
   - Patched APFS/ramfs/VFS handling in `xnu/files/bsd/`.

4. **Display, Input, and Graphics**
   - DECON display pipeline with triggered/triple-buffered scanout (`fb_decon_trig=1 fb_decon_double=1 fb_ca_hz=120`) and `MiniIOMobileFramebuffer`.
   - Melfas MSS100 I2C touchscreen and GPIO power/volume buttons (`hakios.a51input.c`).
   - Mali-G72 MP3 GPU via Mesa Panfrost (`a51gpu=8 a51gpu_keep=1 a51gpu_clock=3`) with `HakiosMetalCA` and `eagl` translation layers driving `backboardd` and `SpringBoard`.

5. **Wi-Fi and Networking**
   - Samsung WLBT Wi-Fi bringup (`hakios.a51wifi.c`, `hakios.apple80211.c`, `hakios.sta.c`) under `a51wifi=8`.
   - Exposes `en0` to `wifid` and iOS Settings, with DHCP and static IPv4 DNS fallbacks (`1.1.1.1`, `8.8.8.8`) to prevent WebKit IPv6 timeout stalls.

## Partial or In-Progress Subsystems

- **Speaker and Media Audio (`a51audio=4`)**:
  - `hakios.a51audio.c` and `docs/a51_audio_bringup.md` document ongoing Exynos ABOX/codec bringup. System sounds and browser/app media playback do not yet produce speaker output.
- **Third-Party App Sideloading**:
  - Decrypted `.ipa` injection and registration (`inject_app.c`, `inject_sb.c`, `app_reg.m`) allow launching compatible iOS 16.5 apps (such as Instagram), subject to missing Apple services and hardware drivers.

## Unavailable / Non-Working Subsystems

- **iCloud, Device Activation, and Official App Store**:
  - `mobileactivationd` and `fairplayd.H2` fail because the Exynos 9611 lacks an Apple Secure Enclave (SEP), factory-burned Apple device certificates, and FairPlay hardware keybags.
  - Native Apple ID sign-in, APNs (`apsd`) push notifications, iCloud sync, and FairPlay-encrypted App Store binaries are not supported.
- **Cellular Modem, Camera, Bluetooth, GPS**:
  - Not implemented.
