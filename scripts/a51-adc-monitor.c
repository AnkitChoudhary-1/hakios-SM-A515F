/* Exynos ADC v3, live rev07 DT, bounded thermistor conversions only.
 * No charger configuration. CHUB arbitration follows Samsung's ADC driver;
 * unlike its timeout path, we release AP_FLAG on every exit.
 */
static vm_offset_t adc_regs, adc_sysreg, adc_cmu;
static bool adc_ready;
static void adc_init(void)
{
    adc_regs=ml_io_map(0x11c30000UL,0x1000);
    adc_sysreg=ml_io_map(0x11c10000UL,0x4000);
    adc_cmu=ml_io_map(0x11c00000UL,0x4000);
    adc_ready=adc_regs && adc_sysreg && adc_cmu;
}
static int adc_sample(unsigned channel, unsigned *value)
{
    if (!adc_ready || channel>11) return -1;
    /* A single battery worker owns the AP side; do not steal another owner. */
    if (rd(adc_sysreg+0x3100)) return -2;
    wr(adc_sysreg+0x3100,1);
    wr(adc_sysreg+0x3108,1); /* give CHUB the turn */
    __asm__ volatile("dsb sy" ::: "memory");
    for (unsigned i=0; rd(adc_sysreg+0x3104)==1 && rd(adc_sysreg+0x3108)==1; i++) {
        if (i==1000) {
            wr(adc_sysreg+0x3100,0);
            __asm__ volatile("dsb sy" ::: "memory");
            return -3;
        }
        delay(100); /* 100ms maximum arbitration wait */
    }
    uint32_t gate=rd(adc_cmu+0x200c), functional=rd(adc_cmu+0x3000);
    /* S0 register gate and dummy-QCH ADC clock request from CAL tables. */
    wr(adc_cmu+0x200c,gate|(3u<<20));
    wr(adc_cmu+0x3000,functional|2u);
    __asm__ volatile("dsb sy" ::: "memory");
    delay(10);
    /* Same reset, conversion timing and channel selection as exynos_adc_v3. */
    wr(adc_regs,4);
    wr(adc_regs,2);
    wr(adc_regs+4,0x60|channel);
    wr(adc_regs+0x14,1); /* clear stale completion */
    wr(adc_regs+0x10,0); /* polled completion, no GIC interrupt */
    wr(adc_regs,3);
    __asm__ volatile("dsb sy" ::: "memory");
    int error=-4;
    for (unsigned i=0;i<10000;i++) {
        if (rd(adc_regs+0x14)&1) {
            *value=rd(adc_regs+8)&0xfff;
            error=0;
            break;
        }
        delay(10);
    }
    wr(adc_regs+0x14,1);
    wr(adc_regs+0x10,0);
    wr(adc_regs+4,channel); /* clear conversion timing as vendor exit_hw */
    wr(adc_cmu+0x3000,functional);
    wr(adc_cmu+0x200c,gate);
    __asm__ volatile("dsb sy" ::: "memory");
    wr(adc_sysreg+0x3100,0);
    __asm__ volatile("dsb sy" ::: "memory");
    return error;
}
static int adc_temperature(unsigned channel, unsigned *raw)
{
    unsigned sum=0,lo=4095,hi=0;
    for (unsigned i=0;i<5;i++) {
        unsigned v;
        if (adc_sample(channel,&v)) return -27300;
        sum+=v; if(v<lo)lo=v; if(v>hi)hi=v;
    }
    *raw=(sum-lo-hi)/3; /* DT adc_check_count=5, vendor trimmed mean */
    return a51_thermistor_tenths(*raw, channel==3);
}
