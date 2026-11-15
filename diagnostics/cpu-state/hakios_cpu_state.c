// SPDX-License-Identifier: GPL-2.0
/* Capture-only Android diagnostic. Never writes an architectural register. */
#include <linux/cpu.h>
#include <linux/errno.h>
#include <linux/init.h>
#include <linux/module.h>
#include <linux/moduleparam.h>
#include <linux/printk.h>
#include <linux/smp.h>
#include <linux/string.h>
#include <asm/sysreg.h>

#define MAX_CAPTURE_CPUS 32
static char *run_id;
module_param(run_id, charp, 0);
MODULE_PARM_DESC(run_id, "Required 16 lowercase hexadecimal characters");

struct cpu_capture {
	u64 el, midr, mpidr, sctlr, tcr, ttbr0, ttbr1, mair, vbar;
	u64 daif, cntfrq, cntvct, mmfr0, mmfr1, pc, sp;
	unsigned int seen;
};
static struct cpu_capture captured[MAX_CAPTURE_CPUS];

static void capture_cpu(void *unused)
{
	unsigned int cpu = raw_smp_processor_id();
	struct cpu_capture *s;

	(void)unused;
	if (cpu >= MAX_CAPTURE_CPUS)
		return;
	s = &captured[cpu];
	s->el = read_sysreg(CurrentEL);
	s->midr = read_sysreg(midr_el1);
	s->mpidr = read_sysreg(mpidr_el1);
	s->sctlr = read_sysreg(sctlr_el1);
	s->tcr = read_sysreg(tcr_el1);
	s->ttbr0 = read_sysreg(ttbr0_el1);
	s->ttbr1 = read_sysreg(ttbr1_el1);
	s->mair = read_sysreg(mair_el1);
	s->vbar = read_sysreg(vbar_el1);
	s->daif = read_sysreg(daif);
	s->cntfrq = read_sysreg(cntfrq_el0);
	s->cntvct = read_sysreg(cntvct_el0);
	s->mmfr0 = read_sysreg(id_aa64mmfr0_el1);
	s->mmfr1 = read_sysreg(id_aa64mmfr1_el1);
	asm volatile("adr %0, .\n\tmov %1, sp" : "=r" (s->pc), "=r" (s->sp));
	s->seen++;
}

static int __init cpu_state_init(void)
{
	unsigned int cpu, count = 0;
	int result = 0;

	if (!run_id || strlen(run_id) != 16)
		return -EINVAL;
	for (cpu = 0; cpu < 16; cpu++)
		if (!((run_id[cpu] >= '0' && run_id[cpu] <= '9') ||
		      (run_id[cpu] >= 'a' && run_id[cpu] <= 'f')))
			return -EINVAL;
	get_online_cpus();
	for_each_online_cpu(cpu)
		if (cpu >= MAX_CAPTURE_CPUS) {
			result = -E2BIG;
			goto unlock;
		}
	on_each_cpu(capture_cpu, NULL, 1);
	for_each_online_cpu(cpu) {
		struct cpu_capture *s = &captured[cpu];

		if (s->seen != 1) {
			result = -EIO;
			goto unlock;
		}
		count++;
		/* No printk or Linux calls occur inside the IPI capture callback. */
		pr_info("HAKIOS_CPU run=%s stage=identity cpu=%u el=%llx midr=%llx mpidr=%llx mmfr0=%llx mmfr1=%llx\n",
			run_id, cpu, s->el, s->midr, s->mpidr, s->mmfr0, s->mmfr1);
		pr_info("HAKIOS_CPU run=%s stage=translation cpu=%u sctlr=%llx tcr=%llx ttbr0=%llx ttbr1=%llx mair=%llx vbar=%llx\n",
			run_id, cpu, s->sctlr, s->tcr, s->ttbr0, s->ttbr1, s->mair, s->vbar);
		pr_info("HAKIOS_CPU run=%s stage=execution cpu=%u pc=%llx sp=%llx daif=%llx cntfrq=%llx cntvct=%llx seen=%u\n",
			run_id, cpu, s->pc, s->sp, s->daif, s->cntfrq, s->cntvct, s->seen);
	}
unlock:
	put_online_cpus();
	if (result) {
		memset(captured, 0, sizeof(captured));
		return result;
	}
	pr_info("HAKIOS_CPU run=%s stage=loaded cpus=%u architectural_writes=0\n", run_id, count);
	return 0;
}

static void __exit cpu_state_exit(void)
{
	memset(captured, 0, sizeof(captured));
	pr_info("HAKIOS_CPU run=%s stage=unloaded capture_cleared=1\n", run_id);
}

module_init(cpu_state_init);
module_exit(cpu_state_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("HakiOS A51 capture-only per-CPU architectural state diagnostic");
MODULE_VERSION("1");
