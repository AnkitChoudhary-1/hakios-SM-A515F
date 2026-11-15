/* SPDX-License-Identifier: MIT */
/*
 * A51 single-core GICv2 backend. The gic_v3_* names are the existing generic
 * platform ABI; this file uses only the GICv2 MMIO interface, never ICC_*.
 * Other CPUs and peripheral drivers remain outside this bring-up configuration.
 */
#include <mach/mach_types.h>
#include <kern/debug.h>
#include <os/atomic_private.h>
#include <arm/cpu_data_internal.h>
#include <arm/cpu_internal.h>
#include <arm/machine_cpu.h>
#include <arm/machine_routines.h>
#include <arm/rtclock.h>
#include <arm64/proc_reg.h>
#include <pexpert/pexpert.h>
#include <pexpert/device_tree.h>
#include <pexpert/arm64/board_config.h>

#if defined(GENERIC_GIC_V2_IRQ)
#define GICD_CTLR           0x000
#define GICD_TYPER          0x004
#define GICD_IGROUPR(n)     (0x080 + 4 * (n))
#define GICD_ISENABLER(n)   (0x100 + 4 * (n))
#define GICD_ICENABLER(n)   (0x180 + 4 * (n))
#define GICD_ICPENDR(n)     (0x280 + 4 * (n))
#define GICD_ICACTIVER(n)   (0x380 + 4 * (n))
#define GICD_IPRIORITYR(n)  (0x400 + (n))
#define GICD_SGIR          0xf00
#define GICC_CTLR          0x000
#define GICC_PMR           0x004
#define GICC_BPR           0x008
#define GICC_IAR           0x00c
#define GICC_EOIR          0x010
#define GICC_APR0          0x0d0
#define GICC_NSAPR0        0x0e0
#define GICC_EOIMODE_NS    (1u << 9)
#define GIC_VTIMER         27
#define GIC_SPURIOUS       1020

static vm_offset_t gicd, gicc;
static uint32_t gic_lines, active_iar;
static bool active, initialized;
/* BSD registers these read-only counters in hakios.platform.c. */
int hakios_gic_version = 2;
uint64_t hakios_timer_irqs, hakios_boot_midr;
uint64_t gic_unhandled_count;
uint32_t gic_last_unhandled;

void gic_v3_irq_cpu_init(void);
void gic_v3_irq_quiesce(void);
void gic_v3_irq_cpu_shutdown(void);
void gic_v3_irq_signal(uint32_t phys_id);
void gic_v3_irq_signal_stop(uint32_t phys_id);
kern_return_t gic_v3_spi_attach(uint32_t, bool, void (*)(void *, uint32_t), void *);
void gic_v3_spi_mask(uint32_t);
void gic_v3_spi_unmask(uint32_t);
void gic_v3_spi_detach(uint32_t);
uint64_t gic_v3_spi_count(uint32_t);

static uint32_t
read32(vm_offset_t base, uint32_t offset)
{

	return *(volatile uint32_t *)(base + offset);
}

static void
write32(vm_offset_t base, uint32_t offset, uint32_t value)
{

	*(volatile uint32_t *)(base + offset) = value;
}

void
gic_v3_spi_mask(uint32_t intid)
{
	if (gicd && intid < gic_lines && intid < GIC_SPURIOUS) {
		write32(gicd, GICD_ICENABLER(intid / 32), 1u << (intid % 32));
		__builtin_arm_dsb(DSB_SY);
	}
}

/* No peripheral IRQ may be enabled until a real driver is implemented. */
void
gic_v3_spi_unmask(uint32_t intid)
{
	(void)intid;
}

kern_return_t
gic_v3_spi_attach(uint32_t intid, bool edge, void (*handler)(void *, uint32_t), void *context)
{
	(void)intid; (void)edge; (void)handler; (void)context;
	return KERN_NOT_SUPPORTED;
}

void
gic_v3_spi_detach(uint32_t intid)
{
	gic_v3_spi_mask(intid);
}

uint64_t
gic_v3_spi_count(uint32_t intid)
{
	(void)intid;
	return 0;
}

/* Only the boot core is advertised. Refuse accidental cross-core requests. */
void
gic_v3_irq_signal(uint32_t phys_id)
{
	if (phys_id != (__builtin_arm_rsr64("MPIDR_EL1") & 0xffffff)) {
		panic("gicv2: cross-core signal is unsupported in single-core bring-up");
	}
	if (gicd) {
		__builtin_arm_dsb(DSB_SY);
		write32(gicd, GICD_SGIR, 2u << 24); /* SGI 0 to this CPU */
	}
}

void
gic_v3_irq_signal_stop(uint32_t phys_id)
{
	(void)phys_id;
	panic("gicv2: cross-core stop is unsupported in single-core bring-up");
}

static void
gic_irq_handler(__unused void *target, __unused void *refCon,
    __unused void *nub, __unused int source)
{
	/* Bound one entry even if a broken source remains asserted. */
	for (unsigned served = 0; served < 128; served++) {
		uint32_t iar = read32(gicc, GICC_IAR);
		uint32_t intid = iar & 0x3ff;

		if (intid >= GIC_SPURIOUS) {
			return;
		}
		active_iar = iar;
		active = true;
		if (intid == GIC_VTIMER) {
			os_atomic_inc(&hakios_timer_irqs, relaxed);
			getCpuDatap()->cpu_decrementer = -1;
			rtclock_intr(TRUE);
		} else if (intid == 0) {
			cpu_signal_handler();
		} else {
			gic_v3_spi_mask(intid);
			gic_unhandled_count++;
			gic_last_unhandled = intid;
		}
		__builtin_arm_dsb(DSB_SY);
		/* Preserve the full IAR, including the source CPU of an SGI. */
		write32(gicc, GICC_EOIR, iar);
		active = false;
	}
	panic("gicv2: IRQ service bound exceeded");
}

void
gic_v3_irq_quiesce(void)
{
	if (!gicd) {
		return;
	}
	__builtin_arm_wsr64("CNTV_CTL_EL0", CNTV_CTL_EL0_IMASKED);
	write32(gicd, GICD_ICENABLER(0), 0xffff0000u);
	if (active) {
		write32(gicc, GICC_EOIR, active_iar);
		active = false;
	}
	__builtin_arm_dsb(DSB_SY);
}

void
gic_v3_irq_cpu_shutdown(void)
{
	gic_v3_irq_quiesce();
	if (gicc) {
		write32(gicc, GICC_CTLR, 0);
		__builtin_arm_dsb(DSB_SY);
	}
}

void
gic_v3_irq_cpu_init(void)
{
	DTEntry entry;
	void const *property;
	unsigned int size;
	uint64_t const *reg;
	vm_offset_t soc;

	if (initialized) {
		return;
	}
	if (ml_get_cpu_count() != 1) {
		panic("gicv2: exactly one advertised CPU is required");
	}
	if (SecureDTLookupEntry(NULL, "/arm-io/gic", &entry) != kSuccess ||
	    SecureDTGetProperty(entry, "reg", &property, &size) != kSuccess ||
	    size != 4 * sizeof(uint64_t)) {
		panic("gicv2: unusable distributor/CPU interface device-tree property");
	}
	reg = property;
	if (reg[1] < 0x1000 || reg[3] < 0x1000 || reg[1] > 0x10000 || reg[3] > 0x10000) {
		panic("gicv2: invalid MMIO sizes");
	}
	soc = pe_arm_get_soc_base_phys();
	gicd = ml_io_map(soc + reg[0], reg[1]);
	gicc = ml_io_map(soc + reg[2], reg[3]);
	if (!gicd || !gicc) {
		panic("gicv2: MMIO mapping failed");
	}
	gic_lines = ((read32(gicd, GICD_TYPER) & 31) + 1) * 32;
	if (gic_lines > GIC_SPURIOUS) {
		gic_lines = GIC_SPURIOUS;
	}
	/* EL1 nonsecure accesses affect nonsecure interrupts only. */
	write32(gicc, GICC_CTLR, 0);
	for (uint32_t n = 1; n < (gic_lines + 31) / 32; n++) {
		write32(gicd, GICD_ICENABLER(n), 0xffffffffu);
		write32(gicd, GICD_ICPENDR(n), 0xffffffffu);
		write32(gicd, GICD_ICACTIVER(n), 0xffffffffu);
	}
	write32(gicd, GICD_ICENABLER(0), 0xffff0000u);
	write32(gicd, GICD_ICPENDR(0), 1u << GIC_VTIMER);
	write32(gicd, GICD_ICACTIVER(0), 1u << GIC_VTIMER);
	write32(gicd, GICD_IGROUPR(0), read32(gicd, GICD_IGROUPR(0)) | (1u << GIC_VTIMER) | 1u);
	*(volatile uint8_t *)(gicd + GICD_IPRIORITYR(GIC_VTIMER)) = 0xa0;
	*(volatile uint8_t *)(gicd + GICD_IPRIORITYR(0)) = 0xa0;
	write32(gicd, GICD_ISENABLER(0), (1u << GIC_VTIMER) | 1u);
	/* In the nonsecure view bit zero enables Group 1. EOI also deactivates. */
	write32(gicd, GICD_CTLR, read32(gicd, GICD_CTLR) | 1u);
	write32(gicc, GICC_PMR, 0xff);
	write32(gicc, GICC_BPR, 0);
	write32(gicc, GICC_APR0, 0);
	write32(gicc, GICC_NSAPR0, 0);
	write32(gicc, GICC_CTLR, (read32(gicc, GICC_CTLR) & ~GICC_EOIMODE_NS) | 1u);
	__builtin_arm_dsb(DSB_SY);
	__builtin_arm_isb(ISB_SY);
	hakios_boot_midr = __builtin_arm_rsr64("MIDR_EL1");
	initialized = true;
	ml_install_interrupt_handler(NULL, 0, NULL, gic_irq_handler, NULL);
	kprintf("gic: v2 MMIO, cpu %d, MIDR 0x%llx, virtual timer PPI %d, lines %u\n",
	    cpu_number(), hakios_boot_midr, GIC_VTIMER, gic_lines);
}
#endif /* GENERIC_GIC_V2_IRQ */
