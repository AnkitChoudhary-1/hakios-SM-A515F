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
static int a51_chg_status(unsigned s1, unsigned s2)
{
    if (s2 & 4) return 0; /* battery absent */
    if (!(s1 & 1)) return 2; /* discharging */
    if ((s1 & 6) || (s2 & 0x80)) return 3; /* input fault / watchdog */
    if (s2 & 0x20) return 4; /* top-off */
    return s2 & 8 ? 1 : 3;
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
