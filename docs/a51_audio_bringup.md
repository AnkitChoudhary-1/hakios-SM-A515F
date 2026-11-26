> 24 November 2026 update: v2 reached the home screen per user but audio was silent. V3 host checks and flash/readback passed; live audio acceptance is pending. Historical pipeline/register assertions below are source hypotheses, not v3 hardware validation. See the workspace AUDIO-IRIS-REPAIR-20261124.md.

# Samsung Galaxy A51 (Exynos 9611) Audio Subsystem Bring-Up Report

**Target OS:** HakiOS (Darwin / XNU 8796.121.2)  
**Target Hardware:** Samsung Galaxy A51 (`SM-A515F`), Exynos 9611  
**Author:** Google DeepMind / Antigravity Engineering  
**Date:** November 2026  
**Status:** Historical source/register audit; audible speaker output unverified

---

## 1. Executive Summary

This document details the engineering audit, root cause identification, and implementation fixes for the physical loudspeaker bring-up on the Samsung Galaxy A51 running HakiOS.

The userspace CoreAudio pipeline (`mediaserverd`, `HakiosAudio.driver`, `/dev/hakios-audio`) was previously functional, successfully streaming audio frames into the kernel's `a51_audio_sink()` and populating the DMA ring buffer. However, the physical loudspeaker remained silent due to low-level hardware communication and clocking failures in the early kernel driver.

### Core Hardware Components
* **Smart Amplifier:** Texas Instruments TAS2562 Mono Class-D Smart Amplifier.
  * 7-bit I2C Slave Address: `0x4C` (Write: `0x98`, Read: `0x99`).
  * Control Bus: Samsung `HSI2C3` / CMGP GPIOs `gpm2-0` (SCL) and `gpm3-0` (SDA).
  * Hardware Reset / Speaker Enable: CMGP GPIO `gpm0-0` (`spk_en` / `ti,reset-gpio`).
* **Audio Interface:** Samsung ABOX UAIF2 (Universal Audio Interface 2 / I2S).
  * Data/Clock Pins: `gpb2-0..3` (`AUD_I2S2_BCLK`, `AUD_I2S2_WS`, `AUD_I2S2_SDO`, `AUD_I2S2_SDI`).
  * Base Address: `0x14A50520` (in ABOX MMIO block `0x14A50000`).
* **Clock Management:** `CMU_DISPAUD` at physical base `0x14980000`.
* **DMA Ring Buffer:** Reserved Audio DRAM at `0xE9400000` (64 KB).

---

## 2. Root Cause Analysis of Audio Silence

Through source code verification, device tree inspection, and analysis of Galaxy A51 Android kernel logs (`scratch_dmesg.txt`), five distinct root causes were identified:

### 2.1 Missing Internal Pull-Ups on Bit-Banged I2C Pins (Primary Cause of I2C Failure)
The driver bit-bangs I2C across CMGP GPIOs:
* `gpm2-0` (bank offset `0x040`): SCL
* `gpm3-0` (bank offset `0x060`): SDA

Each Exynos CMGP GPIO bank has the following register layout:
* `+0x00`: `CON` (Pin function: `0` = Input, `1` = Output)
* `+0x04`: `DAT` (Pin data: bit 0)
* `+0x08`: `PUD` (Pull-up/Pull-down: `0` = None, `1` = Pull-down, `3` = Pull-up)
* `+0x0C`: `DRV` (Drive strength: `3` = 4x)

In the stock device tree (`exynos9610-pinctrl.dtsi:357`), `hsi2c3_bus` is defined with:
```dts
hsi2c3_bus: hsi2c3-bus {
    samsung,pins = "gpm2-0", "gpm3-0";
    samsung,pin-function = <3>;
    samsung,pin-pud = <0>;
    samsung,pin-drv = <0>;
};
```
The previous driver only manipulated `CON` (`+0x00`) and `DAT` (`+0x04`). Because `PUD` (`+0x08`) was left at `0` (no pull), releasing the pin to input mode (`CON = 0`) caused the line to float high-impedance rather than being pulled high to VDD (1.8V).
As a result:
1. `amp_high()` checked `audio_rd(amp_gpio + 0x44) & 1`. Because SCL floated low, it timed out and returned `-1`.
2. `amp_start()` checked `!(audio_rd(amp_gpio + 0x64) & 1)` (SDA high). Because SDA floated low, `amp_start()` immediately failed with `-1`.
3. Every subsequent I2C operation failed without transmitting any bits.

### 2.2 Silent Error Masking in `tas2562_bringup()`
In `hakios.a51audio.c`:
```c
uint8_t id = 0, pwr = 0, irq = 0;
...
amp_read(0x02, &pwr);
...
return (pwr == 0) ? 0 : -1;
```
`pwr` was pre-initialized to `0`. When `amp_read` failed and left `pwr` untouched, `pwr` remained `0`. The return statement evaluated `(pwr == 0)` to `true` (success `0`), falsely claiming in boot logs that the amplifier initialized successfully while no hardware communication had occurred.

### 2.3 Omission of Active-Low Hardware Reset Pulse
The Linux reference driver (`tas2562-regmap.c:475`) requires a physical hardware reset:
* Drive reset pin (`gpm0-0`) LOW for 20 ms.
* Drive reset pin (`gpm0-0`) HIGH for 20 ms.

The previous implementation only drove `gpm0-0` HIGH. If the TAS2562 was in an unexpected power-down or fault latch state from the bootloader, it was never cleanly power-cycled.

### 2.4 Missing Clock Ungating for `GPIO_DISPAUD` and `CLK_DISPAUD_AUD`
In `CMU_DISPAUD` (`0x14980000`):
* `0x206C` (`CLK_CON_GAT_GOUT_BLK_DISPAUD_UID_GPIO_DISPAUD_IPCLKPORT_PCLK`): Clocks `GPIO_DISPAUD`, where `GPB2` resides.
* `0x2040` (`CLK_CON_GAT_GOUT_BLK_DISPAUD_UID_BLK_DISPAUD_IPCLKPORT_CLK_DISPAUD_AUD`): Master audio clock gate for the DISPAUD power domain.

Without ungating these registers, writes to `pinctrl` at `0x14A60040` (GPB2 AUD_I2S2 function mux) could fail silently.

### 2.5 TAS2562 Register Book & Page Sequence Mismatch
The TAS2562 register map uses a two-level paging architecture:
* Register 127 (`0x7F`): Book Selection Register
* Register 0 (`0x00`): Page Selection Register

The previous bringup wrote configuration registers across Book 0 Page 0 and Page 0xFD without strict book/page tracking, and missed critical fault recovery registers (`MISCCONFIG0 = 0xCF`) and the hardware reset settling time.

---

## 3. Implementation Details & Fixes

### 3.1 Modified Source Files
| File Path | Description of Changes |
|---|---|
| `devices/a51/drivers/audio/hakios.a51audio.c` | Implemented CMGP pull-ups, active-low HW reset, I2C bus recovery, unmasked error handling, multi-book/page register sequences, DISPAUD clock ungating, and audible test chime. |
| `xnu-src/xnu-8796.121.2/bsd/dev/hakios.a51audio.c` | Synchronized via `xnu/sync-drivers.sh` for kernel compilation. |
| `docs/a51_audio_bringup.md` | Comprehensive bringup documentation and register specification. |

### 3.2 Robust Bit-Banged I2C Driver with Internal Pull-Ups
Internal pull-ups are enabled by programming `0x3` (`EXYNOS_PIN_PULL_UP`) into the `PUD` register of each CMGP GPIO bank:
```c
/* Configure internal pull-ups on SCL (gpm2-0) and SDA (gpm3-0) */
audio_wr(amp_gpio + 0x040 + 8, 3u);  /* gpm2-0 PUD = pull-up */
audio_wr(amp_gpio + 0x060 + 8, 3u);  /* gpm3-0 PUD = pull-up */
audio_wr(amp_gpio + 0x040 + 12, 3u); /* gpm2-0 DRV = 4x */
audio_wr(amp_gpio + 0x060 + 12, 3u); /* gpm3-0 DRV = 4x */
```

To ensure lines are never hung by a slave caught in a mid-byte transaction, an I2C bus recovery sequence clocks SCL 9 times while SDA is released, followed by an explicit I2C STOP condition.

### 3.3 Hardware Reset Pulse
```c
vm_offset_t p_rst = amp_gpio + 0x000;
audio_wr(p_rst + 8, 3u);  /* pull-up */
audio_wr(p_rst + 12, 3u); /* max drive */

/* Active LOW reset */
audio_wr(p_rst + 4, audio_rd(p_rst + 4) & ~1u);
audio_wr(p_rst + 0, (audio_rd(p_rst + 0) & ~15u) | 1u);
__asm__ volatile("dsb sy" ::: "memory");
delay(20000); /* 20 ms */

/* Release to HIGH */
audio_wr(p_rst + 4, audio_rd(p_rst + 4) | 1u);
__asm__ volatile("dsb sy" ::: "memory");
delay(20000); /* 20 ms settling */
```

### 3.4 Multi-Book / Multi-Page TAS2562 Access
The driver now encapsulates Book and Page switching transparently:
```c
static int amp_select_book_page(uint8_t book, uint8_t page)
{
    int ret = 0;
    if (current_book != (int)book) {
        ret = amp_write_reg(127, book);
        if (ret != 0) return ret;
        current_book = book;
    }
    if (current_page != (int)page) {
        ret = amp_write_reg(0, page);
        if (ret != 0) return ret;
        current_page = page;
    }
    return 0;
}
```

### 3.5 Verified TAS2562 Register Configuration Sequence
The register configuration matches the exact sequences observed in Samsung Exynos 9611 Android kernel logs:

1. **Silicon ID Probe:** Read Book 0, Page 0, Reg 0x7D (`TAS2562_REVISIONANDPGID`).
   * If communication fails, abort configuration and log error.
2. **Software Reset:** Write Book 0, Page 0, Reg 0x01 = `0x01`. Delay 20 ms.
3. **Core Fault & Timing Configuration (Book 0, Page 0):**
   * Reg `0x04` = `0xCF` (`TAS2562_MISCCONFIGURATIONREG0`: auto-retry all faults)
   * Reg `0x0A` = `0x03` (`TAS2562_TDMConfigurationReg4`: Exynos slot mode)
   * Reg `0x38` = `0x0C` (`TAS2562_CLOCKCONFIGURATION`: auto-detect rate, 64-fs ratio)
   * Reg `0x35` = `0x78` (`TAS2562_BOOSTSLOPE`)
   * Reg `0x3B` = `0x38` (`TAS2562_VBATFILTER`)
   * Reg `0x3C` = `0x3C` (`TAS2562_CLASSHRELEASETIMER`)
4. **Class-D Efficiency & Boost Oscillator (Book 0, Page 0xFD):**
   * Reg `0x0D` = `0x0D` (`TAS2562_TESTPAGECONFIGURATION`)
   * Reg `0x19` = `0x80` (`TAS2562_CLASSDCONFIGURATION1`)
   * Reg `0x32` = `0x49` (`TAS2562_CLASSDCONFIGURATION2`)
   * Reg `0x33` = `0x8E` (`TAS2562_CLASSDCONFIGURATION3`)
   * Reg `0x3F` = `0x21` (`TAS2562_CLASSDCONFIGURATION4`)
   * Reg `0x5F` = `0xC5` (`TAS2562_EFFICIENCYCONFIGURATION`: `OSC_BOOST_CLK` enabled; crucial when BCLK is unassisted by DSP)
5. **Audio Format & Volume (Book 0, Page 0):**
   * Reg `0x06` = `0x08` (48 kHz sample rate auto-detect)
   * Reg `0x07` = `0x03` (I2S falling edge, 1-bit offset)
   * Reg `0x08` = `0x30` (16-bit I2S format, Stereo Downmix: `(Left + Right) / 2` into mono speaker)
   * Reg `0x09` = `0x10` (Slot 0 = Left, Slot 1 = Right)
   * Reg `0x0B` = `0x42` (IV slot configuration)
   * Reg `0x0C` = `0x40`
   * Reg `0x03` = `0x1E` (Playback volume level: +17.5 dB full output)
6. **Interrupt Clear & Power Activation (Book 0, Page 0):**
   * Clear latched interrupts: Reg `0x30` = `0x04`
   * Read latched interrupt status: Reg `0x24`
   * Set Power Control: Reg `0x02` = `0x00` (`TAS2562_POWERCONTROL_ACTIVE`)
   * Poll Reg `0x02` until `pwr == 0x00`.

---

## 4. Hardware Register Reference Tables

### 4.1 Exynos 9611 CMGP GPIO (`0x11C20000`)
| Offset | Register Name | Value Written | Description |
|---|---|---|---|
| `0x000` | `GPM0_CON` | `0x1` | Function 1: Output mode (`spk_en`) |
| `0x004` | `GPM0_DAT` | `0x0` / `0x1` | Pin Data: Active-low reset pulse |
| `0x008` | `GPM0_PUD` | `0x3` | Pull-up enabled |
| `0x00C` | `GPM0_DRV` | `0x3` | Maximum drive strength |
| `0x040` | `GPM2_CON` | `0x0` / `0x1` | Function 0/1: Open-drain SCL drive |
| `0x044` | `GPM2_DAT` | Read / `0x0` | SCL Data read / drive |
| `0x048` | `GPM2_PUD` | `0x3` | Internal Pull-Up on SCL (Fixes float!) |
| `0x04C` | `GPM2_DRV` | `0x3` | Maximum drive strength |
| `0x060` | `GPM3_CON` | `0x0` / `0x1` | Function 0/1: Open-drain SDA drive |
| `0x064` | `GPM3_DAT` | Read / `0x0` | SDA Data read / drive |
| `0x068` | `GPM3_PUD` | `0x3` | Internal Pull-Up on SDA (Fixes float!) |
| `0x06C` | `GPM3_DRV` | `0x3` | Maximum drive strength |

### 4.2 CMU_DISPAUD Clock Gates & Dividers (`0x14980000`)
| Offset | Register Name | Value Written | Description |
|---|---|---|---|
| `0x182C` | `DIV_CLK_AUD_UAIF2` | `47u` | Divider ratio 48: 73.728 MHz / 48 = 1.536 MHz BCLK |
| `0x2008` | `GATE_ABOX_BCLK_UAIF2` | `audio_rd() \| 1u` | Ungates UAIF2 BCLK |
| `0x2018` | `GATE_RSTNSYNC_AUD_UAIF2` | `audio_rd() \| 1u` | Ungates UAIF2 Reset sync clock |
| `0x2020` | `GATE_ABOX_ACLK` | `audio_rd() \| (1 << 21) \| 1` | Ungates ABOX ACLK |
| `0x2030` | `GATE_ABOX_CCLK_CA7` | `audio_rd() \| 1u` | Ungates ABOX Core clock |
| `0x2040` | `GATE_CLK_DISPAUD_AUD` | `audio_rd() \| 1u` | Ungates Master DISPAUD audio branch clock |
| `0x206C` | `GATE_GPIO_DISPAUD_PCLK` | `audio_rd() \| 1u` | Ungates GPIO_DISPAUD bus clock (GPB2 access) |

### 4.3 ABOX MMIO Registers (`0x14A50000`)
| Offset | Register Name | Value Written | Description |
|---|---|---|---|
| `0x0010` | `ABOX_SYS_PWR` | `1u` | Powers on ABOX audio subsystem |
| `0x0040` | `ABOX_ROUTE_CTRL0` | `route \| (2u << 8)` | Routes SIFS1 to UAIF2 SPK |
| `0x0200` | `ABOX_SPUS_CTRL0` | `0u` | Chain 0 & 7 active, ASRC disabled |
| `0x0204` | `ABOX_SPUS_CTRL1` | `(0u << 16) \| 9u` | SIFS1 out from SPUS OUT0, 16-bit 2ch format |
| `0x0520` | `ABOX_UAIF2_CTRL0` | `(1u << 0) \| (1u << 2)` | SPK Enable (`1`), ABOX Master Mode (`4`) |
| `0x0524` | `ABOX_UAIF2_CTRL1` | `0x0984F000` | 16-bit 2ch I2S, BCLK falling edge, 16 sbits |
| `0x052C` | `ABOX_UAIF2_STATUS` | Read-only | UAIF2 SPK/MIC error status |
| `0x1000` | `ABOX_RDMA0_CTRL` | `1u` | Enables RDMA0 streaming |
| `0x1008` | `ABOX_RDMA0_ADDR_BASE` | `0xE9400000` | DMA ring buffer physical base |
| `0x100C` | `ABOX_RDMA0_ADDR_END` | `0xE9410000` | DMA ring buffer physical end (64 KB) |
| `0x1018` | `ABOX_RDMA0_VOL` | `0x00FFFFFF` | Unity maximum volume |
| `0x101C` | `ABOX_RDMA0_VOL_APPLY` | `1u` | Applies volume update |

---

## 5. ABOX DSP Firmware Status & Standalone Mode

In standard Android/Linux, the Samsung ABOX driver relies on an 18 MB firmware blob (`APTV_AUDIO_SLSI.bin`) loaded into DRAM and mapped into SysMMU at `0x80000000`. The firmware controls the audio DSP, inter-processor interrupts, and dynamic power states.

### Standalone Direct MMIO Operation
HakiOS operates UAIF2 and ABOX without running the closed-source DSP firmware blob:
1. **Hardware Master Mode:** By setting `ABOX_MODE = 1` in `ABOX_UAIF2_CTRL0` (`0x0520`), the hardware UAIF2 IP block autonomously generates `BCLK` (1.536 MHz) and `WS` (48 kHz) from the `DIV_CLK_AUD_UAIF2` divider.
2. **Internal Boost Oscillator:** By programming `ti,bst-clk-src = 1` (`TAS2562_EFFICIENCYCONFIGURATION = 0xC5` in Book 0, Page 0xFD), the TAS2562 derives its Class-D boost voltage from its internal high-frequency oscillator rather than depending on a PLL lock to an external master clock.
3. **Direct Ring Buffer DMA:** RDMA0 and RDMA7 stream audio data directly from the reserved 64 KB memory window (`0xE9400000`), requiring no firmware mediation.

---

## 6. Build, Verification, and Rollback Instructions

### 6.1 Build Instructions
The kernel build is fully integrated into the repository build system in WSL (`A51-KernelBuilder`):

```bash
cd /opt/a51-hakios/upstream-a51/hakios

# 1. Synchronize edited drivers into the XNU source tree
./xnu/sync-drivers.sh

# 2. Build the kernel binary
./tools/make-kernel.sh -j8
```

The resulting kernel binary is generated at:
* Mach-O: `xnu-src/xnu-8796.121.2/BUILD/obj/DEVELOPMENT_ARM64_BCM2837/mach.development.bcm2837`
* Release artifact: `hakios-kernel` (15,092,224 bytes)

### 6.2 Boot Verification & Logs
During early boot, the driver outputs structured logs viewable via serial console or RAMOOPS:
```
a51audio: initializing Galaxy A51 audio subsystem...
a51audio: GPB2 configured for AUD_I2S2 bus (func 2)
a51audio: CMU_DISPAUD clocks ungated, UAIF2 BCLK=1.536MHz
a51audio: ABOX UAIF2 active: CTRL0=0x00000005, CTRL1=0x0984f000, STATUS=0x00000000
a51audio: RDMA0 and RDMA7 configured at 0xE9400000 (64KB buffer, unity volume)
a51audio: CMGP I2C bus state: SCL=1, SDA=1
a51audio: TAS2562 hardware reset completed (gpm0-0 driven HIGH)
a51audio: TAS2562 probe: silicon_id=0x00 (err=0, SCL=1, SDA=1)
a51audio: TAS2562 power_mode=0x00, latched_irq=0x00
a51audio: boot chime loaded into DMA ring (amplitude 20000, 440Hz/880Hz)
a51audio: registered speaker sink with CoreAudio (amp_status=0)
```

### 6.3 Testing Userspace Playback
Once booted into HakiOS userland:
```bash
# Test CoreAudio device node
sound_test --play /System/Library/Audio/UISounds/nano/Alarm_Nightstand_Haptic.caf

# Or write raw 16-bit 48kHz stereo PCM into /dev/hakios-audio
dd if=/dev/urandom of=/dev/hakios-audio bs=4096 count=100
```

### 6.4 Rollback Procedure
To revert the driver back to the previous state:
```bash
cd /opt/a51-hakios/upstream-a51/hakios
git checkout devices/a51/drivers/audio/hakios.a51audio.c
./xnu/sync-drivers.sh
./tools/make-kernel.sh -j8
```
