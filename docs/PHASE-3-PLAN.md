> Publication note: this is a historical workspace document. Current completion decisions are in [PUBLIC-STATUS.md](PUBLIC-STATUS.md); raw local evidence is described in [PUBLICATION.md](PUBLICATION.md).

# Phase 3 Implementation Plan: Boot Minimal XNU from RAM

Created: 13 November 2026.
Target device: Samsung Galaxy A51 (`SM-A515F` / Exynos 9611).

## Objectives
1. Define the Exynos 9611 platform architecture, memory mapping, and Darwin `boot_args`.
2. Configure the A51 device profile (`devices/a51`) in the HakiOS kernel tree.
3. Implement the freestanding ARM64 Mach-O loader / trampoline bridging from Phase 2 early entry to XNU `start_first_cpu`.
4. Bring up early Exynos 9611 UART console logging (`kprintf` at `0x13820000`).
5. Boot minimal XNU on Core 0 with a RAM root filesystem (`ramdisk`) running process 1 (`hello` user program).
6. Verify three consecutive device runs with repeatable log retrieval and clean restoration to baseline Android.

---

## Physical DRAM Memory Map (Exynos 9611)

On the Samsung Galaxy A51, the primary DRAM bank begins at `0x80000000`:

| Physical Address Span | Size | Purpose |
|---|---|---|
| `0x80000000` – `0x80080000` | 512 KB | Firmware & exception vector preservation |
| `0x80080000` – `0x80200000` | ~1.5 MB | Phase 2 / Phase 3 Entry Loader & Trampoline |
| `0x80200000` – `0x80210000` | 64 KB | Darwin `struct boot_args` & command line |
| `0x80210000` – `0x80400000` | ~1.9 MB | Flattened Apple Device Tree (`DeviceTreeP`) |
| `0x83000000` – `0x84000000` | 16 MB | XNU Mach-O Kernel (`hakios-kernel`, `KERNEL_LINK_OFFSET = 48MB`) |
| `0x84000000` – `0x85000000` | 16 MB | Early RAM Disk (`ramdisk` with PID 1 user program) |
| `0x85000000` – `0xC0000000` | ~944 MB | XNU Dynamic Memory Pool (`physBase` to `memSize`) |
| `0xED000000` – `0xF5A00000` | 138 MB | **EXCLUDED** Modem Memory (Protected) |

---

## Hardware Handoff & Register Contract

Samsung S-Boot hands off execution with:
- `CurrentEL` = **EL1** (verified in Phase 2)
- `SCTLR_EL1` = `0x30c5083a` (MMU = 0, D-Cache = 0, I-Cache = 1)
- `DAIF` = `0x2c0` (IRQ, FIQ, Debug masked; SError unmasked)
- `CNTFRQ_EL0` = 26,000,000 Hz (26 MHz)
- `MIDR_EL1` = `0x410fd034` (Cortex-A53 Core 0)

### Handoff to XNU (`start_first_cpu`):
- `x0` = Physical pointer to `struct boot_args` (`0x80200000`)
- `DAIF` = `0x3c0` (all interrupts masked)
- `SCTLR_EL1` = MMU off, caches off
- PC = Entry point from Mach-O `LC_UNIXTHREAD` / `start_first_cpu`

---

## Deliverables & Milestones
- **P3-001**: Device profile `devices/a51` and `configs/a51_defconfig` passing `tools/hakios-device.py check`.
- **P3-002**: Standalone Mach-O segment loader & `boot_args` generator.
- **P3-003**: Apple Device Tree (`DeviceTreeP`) builder for Exynos 9611.
- **P3-004**: Exynos 9611 early UART driver (`0x13820000`) in XNU.
- **P3-005**: RAM disk packing and first XNU boot on silicon reaching user program.
- **P3-006**: Stability, 3-run verification, and baseline Android restoration.

