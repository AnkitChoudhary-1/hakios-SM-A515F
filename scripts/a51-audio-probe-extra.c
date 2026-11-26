/* A51_DEVICE_SERVICES_AUDIO: bounded open-drain TAS2562 diagnostic.
 * No reset, unmute, gain, boost, DSP, DMA, or audio-sink registration.
 * HSI2C3 pins from live DT: CMGP gpm2-0 SCL / gpm3-0 SDA.
 * GPIO releases a high level by selecting input; it never drives high.
 */
static vm_offset_t amp_gpio;
static uint32_t amp_rd(vm_offset_t a) { return *(volatile uint32_t *)a; }
static void amp_wr(vm_offset_t a, uint32_t v) { *(volatile uint32_t *)a=v; }
static void amp_line(unsigned bank, bool released)
{
    vm_offset_t p=amp_gpio+bank;
    if (!released) amp_wr(p+4,amp_rd(p+4)&~1u);
    amp_wr(p,(amp_rd(p)&~15u)|(released ? 0 : 1));
    __asm__ volatile("dsb sy" ::: "memory");
    delay(5);
}
static int amp_high(void)
{
    amp_line(0x40,true);
    for (unsigned i=0;i<1000;i++) {
        if (amp_rd(amp_gpio+0x44)&1) return 0;
        delay(1); /* bounded slave clock stretch */
    }
    return -1;
}
static int amp_start(void)
{
    amp_line(0x60,true);
    if (amp_high() || !(amp_rd(amp_gpio+0x64)&1)) return -1;
    amp_line(0x60,false);
    amp_line(0x40,false);
    return 0;
}
static void amp_stop(void)
{
    amp_line(0x40,false);
    amp_line(0x60,false);
    (void)amp_high();
    amp_line(0x60,true);
}
static int amp_byte(uint8_t byte)
{
    for (unsigned i=0;i<8;i++) {
        amp_line(0x60,!!(byte&0x80));
        if (amp_high()) return -1;
        amp_line(0x40,false);
        byte<<=1;
    }
    amp_line(0x60,true);
    if (amp_high()) return -1;
    int nack=!!(amp_rd(amp_gpio+0x64)&1);
    amp_line(0x40,false);
    return nack ? -2 : 0;
}
static int amp_read(uint8_t reg, uint8_t *value)
{
    int e=amp_start();
    if (!e) e=amp_byte(0x98);
    if (!e) e=amp_byte(reg);
    if (!e) e=amp_start();
    if (!e) e=amp_byte(0x99);
    uint8_t v=0;
    if (!e) {
        amp_line(0x60,true);
        for (unsigned i=0;i<8;i++) {
            if (amp_high()) { e=-3; break; }
            v=(v<<1)|(amp_rd(amp_gpio+0x64)&1);
            amp_line(0x40,false);
        }
        if (!e) { /* NACK final byte */
            e=amp_high();
            amp_line(0x40,false);
        }
    }
    amp_stop();
    if (!e) *value=v;
    return e;
}
static int amp_select(uint8_t reg, uint8_t value)
{
    int e=amp_start();
    if (!e) e=amp_byte(0x98);
    if (!e) e=amp_byte(reg);
    if (!e) e=amp_byte(value);
    amp_stop();
    return e;
}
static void a51_amp_probe(void)
{
    char line[300];
    amp_gpio=ml_io_map(0x11c20000UL,0x1000);
    if (!amp_gpio) return;
    uint32_t saved[2][3];
    for (unsigned i=0;i<2;i++)
        for (unsigned j=0;j<3;j++) saved[i][j]=amp_rd(amp_gpio+0x40+i*0x20+j*4);
    uint32_t reset=amp_rd(amp_gpio+4);
    snprintf(line,sizeof(line),"a51audio: TAS2562 GPIO probe; reset CON=%x DAT=%x SCL=%x/%x SDA=%x/%x; no reset/unmute\n",
        amp_rd(amp_gpio),reset,saved[0][0],saved[0][1],saved[1][0],saved[1][1]);
    loader_log_line(line);
    if (!(reset&1)) { loader_log_line("a51audio: amplifier held in reset; probe skipped\n"); return; }
    /* Release pins first, then verify pull-ups before emitting any START. */
    amp_line(0x40,true);
    amp_line(0x60,true);
    int e=amp_high();
    if (!e && !(amp_rd(amp_gpio+0x64)&1)) e=-4;
    uint8_t page=0,book=0,id=0,power=0;
    bool got_page=false,got_book=false;
    if (!e) { e=amp_read(0,&page); got_page=!e; }
    if (!e) e=amp_select(0,0);
    if (!e) { e=amp_read(127,&book); got_book=!e; }
    if (!e) e=amp_select(127,0);
    if (!e) e=amp_read(0x7d,&id); /* Samsung TAS2562 revision/PG ID */
    if (!e) e=amp_read(2,&power);
    int restore=0;
    if (got_book) restore=amp_select(127,book);
    if (got_page) { int r=amp_select(0,page); if (r) restore=r; }
    /* Restore DAT while input, then pull and original function; only bit/field0. */
    for (unsigned i=0;i<2;i++) {
        vm_offset_t b=amp_gpio+0x40+i*0x20;
        amp_wr(b+4,(amp_rd(b+4)&~1u)|(saved[i][1]&1));
        amp_wr(b+8,(amp_rd(b+8)&~15u)|(saved[i][2]&15));
        amp_wr(b,(amp_rd(b)&~15u)|(saved[i][0]&15));
    }
    snprintf(line,sizeof(line),"a51audio: TAS2562 transfer error=%d restore=%d revision/PG=%02x power=%02x old selectors=%02x/%02x; identity requires Android comparison; no playback\n",e,restore,id,power,book,page);
    loader_log_line(line);
}
static void a51_audio_services(uint32_t step, vm_offset_t cmu)
{
    if (step<2) return;
    /* CGVAL is bit21; a cleared gate cannot support register access. */
    if (!(audio_rd(cmu+0x2020)&(1u<<21))) {
        loader_log_line("a51audio: ABOX ACLK gated; ABOX reads skipped\n");
    } else {
        loader_log_line("a51audio: stage 2: reading powered ABOX version/route/UAIF2\n");
        vm_offset_t abox=ml_io_map(0x14a50000UL,0x1000);
        if (abox) {
            char line[300];
            snprintf(line,sizeof(line),"a51audio: ABOX index=%08x version=%08x power=%08x route=%08x/%08x UAIF2=%08x/%08x status=%08x\n",
                audio_rd(abox),audio_rd(abox+4),audio_rd(abox+0x14),
                audio_rd(abox+0x40),audio_rd(abox+0x44),audio_rd(abox+0x520),audio_rd(abox+0x524),audio_rd(abox+0x52c));
            loader_log_line(line);
        }
    }
    if (step>=3) a51_amp_probe();
}
