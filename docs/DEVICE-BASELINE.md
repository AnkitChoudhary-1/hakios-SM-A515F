> Publication note: this is a historical workspace document. Current completion decisions are in [PUBLIC-STATUS.md](PUBLIC-STATUS.md); raw local evidence is described in [PUBLICATION.md](PUBLICATION.md).

# A51 baseline and limitations

Live observations were captured 10 November 2026 through read-only ADB and retained input hashes. The earlier 11 November Phase 2 host continuation did not refresh phone measurements. Subsequent privileged read-only observations now verify Shell root, the Linux-exported FDT, memory reports, existing logs and partition hashes, separately from the historical inventory below. Full command arrays and outputs are in `manifests/device-and-inputs.json`, its historical snapshots, `manifests/hardware-inputs.json`, and the corresponding runs.

| Item | Observed value | Evidence level |
|---|---|---|
| Model/device/hardware | SM-A515F / a51 / exynos9611 | Live Android properties |
| Bootloader | A515FXXU8HWI5 | Live Android property |
| Baseband | A515FXXU8HWI1 | Live Android property |
| Android | 16, SDK 36, build BP4A.251205.006 | Live Android properties |
| Running kernel | 4.14.357-Everline-KSUN-A51 | Live uname; existing Android project |
| Revision | `ro.boot.revision=9`; hardware.revision is empty | Reported boot revision, not a verified PCB identifier |
| Display | 1080×2400, exynos-decon driver symlink | Live wm size and sysfs link |
| RAM | MemTotal 5,707,016 KiB ≈ 5.44 GiB | Linux-visible memory, consistent with 6 GB hardware |
| Available RAM at first connected inventory | 1,250,536 KiB ≈ 1.19 GiB | Transient Android workload snapshot |
| CMA | Total 135,168 KiB ≈ 132 MiB | Live meminfo; included in Linux-visible RAM, not all hardware reservations |
| Battery snapshot | 83%, 4.132 V, 32.3 °C, USB powered, charging status 2 | Android battery service reports; not external electrical measurements |
| Boot partition | `/dev/block/sda12`, 61,865,984 bytes | Live by-name link; retained prior readback/partition measurement |
| DTBO/recovery image sizes | 8,388,608 / 71,106,560 bytes | Retained full backups; current size query denied |
| Slots | slot_suffix empty; boot/recovery names have no slot suffix | Live Android observation |

Do not derive a final XNU memory map from MemTotal. Reserved regions and the bootloader's usable RAM need device-tree and privileged live-map validation. Ordinary ADB was denied access to `/proc/iomem`, sysfs partition sizes and device-tree model/compatible. Those failed queries are preserved. A read-only `adb shell su -c id` returned `su: inaccessible or not found`; runtime KernelSU root was unverified in that historical inventory; the subsequent Shell grant and successful root capture are recorded below. This does not prove the kernel hooks are absent or that manager configuration cannot provide access later.

The current ROM reports `ro.boot.flash.locked=1`, `ro.boot.vbmeta.device_state=locked` and verifiedbootstate green, conflicting with prior custom-image/TWRP boot evidence. Treat actual bootloader acceptance/unlock state as unresolved until independently checked; these ROM properties alone are insufficient.

## Retained boot-image structure

Both backups have Android boot magic and header version 2, 2,048-byte pages and a 1,660-byte header. `scripts/trace-hardware.py` parses their headers and hashes the files without modifying them.

| Field | Original Android boot | TWRP recovery |
|---|---|---|
| Kernel bytes | 36,313,128 | 43,745,292 |
| Ramdisk bytes | 1,325,644 | 13,532,879 |
| Kernel address | 0x10008000 | 0x10008000 |
| Ramdisk address | 0x11000000 | 0x11000000 |
| Tags address | 0x10000100 | 0x10000100 |
| DTB bytes | 135,168 | 135,216 |
| DTB address | 0x10000000 | 0x11f00000 |
| Recovery DTBO bytes | 0 | 476,800 |
| Command line | loop.max_part=7 | androidboot.hardware=exynos9611 buildvariant=eng |

Header addresses are retained metadata, not proof of the physical execution address or CPU state accepted by the Samsung bootloader. Phase 2 must trace the real handoff and reservations. Hashes and prior AVB/readback checks are in `everline-ksu/artifacts/repack-validation.json` and the inventory manifest. Original backups are preserved separately from the current KernelSU-containing Android image.

## Retained-tree host findings, 11 November

The [Phase 2 host audit](PHASE-2-HOST-AUDIT.md) verified four pinned images, five Android DT tables and 11 extracted FDTs, then independently compared 1,380 properties with libfdt. Boot DTB sections contain DT tables, rather than a raw FDT at the section start. Original and installed Android boot share the same base FDT; recovery differs in Android fstab/vbmeta data while declaring the same RAM/reservations. Recovery overlays have different hashes from original DTBO and are retained separately.

The base trees declare 6 GiB in `[0x80000000, 0x100000000)`, `[0x880000000, 0x900000000)` and `[0x900000000, 0x980000000)`. Fifteen fixed reservation spans total 251,727,872 bytes; three dynamic reservations remain unplaced: video ION 72 MiB, crypto ION 24 MiB and WLBT 16 MiB. These declarations do not establish current available/secure memory. The QEMU payload address `0xF0000000` lies within declared modem memory `[0xED000000, 0xF5A00000)` and cannot be reused for the A51. All Android header kernel/ramdisk/DTB addresses are outside declared DRAM; Samsung relocation/entry remains unknown.

Reported boot revision 9 conditionally matches DTBO entry 3, corresponding to EUR `_07`/REV02 source definitions. Actual live selection, bootloader fixups and PCB/peripheral identity are unverified. No overlays were applied and no safe load address selected. See [loader requirements](LOADER-DESIGN.md) for the remaining ownership, entry, logs and return evidence.

## Linux references and firmware

`manifests/hardware-inputs.json` records selected source files by absolute path, size and SHA-256, grouped by board, display, touch, GPU, Wi-Fi/Bluetooth, audio, charging and UFS. Linux lineage `468ab8343364e4d3a267e670fa6a22fd4197a805` is recorded in the prior repack metadata. The inspected `/opt/a51-everline/src` has no Git metadata, so this is not a verified HEAD; individual hashes pin inspected bytes. The retained config selects Mali Bifrost r38p1 and platform `exynos`; other Mali versions in the tree are alternate references.

| Subsystem | Linux reference directory/file | Firmware or unresolved input |
|---|---|---|
| Board/RAM | `arch/arm64/boot/dts/exynos/exynos9610.dts`, `exynos9610-rmem.dtsi`; `arch/arm64/boot/dts/samsung/exynos9611-a51*.dts*` | Retained declarations verified; exact live DT/DTBO selection and runtime/secure/dynamic ownership remain unknown |
| Display | `drivers/video/fbdev/exynos/dpu20/`; A51 panel variants | Exact fitted panel ID not established by wm output |
| Touch | `drivers/input/touchscreen/melfas/mss100/` | Source/config mapping; fitted controller identity still requires live confirmation |
| GPU | `drivers/gpu/arm/bv_r38p1/` and Exynos platform code | G72/Exynos command and power paths; Linux API is not a Darwin user client |
| Wi-Fi/Bluetooth | `drivers/misc/samsung/scsc/`, `drivers/net/wireless/scsc/` | Live `/vendor/etc/wifi/mx140*.bin`, `mx140*.hcf`, regulatory database and platform.txt |
| Audio | `sound/soc/samsung/abox/`, RT5665/RT5510 codec code | ABOX firmware listing under `/vendor/firmware` was denied |
| Charging | `drivers/battery_v2/sm5713*.c`, matching PMIC DTS | Source/config mapping; fitted charger/fuel-gauge revisions pending |
| UFS | `drivers/scsi/ufs/ufs-exynos.c` and related platform/PHY definitions | Real partition/memory/controller state must be reconfirmed for loader work |

The live firmware-name query partially succeeded: Wi-Fi/Bluetooth configuration locations were visible but `/vendor/firmware` was denied. No firmware extraction or redistribution occurred. A complete firmware inventory and hashes remain pending privileged access. Do not count a source/config option as independent proof of a fitted peripheral.

The [retained-source trace](SOURCE-TRACE.md) passed 35 guards per host and original-byte replay of 28 sources/40 excerpts, three base FDTs and 22 symbols in 82 indexed files. It added no live observation. KASLR's saved x1–x3, conditional mode-0400 FDT export (possibly after Linux seed removal), disabled DEBUG_FS memory exports and conditional reset/log initialization leave actual entry, ownership, retrieval and return unresolved. The retained tree's legacy `arm,psci`/`smc` binding is a source declaration, not a measured firmware version or reset capability.

## Reconnected inventory

Run `20261110T162731694328Z-device-inventory-reconnected` completed at 21:57 IST after the user confirmed connection and unlock. All 19 basic queries returned exit 0. The immutable inventory is [20261110T162732057411Z.json](PUBLICATION.md). The run's `project-scripts/inventory.py` retains the executed query list.

Model, SoC, bootloader, ROM, running kernel, display dimensions and total RAM agree with the earlier capture. At this later observation, MemAvailable was 1,193,976 KiB (about 1.14 GiB); battery service reported 94%, 4.303 V, 32.3 °C and USB charging. These are transient Android readings, not measurements under XNU. Boot-state properties still report locked/green, and `ro.boot.hardware.revision` is still empty. No reboot, bootloader operation or partition write was used.

## Privileged observations, 11 November at 12:45–12:46 IST

The [selected live report](LIVE-OBSERVATIONS.md) verifies Shell root and one unchanged Linux-exported FDT, 224,774 bytes/1,087 nodes; model `Samsung A51 EUR OPEN REV02 based on Exynos9611`, compatible `samsung,armv8` and `samsung,exynos9610`. Independent libfdt agrees. Exact firmware fixups and overlay index remain unproved.

Live declared RAM totals 6,327,107,584 bytes in five spans: `[0x80000000,0xBAB00000)`, `[0xC0000000,0xE0000000)`, `[0xE1900000,0x100000000)`, `[0x880000000,0x900000000)` and `[0x900000000,0x980000000)`. MemTotal is 5,707,016 KiB; transient MemAvailable 2,315,972 KiB; CMA total 135,168 KiB/free 0. Iomem exposes real kernel code/data addresses but no verified available/secure/dynamic ownership. Initrd is declared at `[0x89000000,0x89143800)`.

Boot/DTBO/recovery sizes and SHA-256 match the retained installed boot/original DTBO/original recovery inputs. This does not demonstrate restoration. Existing Android console-ramoops/filtered previous last_kmsg were read; no new payload ran. Live kexec and DEBUG_FS are disabled. Five unavailable interfaces have retained true failures; root availability does not make them usable or establish a no-flash launch.
