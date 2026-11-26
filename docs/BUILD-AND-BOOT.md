# Build and Boot Workflow

This document outlines how the A51 HakiOS build, recovery packaging, and Fastboot RAM boot pipeline are structured in this repository.

## Prerequisites

- **Build Host**: Linux / WSL2 (`A51-KernelBuilder`) with the HakiOS toolchain, Clang/LLVM, Theos, and EDK2/Mu-Silicium build dependencies.
- **Windows Host Tools**: Python 3 and Android `platform-tools` (`adb`, `fastboot`).
- **Device**: Samsung Galaxy A51 (`SM-A515F`) with an unlocked bootloader, TWRP recovery (for initial recovery partition flashing), and a backup of stock partitions.

## 1. Kernel, Drivers, and Userland

- Device drivers and config live in `device/` (mirrored to `devices/a51/` in the HakiOS tree).
- Kernel, loader, and userland modifications are captured in `hakios-changes/` and `patches/`.
- Userland build orchestration is handled in WSL via `hakios-changes/userland/build.sh` (or `scripts/build-a51-instagram.sh` for app-bundled builds).

## 2. Recovery Image and Payload Packaging

- `scripts/prepare_boot.py` assembles the kernel, `root.apfs`, `flashboot.apfs`, `SILICIUM_UEFI.fd`, `a51.dtb`, and boot command line into `.xnup` payloads and recovery images while validating the kernel boot-line byte budget (`scripts/boot_line_budget.py`).
- Default diagnostic boot command line parameters include:
  - `loader_return_after=0` (persistent run without timed return)
  - `root_apfs=ufs_darwin ufs=2 ufs_write=1 var_store=1`
  - `bootcpu=4 cpus=7 small_cores_after=0`
  - `touchscreen=1 a51gpu=8 a51gpu_keep=1 a51gpu_clock=3 a51wifi=8 a51audio=4 a51battery=2`
  - `fb_threads=1 fb_decon_trig=1 fb_decon_double=1 fb_ca_hz=120 sb_delay=8 enable_skstb=1 fbscale=2`

## 3. Flashing Recovery and Booting via Fastboot

1. From TWRP recovery, flash the diagnostic recovery image (`a51-ios16.5-diagnostic-recovery.img`) to `/dev/block/by-name/recovery` (`adb push` + `dd` with SHA-256 read-back verification).
2. Reboot to recovery (`adb reboot recovery`) so the device enters `xnuloader` Fastboot mode.
3. Run `scripts/boot_perfect.py` (which invokes `scripts/run_diagnostic.py --run --manual-return`) to:
   - Detect `xnuloader` over Fastboot.
   - Generate a fresh-epoch `run-payload.xnup`.
   - Stage the payload and execute `fastboot oem run`.
   - Poll loader state, capture serial logs (`log-*.txt`), and grab framebuffer screenshots (`screen-*.png`).
