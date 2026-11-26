from pathlib import Path
import hashlib
import json
repo=Path(r'\\wsl.localhost\A51-KernelBuilder\opt\a51-hakios\upstream-a51\hakios')
base=Path(__file__).resolve().parents[1]/'full-quality-recovery'
record=json.loads((base/'source-changes.json').read_text())
for rel in ('userland/src/eagl.c','drivers/input/hakios.input.c'):
    assert hashlib.sha256((repo/rel).read_bytes()).hexdigest()==record['files'][rel]['after_sha256']
p=repo/'drivers/input/hakios.input.c'
text=p.read_text()
text=text.replace('#include <kern/thread_call.h>','#include <kern/thread_call.h>\n#include <kern/thread.h>')
old='static bool\nlatency_lines(void)'
new='''/* backboardd is uid mobile. Permit only self-binding to the rendering core
 * selected for this DEVELOPMENT experiment, never arbitrary task/core access.
 * The stock enable_skstb guard remains required. No shipping scheduler change. */
#if DEVELOPMENT || DEBUG
extern int32_t sysctl_get_bound_cpuid(void);
extern kern_return_t sysctl_thread_bind_cpuid(int32_t cpuid);
static int
hakios_render_cpu SYSCTL_HANDLER_ARGS
{
#pragma unused(oidp, arg1, arg2)
	int selected = -1;
	if (!PE_parse_boot_argn("enable_skstb", NULL, 0) ||
	    !PE_parse_boot_argn("gl_cpu", &selected, sizeof(selected)) || selected != 1) return ENOENT;
	int32_t bound = sysctl_get_bound_cpuid(), requested = bound;
	int changed = 0;
	int error = sysctl_io_number(req, bound, sizeof(bound), &requested, &changed);
	if (error || !changed) return error;
	if (requested != 1 && requested != -1) return EINVAL;
	kern_return_t kr = sysctl_thread_bind_cpuid(requested);
	hakios_tl("tl: render tid %llu requested %d bound %d result %d\\n",
	    thread_tid(current_thread()), requested, sysctl_get_bound_cpuid(), kr);
	return kr == KERN_SUCCESS ? 0 : EINVAL;
}
SYSCTL_PROC(_kern, OID_AUTO, hakios_render_cpu, CTLTYPE_INT | CTLFLAG_RW | CTLFLAG_LOCKED | CTLFLAG_ANYBODY,
    0, 0, hakios_render_cpu, "I", "Experimental calling-thread render CPU");
#endif

static bool
latency_lines(void)'''
assert text.count(old)==1
p.write_text(text.replace(old,new),newline='\n')
p=repo/'userland/src/eagl.c'
text=p.read_text().replace('kern.sched_thread_bind_cpu','kern.hakios_render_cpu')
text=text.replace('/* Opt-in experiment, confined to the compositor\'s GL threads. The stock\n * development sysctl retains its enable_skstb guard and permission checks. */',
    '/* Opt-in experiment, confined to the compositor\'s GL threads. The kernel\n * restricts self-binding to this selected core with enable_skstb present. */')
p.write_text(text,newline='\n')
for rel,item in record['files'].items():
    item['after_sha256']=hashlib.sha256((repo/rel).read_bytes()).hexdigest()
(base/'source-changes.json').write_text(json.dumps(record,indent=2)+'\n')
