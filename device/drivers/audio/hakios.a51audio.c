/* A51 Exynos9611 Audio Driver: TI TAS2562 Smart Amp + ABOX UAIF2
 * Experimental speaker output. Host checks do not establish audible playback.
 * Wired headphones, capture and route switching are not implemented here.
 */
#include <kern/startup.h>
#include <kern/clock.h>
#include <kern/locks.h>
#include <kern/thread.h>
#include <libkern/libkern.h>
#include <mach/mach_types.h>
#include <pexpert/pexpert.h>
#include <sys/systm.h>
#include <sys/sysctl.h>
#include <sys/hakios.audio.h>

extern vm_offset_t ml_io_map(vm_offset_t phys_addr, vm_size_t size);
extern void loader_log_line(const char *line);
extern void hakios_audio_set_sink(const char *name, hakios_audio_sink_t sink);

static inline int64_t a51_audio_smc(uint64_t cmd, uint64_t arg0, uint64_t arg1, uint64_t arg2)
{
    register uint64_t x0 __asm__("x0") = cmd;
    register uint64_t x1 __asm__("x1") = arg0;
    register uint64_t x2 __asm__("x2") = arg1;
    register uint64_t x3 __asm__("x3") = arg2;
    __asm__ volatile("smc #0"
                     : "+r"(x0), "+r"(x1), "+r"(x2), "+r"(x3)
                     :
                     : "x4", "x5", "x6", "x7", "x8", "x9", "x10", "x11",
                       "x12", "x13", "x14", "x15", "x16", "x17", "memory");
    return (int64_t)(int32_t)x0;
}

static inline void a51_audio_dcache_clean(const volatile void *addr, uint64_t len)
{
    if (!addr || !len) return;
    uint64_t p = ((uint64_t)(uintptr_t)addr) & ~63ULL;
    uint64_t end = (uint64_t)(uintptr_t)addr + len;
    for (; p < end; p += 64ULL) {
        __asm__ volatile("dc civac, %0" :: "r"(p) : "memory");
    }
    __asm__ volatile("dsb sy" ::: "memory");
}

/* Init log is cached in ordinary kernel memory, never assumed-reserved RAM.
 * Only the startup thread appends; userland reads after startup completes.
 */
static char audio_diag[4096];
static size_t audio_diag_used;
static uint32_t sink_calls, sink_frames, sink_status;
static void a51audio_log(const char *line)
{
    loader_log_line(line);
    size_t n = strlen(line);
    if (n > sizeof(audio_diag) - 1 - audio_diag_used)
        n = sizeof(audio_diag) - 1 - audio_diag_used;
    memcpy(audio_diag + audio_diag_used, line, n);
    audio_diag_used += n;
    audio_diag[audio_diag_used] = 0;
}
static int audio_diagnostic SYSCTL_HANDLER_ARGS
{
#pragma unused(oidp, arg1, arg2)
    char output[4352];
    snprintf(output, sizeof(output), "%s\nsink_calls=%u accepted_frames=%u last_dma_status=%08x\n",
        audio_diag, sink_calls, sink_frames, sink_status);
    return SYSCTL_OUT(req, output, strlen(output) + 1);
}
SYSCTL_PROC(_kern, OID_AUTO, hakios_a51audio, CTLTYPE_STRING | CTLFLAG_RD | CTLFLAG_LOCKED,
    0, 0, audio_diagnostic, "A", "Cached A51 speaker diagnostics");

static inline uint32_t audio_rd(vm_offset_t address)
{
    return *(volatile uint32_t *)address;
}

static inline void audio_wr(vm_offset_t address, uint32_t val)
{
    *(volatile uint32_t *)address = val;
    __asm__ volatile("dsb sy" ::: "memory");
}

/* =========================================================================
 * CMGP GPIO for HSI2C3 (Bit-banged I2C) & TAS2562 Hardware Reset
 * Exynos 9611 CMGP Base: 0x11C20000
 * Banks:
 *   gpm0: offset 0x000 (gpm0-0 = spk_en / ti,reset-gpio)
 *   gpm2: offset 0x040 (gpm2-0 = SCL, hsi2c3_bus)
 *   gpm3: offset 0x060 (gpm3-0 = SDA, hsi2c3_bus)
 * Registers per bank:
 *   +0x00: CON (function: 0 = input, 1 = output)
 *   +0x04: DAT (bit 0 = pin data)
 *   +0x08: PUD (pull-up/down: 0 = none, 1 = pulldown, 3 = pullup)
 *   +0x0C: DRV (drive strength: 3 = 4x)
 * ========================================================================= */
static vm_offset_t amp_gpio;

static inline int amp_read_scl(void)
{
    return (int)(audio_rd(amp_gpio + 0x040 + 4) & 1u);
}

static inline int amp_read_sda(void)
{
    return (int)(audio_rd(amp_gpio + 0x060 + 4) & 1u);
}

/* Configure open-drain pin state: released (high-Z with pullup) or low (driving 0) */
static void amp_line(unsigned bank, bool released)
{
    vm_offset_t p = amp_gpio + bank;
    if (released) {
        /* Input mode: line pulled HIGH by internal pull-up */
        audio_wr(p + 0, audio_rd(p + 0) & ~15u);
    } else {
        /* Output mode driving LOW (0) */
        audio_wr(p + 4, audio_rd(p + 4) & ~1u);
        audio_wr(p + 0, (audio_rd(p + 0) & ~15u) | 1u);
    }
    __asm__ volatile("dsb sy" ::: "memory");
    delay(5);
}

/* Wait for SCL to go high (clock stretching support) */
static int amp_high(void)
{
    amp_line(0x040, true); /* SCL released */
    for (unsigned i = 0; i < 2000; i++) {
        if (amp_read_scl() != 0) return 0;
        delay(1);
    }
    return -1; /* Clock stretch timeout or stuck low */
}

/* I2C START condition */
static int amp_start(void)
{
    amp_line(0x060, true); /* SDA high */
    if (amp_high() != 0) return -1; /* SCL high */
    if (!amp_read_sda()) return -2; /* SDA stuck low */
    delay(5);
    amp_line(0x060, false); /* SDA low while SCL high */
    delay(5);
    amp_line(0x040, false); /* SCL low */
    delay(5);
    return 0;
}

/* I2C STOP condition */
static void amp_stop(void)
{
    amp_line(0x040, false); /* SCL low */
    amp_line(0x060, false); /* SDA low */
    delay(5);
    (void)amp_high();       /* SCL high */
    delay(5);
    amp_line(0x060, true);  /* SDA high while SCL high */
    delay(5);
}

/* Write single byte over I2C and check ACK */
static int amp_write_byte(uint8_t byte)
{
    for (int i = 7; i >= 0; i--) {
        amp_line(0x060, !!(byte & (1 << i)));
        delay(2);
        if (amp_high() != 0) return -1;
        delay(5);
        amp_line(0x040, false);
        delay(2);
    }
    /* Read ACK from slave */
    amp_line(0x060, true); /* Release SDA */
    delay(2);
    if (amp_high() != 0) return -1;
    delay(3);
    int ack = (amp_read_sda() == 0); /* 0 = ACK, 1 = NACK */
    delay(2);
    amp_line(0x040, false);
    delay(2);
    return ack ? 0 : -2; /* -2 = NACK */
}

/* Read single byte over I2C */
static int amp_read_byte(uint8_t *val, bool send_ack)
{
    uint8_t byte = 0;
    amp_line(0x060, true); /* Release SDA to sample */
    for (int i = 7; i >= 0; i--) {
        if (amp_high() != 0) return -1;
        delay(3);
        if (amp_read_sda()) {
            byte |= (1 << i);
        }
        delay(2);
        amp_line(0x040, false);
        delay(2);
    }
    /* Send ACK or NACK to slave */
    amp_line(0x060, !send_ack);
    delay(2);
    if (amp_high() != 0) return -1;
    delay(5);
    amp_line(0x040, false);
    amp_line(0x060, true);
    delay(2);
    *val = byte;
    return 0;
}

/* Bus recovery: release hung slave holding SDA low */
static void amp_bus_recovery(void)
{
    amp_line(0x060, true); /* SDA released */
    for (int i = 0; i < 9; i++) {
        amp_line(0x040, false);
        delay(5);
        if (amp_high() != 0) break;
        delay(5);
        if (amp_read_sda() != 0) break;
    }
    amp_stop();
}

/* Write 8-bit register on TAS2562 (I2C 0x4C) */
static int amp_write_reg(uint8_t reg, uint8_t val)
{
    int ret = amp_start();
    if (ret != 0) goto out;
    ret = amp_write_byte(0x98); /* 0x4C << 1 | 0 */
    if (ret != 0) goto out;
    ret = amp_write_byte(reg);
    if (ret != 0) goto out;
    ret = amp_write_byte(val);
out:
    amp_stop();
    return ret;
}

/* Read 8-bit register on TAS2562 (I2C 0x4C) */
static int amp_read_reg(uint8_t reg, uint8_t *val)
{
    int ret = amp_start();
    if (ret != 0) goto out;
    ret = amp_write_byte(0x98);
    if (ret != 0) goto out;
    ret = amp_write_byte(reg);
    if (ret != 0) goto out;
    /* Repeated START */
    ret = amp_start();
    if (ret != 0) goto out;
    ret = amp_write_byte(0x99); /* 0x4C << 1 | 1 */
    if (ret != 0) goto out;
    ret = amp_read_byte(val, false); /* Send NACK for single-byte read */
out:
    amp_stop();
    return ret;
}

/* Cached Book / Page tracking */
static int current_book = -1;
static int current_page = -1;

static int amp_select_book_page(uint8_t book, uint8_t page)
{
    int ret = 0;
    if (current_book != (int)book) {
        /* Book select is only accessible on page zero. */
        ret = amp_write_reg(0, 0);
        if (ret != 0) { current_page = -1; return ret; }
        current_page = 0;
        ret = amp_write_reg(127, book); /* Book register is 127 */
        if (ret != 0) return ret;
        current_book = book;
    }
    if (current_page != (int)page) {
        ret = amp_write_reg(0, page);   /* Page register is 0 */
        if (ret != 0) return ret;
        current_page = page;
    }
    return 0;
}

static int amp_write(uint8_t book, uint8_t page, uint8_t reg, uint8_t val)
{
    int ret = amp_select_book_page(book, page);
    if (ret != 0) return ret;
    ret = amp_write_reg(reg, val);
    if (ret) {
        char line[120];
        snprintf(line, sizeof(line), "a51audio: amp_write failed book=%u page=%u reg=%02x err=%d\n", book, page, reg, ret);
        a51audio_log(line);
    }
    return ret;
}

static int amp_read(uint8_t book, uint8_t page, uint8_t reg, uint8_t *val)
{
    int ret = amp_select_book_page(book, page);
    if (ret != 0) return ret;
    ret = amp_read_reg(reg, val);
    if (ret) {
        char line[120];
        snprintf(line, sizeof(line), "a51audio: amp_read failed book=%u page=%u reg=%02x err=%d\n", book, page, reg, ret);
        a51audio_log(line);
    }
    return ret;
}

/* =========================================================================
 * Audio DMA Ring Buffer in Reserved Audio DRAM (0xE9400000, 64KB)
 * ========================================================================= */
#define A51_DMA_BASE_PA      0xE9400000UL
#define A51_DMA_BUFFER_SIZE  (64 * 1024)
#define A51_DMA_FRAMES       (A51_DMA_BUFFER_SIZE / HAKIOS_AUDIO_FRAME)

static int16_t *dma_virt_buffer = NULL;
static vm_offset_t abox_base = 0;
static volatile uint32_t dma_write_frame_offset = 0;
static bool audio_sink_active = false;

/* BUF_OFFSET is the DMA period size, not a software producer pointer.
 * Read STATUS to keep writes ahead of the hardware consumer. Generic audio
 * serializes this sink. RDMA0 alone feeds SPUS OUT0 -> SIFS1 -> UAIF2.
 */
#define A51_DMA_PERIOD 4096u
static bool dma_writer_started;
static uint32_t dma_last_read;
static uint32_t a51_audio_sink(const int16_t *frames, uint32_t count)
{
    sink_calls++;
    if (!audio_sink_active || !dma_virt_buffer || !abox_base) return 0;
    if (!count) return 0;
    uint32_t status = audio_rd(abox_base + 0x1030);
    sink_status = status;
    if (!(status & (1u << 31))) {
        if (sink_calls <= 5 || (sink_calls % 500) == 0) {
            char line[128];
            snprintf(line, sizeof(line), "a51audio: sink stalled call=%u rdma0=%08x uaif2=%08x\n",
                     sink_calls, status, audio_rd(abox_base + 0x052c));
            a51audio_log(line);
        }
        return 0;
    }
    uint32_t read_frame = (((status >> 16) & 0x1fffu) << 4) / HAKIOS_AUDIO_FRAME;
    if (read_frame >= A51_DMA_FRAMES) return 0;
    volatile uint32_t *words = (volatile uint32_t *)dma_virt_buffer;
    /* Clear consumed samples so idle playback does not loop old sound. */
    if (dma_writer_started) {
        for (uint32_t f = dma_last_read; f != read_frame; f = (f + 1) % A51_DMA_FRAMES)
            words[f] = 0;
    }
    dma_last_read = read_frame;
    uint32_t cur = dma_write_frame_offset;
    uint32_t ahead = (cur + A51_DMA_FRAMES - read_frame) % A51_DMA_FRAMES;
    uint32_t period_frames = A51_DMA_PERIOD / HAKIOS_AUDIO_FRAME;
    if (!dma_writer_started || ahead < period_frames) {
        cur = (read_frame + 2 * period_frames) % A51_DMA_FRAMES;
        ahead = 2 * period_frames;
        dma_writer_started = true;
    }
    uint32_t free_frames = ahead >= A51_DMA_FRAMES - period_frames ? 0 : A51_DMA_FRAMES - ahead - period_frames;
    if (count > free_frames) count = free_frames;
    for (uint32_t i = 0; i < count; i++) {
        uint32_t sample = ((uint32_t)(uint16_t)frames[2*i + 1] << 16) | (uint16_t)frames[2*i];
        words[(cur + i) % A51_DMA_FRAMES] = sample;
    }
    a51_audio_dcache_clean(dma_virt_buffer, A51_DMA_BUFFER_SIZE);
    dma_write_frame_offset = (cur + count) % A51_DMA_FRAMES;
    sink_frames += count;
    return count;
}

/* Retained PLL_AUD: 26 MHz reference, signed fractional K, AUDIF parent.
 * Do not assume a 73.728 MHz parent or silently claim a measured BCLK.
 */
static uint32_t a51_bclk_div(uint32_t con0, uint32_t con3, uint32_t audif,
    uint32_t *actual)
{
    uint32_t p = (con0 >> 8) & 63, m = (con0 >> 16) & 1023, shift = con0 & 7;
    if (!p || !m || (con0 & 0xa0000000u) != 0xa0000000u) return 0;
    int64_t fixed = (int64_t)m * 65536 + (int16_t)(con3 & 65535);
    if (fixed <= 0) return 0;
    uint64_t parent = (26000000ULL * (uint64_t)fixed) /
        ((uint64_t)p * 65536 * (1u << shift) * ((audif & 511) + 1));
    uint32_t div = (uint32_t)((parent + 768000) / 1536000);
    if (!div || div > 512) return 0;
    *actual = (uint32_t)(parent / div);
    uint32_t error = *actual > 1536000 ? *actual - 1536000 : 1536000 - *actual;
    return error <= 15360 ? div : 0; /* within one percent of 48k/32fs */
}

/* =========================================================================
 * Exynos 9611 DISPAUD Pinmux, Clocks, SysMMU, ABOX Routing & DMA Configuration
 * ========================================================================= */
/* Samsung ra.c: manual gate uses bits 20/21; QCH request only works
 * when ENABLE(bit0)=0. Preserve unrelated fields, disable auto gating(bit28).
 */
static uint32_t a51_gate_value(uint32_t old)
{
    return (old & ~(1u << 28)) | (1u << 20) | (1u << 21);
}
static uint32_t a51_qch_value(uint32_t old)
{
    return (old & ~7u) | 6u; /* manual clock request + PM ignore, QCH disabled */
}
static int clock_wait(vm_offset_t reg, uint32_t mask, uint32_t expected)
{
    for (unsigned i = 0; i < 10000; i++) {
        if ((audio_rd(reg) & mask) == expected) return 0;
        delay(10);
    }
    a51audio_log("a51audio: clock transition timed out; sink unavailable\n");
    return -1;
}
static int a51_audio_hardware_init(vm_offset_t cmu)
{
    static const uint16_t gates[] = {
        0x206c, 0x2040, 0x2008, 0x2018, 0x201c, 0x2020, 0x202c, 0x2030,
        0x203c, 0x2048, 0x204c, 0x2078, 0x207c, 0x2080, 0x2084, 0x2088,
        0x2094, 0x2098, 0x209c, 0x20a4, 0x20b0, 0x20b8
    };
    static const uint16_t qchs[] = {
        0x3000, 0x3014, 0x3020, 0x3028, 0x3040, 0x3044, 0x304c, 0x3050,
        0x3060, 0x3068
    };
    static const uint16_t auto_cg_regs[] = {0x0108, 0x0800, 0x1000, 0x1808};
    for (unsigned i = 0; i < sizeof(auto_cg_regs)/sizeof(auto_cg_regs[0]); i++) {
        char dline[128];
        uint32_t before = audio_rd(cmu + auto_cg_regs[i]);
        uint32_t after = before & ~(1u << 28);
        audio_wr(cmu + auto_cg_regs[i], after);
        snprintf(dline, sizeof(dline), "autocg %04x: %08x -> %08x\n", auto_cg_regs[i], before, audio_rd(cmu + auto_cg_regs[i]));
        a51audio_log(dline);
    }
    char line[180];
    for (unsigned i = 0; i < sizeof(gates)/sizeof(gates[0]); i++) {
        uint32_t before = audio_rd(cmu + gates[i]), desired = a51_gate_value(before);
        audio_wr(cmu + gates[i], desired);
        uint32_t after = audio_rd(cmu + gates[i]);
        snprintf(line, sizeof(line), "gate %04x: %08x -> %08x\n", gates[i], before, after);
        a51audio_log(line);
        if ((after & ((1u << 28)|(3u << 20))) != (3u << 20)) return -1;
    }
    for (unsigned i = 0; i < sizeof(qchs)/sizeof(qchs[0]); i++) {
        uint32_t before = audio_rd(cmu + qchs[i]);
        audio_wr(cmu + qchs[i], a51_qch_value(before));
        uint32_t after = audio_rd(cmu + qchs[i]);
        snprintf(line, sizeof(line), "qch %04x: %08x -> %08x\n", qchs[i], before, after);
        a51audio_log(line);
        if ((after & 7u) != 6u) return -1;
    }
    vm_offset_t pinctrl = ml_io_map(0x14a60000UL, 0x1000);
    if (!pinctrl) return -1;
    audio_wr(pinctrl + 0x40, (audio_rd(pinctrl + 0x40) & ~0xffffu) | 0x2222u);
    audio_wr(pinctrl + 0x48, audio_rd(pinctrl + 0x48) & ~0xffffu);
    audio_wr(pinctrl + 0x4c, (audio_rd(pinctrl + 0x4c) & ~0xffffu) | 0x3333u);
    /* Retain the reference-supported 48k PLL plan used in the later source.
     * cmucal-node.c PLL_RATE_MPSK(1179648071,45,1,0,24319).
     * Fail on a real transition error rather than assuming a successful lock.
     */
    uint32_t con = audio_rd(cmu + 0x160);
    uint32_t mps = (45u << 16) | (1u << 8);
    uint32_t mpsmask = (1023u << 16) | (63u << 8) | 7u;
    if ((con & mpsmask) != mps || (audio_rd(cmu + 0x16c) & 65535u) != 24319u || !(con & (1u << 31))) {
        audio_wr(cmu + 0x160, con & ~(1u << 4));
        if (clock_wait(cmu + 0x160, 1u << 7, 0)) return -1;
        audio_wr(cmu + 0x16c, (audio_rd(cmu + 0x16c) & ~65535u) | 24319u);
        audio_wr(cmu + 0x160, (con & ~(mpsmask | (1u << 4))) | mps | (1u << 31));
    }
    if (clock_wait(cmu + 0x160, 1u << 29, 1u << 29)) return -1;
    audio_wr(cmu + 0x160, audio_rd(cmu + 0x160) | (1u << 4));
    if (clock_wait(cmu + 0x160, 1u << 7, 0)) return -1;
    audio_wr(cmu + 0x1800, (audio_rd(cmu + 0x1800) & ~((1u << 28) | 511u)) | 47u);
    if (clock_wait(cmu + 0x1800, 1u << 16, 0)) return -1;
    uint32_t bclk = 0;
    uint32_t div = a51_bclk_div(audio_rd(cmu + 0x160), audio_rd(cmu + 0x16c), audio_rd(cmu + 0x1800), &bclk);
    snprintf(line, sizeof(line), "PLL=%08x K=%08x AUDIF=%08x BCLK estimate=%u divider=%u\n",
        audio_rd(cmu + 0x160), audio_rd(cmu + 0x16c), audio_rd(cmu + 0x1800), bclk, div);
    a51audio_log(line);
    if (!div) return -1;
    audio_wr(cmu + 0x182c, (audio_rd(cmu + 0x182c) & ~((1u << 28)|511u)) | (div - 1));
    if (clock_wait(cmu + 0x182c, 1u << 16, 0)) return -1;
    audio_wr(cmu + 0x1018, audio_rd(cmu + 0x1018) & ~((1u << 28)|1u));
    if (clock_wait(cmu + 0x1018, 1u << 16, 0)) return -1;
    {
        char cline[160];
        snprintf(cline, sizeof(cline), "cmu aud_user=%08x aud_bus_mux=%08x aud_bus_div=%08x\n",
                 audio_rd(cmu + 0x0100), audio_rd(cmu + 0x1000), audio_rd(cmu + 0x1808));
        a51audio_log(cline);
    }

    vm_offset_t pmu = ml_io_map(0x11860000UL, 0x4000);
    if (!pmu) return -1;
    /* Release PAD_RETENTION_ABOX_OPTION */
    audio_wr(pmu + 0x3048, audio_rd(pmu + 0x3048) | 0x10000000u);

    vm_offset_t sysmmu = ml_io_map(0x14920000UL, 0x1000);
    if (!sysmmu) return -1;
    audio_wr(sysmmu + 0x0004, 0u); /* REG_MMU_CFG */
    audio_wr(sysmmu + 0x0000, 0u); /* REG_MMU_CTRL */
    { char dline[128]; snprintf(dline, sizeof(dline), "sysmmu ver=%08x cfg=%08x ctrl=%08x stat=%08x\n",
             audio_rd(sysmmu + 0x0034), audio_rd(sysmmu + 0x0004),
             audio_rd(sysmmu + 0x0000), audio_rd(sysmmu + 0x0008)); a51audio_log(dline); }
    if (audio_rd(sysmmu) != 0) return -1;

    /* 5. ABOX system registers & UAIF2 interface */
    abox_base = ml_io_map(0x14a50000UL, 0x10000);
    if (abox_base) {
        /* Power on ABOX system */
        audio_wr(abox_base + 0x0010, 1u);
        uint32_t syspwr = 0;
        for (int i = 0; i < 10000; i++) {
            syspwr = audio_rd(abox_base + 0x0014);
            if (syspwr & 1u) break;
            __asm__ volatile("yield");
        }
        audio_wr(abox_base + 0x0030, 0x7fffffffu); /* ABOX_DYN_CLOCK_OFF: disable dynamic clock gating (9610 default) */
        audio_wr(abox_base + 0x0038, 0x1ffu); /* ABOX_QCHANNEL_DISABLE */
        audio_wr(abox_base + 0x0208, 1u);     /* ABOX_SPUS_CTRL2 flush */
        audio_wr(abox_base + 0x020c, 7u);     /* ABOX_SPUS_CTRL3 flush */
        delay(10);
        audio_wr(abox_base + 0x0208, 0u);     /* release MIXP flush */
        audio_wr(abox_base + 0x020c, 0u);     /* release SIFS1/2/M flush */
        { char dline[192]; snprintf(dline, sizeof(dline),
                 "abox id=%08x ver=%08x sys=%08x dyncg=%08x tick=%08x syspwr=%08x qch_dis=%08x spus2=%08x spus3=%08x\n",
                 audio_rd(abox_base + 0x0000), audio_rd(abox_base + 0x0004),
                 audio_rd(abox_base + 0x0020), audio_rd(abox_base + 0x0030),
                 audio_rd(abox_base + 0x0050), syspwr, audio_rd(abox_base + 0x0038),
                 audio_rd(abox_base + 0x0208), audio_rd(abox_base + 0x020c)); a51audio_log(dline); }

        /* Route SIFS0 (MIXP) to UAIF2 SPK (bits [11:8] = 1) */
        uint32_t route = audio_rd(abox_base + 0x0040);
        route &= ~(0xfu << 8);
        route |= (1u << 8);
        audio_wr(abox_base + 0x0040, route);

        /* SPUS_CTRL0 (0x0200): Chain 0 (RDMA0 -> SIFS0/MIXP [bits 2:1 = 1], ASRC Off) */
        audio_wr(abox_base + 0x0200, (1u << 1));

        /* SPUS_CTRL1 (0x0204): MIXP format 16-bit 2ch (bits 4:0 = 9) */
        audio_wr(abox_base + 0x0204, 9u);

        /* SPUS_CTRL_SIFS_CNT0 (0x0280): SIFS0_CNT_VAL (bits 15:0) paces MIXP/SIFS0 from AUD_BUS (abox_sifsx_cnt_val). */
        uint32_t bus_div = (audio_rd(cmu + 0x1808) & 511u) + 1u;
        uint64_t aclk_hz = 1179648071ULL / bus_div;
        uint32_t sifs0_cnt = (uint32_t)(((aclk_hz * 4ULL) / 2ULL / 48000ULL) - 7ULL);
        audio_wr(abox_base + 0x0280, sifs0_cnt & 0xffffu);

        /* UAIF2 CTRL1: 16-bit 2ch I2S, IB_NF (BCLK polarity 0 per tas2562-codec.c), slot_max=1, sbit_max=15 -> 0x0904F000 */
        audio_wr(abox_base + 0x0524, 0x0904F000);

        /* UAIF2 CTRL0: FIFO diff = 4 samples, DATA_MODE=1 (9610 default), ABOX Master Mode (bit 2), SPK_ENABLE OFF until DMA primed */
        audio_wr(abox_base + 0x0520, (4u << 24) | (1u << 4) | (1u << 2));

        /* Stop before changing DMA geometry; no continuous boot tone. */
        audio_wr(abox_base + 0x1000, 0u);
        audio_wr(abox_base + 0x1700, 0u);
        dma_virt_buffer = (int16_t *)ml_io_map(A51_DMA_BASE_PA, A51_DMA_BUFFER_SIZE);
        if (!dma_virt_buffer) return -1;
        volatile uint32_t *words = (volatile uint32_t *)dma_virt_buffer;
        for (uint32_t f = 0; f < A51_DMA_FRAMES; f++) words[f] = 0;
        a51_audio_dcache_clean(dma_virt_buffer, A51_DMA_BUFFER_SIZE);
        dma_write_frame_offset = 0;
        dma_writer_started = false;
        audio_wr(abox_base + 0x1008, (uint32_t)A51_DMA_BASE_PA);
        audio_wr(abox_base + 0x100c, (uint32_t)(A51_DMA_BASE_PA + A51_DMA_BUFFER_SIZE));
        audio_wr(abox_base + 0x1010, A51_DMA_PERIOD);
        audio_wr(abox_base + 0x1014, (uint32_t)A51_DMA_BASE_PA);
        audio_wr(abox_base + 0x1018, 0u);
        audio_wr(abox_base + 0x101c, 1u);
        /* Match Calliope RDMA0 start sequence: configure -> ENABLE=1 -> [18:16]=2 -> delay(1ms) -> VOL=0x800000 -> [18:16]=0 */
        uint32_t rdma_cfg = (8u << 19) | (9u << 8) | (1u << 5) | (1u << 4);
        audio_wr(abox_base + 0x1000, rdma_cfg);
        audio_wr(abox_base + 0x1004, 1u); /* ABOX_RDMA0_CTRL1 */
        audio_wr(abox_base + 0x1000, rdma_cfg | 1u);
        audio_wr(abox_base + 0x1000, rdma_cfg | 1u | (2u << 16));
        delay(1000);
        audio_wr(abox_base + 0x1018, 0x00800000u); /* unity gain (Q1.23) */
        audio_wr(abox_base + 0x1000, rdma_cfg | 1u);

        /* Now that RDMA is streaming samples into SIFS1 FIFO, enable UAIF2 SPK transmitter */
        audio_wr(abox_base + 0x0520, (1u << 0) | (4u << 24) | (1u << 4) | (1u << 2));
        audio_wr(abox_base + 0x052c, 3u); /* W1C initial UAIF2 status/error bits */
        delay(20000); /* 20ms settling time for BCLK and WS */

        uint32_t st_dram = audio_rd(abox_base + 0x1030);
        char log[256];
        snprintf(log, sizeof(log), "a51audio: ABOX UAIF2 active: CTRL0=0x%08x CTRL1=0x%08x STATUS=0x%08x RDMA0_CTRL0=0x%08x CTRL1=0x%08x SBACK=%08x STATUS=0x%08x ROUTE=0x%08x SPUS0=0x%08x SPUS1=0x%08x CNT0=0x%08x\n",
                 audio_rd(abox_base + 0x0520), audio_rd(abox_base + 0x0524),
                 audio_rd(abox_base + 0x052c), audio_rd(abox_base + 0x1000),
                 audio_rd(abox_base + 0x1004), audio_rd(abox_base + 0x1020), st_dram,
                 audio_rd(abox_base + 0x0040), audio_rd(abox_base + 0x0200),
                 audio_rd(abox_base + 0x0204), audio_rd(abox_base + 0x0280));
        a51audio_log(log);

        /* If DRAM (0xE9400000) did not advance RDMA0, test ABOX internal SRAM (0x14B20000) */
        if ((st_dram & 0x1fffffffu) == 0) {
            vm_offset_t sram_dma = ml_io_map(0x14B20000UL, A51_DMA_BUFFER_SIZE);
            if (sram_dma) {
                audio_wr(abox_base + 0x1000, rdma_cfg);
                delay(100);
                volatile uint32_t *swords = (volatile uint32_t *)sram_dma;
                for (uint32_t f = 0; f < A51_DMA_FRAMES; f++) swords[f] = 0;
                __asm__ volatile("dsb sy" ::: "memory");
                audio_wr(abox_base + 0x1008, 0x14B20000u);
                audio_wr(abox_base + 0x100c, 0x14B20000u + A51_DMA_BUFFER_SIZE);
                audio_wr(abox_base + 0x1010, A51_DMA_PERIOD);
                audio_wr(abox_base + 0x1014, 0x14B20000u);
                audio_wr(abox_base + 0x1018, 0u);
                audio_wr(abox_base + 0x101c, 1u);
                audio_wr(abox_base + 0x1004, 1u);
                audio_wr(abox_base + 0x1000, rdma_cfg | 1u);
                audio_wr(abox_base + 0x1000, rdma_cfg | 1u | (2u << 16));
                delay(1000);
                audio_wr(abox_base + 0x1018, 0x00800000u);
                audio_wr(abox_base + 0x1000, rdma_cfg | 1u);
                delay(20000);
                uint32_t st_sram = audio_rd(abox_base + 0x1030);
                snprintf(log, sizeof(log), "a51audio: SRAM RDMA0 test (0x14B20000): STATUS=0x%08x UAIF2_STATUS=0x%08x\n",
                         st_sram, audio_rd(abox_base + 0x052c));
                a51audio_log(log);
                if ((st_sram & 0x1fffffffu) != 0) {
                    dma_virt_buffer = (int16_t *)sram_dma;
                    a51audio_log("a51audio: switched DMA ring to ABOX SRAM 0x14B20000\n");
                } else {
                    /* Restore 0xE9400000 if neither advanced */
                    audio_wr(abox_base + 0x1000, rdma_cfg);
                    audio_wr(abox_base + 0x1008, (uint32_t)A51_DMA_BASE_PA);
                    audio_wr(abox_base + 0x100c, (uint32_t)(A51_DMA_BASE_PA + A51_DMA_BUFFER_SIZE));
                    audio_wr(abox_base + 0x1014, (uint32_t)A51_DMA_BASE_PA);
                    audio_wr(abox_base + 0x1000, rdma_cfg | 1u);
                }
            }
        }
        return 0;
    }
    return -1;
}

/* =========================================================================
 * TAS2562 Smart Amp Bring-up (invoked AFTER clocks and pinmux are active!)
 * ========================================================================= */
static int tas2562_bringup(void)
{
    char log[256];
    amp_gpio = ml_io_map(0x11c20000UL, 0x1000);
    if (!amp_gpio) {
        a51audio_log("a51audio: failed to map CMGP GPIO (0x11C20000)\n");
        return -1;
    }

    /* 1. Configure internal pull-ups on I2C lines: gpm2-0 (SCL) and gpm3-0 (SDA) */
    audio_wr(amp_gpio + 0x040 + 8, 3u);  /* gpm2-0 PUD = EXYNOS_PIN_PULL_UP */
    audio_wr(amp_gpio + 0x060 + 8, 3u);  /* gpm3-0 PUD = EXYNOS_PIN_PULL_UP */
    audio_wr(amp_gpio + 0x040 + 12, 3u); /* gpm2-0 DRV = 4x */
    audio_wr(amp_gpio + 0x060 + 12, 3u); /* gpm3-0 DRV = 4x */

    /* Release lines to high-Z input */
    amp_line(0x040, true);
    amp_line(0x060, true);
    delay(100);

    /* Diagnostic bus idle check */
    int scl_idle = amp_read_scl();
    int sda_idle = amp_read_sda();
    snprintf(log, sizeof(log), "a51audio: CMGP I2C bus state: SCL=%d, SDA=%d\n", scl_idle, sda_idle);
    a51audio_log(log);

    /* Run bus recovery in case slave was previously stuck in data phase */
    amp_bus_recovery();

    /* 2. Hardware Reset Sequence: gpm0-0 (spk_en / ti,reset-gpio)
     * Active LOW pulse: 20ms LOW, then 20ms HIGH
     */
    vm_offset_t p_rst = amp_gpio + 0x000;
    audio_wr(p_rst + 8, 3u);  /* pull-up */
    audio_wr(p_rst + 12, 3u); /* max drive */
    /* Drive LOW (Reset active) */
    audio_wr(p_rst + 4, audio_rd(p_rst + 4) & ~1u);
    audio_wr(p_rst + 0, (audio_rd(p_rst + 0) & ~15u) | 1u);
    __asm__ volatile("dsb sy" ::: "memory");
    delay(20000); /* 20 ms reset pulse */

    /* Drive HIGH (Reset released / enabled) */
    audio_wr(p_rst + 4, audio_rd(p_rst + 4) | 1u);
    __asm__ volatile("dsb sy" ::: "memory");
    delay(20000); /* 20 ms reset recovery */
    a51audio_log("a51audio: TAS2562 hardware reset completed (gpm0-0 driven HIGH)\n");

    /* Invalidate cached book/page after hardware reset */
    current_book = -1;
    current_page = -1;

    /* 3. Probe: Read Silicon ID from Book 0, Page 0, Reg 0x7D (TAS2562_REVISIONANDPGID) */
    uint8_t id = 0;
    int err = amp_read(0, 0, 0x7D, &id);
    snprintf(log, sizeof(log), "a51audio: TAS2562 probe: silicon_id=0x%02x (err=%d, SCL=%d, SDA=%d)\n",
             id, err, amp_read_scl(), amp_read_sda());
    a51audio_log(log);

    if (err != 0) {
        a51audio_log("a51audio: TAS2562 I2C probe failed; aborting amplifier configuration\n");
        return err;
    }

    /* 4. Software Reset: Book 0, Page 0, Reg 0x01 = 0x01 */
    if (amp_write(0, 0, 0x01, 0x01) != 0) return -1;
    delay(20000); /* 20 ms post-SW-reset settling */
    current_book = -1;
    current_page = -1;

    /* 5. Configure Hardware Settings matching Exynos 9611 Android Kernel */
    /* Book 0, Page 0 */
    if (amp_write(0, 0, 0x04, 0xCF) != 0) return -1; /* MISCCONFIG0: auto retry all faults */
    if (amp_write(0, 0, 0x0A, 0x03) != 0) return -1; /* TDMConfigurationReg4: Exynos slot mode */
    if (amp_write(0, 0, 0x38, 0x08) != 0) return -1; /* CLOCKCONFIGURATION: 32fs, 16-bit stereo */
    if (amp_write(0, 0, 0x35, 0x78) != 0) return -1; /* BOOSTSLOPE */
    if (amp_write(0, 0, 0x3B, 0x38) != 0) return -1; /* VBATFILTER */
    if (amp_write(0, 0, 0x3C, 0x3C) != 0) return -1; /* CLASSHRELEASETIMER */

    /* Book 0, Page 0xFD: Class-D & Internal Boost Oscillator (ti,bst-clk-src = 1) */
    if (amp_write(0, 0xFD, 0x0D, 0x0D) != 0) return -1; /* TESTPAGECONFIGURATION */
    if (amp_write(0, 0xFD, 0x19, 0x80) != 0) return -1; /* CLASSDCONFIGURATION1 */
    if (amp_write(0, 0xFD, 0x32, 0x49) != 0) return -1; /* CLASSDCONFIGURATION2 */
    if (amp_write(0, 0xFD, 0x33, 0x8E) != 0) return -1; /* CLASSDCONFIGURATION3 */
    if (amp_write(0, 0xFD, 0x3F, 0x21) != 0) return -1; /* CLASSDCONFIGURATION4 */
    if (amp_write(0, 0xFD, 0x5F, 0xC5) != 0) return -1; /* EFFICIENCYCONFIGURATION: OSC_BOOST_CLK enabled */
    if (amp_write(0, 0xFD, 0x0D, 0x0D) != 0) return -1; /* Confirm test page config */

    /* Book 0, Page 0: Audio format, Volume, Power */
    if (amp_write(0, 0, 0x06, 0x08) != 0) return -1; /* 48 kHz sample rate auto-detect */
    if (amp_write(0, 0, 0x07, 0x03) != 0) return -1; /* I2S IB_NF: RXEDGE_FALLING (tas2562-codec default), 1-bit offset */
    if (amp_write(0, 0, 0x08, 0x30) != 0) return -1; /* RXSCFG54_STEREO_DOWNMIX, 16-bit */
    if (amp_write(0, 0, 0x09, 0x10) != 0) return -1; /* Left=slot 0, Right=slot 1 */
    /* p_tas2562_classh_d_data (tas2562-codec.c) */
    if (amp_write(0x64, 0x07, 0x48, 0x09) != 0) return -1;
    if (amp_write(0x64, 0x07, 0x49, 0x99) != 0) return -1;
    if (amp_write(0x64, 0x07, 0x4A, 0x99) != 0) return -1;
    if (amp_write(0x64, 0x07, 0x4B, 0x9A) != 0) return -1;
    if (amp_write(0x64, 0x07, 0x4C, 0x00) != 0) return -1;
    if (amp_write(0x64, 0x07, 0x4D, 0x00) != 0) return -1;
    if (amp_write(0x64, 0x07, 0x4E, 0x00) != 0) return -1;
    if (amp_write(0x64, 0x07, 0x4F, 0x00) != 0) return -1;
    if (amp_write(0x64, 0x05, 0x4C, 0x0B) != 0) return -1;
    if (amp_write(0x64, 0x05, 0x4D, 0x00) != 0) return -1;
    if (amp_write(0x64, 0x05, 0x4E, 0x00) != 0) return -1;
    if (amp_write(0x64, 0x05, 0x4F, 0x00) != 0) return -1;
    if (amp_write(0, 0, 0x0B, 0x42) != 0) return -1; /* IV slot config */
    if (amp_write(0, 0, 0x0C, 0x40) != 0) return -1;
    if (amp_write(0, 0, 0x31, 0x00) != 0) return -1; /* TAS2562_DIGITALINPUTPINPULLDOWN: disable weak pull-downs */
    if (amp_write(0, 0, 0x3E, 0x00) != 0) return -1; /* TAS2562_ICN_SW_REG: disable ICN squelch muting */
    if (amp_write(0, 0, 0x03, 0x1E) != 0) return -1; /* Playback Volume/Level (+17.5 dB full output level) */

    /* 6. Clear latched interrupts while clocks are running and transition to ACTIVE */
    uint8_t pwr = 0xFF, irq = 0xFF;
    for (int retry = 0; retry < 15; retry++) {
        if (amp_write(0, 0, 0x30, 0x04) != 0) return -1; /* TAS2562_INTERRUPTCONFIGURATION: LTCHINTCLEAR */
        if (amp_read(0, 0, 0x24, &irq) != 0) return -1;   /* TAS2562_LATCHEDINTERRUPTREG0: read and clear */
        if (amp_write(0, 0, 0x02, 0x00) != 0) return -1; /* TAS2562_POWERCONTROL: ACTIVE */
        delay(6000);                 /* 6ms settling */
        if (amp_read(0, 0, 0x02, &pwr) != 0) return -1;
        if (amp_read(0, 0, 0x24, &irq) != 0) return -1;
        if (pwr == 0x00 && (irq & 0x04) == 0) {
            break;
        }
    }
    snprintf(log, sizeof(log), "a51audio: TAS2562 power_mode=0x%02x, latched_irq=0x%02x\n", pwr, irq);
    a51audio_log(log);

    /* 7. Diagnostic Status Readbacks: INTSTATUS, Live Clock Faults, and Battery ADC */
    uint8_t intstatus = 0, liveirq = 0, vbat_msb = 0, vbat_lsb = 0;
    if (amp_read(0, 0, 0x78, &intstatus) != 0) return -1;
    if (amp_read(0, 0, 0x1F, &liveirq) != 0) return -1;
    if (amp_read(0, 0, 0x2A, &vbat_msb) != 0) return -1;
    if (amp_read(0, 0, 0x2B, &vbat_lsb) != 0) return -1;
    uint32_t vbat_mv = (((uint32_t)vbat_msb << 4) | (vbat_lsb >> 4)) * 61 / 10;
    snprintf(log, sizeof(log), "a51audio: TAS2562 state: INTSTATUS=0x%02x (ClassD=%d, DAC=%d), LIVE_IRQ=0x%02x, VBAT=%u mV\n",
             intstatus, !!(intstatus & 0x04), !!(intstatus & 0x08), liveirq, vbat_mv);
    a51audio_log(log);

    return (pwr == 0x00 && (irq & 0x04) == 0 && (liveirq & 0x04) == 0) ? 0 : -1;
}

/* =========================================================================
 * Driver Initialization Entry Point
 * ========================================================================= */
static void a51audio_init(void)
{
    uint32_t step = 0;
    if (!PE_parse_boot_argn("a51audio", &step, sizeof(step))) {
        step = 4; /* Default to fully enabled audio on A51 */
    }
    if (step == 0) return;

    a51audio_log("a51audio: initializing Galaxy A51 audio subsystem...\n");

    /* 1. Verify PMU DISPAUD power domain */
    vm_offset_t pmu = ml_io_map(0x11860000UL, 0x5000);
    if (!pmu) {
        a51audio_log("a51audio: PMU mapping failed; aborting\n");
        return;
    }
    uint32_t status = audio_rd(pmu + 0x4004);
    if ((status & 0xf) != 0xf) {
        a51audio_log("a51audio: DISPAUD power domain is off\n");
        return;
    }

    /* 2. Map CMU_DISPAUD */
    vm_offset_t cmu = ml_io_map(0x14980000UL, 0x4000);
    if (!cmu) {
        a51audio_log("a51audio: CMU mapping failed; aborting\n");
        return;
    }

    /* 3. Configure Exynos hardware pinmux, clocks, ABOX routing & DMA FIRST */
    if (a51_audio_hardware_init(cmu) != 0) {
        a51audio_log("a51audio: hardware setup failed; sink unavailable\n");
        return;
    }

    /* 4. Bring up TAS2562 Smart Amp (now that BCLK is actively running!) */
    int amp_status = tas2562_bringup();

    if (amp_status != 0) {
        (void)amp_write(0, 0, 0x02, 0x02); /* shutdown */
        audio_wr(abox_base + 0x1000, 0u);
        audio_wr(abox_base + 0x0520, audio_rd(abox_base + 0x0520) & ~1u);
        a51audio_log("a51audio: amp configuration failed; sink unavailable\n");
        return;
    }

    /* 5. Register with Darwin / CoreAudio as primary output sink */
    hakios_audio_set_sink("Galaxy A51 Speaker (TAS2562 / ABOX)", a51_audio_sink);
    audio_sink_active = true;

    char msg[128];
    snprintf(msg, sizeof(msg), "a51audio: registered speaker sink with CoreAudio (amp_status=%d)\n", amp_status);
    a51audio_log(msg);
}

STARTUP(EARLY_BOOT, STARTUP_RANK_LAST, a51audio_init);
