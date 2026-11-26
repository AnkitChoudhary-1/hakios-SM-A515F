"""Exercise real register decoders and SRAM bounds, without hardware access."""
from pathlib import Path
import json
import re
import subprocess
import tempfile

HERE=Path(__file__).resolve().parent
REPO=Path('/opt/a51-hakios/upstream-a51/hakios')
source=(REPO/'devices/a51/drivers/gpu/hakios.a51gpu.c').read_text(encoding='utf-8')
bounds=re.search(r'static bool\nacpm_range_valid\(.*?\n\}',source,re.S).group()
decoder=(HERE/'a51-sm5713-decode.h').read_text(encoding='utf-8')
sram_size=re.search(r'^#define ACPM_SRAM_SIZE\s+\S+',source,re.M).group()
test=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
SRAM_SIZE
DECODER
BOUNDS
int main(void) {
    for(unsigned r=0;r<65536;r++) {
        int soc=(r>>8)*100+(r&255)*100/256;
        if((r&0x8000)||soc>10000) soc=-1;
        assert(a51_fg_soc(r)==soc);
        int mag=(r&0x3fff)*1000/2048;
        assert(a51_fg_mv(r)==mag);
        assert(a51_fg_ma(r)==((r&0x8000)?-mag:mag));
        int temp=(r&0x7ff0)*10/256;
        assert(a51_fg_temp_tenths(r)==((r&0x8000)?-temp:temp));
    }
    assert(a51_chg_status(1,8)==1);
    assert(a51_chg_status(0,8)==2);
    assert(a51_chg_status(1,0)==3);
    assert(a51_chg_status(1,0x28)==4);
    assert(a51_chg_status(3,8)==3);
    assert(a51_chg_status(5,8)==3);
    assert(a51_chg_status(1,0x88)==3);
    assert(a51_chg_status(1,0x0c)==0);
    for(int ch=0;ch<2;ch++) {
        const int *ad=ch?a51_charger_adc:a51_battery_adc;
        const int *te=ch?a51_charger_temp:a51_battery_temp;
        unsigned n=ch?sizeof(a51_charger_adc)/sizeof(int):sizeof(a51_battery_adc)/sizeof(int);
        for(unsigned i=0;i<n;i++) assert(a51_thermistor_tenths(ad[i],ch)==te[i]);
        assert(a51_thermistor_tenths(ad[0]-1,ch)==-27300);
        assert(a51_thermistor_tenths(ad[n-1]+1,ch)==-27300);
        int prev=901;
        for(unsigned i=ad[0];i<=(unsigned)ad[n-1];i++) {
            int t=a51_thermistor_tenths(i,ch);
            assert(t<=prev && t>=-200 && t<=900);prev=t;
        }
    }
    /* Actual Android reference, interpolation differs by <=0.1 degree. */
    assert(a51_thermistor_tenths(1884,0)>=285 && a51_thermistor_tenths(1884,0)<=286);
    assert(a51_thermistor_tenths(1757,1)>=296 && a51_thermistor_tenths(1757,1)<=297);
    assert(!acpm_range_valid(0,4));
    assert(!acpm_range_valid(1,4));
    assert(!acpm_range_valid(ACPM_SRAM_SIZE,4));
    assert(!acpm_range_valid(ACPM_SRAM_SIZE-4,8));
    assert(!acpm_range_valid(0xfffffffc,8));
    assert(!acpm_range_valid(4,0xffffffff));
    assert(acpm_range_valid(4,4));
    assert(acpm_range_valid(ACPM_SRAM_SIZE-4,4));
    return 0;
}
'''.replace('DECODER',decoder).replace('BOUNDS',bounds).replace('SRAM_SIZE',sram_size,1)
with tempfile.TemporaryDirectory(prefix='a51-device-services-') as d:
    p=Path(d)/'test.c';p.write_text(test,encoding='utf-8')
    exe=Path(d)/'test'
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=undefined',str(p),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
record={'passed':True,'all_65536_gauge_words_exercised':True,'status_cases':8,
        'thermistor_tables_and_android_reference_passed':True,'sram_bounds_cases':8,
        'hardware_access':False,'i2c_adc_charging_speaker_hardware_verified':False}
(HERE.parent/'device-services'/'decoder-checks.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
print(json.dumps(record))
