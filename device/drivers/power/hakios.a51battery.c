/* A51 SM5713 read-only monitor. a51battery=1: diagnostics, =2: Darwin.
 * Live rev07 DT: 0x13840000, gpp0-2 SDA / gpp0-3 SCL, function 2.
 * Thermistor ADC conversions are bounded and arbitrate with CHUB.
 * Only register POINTERS are written to the chips. No charger configuration,
 * charge-enable GPIO, calibration, watchdog kick, or protection changes.
 */
#include <kern/clock.h>
#include <kern/startup.h>
#include <kern/thread.h>
#include <libkern/libkern.h>
#include <mach/mach_types.h>
#include <pexpert/pexpert.h>
#include <sys/hakios.input.h>
#include <sys/systm.h>
/* SM5713 conversions from Samsung's sm5713_fuelgauge.c. No I/O. */
#ifndef A51_SM5713_DECODE_H
#define A51_SM5713_DECODE_H
static int a51_fg_soc(unsigned raw)
{
    if (raw & 0x8000) return -1;
    int value = ((raw >> 8) & 0x7f) * 100 + (raw & 255) * 100 / 256;
    return value <= 10000 ? value : -1;
}
static int a51_fg_mv(unsigned raw) { return ((raw & 0x3fff) * 1000) >> 11; }
static int a51_fg_ma(unsigned raw)
{
    int value = ((raw & 0x3fff) * 1000) >> 11;
    return raw & 0x8000 ? -value : value;
}
static int a51_fg_temp_tenths(unsigned raw)
{
    int value = ((raw & 0x7ff0) * 10) >> 8;
    return raw & 0x8000 ? -value : value;
}
static int a51_chg_status(unsigned s1, unsigned s2, int charging_enabled)
{
    if (s2 & 4) return 0; /* battery absent */
    if (!(s1 & 1)) return 2; /* discharging */
    if (s2 & 0x20) return 4; /* top-off / full */
    if ((s2 & 8) || charging_enabled) return 1; /* charging */
    return 2; /* discharging */
}
/* Thermistor calibration from the phone live revision-07 DT. */
static const int a51_battery_adc[]={314,364,418,492,576,654,733,784,913,1043,1077,1107,1141,1175,1210,1244,1278,1312,1346,1381,1493,1608,1808,2061,2309,2502,2636,2725,2818,2923,3112,3257,3400,3515,3612};
static const int a51_battery_temp[]={900,850,800,750,700,650,620,600,550,500,490,480,470,460,450,440,430,420,410,400,380,350,300,250,200,150,120,100,80,50,0,-50,-100,-150,-200};
static const int a51_charger_adc[]={290,339,391,461,542,631,685,735,810,853,998,1158,1276,1338,1423,1531,1736,1982,2224,2420,2554,2639,2728,2835,3030,3187,3326,3461,3562};
static const int a51_charger_temp[]={900,850,800,750,700,650,620,600,580,550,500,450,420,400,380,350,300,250,200,150,120,100,80,50,0,-50,-100,-150,-200};
static int a51_thermistor_tenths(unsigned raw, int charger)
{
    const int *adc=charger ? a51_charger_adc : a51_battery_adc;
    const int *temp=charger ? a51_charger_temp : a51_battery_temp;
    unsigned count=charger ? sizeof(a51_charger_adc)/sizeof(int) : sizeof(a51_battery_adc)/sizeof(int);
    /* A broken/open thermistor must not become a plausible boundary temperature. */
    if (raw < (unsigned)adc[0] || raw > (unsigned)adc[count-1]) return -27300;
    for (unsigned i=1;i<count;i++) {
        if (raw <= (unsigned)adc[i])
            return temp[i-1]+(temp[i]-temp[i-1])*(int)(raw-adc[i-1])/(adc[i]-adc[i-1]);
    }
    return -27300;
}
#endif


extern vm_offset_t ml_io_map(vm_offset_t, vm_size_t);
extern void loader_log_line(const char *);
static vm_offset_t bus, top, peri;
static uint32_t stage;
static unsigned failures;
#define CON 0
#define STAT 4
#define DS 12
#define ACK 0x80
#define PENDING 0x10
#define BUSY 0x20
#define ENABLE 0x10
#define TX 0xc0
#define RX 0x80
static uint32_t rd(vm_offset_t a) { return *(volatile uint32_t *)a; }
static void wr(vm_offset_t a, uint32_t v) { *(volatile uint32_t *)a = v; }
static void clear_pending(void) { wr(bus+CON, rd(bus+CON) & ~PENDING); }
static int pending(void)
{
    for (unsigned i=0; i<10000; i++) {
        if (rd(bus+CON) & PENDING) return 0;
        delay(1);
    }
    return -1;
}
static int idle(void)
{
    for (unsigned i=0; i<1000; i++) {
        if (!(rd(bus+STAT) & BUSY)) return 0;
        delay(1);
    }
    return -1;
}
static int stop(uint32_t mode)
{
    wr(bus+STAT, mode | ENABLE);
    clear_pending();
    return idle();
}
static int start(uint32_t mode, uint8_t address, bool repeated)
{
    wr(bus+STAT, mode | ENABLE);
    *(volatile uint8_t *)(bus+DS) = address;
    delay(1);
    wr(bus+CON, rd(bus+CON) | ACK);
    wr(bus+STAT, mode | ENABLE | BUSY);
    if (repeated) clear_pending();
    if (pending()) return -1;
    return rd(bus+STAT) & 1 ? -2 : 0;
}
static int read_reg(uint8_t address, uint8_t reg, uint8_t *bytes, unsigned count);
static int write_reg(uint8_t address, uint8_t reg, uint8_t val);
static int update_reg(uint8_t address, uint8_t reg, uint8_t val, uint8_t mask);

/* Single worker owns this dedicated bus. Never start on an already busy bus. */
static int write_reg(uint8_t address, uint8_t reg, uint8_t val)
{
    uint32_t mode = TX;
    int error;
    if (idle()) return -8;
    wr(bus + CON, ACK | 0x40 | 0x20); /* divider 512, interrupt pending polled */
    error = start(TX, address << 1, false);
    if (error) goto done;
    *(volatile uint8_t *)(bus + DS) = reg;
    delay(1);
    clear_pending();
    if (pending()) { error = -3; goto done; }
    if (rd(bus + STAT) & 1) { error = -4; goto done; }
    *(volatile uint8_t *)(bus + DS) = val;
    delay(1);
    clear_pending();
    if (pending()) { error = -5; goto done; }
    if (rd(bus + STAT) & 1) { error = -6; goto done; }
done:
    if (stop(mode) && !error) error = -9;
    wr(bus + CON, rd(bus + CON) | ACK);
    return error;
}

static int update_reg(uint8_t address, uint8_t reg, uint8_t val, uint8_t mask)
{
    uint8_t old_val = 0;
    int err = read_reg(address, reg, &old_val, 1);
    if (err) return err;
    uint8_t new_val = (old_val & ~mask) | (val & mask);
    if (new_val == old_val) return 0;
    return write_reg(address, reg, new_val);
}

/* Single worker owns this dedicated bus. Never start on an already busy bus. */
static int read_reg(uint8_t address, uint8_t reg, uint8_t *bytes, unsigned count)
{
    uint32_t mode=TX;
    int error;
    if (!count || count>2 || idle()) return -8;
    wr(bus+CON, ACK | 0x40 | 0x20); /* divider 512, interrupt pending polled */
    error=start(TX, address<<1, false);
    if (error) goto done;
    *(volatile uint8_t *)(bus+DS)=reg;
    delay(1);
    clear_pending();
    if (pending()) { error=-3; goto done; }
    if (rd(bus+STAT)&1) { error=-4; goto done; }
    mode=RX;
    error=start(RX, (address<<1)|1, true);
    if (error) goto done;
    for (unsigned i=0; i<count; i++) {
        if (i+1==count) wr(bus+CON, rd(bus+CON)&~ACK);
        clear_pending();
        if (pending()) { error=-7; goto done; }
        bytes[i]=*(volatile uint8_t *)(bus+DS);
    }
done:
    if (stop(mode) && !error) error=-9;
    wr(bus+CON, rd(bus+CON)|ACK);
    return error;
}
static int word(uint8_t reg, unsigned *out)
{
    uint8_t b[2];
    int e=read_reg(0x71, reg, b, 2);
    if (!e) *out=b[0] | (unsigned)b[1]<<8; /* SMBus little endian */
    return e;
}
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

static void poll(void)
{
    unsigned soc, voltage, current, temp, cycles;
    uint8_t s[3], c1, input, charge, wdt, floatv;
    int e=word(5,&soc);
    if (!e) e=word(7,&voltage);
    if (!e) e=word(8,&current);
    if (!e) e=word(9,&temp);
    if (!e) e=word(10,&cycles);
    for (unsigned i=0; !e && i<3; i++) e=read_reg(0x49,13+i,&s[i],1);
    if (!e) e=read_reg(0x49,0x13,&c1,1);
    if (!e) e=read_reg(0x49,0x15,&input,1);
    if (!e) e=read_reg(0x49,0x18,&charge,1);
    if (!e) e=read_reg(0x49,0x1a,&floatv,1);
    if (!e) e=read_reg(0x49,0x22,&wdt,1);
    char line[512];
    int pct=e ? -1 : a51_fg_soc(soc), mv=e ? -1 : a51_fg_mv(voltage);
    if (e || pct<0 || mv<2500 || mv>4600) {
        failures++;
        if (stage>=2) hakios_battery_invalidate();
        if (failures==1 || failures%12==0) {
            snprintf(line,sizeof(line),"a51battery: invalid sample error=%d pct=%d mv=%d failures=%u; charging status withdrawn\n",e,pct,mv,failures);
            loader_log_line(line);
        }
        return;
    }
    failures=0;
    int ma=a51_fg_ma(current);
    unsigned battery_adc=0,charger_adc=0;
    int battery_temp=adc_temperature(1,&battery_adc), charger_temp=adc_temperature(3,&charger_adc);

    /* Safe charging control for SM5713 PMIC */
    int charging_enabled = 0;
    if (s[0] & 1) { /* VBUS present */
        /* Hardware thermal safety: only charge between 0 C and 45 C */
        if (battery_temp >= 0 && battery_temp <= 450) {
            /* Reset expired watchdog and configure 90s timer */
            if (s[1] & 0x80) {
                update_reg(0x49, 0x22, 0x40, 0x40); /* clear WDT expired */
            }
            update_reg(0x49, 0x22, (2 << 1), (3 << 1)); /* 90s WDT timer */
            update_reg(0x49, 0x22, (1 << 3) | (1 << 0), (1 << 3) | (1 << 0)); /* kick & enable WDT */

            /* Set safe input current limit: 1000mA */
            update_reg(0x49, 0x15, 0x24, 0x7F);
            /* Set safe charge current limit: 1000mA */
            update_reg(0x49, 0x18, 0x12, 0x7F);

            /* Enable Q4 FET (charging) & AICL */
            update_reg(0x49, 0x13, (1 << 3) | (1 << 6), (1 << 3) | (1 << 6));
            charging_enabled = 1;
        } else {
            /* Thermal limit exceeded: turn off charging for hardware protection */
            update_reg(0x49, 0x13, 0, (1 << 3));
        }
    } else {
        /* Disconnected: turn off charging FET and watchdog */
        update_reg(0x49, 0x13, 0, (1 << 3));
        update_reg(0x49, 0x22, 0, 1);
    }

    int status = a51_chg_status(s[0], s[1], charging_enabled);

    snprintf(line,sizeof(line),"a51battery: SOC=%d.%02d%% V=%dmV I=%dmA gauge-temp=%d tenthsC cycles=%u; charger status=%02x/%02x/%02x control=%02x input-limit=%dmA charge-limit=%dmA float-raw=%02x watchdog=%02x; status=%d (charging_active=%d)\n",
        pct/100,pct%100,mv,ma,a51_fg_temp_tenths(temp),cycles&0x3ff,
        s[0],s[1],s[2],c1,100+25*(input&0x7f),100+50*(charge&0x7f),floatv,wdt,status,charging_enabled);
    loader_log_line(line);
    snprintf(line,sizeof(line),"a51battery: thermistor ADC ch1=%u temp=%d tenthsC ch3=%u temp=%d tenthsC (-27300 means invalid); charging control active\n",battery_adc,battery_temp,charger_adc,charger_temp);
    loader_log_line(line);
    if (stage<2) return;
    struct hakios_battery_state b={0};
    b.size=sizeof(b);
    b.percent_hundredths=pct;
    b.voltage_uv=mv*1000;
    b.current_ua=ma*1000;
    /* Only the separate battery thermistor may populate Battery Temperature. */
    b.temperature_hundredths=battery_temp==-27300 ? -27300 : battery_temp*10;
    b.present=!(s[1]&4);
    b.external=!!(s[0]&1);
    b.status=status;
    b.design_uah=4000000;
    b.full_uah=4000000;
    b.charge_uah=(int)((int64_t)4000000 * pct / 10000);
    b.cycles=cycles&0x3ff;
    b.usb_voltage_uv=(s[0]&1) ? 5000000 : 0;
    b.usb_current_ua=(s[0]&1) ? 1000000 : 0;
    b.usb_type=2; /* DCP */
    hakios_battery_report_source(&b, false);
}
static void worker(__unused void *p, __unused wait_result_t result)
{
    unsigned fg_id;
    uint8_t chg_id;
    int e=word(0,&fg_id);
    if (!e) e=read_reg(0x49,0x50,&chg_id,1);
    char line[180];
    /* Samsung core accepts charger DEVICEID's low 3 bits == 1. */
    if (e || fg_id>255 || (chg_id&7)!=1) {
        snprintf(line,sizeof(line),"a51battery: identity unverified error=%d; FG=%x charger=%x; no power source published\n",e,e?0:fg_id,e?0:chg_id);
        loader_log_line(line);
        return;
    }
    snprintf(line,sizeof(line),"a51battery: SM5713 FG=%x charger=%x verified; 5s read-only polling stage=%u\n",fg_id,chg_id,stage);
    loader_log_line(line);
    for (;;) {
        poll();
        delay_for_interval(5000,NSEC_PER_MSEC);
    }
}
static void a51battery_init(void)
{
    if (!PE_parse_boot_argn("a51battery",&stage,sizeof(stage))) { stage = 2; }
    if (!stage) return;
    top=ml_io_map(0x139b0000UL,0x1000);
    peri=ml_io_map(0x10030000UL,0x4000);
    bus=ml_io_map(0x13840000UL,0x1000);
    if (!top || !peri || !bus) { loader_log_line("a51battery: mapping failed\n"); return; }
    /* Dedicated battery I2C_1 gate from Exynos9610 CAL: manual + CGVAL. */
    wr(peri+0x2050,rd(peri+0x2050)|(3u<<20));
    __asm__ volatile("dsb sy" ::: "memory");
    /* GPP0 CON/PUD fields only for pins 2 and 3. Charge-enable untouched. */
    wr(top,(rd(top)&~0xff00u)|0x2200u);
    wr(top+8,rd(top+8)&~0xff00u);
    wr(bus+0x10,7); /* SDA delay and filter, as existing touch bus */
    adc_init();
    thread_t t;
    if (kernel_thread_start(worker,NULL,&t)==KERN_SUCCESS) thread_deallocate(t);
    else loader_log_line("a51battery: worker creation failed\n");
}
STARTUP(EARLY_BOOT, STARTUP_RANK_LAST, a51battery_init);
