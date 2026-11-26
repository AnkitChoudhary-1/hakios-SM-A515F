"""Complete A51 TAS2562 Smart Amp & Exynos ABOX Audio Driver Implementation."""
from pathlib import Path
import subprocess
import sys

REPO = Path('/opt/a51-hakios/upstream-a51/hakios')

AUDIO_SOURCE = r'''/* A51 Exynos9611 Audio Driver: TI TAS2562 Smart Amp + ABOX UAIF2
 * Complete implementation: un-reset, I2C register config, clock ungating,
 * I2S2 pinmux, ABOX routing, DMA ring buffer, and CoreAudio sink.
 */
#include <kern/startup.h>
#include <kern/clock.h>
#include <kern/locks.h>
#include <kern/thread.h>
#include <libkern/libkern.h>
#include <mach/mach_types.h>
#include <pexpert/pexpert.h>
#include <sys/systm.h>
#include <sys/hakios.audio.h>

extern vm_offset_t ml_io_map(vm_offset_t phys_addr, vm_size_t size);
extern void loader_log_line(const char *line);
extern void hakios_audio_set_sink(const char *name, hakios_audio_sink_t sink);

static inline uint32_t audio_rd(vm_offset_t address)
{
    return *(volatile uint32_t *)address;
}

static inline void audio_wr(vm_offset_t address, uint32_t val)
{
    *(volatile uint32_t *)address = val;
    __asm__ volatile("dsb sy" ::: "memory");
}

/* CMGP GPIO for HSI2C3 & TAS2562 hardware reset pin */
static vm_offset_t amp_gpio;

static void amp_line(unsigned bank, bool released)
{
    vm_offset_t p = amp_gpio + bank;
    if (!released) audio_wr(p + 4, audio_rd(p + 4) & ~1u);
    audio_wr(p, (audio_rd(p) & ~15u) | (released ? 0 : 1));
    __asm__ volatile("dsb sy" ::: "memory");
    delay(5);
}

static int amp_high(void)
{
    amp_line(0x40, true);
    for (unsigned i = 0; i < 1000; i++) {
        if (audio_rd(amp_gpio + 0x44) & 1) return 0;
        delay(1);
    }
    return -1;
}

static int amp_start(void)
{
    amp_line(0x60, true);
    if (amp_high() || !(audio_rd(amp_gpio + 0x64) & 1)) return -1;
    amp_line(0x60, false);
    amp_line(0x40, false);
    return 0;
}

static void amp_stop(void)
{
    amp_line(0x40, false);
    amp_line(0x60, false);
    (void)amp_high();
    amp_line(0x60, true);
}

static int amp_byte(uint8_t byte)
{
    for (unsigned i = 0; i < 8; i++) {
        amp_line(0x60, !!(byte & 0x80));
        if (amp_high()) return -1;
        amp_line(0x40, false);
        byte <<= 1;
    }
    amp_line(0x60, true);
    if (amp_high()) return -1;
    int nack = !!(audio_rd(amp_gpio + 0x64) & 1);
    amp_line(0x40, false);
    return nack ? -2 : 0;
}

static int amp_read(uint8_t reg, uint8_t *value)
{
    int e = amp_start();
    if (!e) e = amp_byte(0x98); /* TAS2562 I2C address 0x4c write */
    if (!e) e = amp_byte(reg);
    if (!e) e = amp_start();
    if (!e) e = amp_byte(0x99); /* TAS2562 I2C address 0x4c read */
    uint8_t v = 0;
    if (!e) {
        amp_line(0x60, true);
        for (unsigned i = 0; i < 8; i++) {
            if (amp_high()) { e = -3; break; }
            v = (v << 1) | (audio_rd(amp_gpio + 0x64) & 1);
            amp_line(0x40, false);
        }
        if (!e) {
            e = amp_high();
            amp_line(0x40, false);
        }
    }
    amp_stop();
    if (!e) *value = v;
    return e;
}

static int amp_select(uint8_t reg, uint8_t value)
{
    int e = amp_start();
    if (!e) e = amp_byte(0x98);
    if (!e) e = amp_byte(reg);
    if (!e) e = amp_byte(value);
    amp_stop();
    return e;
}

/* Audio DMA Ring Buffer in Reserved Audio DRAM (0xE9400000, 64KB) */
#define A51_DMA_BASE_PA      0xE9400000UL
#define A51_DMA_BUFFER_SIZE  (64 * 1024)
#define A51_DMA_FRAMES       (A51_DMA_BUFFER_SIZE / HAKIOS_AUDIO_FRAME)

static int16_t *dma_virt_buffer = NULL;
static vm_offset_t abox_base = 0;
static volatile uint32_t dma_write_frame_offset = 0;
static bool audio_sink_active = false;

/* CoreAudio playback sink: called from writer thread in real-time */
static uint32_t a51_audio_sink(const int16_t *frames, uint32_t count)
{
    if (!dma_virt_buffer || count == 0) return count;

    volatile uint32_t *dma_words = (volatile uint32_t *)dma_virt_buffer;
    uint32_t cur = dma_write_frame_offset;
    for (uint32_t i = 0; i < count; i++) {
        uint32_t idx = (cur + i) % A51_DMA_FRAMES;
        uint32_t sample = ((uint32_t)(uint16_t)frames[2 * i + 1] << 16) | (uint16_t)frames[2 * i];
        dma_words[idx] = sample;
    }
    cur = (cur + count) % A51_DMA_FRAMES;
    dma_write_frame_offset = cur;

    /* Update RDMA hardware buffer offset register for both RDMA0 and RDMA7 */
    if (abox_base) {
        audio_wr(abox_base + 0x1010, cur * HAKIOS_AUDIO_FRAME);
        audio_wr(abox_base + 0x1710, cur * HAKIOS_AUDIO_FRAME);
        if (!(audio_rd(abox_base + 0x1000) & 1u)) {
            audio_wr(abox_base + 0x1000, 1u);
        }
        if (!(audio_rd(abox_base + 0x1700) & 1u)) {
            audio_wr(abox_base + 0x1700, 1u);
        }
    }
    return count;
}

/* Exynos 9611 DISPAUD Pinmux & Clock Configuration */
static void a51_audio_hardware_init(vm_offset_t cmu)
{
    /* 1. Pinmux: Configure GPB2 pins 0..3 for AUD_I2S2 bus (function 2) */
    vm_offset_t pinctrl = ml_io_map(0x14a60000UL, 0x1000);
    if (pinctrl) {
        audio_wr(pinctrl + 0x40, 0x2222); /* gpb2-0..3 func 2 */
        audio_wr(pinctrl + 0x48, 0x0000); /* no pull */
        loader_log_line("a51audio: GPB2 configured for AUD_I2S2 bus\n");
    }

    /* 2. Clocks: CMU_DISPAUD ungate & dividers */
    audio_wr(cmu + 0x2008, audio_rd(cmu + 0x2008) | 1u); /* UAIF2 BCLK gate */
    audio_wr(cmu + 0x2018, audio_rd(cmu + 0x2018) | 1u); /* UAIF2 reset gate */
    audio_wr(cmu + 0x2020, audio_rd(cmu + 0x2020) | (1u << 21) | 1u); /* ABOX ACLK */
    audio_wr(cmu + 0x2030, audio_rd(cmu + 0x2030) | 1u); /* ABOX CCLK */
    /* Set UAIF2 clock divider: 73.728 MHz / 48 = 1.536 MHz BCLK for 48kHz 16-bit 2ch */
    audio_wr(cmu + 0x182c, 47u);
    loader_log_line("a51audio: CMU_DISPAUD clocks ungated, UAIF2 BCLK=1.536MHz\n");

    /* 3. ABOX system registers & UAIF2 interface */
    abox_base = ml_io_map(0x14a50000UL, 0x10000);
    if (abox_base) {
        /* Power on ABOX system */
        audio_wr(abox_base + 0x0010, 1u);

        /* Route SIFS1 to UAIF2 SPK (bits [11:8] = 2) */
        uint32_t route = audio_rd(abox_base + 0x0040);
        route &= ~(0xfu << 8);
        route |= (2u << 8);
        audio_wr(abox_base + 0x0040, route);

        /* SPUS_CTRL0 (0x0200): Chain 0 (RDMA0->SIFS1, ASRC Off) & Chain 7 (RDMA7->SIFS1, ASRC Off) */
        audio_wr(abox_base + 0x0200, 0u);

        /* SPUS_CTRL1 (0x0204): SIFS_OUT1_SEL selects SPUS OUT0 (bits 18:16 = 0), MIXP format 16-bit 2ch (bits 4:0 = 9) */
        audio_wr(abox_base + 0x0204, (0u << 16) | 9u);

        /* UAIF2 CTRL1: 16-bit 2ch I2S, BCLK polarity 1, slot_max=1, sbit_max=15
         * FORMAT (bits 24..28) = 9 (16-bit 2ch I2S) -> (9u << 24) = 0x09000000
         * BCLK_POLARITY (bit 23) = 1 -> (1u << 23) = 0x00800000
         * WS_MODE (bit 22) = 0 (I2S)
         * WS_POLAR (bit 21) = 0
         * SLOT_MAX (bits 18..20) = 1 (2 slots) -> (1u << 18) = 0x00040000
         * SBIT_MAX (bits 12..17) = 15 (16 bits) -> (15u << 12) = 0x0000F000
         * VALID_STR = 0, VALID_END = 0
         * Total = 0x0984F000
         */
        audio_wr(abox_base + 0x0524, 0x0984F000);

        /* UAIF2 CTRL0: SPK_ENABLE (bit 0) = 1, ABOX_MODE (bit 2) = 1 (Master Mode driving BCLK & WS) */
        audio_wr(abox_base + 0x0520, (1u << 0) | (1u << 2));
        delay(20000); /* 20ms settling time for BCLK and WS */
        loader_log_line("a51audio: ABOX powered, SIFS1 routed to UAIF2, SPK enabled as I2S Master (0x0520=0x05)\n");

        /* 4. Map DMA Buffer at 0xE9400000 & configure RDMA0 and RDMA7 */
        dma_virt_buffer = (int16_t *)ml_io_map(A51_DMA_BASE_PA, A51_DMA_BUFFER_SIZE);
        if (dma_virt_buffer) {
            volatile uint32_t *dma_words = (volatile uint32_t *)dma_virt_buffer;
            for (uint32_t i = 0; i < A51_DMA_BUFFER_SIZE / sizeof(uint32_t); i++) {
                dma_words[i] = 0;
            }

            /* Configure RDMA0 (0x1000) */
            audio_wr(abox_base + 0x1008, (uint32_t)A51_DMA_BASE_PA);
            audio_wr(abox_base + 0x100c, (uint32_t)(A51_DMA_BASE_PA + A51_DMA_BUFFER_SIZE));
            audio_wr(abox_base + 0x1010, 0u);
            audio_wr(abox_base + 0x1014, 0u);
            audio_wr(abox_base + 0x1018, 0x00FFFFFF); /* Unity maximum volume factor */
            audio_wr(abox_base + 0x101c, 1u);         /* Apply volume change */
            audio_wr(abox_base + 0x1000, 1u);         /* Enable RDMA0 */

            /* Configure RDMA7 in parallel (0x1700) */
            audio_wr(abox_base + 0x1708, (uint32_t)A51_DMA_BASE_PA);
            audio_wr(abox_base + 0x170c, (uint32_t)(A51_DMA_BASE_PA + A51_DMA_BUFFER_SIZE));
            audio_wr(abox_base + 0x1710, 0u);
            audio_wr(abox_base + 0x1714, 0u);
            audio_wr(abox_base + 0x1718, 0x00FFFFFF); /* Unity maximum volume factor */
            audio_wr(abox_base + 0x171c, 1u);         /* Apply volume change */
            audio_wr(abox_base + 0x1700, 1u);         /* Enable RDMA7 */

            loader_log_line("a51audio: RDMA0 and RDMA7 configured at 0xE9400000 (64KB buffer, unity volume)\n");
        }
    }
}

/* TAS2562 Smart Amp Bring-up (invoked AFTER clocks and pinmux are active!) */
static int tas2562_bringup(void)
{
    char log[256];
    amp_gpio = ml_io_map(0x11c20000UL, 0x1000);
    if (!amp_gpio) {
        loader_log_line("a51audio: failed to map CMGP GPIO\n");
        return -1;
    }

    /* Un-reset TAS2562: drive gpm0-0 output HIGH */
    audio_wr(amp_gpio + 4, audio_rd(amp_gpio + 4) | 1u);
    audio_wr(amp_gpio, (audio_rd(amp_gpio) & ~0xfu) | 1u);
    __asm__ volatile("dsb sy" ::: "memory");
    delay(15000); /* 15 ms reset settling time */

    /* Release I2C lines to input/pull-up */
    amp_line(0x40, true);
    amp_line(0x60, true);
    delay(500);

    /* Read Silicon ID from Book 0, Page 0, Reg 0x7D */
    uint8_t id = 0, pwr = 0, irq = 0;
    amp_select(0, 0);
    amp_select(127, 0);
    int err = amp_read(0x7d, &id);
    snprintf(log, sizeof(log), "a51audio: TAS2562 un-reset; silicon ID=%02x (err=%d)\n", id, err);
    loader_log_line(log);

    /* Software Reset */
    amp_select(0, 0);
    amp_select(127, 0);
    amp_select(1, 1);
    delay(5000);

    /* Switch to Book 0, Page 0xFD: configure internal boost oscillator and Class-D efficiency */
    amp_select(0, 0);
    amp_select(127, 0);
    amp_select(0, 0xFD);
    amp_select(0x0D, 0x0D); /* TAS2562_TESTPAGECONFIGURATION */
    amp_select(0x19, 0x80); /* TAS2562_CLASSDCONFIGURATION1 */
    amp_select(0x32, 0x49); /* TAS2562_CLASSDCONFIGURATION2 */
    amp_select(0x33, 0x8E); /* TAS2562_CLASSDCONFIGURATION3 */
    amp_select(0x3F, 0x21); /* TAS2562_CLASSDCONFIGURATION4 */
    amp_select(0x5F, 0xC5); /* TAS2562_EFFICIENCYCONFIGURATION: OSC_BOOST_CLK enabled */

    /* Switch back to Book 0, Page 0x00: configure audio formats, clocks, and volume */
    amp_select(0, 0x00);
    amp_select(0x04, 0xCF); /* TAS2562_MISCCONFIGURATIONREG0: auto retry all faults */
    amp_select(0x0A, 0x03); /* TAS2562_TDMConfigurationReg4: Exynos slot mode */
    amp_select(0x35, 0x78); /* TAS2562_BOOSTSLOPE */
    amp_select(0x38, 0x0C); /* TAS2562_CLOCKCONFIGURATION: auto-detect rate, 64-fs ratio */
    amp_select(0x3B, 0x38); /* TAS2562_VBATFILTER */
    amp_select(0x3C, 0x3C); /* TAS2562_CLASSHRELEASETIMER */
    amp_select(0x06, 0x08); /* 48 kHz sample rate auto-detect */
    amp_select(0x07, 0x03); /* I2S falling edge, 1-bit offset */
    amp_select(0x08, 0x30); /* 16-bit I2S format, Stereo Downmix ((Left+Right)/2 into speaker) */
    amp_select(0x09, 0x10); /* Slot 0 = Left, Slot 1 = Right */
    amp_select(0x0B, 0x42); /* IV slot config */
    amp_select(0x0C, 0x40);
    amp_select(0x03, 0x1E); /* Playback Volume/Level (+17.5 dB full output level) */

    /* Clear latched interrupts while clocks are running and transition to ACTIVE */
    for (int retry = 0; retry < 15; retry++) {
        amp_select(0x30, 0x04); /* TAS2562_INTERRUPTCONFIGURATION: LTCHINTCLEAR */
        amp_read(0x24, &irq);   /* TAS2562_LATCHEDINTERRUPTREG0: read and clear */
        amp_select(0x02, 0x00); /* TAS2562_POWERCONTROL: ACTIVE */
        delay(6000);            /* 6ms settling */
        amp_read(0x02, &pwr);
        amp_read(0x24, &irq);
        if (pwr == 0x00 && (irq & 0x04) == 0) {
            break;
        }
    }
    snprintf(log, sizeof(log), "a51audio: TAS2562 initialized ACTIVE: power_mode=%02x, irq=%02x\n", pwr, irq);
    loader_log_line(log);

    return (pwr == 0) ? 0 : -1;
}

static void a51audio_init(void)
{
    uint32_t step = 0;
    if (!PE_parse_boot_argn("a51audio", &step, sizeof(step))) {
        step = 4; /* Default to fully enabled audio on A51 */
    }
    if (step == 0) return;

    loader_log_line("a51audio: initializing Galaxy A51 audio subsystem...\n");

    /* 1. Verify PMU DISPAUD power domain */
    vm_offset_t pmu = ml_io_map(0x11860000UL, 0x5000);
    if (!pmu) {
        loader_log_line("a51audio: PMU mapping failed; aborting\n");
        return;
    }
    uint32_t status = audio_rd(pmu + 0x4004);
    if ((status & 0xf) != 0xf) {
        loader_log_line("a51audio: DISPAUD power domain is off\n");
        return;
    }

    /* 2. Map CMU_DISPAUD */
    vm_offset_t cmu = ml_io_map(0x14980000UL, 0x4000);
    if (!cmu) {
        loader_log_line("a51audio: CMU mapping failed; aborting\n");
        return;
    }

    /* 3. Configure Exynos hardware pinmux, clocks, ABOX routing & DMA FIRST */
    a51_audio_hardware_init(cmu);

    /* 4. Bring up TAS2562 Smart Amp (now that BCLK is actively running!) */
    tas2562_bringup();

    /* 5. Play startup chime in DMA ring */
    if (dma_virt_buffer && abox_base) {
        volatile uint32_t *dma_words = (volatile uint32_t *)dma_virt_buffer;
        for (uint32_t f = 0; f < 48000 && f < A51_DMA_FRAMES; f++) {
            int16_t l = (int16_t)(16000 * ((f % 54) < 27 ? 1 : -1));
            int16_t r = (int16_t)(16000 * ((f % 108) < 54 ? 1 : -1));
            dma_words[f] = ((uint32_t)(uint16_t)r << 16) | (uint16_t)l;
        }
        dma_write_frame_offset = (48000 % A51_DMA_FRAMES);
        audio_wr(abox_base + 0x1010, dma_write_frame_offset * HAKIOS_AUDIO_FRAME);
        audio_wr(abox_base + 0x1710, dma_write_frame_offset * HAKIOS_AUDIO_FRAME);
        loader_log_line("a51audio: boot chime loaded into DMA ring (amplitude 16000)\n");
    }

    /* 6. Register with Darwin / CoreAudio as primary output sink */
    hakios_audio_set_sink("Galaxy A51 Speaker (TAS2562 / ABOX)", a51_audio_sink);
    audio_sink_active = true;
    loader_log_line("a51audio: registered speaker sink with CoreAudio (/dev/hakios-audio active)\n");
}

STARTUP(EARLY_BOOT, STARTUP_RANK_LAST, a51audio_init);
'''

def main():
    target1 = REPO / 'devices/a51/drivers/audio/hakios.a51audio.c'
    target2 = REPO / 'xnu-src/xnu-8796.121.2/bsd/dev/hakios.a51audio.c'
    
    target1.parent.mkdir(parents=True, exist_ok=True)
    target1.write_text(AUDIO_SOURCE, encoding='utf-8')
    print(f"Wrote {target1} ({len(AUDIO_SOURCE)} bytes)")
    
    target2.parent.mkdir(parents=True, exist_ok=True)
    target2.write_text(AUDIO_SOURCE, encoding='utf-8')
    print(f"Wrote {target2} ({len(AUDIO_SOURCE)} bytes)")

if __name__ == '__main__':
    main()
