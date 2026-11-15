/* SPDX-License-Identifier: MIT */
/* Static Darwin arm64 PID 1. No libc, dyld, or Apple user-space binaries. */
typedef unsigned long u64;


/* Clang emits bzero for aggregate initialization in this static binary. */
void
bzero(void *out, unsigned long size)
{
	volatile unsigned char *p = out;
	while (size--) { *p++ = 0; }
}

#define SYS_exit 1
#define SYS_write 4
#define SYS_open 5
#define SYS_getpid 20
#define SYS_getuid 24
#define SYS_select 93
#define SYS_gettimeofday 116
#define SYS_sysctlbyname 274
#define O_RDWR 2

/* Darwin returns a positive errno with carry set. Normalize it to -errno. */
static long
call(long num, long a, long b, long c, long d, long e, long f)
{
	register long x16 __asm__("x16") = num;
	register long x0 __asm__("x0") = a;
	register long x1 __asm__("x1") = b;
	register long x2 __asm__("x2") = c;
	register long x3 __asm__("x3") = d;
	register long x4 __asm__("x4") = e;
	register long x5 __asm__("x5") = f;
	__asm__ volatile ("svc #0x80\n\tcneg x0, x0, cs"
	    : "+r" (x0), "+r" (x1), "+r" (x2), "+r" (x3), "+r" (x4), "+r" (x5)
	    : "r" (x16) : "memory", "cc");
	return x0;
}

static unsigned
length(const char *s)
{
	unsigned n = 0;
	while (s[n]) { n++; }
	return n;
}

static void
put(int fd, const char *s)
{
	unsigned remaining = length(s);
	while (remaining) {
		long n = call(SYS_write, fd, (long)s, remaining, 0, 0, 0);
		if (n <= 0 || (u64)n > remaining) { return; }
		s += n;
		remaining -= (unsigned)n;
	}
}

static void
number(int fd, long v)
{
	char buf[24];
	unsigned i = sizeof(buf);
	u64 n = v < 0 ? 0UL - (u64)v : (u64)v;
	buf[--i] = 0;
	do { buf[--i] = (char)('0' + n % 10); n /= 10; } while (n);
	if (v < 0) { buf[--i] = '-'; }
	put(fd, buf + i);
}

static void
hex(int fd, u64 n)
{
	char buf[19];
	unsigned i = sizeof(buf);
	buf[--i] = 0;
	do { buf[--i] = "0123456789abcdef"[n & 15]; n >>= 4; } while (n);
	buf[--i] = 'x'; buf[--i] = '0';
	put(fd, buf + i);
}

static long
sysctl(const char *name, void *out, u64 *size)
{
	return call(SYS_sysctlbyname, (long)name, length(name), (long)out, (long)size, 0, 0);
}

static long
integer(const char *name, int *out)
{
	u64 size = sizeof(*out);
	long result = sysctl(name, out, &size);
	return result ? result : (size == sizeof(*out) ? 0 : -1);
}

static long
quad(const char *name, u64 *out)
{
	u64 size = sizeof(*out);
	long result = sysctl(name, out, &size);
	return result ? result : (size == sizeof(*out) ? 0 : -1);
}

/* user64_timeval: 64-bit seconds, 32-bit microseconds, four padding bytes. */
struct timeval { long sec; int usec; int padding; };

static long
now(long *us)
{
	struct timeval tv = {0, 0, 0};
	long result = call(SYS_gettimeofday, (long)&tv, 0, 0, 0, 0, 0);
	if (result) { return result; }
	if (tv.sec < 0 || tv.sec > 9000000000000L || tv.usec < 0 || tv.usec >= 1000000) { return -1; }
	*us = tv.sec * 1000000L + tv.usec;
	return 0;
}

static long
wait_seconds(const char *args)
{
	const char *key = "hello_wait=";
	for (unsigned i = 0; args[i]; i++) {
		unsigned j = 0;
		if (i && args[i - 1] != ' ') { continue; }
		while (key[j] && args[i + j] && key[j] == args[i + j]) { j++; }
		if (!key[j]) {
			long n = 0;
			for (i += j; args[i] >= '0' && args[i] <= '9'; i++) {
				n = n * 10 + args[i] - '0';
				if (n > 30) { return -1; }
			}
			return n;
		}
	}
	return 0;
}

static int
show_nonce(int fd, const char *args)
{
	const char *key = "hakios_run_nonce=";
	for (unsigned i = 0; args[i]; i++) {
		unsigned j = 0;
		if (i && args[i - 1] != ' ') { continue; }
		while (key[j] && args[i + j] && key[j] == args[i + j]) { j++; }
		if (!key[j]) {
			char value[33];
			unsigned n = 0;
			for (i += j; args[i] && args[i] != ' '; i++) {
				char c = args[i];
				if (n == 32 || !((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) { return 0; }
				value[n++] = c;
			}
			if (n != 32) { return 0; }
			value[n] = 0;
			put(fd, "HAKIOS_RUN_NONCE="); put(fd, value); put(fd, "\n");
			return 1;
		}
	}
	return 0;
}

void
start(void)
{
	long opened = call(SYS_open, (long)"/dev/console", O_RDWR, 0, 0, 0, 0);
	int fd = opened < 0 ? 1 : (int)opened;
	long pid = call(SYS_getpid, 0, 0, 0, 0, 0, 0);
	long uid = call(SYS_getuid, 0, 0, 0, 0, 0, 0);
	char args[700] = {0};
	u64 size = sizeof(args);
	long args_rc = sysctl("kern.bootargs", args, &size);
	args[sizeof(args) - 1] = 0;
	int failed = opened < 0 || pid != 1 || uid != 0 || args_rc != 0 || size > sizeof(args);
	int timer_verified = 0;

	put(fd, "\nHello from user space on Darwin!\nHAKIOS_USER_BEGIN pid="); number(fd, pid);
	put(fd, " uid="); number(fd, uid); put(fd, " console="); number(fd, opened); put(fd, "\n");
	put(fd, "kern.bootargs="); put(fd, args); put(fd, "\n");
	int nonce_ok = show_nonce(fd, args);
	{
		char version[96] = {0};
		size = sizeof(version);
		long result = sysctl("kern.hakios.version", version, &size);
		version[sizeof(version) - 1] = 0;
		put(fd, "kernel.ver="); put(fd, result ? "unavailable" : version); put(fd, "\n");
	}
	long wait = wait_seconds(args);
	if (wait < 0) { failed = 1; put(fd, "HAKIOS_TIMER_FAIL invalid_wait\n"); }
	if (wait > 0) {
		int gic = 0, cores = 0;
		u64 midr = 0;
		long gic_rc = integer("kern.hakios.gic_version", &gic);
		long core_rc = integer("hw.ncpu", &cores);
		long midr_rc = quad("kern.hakios.boot_midr", &midr);
		put(fd, "HAKIOS_PLATFORM gic="); number(fd, gic);
		put(fd, " cores="); number(fd, cores); put(fd, " midr="); hex(fd, midr); put(fd, "\n");
		if (!nonce_ok || gic_rc || core_rc || midr_rc || gic != 2 || cores != 1 || !midr || wait < 3) {
			failed = 1; put(fd, "HAKIOS_TIMER_FAIL platform_or_nonce\n");
		}
		for (long sample = 1; sample <= wait; sample++) {
			u64 before = 0, after = 0;
			long start_us = 0, end_us = 0;
			long before_rc = quad("kern.hakios.timer_irqs", &before);
			long start_rc = now(&start_us);
			struct timeval timeout = {1, 0, 0};
			long sleep_rc = call(SYS_select, 0, 0, 0, 0, (long)&timeout, 0);
			long end_rc = now(&end_us);
			long after_rc = quad("kern.hakios.timer_irqs", &after);
			long elapsed = end_us - start_us;
			int ok = !before_rc && !after_rc && !start_rc && !end_rc && sleep_rc == 0 &&
			    elapsed >= 900000 && elapsed <= 3000000 && after > before;
			put(fd, "HAKIOS_TIMER_SAMPLE index="); number(fd, sample);
			put(fd, " select_rc="); number(fd, sleep_rc); put(fd, " elapsed_us="); number(fd, elapsed);
			put(fd, " irq_before="); number(fd, (long)before); put(fd, " irq_after="); number(fd, (long)after);
			put(fd, " read_rc="); number(fd, before_rc | after_rc | start_rc | end_rc);
			put(fd, " pass="); number(fd, ok); put(fd, "\n");
			if (!ok) { failed = 1; }
		}
		timer_verified = !failed;
		put(fd, failed ? "HAKIOS_TIMER_FAIL samples=" : "HAKIOS_TIMER_PASS samples=");
		number(fd, wait); put(fd, "\n");
	}
	put(fd, "HAKIOS_USER_EXIT outcome="); number(fd, failed);
	put(fd, " timer_verified="); number(fd, timer_verified); put(fd, "\n");
	/* PID 1 exit intentionally invokes XNU's panic/loader-return path. */
	call(SYS_exit, failed, 0, 0, 0, 0, 0);
	for (;;) { }
}
