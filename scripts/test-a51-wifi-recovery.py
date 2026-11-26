"""Execute actual driver/station functions against host fault-injection fixtures (WSL)."""
from pathlib import Path
import argparse
import hashlib, json, re, subprocess

repo = Path('/opt/a51-hakios/upstream-a51/hakios')
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--package-dir', type=Path,
                    default=Path(__file__).resolve().parents[1] / 'wifi-stability-recovery')
args = parser.parse_args()
out = args.package_dir.resolve() / 'host-tests'
out.mkdir(parents=True, exist_ok=True)
wifi = (repo / 'devices/a51/drivers/wifi/hakios.a51wifi.c').read_text()
sta = (repo / 'drivers/wifi/hakios.sta.c').read_text()
def function(name):
    a = wifi.index('\n'+name+'(')
    a = wifi.rfind('static ', 0, a)
    b = wifi.index('{', a); depth = 1; pos = b + 1
    while depth:
        depth += (wifi[pos] == '{') - (wifi[pos] == '}'); pos += 1
    return wifi[a:pos]

pre = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>
#include <unistd.h>
typedef uintptr_t vm_offset_t;
#define WLBT_MEMORY (16u<<20)
#define HIP_SCOREBOARD 448
#define HIP_QUEUE(n) (1472+(n)*1088)
#define Q_FH_CTRL 0
#define Q_FH_DAT 1
#define Q_TH_RFB 5
#define HIP_FROMHOST_BIT 5
#define MBOX_INTGR1 0x1c
#define MX_TOAP_RING 0x400
#define MX_TOAP_RIDX 0x600
#define MX_PACKETS 4
#define MX_PACKET_SIZE 128
#define PMU_PHYS 0x11860000UL
#define WLBT_CTRL_NS 0x50
#define WLBT_CTRL_S 0x54
#define WLBT_DEBUG 0x5c
#define CENTRAL_SEQ_WLBT_CONFIGURATION 0x180
#define CENTRAL_SEQ_WLBT_STATUS 0x184
#define MASK_PWR_REQ (1u<<18)
#define WLBT_RESET_SET 1u
static vm_offset_t wlbt_memory;
static uint32_t hip_base, mx_heap=0x10000, runtime_panic_offset=0x1000;
static bool wifi_transport_fault;
static uint32_t wifi_log_tail[64], wifi_log_words;
static uint8_t pmu_memory[0x2000], mailbox[0x1000];
static unsigned sleeps, consumption_after, reset_after, write_count;
static uint32_t offsets[32], values[32];
static pthread_mutex_t svc_lock=PTHREAD_MUTEX_INITIALIZER;
static void lck_mtx_lock(pthread_mutex_t *p) { pthread_mutex_lock(p); }
static void lck_mtx_unlock(pthread_mutex_t *p) { pthread_mutex_unlock(p); }
static void cache_out(vm_offset_t a, size_t n) {(void)a;(void)n;}
static uint32_t rd(vm_offset_t a) { return *(uint32_t*)a; }
static void wr(vm_offset_t a,uint32_t v) {
 if (a>=(uintptr_t)pmu_memory && a<(uintptr_t)pmu_memory+sizeof(pmu_memory)) {
  offsets[write_count]=a-(uintptr_t)pmu_memory; values[write_count++]=v;
 }
 *(uint32_t*)a=v;
}
static void w32(vm_offset_t a,uint32_t v) { *(uint32_t*)a=v; }
static void w8(vm_offset_t a,uint8_t v) { *(uint8_t*)a=v; }
static vm_offset_t ml_io_map(vm_offset_t a,size_t n) {(void)a;(void)n;return (uintptr_t)pmu_memory;}
static void IOSleep(unsigned ms) {
 (void)ms;sleeps++;
 if(consumption_after && sleeps==consumption_after) *((uint8_t*)wlbt_memory+HIP_SCOREBOARD+64+Q_TH_RFB)=1;
 if(reset_after && sleeps==reset_after) *(uint32_t*)(pmu_memory+CENTRAL_SEQ_WLBT_STATUS)=0x80<<16;
}
static void svc_event(const char *fmt,...) {(void)fmt;}
'''
body = '\n'.join(function(n) for n in ['hip_give_back','wifi_aux_drain','wifi_aux_service','wifi_panic_valid','wifi_stalled','wifi_reset'])
body = body.replace('__asm__ volatile ("dsb sy");', '/* host fixture: no ARM barrier */')
body = body.replace('__asm__ volatile ("dsb sy" : : : "memory");', '/* host fixture: no ARM barrier */')
tests = r'''
int main(void) {
 wlbt_memory=(uintptr_t)calloc(1,WLBT_MEMORY);assert(wlbt_memory);
 uint8_t *sb=(uint8_t*)wlbt_memory+HIP_SCOREBOARD;
 /* Return queue wrap, full queue preservation, and firmware freeing one slot. */
 sb[Q_TH_RFB]=255;sb[64+Q_TH_RFB]=1;
 assert(hip_give_back((uintptr_t)mailbox,0x1234));assert(sb[Q_TH_RFB]==0);
 sb[Q_TH_RFB]=255;sb[64+Q_TH_RFB]=0;sleeps=0;
 assert(!hip_give_back((uintptr_t)mailbox,0x5678));assert(sleeps==10 && sb[Q_TH_RFB]==255);
 assert(rd(wlbt_memory+HIP_QUEUE(Q_TH_RFB)+4*255)==0x1234);
 sleeps=0;consumption_after=2;wifi_transport_fault=false;
 assert(hip_give_back((uintptr_t)mailbox,0x5678));assert(sleeps==2 && !wifi_transport_fault);
 consumption_after=0;
 /* Idle networks never reset; pending queues require a full 15 seconds without progress. */
 memset(sb,0,128);uint8_t prev[6]={0};uint64_t progress=0;
 assert(!wifi_stalled(wlbt_memory,20000,prev,&progress) && progress==20000);
 sb[Q_FH_DAT]=1;
 assert(!wifi_stalled(wlbt_memory,34999,prev,&progress));
 assert(wifi_stalled(wlbt_memory,35000,prev,&progress));
 sb[64+Q_FH_DAT]=1;assert(!wifi_stalled(wlbt_memory,35001,prev,&progress));
 sb[Q_FH_DAT]=2;assert(!wifi_stalled(wlbt_memory,50000,prev,&progress));
 sb[64+Q_FH_CTRL]=2;assert(!wifi_stalled(wlbt_memory,50001,prev,&progress) && progress==50001);
 /* Only complete checksummed version-2 panic records trigger recovery. */
 uint32_t *record=(uint32_t*)(wlbt_memory+runtime_panic_offset);
 assert(!wifi_panic_valid());record[0]=2;record[1]=20;record[2]=0xb50ff;record[3]=0x25002a02;
 record[4]=0xa5a5a5a5^record[0]^record[1]^record[2]^record[3];assert(wifi_panic_valid());
 record[4]^=1;assert(!wifi_panic_valid());record[1]=0;assert(!wifi_panic_valid());
 record[1]=1024;assert(!wifi_panic_valid());runtime_panic_offset=WLBT_MEMORY-4;assert(!wifi_panic_valid());
 /* Management/debug/log rings wrap correctly; their writer indices must remain untouched. */
 uint8_t *mx=(uint8_t*)wlbt_memory+mx_heap;
 *(uint32_t*)(mx+0x600)=3;*(uint32_t*)(mx+0x640)=1;
 mx[0x400+3*128]=1;mx[0x400+3*128+1]=2;
 wifi_aux_drain((uintptr_t)mailbox,0x400,0x600,4,128,1,false);
 assert(*(uint32_t*)(mx+0x600)==1 && *(uint32_t*)(mx+0x640)==1);
 *(uint32_t*)(mx+0x9000)=4095;*(uint32_t*)(mx+0x9040)=1;
 *(uint32_t*)(mx+0x5000+4095*4)=0xabc;*(uint32_t*)(mx+0x5000)=0xdef;
 wifi_aux_drain((uintptr_t)mailbox,0x5000,0x9000,4096,4,4,true);
 assert(wifi_log_words==2 && wifi_log_tail[0]==0xabc && wifi_log_tail[1]==0xdef);
 assert(*(uint32_t*)(mx+0x9000)==1 && *(uint32_t*)(mx+0x9040)==1);
 *(uint32_t*)(mx+0x600)=4;wifi_transport_fault=false;
 wifi_aux_drain((uintptr_t)mailbox,0x400,0x600,4,128,1,false);assert(wifi_transport_fault);
 /* Reset timeout preserves shared memory; register sequence matches Samsung's case-2 reset. */
 memset(pmu_memory,0xff,sizeof(pmu_memory));sleeps=write_count=0;reset_after=0;
 uint32_t marker=rd(wlbt_memory+0x5000);
 assert(!wifi_reset() && sleeps==50 && rd(wlbt_memory+0x5000)==marker);
 const uint32_t sequence[]={0x50,0x180,0x1360,0x1364,0x1368,0x136c,0x1370,0x1374,0x50};
 assert(write_count==9);for(unsigned i=0;i<9;i++)assert(offsets[i]==sequence[i]);
 assert((values[1]&(1u<<16))==0 && (values[2]&3)==0 && (values[6]&1)==1);
 assert((values[8]&WLBT_RESET_SET)!=0);
 memset(pmu_memory,0,sizeof(pmu_memory));sleeps=write_count=0;reset_after=3;
 assert(wifi_reset() && sleeps==3 && write_count==10);
 assert((rd((uintptr_t)pmu_memory+WLBT_CTRL_NS)&MASK_PWR_REQ)==0);
 free((void*)wlbt_memory);puts("driver fault-injection tests passed");
}
'''
(out/'driver-fixture.c').write_text(pre+body+tests)

station_pre = pre[:pre.index('typedef uintptr_t')] + r'''
#define KERNEL 1
#include <sys/errno.h>
#include "hakios.sta.h"
#define __unused __attribute__((unused))
#define LCK_GRP_DECLARE(n,s) int n
#define LCK_MTX_DECLARE(n,g) pthread_mutex_t n=PTHREAD_MUTEX_INITIALIZER
#define LCK_SLEEP_DEFAULT 0
#define THREAD_UNINT 0
#define Z_WAITOK 1
#define Z_ZERO 2
#define KERN_SUCCESS 0
typedef void* event_t;typedef void* thread_t;typedef int wait_result_t;
static pthread_cond_t condition=PTHREAD_COND_INITIALIZER;
static void lck_mtx_lock(pthread_mutex_t *p) { pthread_mutex_lock(p); }
static void lck_mtx_unlock(pthread_mutex_t *p) { pthread_mutex_unlock(p); }
static void lck_mtx_sleep(pthread_mutex_t *p,int flags,event_t e,int mode) {(void)flags;(void)e;(void)mode;pthread_cond_wait(&condition,p);}
static void thread_wakeup(event_t e) {(void)e;pthread_cond_broadcast(&condition);}
static void *kalloc_data(size_t n,int f) {(void)f;return calloc(1,n);}
static void kfree_data(void*p,size_t n) {(void)n;free(p);}
static int kernel_thread_start(void (*f)(void*,int),void*p,thread_t*t) {(void)f;(void)p;*t=NULL;return 0;}
static void thread_deallocate(thread_t t) {(void)t;}
void thread_set_thread_name(thread_t t,const char *n) {(void)t;(void)n;}
static void hakios_wifi_tell(const char*f,...) {(void)f;}
void hakios_apple80211_event(enum hakios_sta_event e,int s) {(void)e;(void)s;}
'''
station_tests = r'''
static unsigned state_calls;
static void state_impl(struct hakios_sta_state *s) {state_calls++;s->phase=HAKIOS_STA_JOINED;}
static void *begin_thread(void *p) {(void)p;hakios_sta_recovery_begin();return NULL;}
int main(void) {
 static struct hakios_sta_ops ops={.state=state_impl};sta_ops=&ops;sta_on=true;
 struct hakios_sta_join a={.ssid_length=1,.ssid={'A'}},b={.ssid_length=1,.ssid={'B'}};
 assert(hakios_sta_ask_join_standing(&a)==0);asked_join=false;
 hakios_sta_recovery_begin();struct hakios_sta_state state;
 hakios_sta_state(&state);assert(state.phase==HAKIOS_STA_IDLE && state.last_error==EIO && !state_calls);
 assert(hakios_sta_busy());hakios_sta_recovery_end();assert(asked_join && asked_join_what.ssid[0]=='A');
 asked_join=false;hakios_sta_recovery_begin();assert(hakios_sta_ask_join(&b)==0);
 hakios_sta_recovery_end();assert(asked_join_what.ssid[0]=='B');
 asked_join=false;hakios_sta_recovery_begin();assert(hakios_sta_ask_power(false)==0);
 hakios_sta_recovery_end();assert(!asked_join && !sta_on && asked_power && !asked_power_on);
 asked_power=false;sta_on=true;hakios_sta_recovery_begin();assert(hakios_sta_ask_leave()==0);
 hakios_sta_recovery_end();assert(!asked_join && asked_leave && reconnect.ssid_length==0);
 /* Real pthread wait: recovery cannot return while a callback/read still uses the driver. */
 sta_calls=true;sta_reads=1;pthread_t t;assert(!pthread_create(&t,NULL,begin_thread,NULL));
 bool paused=false;for(unsigned i=0;i<1000 && !paused;i++) {
  usleep(1000);lck_mtx_lock(&sta_lock);paused=sta_recovering;lck_mtx_unlock(&sta_lock);
 }assert(paused);
 lck_mtx_lock(&sta_lock);assert(sta_calls && sta_reads==1);sta_calls=false;sta_reads=0;lck_mtx_unlock(&sta_lock);
 thread_wakeup((event_t)&sta_calls);assert(!pthread_join(t,NULL));
 assert(sta_recovering);hakios_sta_recovery_end();
 puts("station request/concurrency tests passed");
}
'''
(out/'hakios.sta.h').write_text((repo/'xnu/files/bsd/sys/hakios.sta.h').read_text())
(out/'station-fixture.c').write_text(station_pre+re.sub(r'^#include .*\n','',sta,flags=re.M)+station_tests)
results=[]
for name in ['driver','station']:
    subprocess.run(['clang','-O1','-g','-fsanitize=address,undefined','-pthread',f'{name}-fixture.c','-o',f'{name}-fixture'],cwd=out,check=True)
    run=subprocess.run([str(out/f'{name}-fixture')],cwd=out,check=True,text=True,capture_output=True)
    results.append({'fixture':name,'result':run.stdout.strip()})
# Firmware reads refs from mxconf; verify ALL seven streams separate their owned indices.
streams=re.findall(r'mx_stream(?:_sized)?\(conf \+ \d+, [^,]+, (0x[0-9a-f]+|MX_\w+), (0x[0-9a-f]+|MX_\w+),',wifi)
defines={k:int(v,16) for k,v in re.findall(r'#define (MX_\w+)\s+(0x[0-9a-f]+)',wifi)}
assert len(streams)==7
for r,w in streams:
    r=defines[r] if r in defines else int(r,16);w=defines[w] if w in defines else int(w,16)
    assert r//64 != w//64 and w-r==64
results.append({'fixture':'mxconf ownership','result':'all 7 streams use separate read/write cache lines'})
(out/'results.json').write_text(json.dumps({'tests':results,'hardware_tested':False,'sources':{
    'wifi':hashlib.sha256(wifi.encode()).hexdigest(),'station':hashlib.sha256(sta.encode()).hexdigest()}},indent=2)+'\n')
print(json.dumps(results,indent=2))
