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
#include "a51-sm5713-decode.h"

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
#include "a51-adc-monitor.c"
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
    int ma=a51_fg_ma(current), status=a51_chg_status(s[0],s[1]);
    unsigned battery_adc=0,charger_adc=0;
    int battery_temp=adc_temperature(1,&battery_adc), charger_temp=adc_temperature(3,&charger_adc);
    snprintf(line,sizeof(line),"a51battery: SOC=%d.%02d%% V=%dmV I=%dmA gauge-temp=%d tenthsC cycles=%u; charger status=%02x/%02x/%02x control=%02x input-limit=%dmA charge-limit=%dmA float-raw=%02x watchdog=%02x; status=%d (read-only)\n",
        pct/100,pct%100,mv,ma,a51_fg_temp_tenths(temp),cycles&0x3ff,
        s[0],s[1],s[2],c1,100+25*(input&0x7f),100+50*(charge&0x7f),floatv,wdt,status);
    loader_log_line(line);
    snprintf(line,sizeof(line),"a51battery: thermistor ADC ch1=%u temp=%d tenthsC ch3=%u temp=%d tenthsC (-27300 means invalid); conversion diagnostics, no charging control\n",battery_adc,battery_temp,charger_adc,charger_temp);
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
    b.design_uah=4000000; /* live DT design; learned full/remaining unknown */
    b.cycles=cycles&0x3ff;
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
    if (!PE_parse_boot_argn("a51battery",&stage,sizeof(stage)) || !stage) return;
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
