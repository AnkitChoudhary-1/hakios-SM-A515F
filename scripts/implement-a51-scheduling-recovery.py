"""One-time guarded incremental changes, with a snapshot of the tested parent."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import shutil

BASE = Path(__file__).resolve().parents[1]
REPO = Path(r'\\wsl.localhost\A51-KernelBuilder\opt\a51-hakios\upstream-a51\hakios')
OUT = BASE / 'full-quality-recovery'
PARENT = BASE / 'full-quality'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
assert not (OUT / 'source-changes.json').exists(), 'Already applied; do not rerun'
parent = json.loads((PARENT / 'source-changes.json').read_text())
for rel, entry in parent['files'].items():
    assert sha(REPO / rel) == entry['after_sha256'], rel
files = list(parent['files']) + ['userland/src/net_test.m', 'drivers/input/hakios.input.c',
                               'devices/a51/drivers/wifi/hakios.a51wifi.c']
for rel in files:
    saved = OUT / 'source-before' / rel
    saved.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO / rel, saved)
for name in ('source-changes.json', 'boot-package-manifest.json', 'runtime-verification.json'):
    if (PARENT / name).exists(): shutil.copy2(PARENT / name, OUT / ('parent-' + name))
def edit(rel, old, new):
    p = REPO / rel
    text = p.read_text()
    assert text.count(old) == 1, (rel, old[:70], text.count(old))
    p.write_text(text.replace(old, new), newline='\n')

fb = 'xnu/files/iokit/Kernel/MiniIOMobileFramebuffer.cpp'
edit(fb, '#include <kern/clock.h>', '#include <kern/clock.h>\n#include <kern/processor.h>\n#include <kern/sched_prim.h>')
edit(fb, '\tnanoseconds_to_absolutetime(SETTLE_MS * NSEC_PER_MSEC, &settleTime);', '''
	/* Optional A51 experiment: only the always-online boot CPU may be bound.
	 * It is logical CPU 0 (physical A73 4 with bootcpu=4). Other/default
	 * configurations retain normal scheduling. Rendering uses a separate core. */
	int targetCPU = -1;
	if (PE_parse_boot_argn("fb_cpu", &targetCPU, sizeof(targetCPU)) && targetCPU == 0) {
		processor_t target = cpu_to_processor(0);
		if (target != PROCESSOR_NULL) {
			thread_bind(target);
			thread_block(THREAD_CONTINUE_NULL);
			hakios_tl("tl: display presenter bound cpu %d actual %d\\n", targetCPU, cpu_number());
		}
	}
	nanoseconds_to_absolutetime(SETTLE_MS * NSEC_PER_MSEC, &settleTime);'''.strip('\n'))
edit(fb, '\tuint32_t layers = 0;\n\tMiniIOSurface * recorded', '\tuint32_t layers = 0;\n\tint readyCPU = -1, drawnCPU = -1;\n\tMiniIOSurface * recorded')
edit(fb, '\tbegan = ready = mach_absolute_time();', '\tbegan = ready = mach_absolute_time();\n\treadyCPU = cpu_number();')
edit(fb, '\tdrawn = mach_absolute_time();\n\tdeconAfter();', '\tdrawn = mach_absolute_time();\n\tdrawnCPU = cpu_number();\n\tdeconAfter();')
edit(fb, '"tl: v %u ready %llu shown %llu done %llu\\n"', '"tl: v %u ready %llu shown %llu done %llu cpu %d %d\\n"')
edit(fb, '\t\t    micros(drawn));', '\t\t    micros(drawn), readyCPU, drawnCPU);')

gl = 'userland/src/eagl.c'
edit(gl, 'static void\neagl_enter(struct eagl *e, unsigned offset)', '''/* Opt-in experiment, confined to the compositor's GL threads. The stock
 * development sysctl retains its enable_skstb guard and permission checks. */
static int render_cpu = -1;
static _Thread_local bool render_cpu_tried;
static void
render_bind(void)
{
	if (render_cpu != 1 || render_cpu_tried) return;
	render_cpu_tried = true;
	int bound = -1;
	size_t len = sizeof(bound);
	int result = sysctlbyname("kern.sched_thread_bind_cpu", NULL, NULL, &render_cpu, sizeof(render_cpu));
	int error = result == 0 ? 0 : errno;
	if (result == 0) result = sysctlbyname("kern.sched_thread_bind_cpu", &bound, &len, NULL, 0);
	char line[128];
	snprintf(line, sizeof(line), "render binding requested=1 actual=%d error=%d", bound, error ? error : (result ? errno : 0));
	say("hakios-gl: %s\\n", line);
	sysctlbyname("kern.hakios_netlog", NULL, NULL, line, strlen(line));
}

static void
eagl_enter(struct eagl *e, unsigned offset)''')
edit(gl, '\tslot_calls[offset / 8]++;', '\trender_bind();\n\tslot_calls[offset / 8]++;')
edit(gl, '\t/* the kernel\'s boot-args are where a run is told things */', '''	/* Logical A73 CPU 1 is separate from the display's boot CPU 0. */
	/* the kernel's boot-args are where a run is told things */''')
edit(gl, '\t\tif ((argument = strstr(arguments, "gltrace=")) != NULL) {', '''		if (strcmp(getprogname(), "backboardd") == 0 && strstr(arguments, " gl_cpu=1") != NULL) render_cpu = 1;
		if ((argument = strstr(arguments, "gltrace=")) != NULL) {''')

inp = 'drivers/input/hakios.input.c'
edit(inp, '#include <sys/uio.h>', '#include <sys/uio.h>\n#include <sys/sysctl.h>')
edit(inp, 'static bool\nlatency_lines(void)', '''/* Small root-only diagnostic messages retained by the loader. No read API,
 * no embedded lines, and no arbitrary length access to the loader log. */
static int
hakios_netlog SYSCTL_HANDLER_ARGS
{
#pragma unused(oidp, arg1, arg2)
	char line[160];
	if (req->newptr == USER_ADDR_NULL || req->newlen == 0 || req->newlen >= sizeof(line)) return EINVAL;
	int error = SYSCTL_IN(req, line, req->newlen);
	if (error) return error;
	line[req->newlen] = 0;
	for (size_t i = 0; i < req->newlen; i++) if ((unsigned char)line[i] < 32) line[i] = ' ';
	hakios_tl("tl: net %s\\n", line);
	return 0;
}
SYSCTL_PROC(_kern, OID_AUTO, hakios_netlog, CTLTYPE_STRING | CTLFLAG_WR | CTLFLAG_LOCKED,
    0, 0, hakios_netlog, "A", "Root diagnostic line to loader");

static bool
latency_lines(void)''')

wifi = 'devices/a51/drivers/wifi/hakios.a51wifi.c'
edit(wifi, 'static char svc_events[700];', 'extern void hakios_tl(const char *format, ...) __printflike(1, 2);\nstatic char svc_events[700];')
edit(wifi, '\tprintf("a51wifi: %s\\n", line);', '\tprintf("a51wifi: %s\\n", line);\n\thakios_tl("tl: wifi at %llus %s\\n", now_ms() / 1000, line);')
edit(wifi, '\t\t\tfor (int i = 0; i < CTL_BLOCKS; i++) {', '\t\t\tlck_mtx_lock(&svc_lock);\n\t\t\tfor (int i = 0; i < CTL_BLOCKS; i++) {')
edit(wifi, '\t\t\tprintf("a51wifi: service: panic record', '''			lck_mtx_unlock(&svc_lock);
			hakios_tl("tl: wifi at %llus phase %d error %d tx %llu rx %llu drop %llu/%llu busy %u/%u panic %x/%x\\n",
			    now_ms()/1000, svc.phase, svc.last_error, svc.sent, svc.received, svc.dropped_out, svc.dropped_in,
			    busy_ctl, busy_dat, pw[2], pw[3]);
			hakios_tl("tl: wifi queues host %02x %02x %02x %02x %02x %02x fw %02x %02x %02x %02x %02x %02x\\n",
			    *(volatile uint8_t *)(sb+0), *(volatile uint8_t *)(sb+1), *(volatile uint8_t *)(sb+2),
			    *(volatile uint8_t *)(sb+3), *(volatile uint8_t *)(sb+4), *(volatile uint8_t *)(sb+5),
			    *(volatile uint8_t *)(sb+64), *(volatile uint8_t *)(sb+65), *(volatile uint8_t *)(sb+66),
			    *(volatile uint8_t *)(sb+67), *(volatile uint8_t *)(sb+68), *(volatile uint8_t *)(sb+69));
			printf("a51wifi: service: panic record''')

net = 'userland/src/net_test.m'
edit(net, '#include <unistd.h>', '#include <unistd.h>\n#include "net-recovery-policy.h"')
edit(net, 'extern Boolean SCDynamicStoreSetNotificationKeys', 'extern Boolean SCDynamicStoreNotifyValue(SCDynamicStoreRef store, CFStringRef key);\nextern Boolean SCDynamicStoreSetNotificationKeys')
edit(net, '\t\t\thas_ipv4 = true;', '\t\t\thas_ipv4 |= net_ipv4_usable(ntohl(in->sin_addr.s_addr));')
edit(net, '/* ---- wrongjoin --------------------------------------------------------------------------------------- */', '''/* ---- recovery: refresh the existing configd service, never a second DHCP client ---- */
static NSDictionary *net_dict(SCDynamicStoreRef session, NSString *key)
{
	id value = CFBridgingRelease(SCDynamicStoreCopyValue(session, (__bridge CFStringRef)key));
	return [value isKindOfClass:NSDictionary.class] ? value : nil;
}
static bool net_router(id value)
{
	struct in_addr addr;
	return [value isKindOfClass:NSString.class] && inet_pton(AF_INET, [value UTF8String], &addr) == 1 &&
	    net_ipv4_usable(ntohl(addr.s_addr));
}
static void net_line(NSString *message)
{
	printf("net_test: %s\\n", message.UTF8String);
	const char *line = message.UTF8String;
	sysctlbyname("kern.hakios_netlog", NULL, NULL, line, strnlen(line, 159));
}
static void recover(const char *name)
{
	struct net_recovery_state state = {0};
	double reported = -60;
	for (;;) {
		@autoreleasepool {
			double now = seconds();
			SCDynamicStoreRef session = SCDynamicStoreCreate(NULL, CFSTR("hakios DHCP recovery"), NULL, NULL);
			bool known = session != NULL, up = false, ipv4 = false, ipv6 = false, router = false, dhcp_service = false;
			NSString *ipText = @"-", *routerText = @"-", *dnsText = @"-";
			struct ifaddrs *list = NULL;
			if (getifaddrs(&list) != 0) known = false;
			for (struct ifaddrs *a = list; a; a = a->ifa_next) {
				if (strcmp(a->ifa_name, name) || !a->ifa_addr) continue;
				up |= (a->ifa_flags & (IFF_UP|IFF_RUNNING)) == (IFF_UP|IFF_RUNNING);
				if (a->ifa_addr->sa_family == AF_INET) {
					struct in_addr ip = ((struct sockaddr_in *)a->ifa_addr)->sin_addr;
					char text[64]; inet_ntop(AF_INET, &ip, text, sizeof(text)); ipText = @(text);
					ipv4 |= net_ipv4_usable(ntohl(ip.s_addr));
				} else if (a->ifa_addr->sa_family == AF_INET6) {
					struct in6_addr *ip = &((struct sockaddr_in6 *)a->ifa_addr)->sin6_addr;
					ipv6 |= !IN6_IS_ADDR_LINKLOCAL(ip) && !IN6_IS_ADDR_UNSPECIFIED(ip) &&
					    !IN6_IS_ADDR_LOOPBACK(ip) && !IN6_IS_ADDR_MULTICAST(ip);
				}
			}
			if (list) freeifaddrs(list);
			/* Apple80211 state 4 means JOINED in this port, independent of a stale UI toggle. */
			struct { char name[16]; int32_t type, value; uint32_t length; void *data __attribute__((aligned(8))); } request = { .type = 13 };
			strlcpy(request.name, name, sizeof(request.name));
			int fd = socket(AF_INET, SOCK_DGRAM, 0);
			bool joined = fd >= 0 && ioctl(fd, 0xc02869c9u, &request) == 0 && request.value == 4;
			if (fd >= 0) close(fd);
			if (session) {
				NSArray *keys = CFBridgingRelease(SCDynamicStoreCopyKeyList(session, CFSTR("Setup:/Network/Service/[^/]+/Interface")));
				if (!keys) known = false;
				for (NSString *key in keys) {
					NSDictionary *interface = net_dict(session, key);
					if (![interface[@"DeviceName"] isEqual:@(name)]) continue;
					NSString *setup = [key substringToIndex:key.length - @"Interface".length];
					NSDictionary *method = net_dict(session, [setup stringByAppendingString:@"IPv4"]);
					if (![method[@"ConfigMethod"] isEqual:@"DHCP"]) continue;
					dhcp_service = true;
					NSString *runtime = [setup stringByReplacingOccurrencesOfString:@"Setup:" withString:@"State:"];
					NSDictionary *v4 = net_dict(session, [runtime stringByAppendingString:@"IPv4"]);
					id gateway = v4[@"Router"];
					router |= net_router(gateway);
					if ([gateway isKindOfClass:NSString.class]) routerText = gateway;
					NSDictionary *dns = net_dict(session, [runtime stringByAppendingString:@"DNS"]);
					id servers = dns[@"ServerAddresses"];
					if ([servers isKindOfClass:NSArray.class]) dnsText = [servers componentsJoinedByString:@","];
				}
			}
			if (now - reported >= 60) {
				net_line([NSString stringWithFormat:@"DHCP %@ joined=%d up=%d service=%d known=%d ip=%@ router=%@ v6=%d", @(name), joined, up, dhcp_service, known, ipText, routerText, ipv6]);
				net_line([NSString stringWithFormat:@"DHCP %@ DNS=%@", @(name), dnsText]);
				reported = now;
			}
			if (net_recovery_due(&state, now, known, joined, up, dhcp_service, ipv4, router, ipv6)) {
				NSString *key = [NSString stringWithFormat:@"State:/Network/Interface/%@/RefreshConfiguration", @(name)];
				Boolean sent = SCDynamicStoreNotifyValue(session, (__bridge CFStringRef)key);
				net_line([NSString stringWithFormat:@"DHCP %@ persistent lease failure refresh sent=%d", @(name), sent]);
			}
			if (session) CFRelease(session);
		}
		sleep(10);
	}
}

/* ---- wrongjoin --------------------------------------------------------------------------------------- */''')
edit(net, '\t\t\t} else if (strcmp(step, "wrongjoin") == 0) {', '\t\t\t} else if (strcmp(step, "recover") == 0 && i + 1 < argc) {\n\t\t\t\trecover(argv[++i]);\n\t\t\t} else if (strcmp(step, "wrongjoin") == 0) {')
new = 'userland/src/net-recovery-policy.h'
shutil.copy2(BASE / 'scripts/net-recovery-policy.h', REPO / new)
records = {rel: {'before_sha256': sha(OUT/'source-before'/rel), 'after_sha256': sha(REPO/rel)} for rel in files}
records[new] = {'before_sha256': None, 'after_sha256': sha(REPO/new)}
(OUT / 'source-changes.json').write_text(json.dumps(dict(at_utc=datetime.now(timezone.utc).isoformat(),
    parent_profile='full-quality', parent_manifest_sha256=sha(PARENT/'boot-package-manifest.json'), files=records,
    preserves_original_render_quality=True, hardware_tested=False), indent=2)+'\n')
print('Candidate source changes and tested-parent snapshots saved:', OUT)
