"""Test the actual restricted self-binding handler with scheduler/sysctl mocks."""
from pathlib import Path
import hashlib
import json
import subprocess
import tempfile
repo=Path('/opt/a51-hakios/upstream-a51/hakios')
source=(repo/'drivers/input/hakios.input.c').read_text()
body=source.split('static int\nhakios_render_cpu SYSCTL_HANDLER_ARGS\n{',1)[1].split('\nSYSCTL_PROC(_kern, OID_AUTO, hakios_render_cpu',1)[0]
body=body.replace('#pragma unused(oidp, arg1, arg2)','')
test=r'''
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <assert.h>
#include <errno.h>
typedef int kern_return_t;
#define KERN_SUCCESS 0
static bool enable, change;
static int selected, asked, bound=-1, calls, failure, ioerror;
static int PE_parse_boot_argn(const char *name, void *dst, unsigned n) {
    (void)n;
    if(!strcmp(name,"enable_skstb")) return enable;
    if(dst) *(int*)dst=selected;
    return selected!=-1;
}
static int sysctl_get_bound_cpuid(void) { return bound; }
static int sysctl_io_number(void *req,int old,unsigned n,int *value,int *changed) {
    (void)req;(void)old;(void)n;*value=asked;*changed=change;return ioerror;
}
static int sysctl_thread_bind_cpuid(int cpu) { calls++;if(!failure) bound=cpu;return failure; }
static void hakios_tl(const char *fmt,...) { (void)fmt; }
static void *current_thread(void) { return 0; }
static uint64_t thread_tid(void *thread) { (void)thread;return 1; }
static int handler(void *req) {
''' + body + r'''
int main(void) {
    selected=1;asked=1;change=true;
    assert(handler(0)==ENOENT && calls==0); /* boot gate absent */
    enable=true;selected=-1;assert(handler(0)==ENOENT && calls==0);
    selected=2;assert(handler(0)==ENOENT && calls==0);
    selected=1;asked=0;assert(handler(0)==EINVAL && calls==0);
    asked=5;assert(handler(0)==EINVAL && calls==0);
    asked=1;assert(handler(0)==0 && calls==1 && bound==1);
    change=false;assert(handler(0)==0 && calls==1); /* read does not bind */
    change=true;asked=-1;assert(handler(0)==0 && calls==2 && bound==-1);
    ioerror=EFAULT;asked=1;assert(handler(0)==EFAULT && calls==2);
    ioerror=0;failure=4;assert(handler(0)==EINVAL && calls==3 && bound==-1);
}
'''
with tempfile.TemporaryDirectory(prefix='a51-bind-') as tmp:
    tmp=Path(tmp)
    (tmp/'test.c').write_text(test)
    subprocess.run(['clang','-std=c11','-O1','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
                    str(tmp/'test.c'),'-o',str(tmp/'test')],check=True)
    subprocess.run([str(tmp/'test')],check=True)
fb=(repo/'xnu/files/iokit/Kernel/MiniIOMobileFramebuffer.cpp').read_text()
assert 'targetCPU == 0' in fb and 'thread_bind(target);' in fb and 'thread_block(THREAD_CONTINUE_NULL);' in fb
gl=(repo/'userland/src/eagl.c').read_text()
assert 'strcmp(getprogname(), "backboardd") == 0' in gl
assert 'static _Thread_local bool render_cpu_tried;' in gl
record=dict(passed=True,cases='Both boot gates, wrong selection, wrong caller request, self-bind, read, unbind, copy failure, scheduler failure',
    source_sha256={rel:hashlib.sha256((repo/rel).read_bytes()).hexdigest() for rel in
                   ('drivers/input/hakios.input.c','userland/src/eagl.c','xnu/files/iokit/Kernel/MiniIOMobileFramebuffer.cpp')},
    on_device_placement_verified=False)
(Path(__file__).resolve().parents[1]/'full-quality-recovery/binding-tests.json').write_text(json.dumps(record,indent=2)+'\n')
print('Actual self-binding handler guard and failure cases passed under ASan/UBSan.')
