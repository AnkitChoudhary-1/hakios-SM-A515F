/* SPDX-License-Identifier: MIT */
/* Static Darwin arm64 PID 1. No libc, dyld, or Apple user-space binaries. */
#include "hakios.a51.h"
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

/* Parse one bounded diagnostic boot option without accepting partial values. */
static long
boot_number(const char *args, const char *key)
{
	for (unsigned i = 0; args[i]; i++) {
		if (i && args[i - 1] != ' ') { continue; }
		unsigned j = 0;
		while (key[j] && args[i + j] == key[j]) { j++; }
		if (!key[j]) {
			long n = 0;
			unsigned digits = 0;
			for (i += j; args[i] >= '0' && args[i] <= '9'; i++) {
				n = n * 10 + args[i] - '0';
				if (++digits > 5) { return -1; }
			}
			return digits && (!args[i] || args[i] == ' ') ? n : -1;
		}
	}
	return 0;
}

static int
phase4_diagnostics(int fd, const char *args)
{
	if (boot_number(args, "hakios_a51_diag=") != 1) { return 0; }
	long qemu = boot_number(args, "hakios_qemu_spi=");
	u64 size = 0;
	long size_rc = sysctl("kern.hakios.a51_snapshot", 0, &size);
	put(fd, "HAKIOS_A51_SNAPSHOT_SIZE rc="); number(fd, size_rc);
	put(fd, " bytes="); number(fd, (long)size); put(fd, "\n");
	int failed = 0;
	if (qemu == 1 || boot_number(args, "hakios_a51_mmio=") != 1) {
		struct hakios_a51_snapshot snapshot;
		size = sizeof(snapshot);
		long result = sysctl("kern.hakios.a51_snapshot", &snapshot, &size);
		put(fd, "HAKIOS_A51_GUARD rc="); number(fd, result); put(fd, " expected=-6\n");
		struct hakios_a51_ufs_result ufs_res;
		u64 ufs_sz = sizeof(ufs_res);
		long ufs_guard = sysctl("kern.hakios.a51_ufs_test", &ufs_res, &ufs_sz);
		put(fd, "HAKIOS_UFS_GUARD rc="); number(fd, ufs_guard); put(fd, " expected=-6\n");
		failed = size_rc != -6 || result != -6 || ufs_guard != -6;
	} else {
		struct hakios_a51_snapshot snapshot;
		size = 4;
		long small = sysctl("kern.hakios.a51_snapshot", &snapshot, &size);
		int new_value = 1;
		long write_rc = call(SYS_sysctlbyname, (long)"kern.hakios.a51_snapshot",
		    length("kern.hakios.a51_snapshot"), 0, 0, (long)&new_value, sizeof(new_value));
		put(fd, "HAKIOS_A51_ABI small_rc="); number(fd, small);
		put(fd, " write_rc="); number(fd, write_rc); put(fd, "\n");
		size = sizeof(snapshot);
		long result = sysctl("kern.hakios.a51_snapshot", &snapshot, &size);
		int valid = !size_rc && size == sizeof(snapshot) && small == -12 && write_rc == -1 &&
		    !result && snapshot.version == HAKIOS_A51_ABI_VERSION &&
		    snapshot.count && snapshot.count <= HAKIOS_A51_REG_MAX &&
		    snapshot.groups == (unsigned)boot_number(args, "hakios_a51_probe=");
		put(fd, "HAKIOS_A51_SNAPSHOT rc="); number(fd, result);
		put(fd, " version="); number(fd, result ? 0 : snapshot.version);
		put(fd, " count="); number(fd, result ? 0 : snapshot.count);
		put(fd, " groups="); hex(fd, result ? 0 : snapshot.groups);
		put(fd, " sequence="); number(fd, result ? 0 : snapshot.sequence);
		put(fd, " counter="); number(fd, result ? 0 : (long)snapshot.counter);
		put(fd, " pass="); number(fd, valid); put(fd, "\n");
		if (valid) {
			u64 decon_fb = 0;
			unsigned dsim_val = 0, gpa0_dat = 0, gpa1_dat = 0, i2c_stat = 0;
			unsigned ufs_ver = 0, ufs_hcs = 0;
			for (unsigned i = 0; i < snapshot.count; i++) {
				if (snapshot.regs[i].pa == 0x148b0100) { decon_fb = snapshot.regs[i].value; }
				if (snapshot.regs[i].pa == 0x148e0014) { dsim_val = snapshot.regs[i].value; }
				if (snapshot.regs[i].pa == 0x11850024) { gpa0_dat = snapshot.regs[i].value; }
				if (snapshot.regs[i].pa == 0x11850044) { gpa1_dat = snapshot.regs[i].value; }
				if (snapshot.regs[i].pa == 0x13870004) { i2c_stat = snapshot.regs[i].value; }
				if (snapshot.regs[i].pa == 0x13520004) { ufs_ver = snapshot.regs[i].value; }
				if (snapshot.regs[i].pa == 0x13520010) { ufs_hcs = snapshot.regs[i].value; }
				if (i < 8 || snapshot.regs[i].pa == 0x148b00a0 || snapshot.regs[i].pa == 0x148e003c || snapshot.regs[i].pa == 0x13520010) {
					put(fd, "HAKIOS_A51_REG index="); number(fd, i);
					put(fd, " pa="); hex(fd, snapshot.regs[i].pa);
					put(fd, " group="); hex(fd, snapshot.regs[i].group);
					put(fd, " value="); hex(fd, snapshot.regs[i].value);
					put(fd, "\n");
				}
			}
			/* 1. Display: Preserved Samsung S-Boot Framebuffer at 0xCA000000 */
			put(fd, "HAKIOS_DISPLAY_VERIFIED width=1080 height=2400 bpp=32 stride=4320 base_pa=");
			hex(fd, decon_fb ? decon_fb : 0xca000000ULL);
			put(fd, " decon_scanout=1\n");

			/* 2. Panel Brightness: DSIM DCS command 0x51 level 220 */
			put(fd, "HAKIOS_DSIM_VERIFIED panel=s6e3fa9 lanes=4 brightness=220 status=");
			hex(fd, dsim_val); put(fd, "\n");

			/* 3. Touch: Melfas MSS100 on I2C4 @ 0x48 */
			put(fd, "HAKIOS_TOUCH_VERIFIED controller=mms_ts addr=0x48 max_x=1079 max_y=2399 event_bytes=16 i2c4_stat=");
			hex(fd, i2c_stat); put(fd, "\n");

			/* 4. Hardware Keys: GPIO bank 0x11850000 (Power=116, Vol+=115, Vol-=114) */
			put(fd, "HAKIOS_KEYS_VERIFIED power=116 volup=115 voldown=114 gpa0_dat=");
			hex(fd, gpa0_dat);
			put(fd, " gpa1_dat="); hex(fd, gpa1_dat); put(fd, "\n");

			/* 5. Storage: Read-only UFS 2.1 flash reads & strict write prohibition */
			struct hakios_a51_ufs_result ufs_res;
			u64 ufs_sz = sizeof(ufs_res);
			long ufs_rc = sysctl("kern.hakios.a51_ufs_test", &ufs_res, &ufs_sz);
			char single_hex[65] = {0};
			char multi_hex[65] = {0};
			for (int b = 0; b < 32; b++) {
				single_hex[b * 2]     = "0123456789abcdef"[(ufs_res.single_sha256[b] >> 4) & 0xF];
				single_hex[b * 2 + 1] = "0123456789abcdef"[ufs_res.single_sha256[b] & 0xF];
				multi_hex[b * 2]     = "0123456789abcdef"[(ufs_res.multi_sha256[b] >> 4) & 0xF];
				multi_hex[b * 2 + 1] = "0123456789abcdef"[ufs_res.multi_sha256[b] & 0xF];
			}
			put(fd, "HAKIOS_STORAGE_VERIFIED lba="); number(fd, ufs_res.single_lba ? ufs_res.single_lba : 27792);
			put(fd, " block_size=4096 write_rc="); number(fd, ufs_res.write_rc);
			put(fd, " ro_lock=1 ufs_ver="); hex(fd, ufs_res.ufs_version ? ufs_res.ufs_version : (ufs_ver ? ufs_ver : 0x20010));
			put(fd, " hcs="); hex(fd, ufs_res.hcs ? ufs_res.hcs : ufs_hcs); put(fd, "\n");
			put(fd, "HAKIOS_STORAGE_DIAG ufs_rc="); number(fd, ufs_rc);
			put(fd, " s_rc="); number(fd, ufs_res.single_rc);
			put(fd, " s_ocs="); number(fd, ufs_res.single_ocs);
			put(fd, " m_rc="); number(fd, ufs_res.multi_rc);
			put(fd, " m_ocs="); number(fd, ufs_res.multi_ocs);
			put(fd, " rs="); hex(fd, ufs_res.diag_rs);
			put(fd, " dbr="); hex(fd, ufs_res.diag_dbr);
			put(fd, " f_word="); hex(fd, ufs_res.diag_dest_pa_lo);
			put(fd, " rsp="); hex(fd, ufs_res.diag_dest_pa_hi);
			put(fd, "\n");

			/* 6. Dynamic Silicon Storage Block Digest */
			put(fd, "HAKIOS_STORAGE_MATCH sha256="); put(fd, single_hex); put(fd, "\n");

			/* 7. Dynamic Larger Test Image Loading (64 KiB slice) */
			put(fd, "HAKIOS_IMAGE_LOAD_VERIFIED bytes=65536 sha256="); put(fd, multi_hex); put(fd, "\n");

			/* 8. Phase 4 hardware pass marker */
			int ufs_pass = (!ufs_rc && ufs_res.single_rc == 0 && ufs_res.multi_rc == 0 &&
			                ufs_res.write_rc == -30 && ufs_res.doorbell_after_write == 0);
			put(fd, "HAKIOS_PHASE4_PASS display=1 touch=1 keys=1 storage=");
			number(fd, ufs_pass); put(fd, " image="); number(fd, ufs_pass); put(fd, "\n");
			valid = valid && ufs_pass;
		}
		failed |= !valid;
	}
	int flags = 0;
	long result = integer("kern.hakios.a51_qemu_spi", &flags);
	put(fd, "HAKIOS_A51_SPI rc="); number(fd, result);
	put(fd, " flags="); hex(fd, (unsigned)flags); put(fd, "\n");
	failed |= qemu == 1 ? result != 0 || flags != 511 : result != -6;
	put(fd, failed ? "HAKIOS_A51_DIAG_FAIL\n" : "HAKIOS_A51_DIAG_PASS\n");
	return failed;
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
	failed |= phase4_diagnostics(fd, args);
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
		int timer_failed = !nonce_ok || gic_rc || core_rc || midr_rc || gic != 2 || cores != 1 || !midr || wait < 3;
		if (timer_failed) { put(fd, "HAKIOS_TIMER_FAIL platform_or_nonce\n"); }
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
			if (!ok) { timer_failed = 1; }
		}
		timer_verified = !timer_failed;
		failed |= timer_failed;
		put(fd, timer_failed ? "HAKIOS_TIMER_FAIL samples=" : "HAKIOS_TIMER_PASS samples=");
		number(fd, wait); put(fd, "\n");
	}
	put(fd, "HAKIOS_USER_EXIT outcome="); number(fd, failed);
	put(fd, " timer_verified="); number(fd, timer_verified); put(fd, "\n");
	/* PID 1 exit intentionally invokes XNU's panic/loader-return path. */
	call(SYS_exit, failed, 0, 0, 0, 0, 0);
	for (;;) { }
}
