/* SPDX-License-Identifier: MIT */
/* Single-core GICv2 backend, including bounded peripheral SPI registration. */
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
#define GICD_ISPENDR(n)     (0x200 + 4 * (n))
#define GICD_ICPENDR(n)     (0x280 + 4 * (n))
#define GICD_ICACTIVER(n)   (0x380 + 4 * (n))
#define GICD_IPRIORITYR(n)  (0x400 + (n))
#define GICD_ITARGETSR(n)   (0x800 + (n))
#define GICD_ICFGR(n)       (0xc00 + 4 * (n))
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
#define GIC_SPI_MIN        32
#define GIC_SPURIOUS       1020
#define GIC_SPI_SLOTS      64

static vm_offset_t gicd, gicc;
static uint32_t gic_lines, active_iar;
static uint8_t cpu_target;
static bool active, initialized;
int hakios_gic_version = 2;
uint64_t hakios_timer_irqs, hakios_boot_midr;
uint64_t gic_unhandled_count;
uint32_t gic_last_unhandled;

/* Local interrupt exclusion serializes this table on the sole advertised CPU.
 * Handlers run with interrupts disabled, cannot sleep and must quiet or mask a
 * level source before returning. Multi-core use requires a different locking ABI. */
struct gic_spi {
	uint32_t intid;
	void (*handler)(void *, uint32_t);
	void *context;
	uint64_t count;
};
static struct gic_spi spi_slots[GIC_SPI_SLOTS];

void gic_v3_irq_cpu_init(void);
void gic_v3_irq_quiesce(void);
void gic_v3_irq_cpu_shutdown(void);
void gic_v3_irq_signal(uint32_t);
void gic_v3_irq_signal_stop(uint32_t);
kern_return_t gic_v3_spi_attach(uint32_t, bool, void (*)(void *, uint32_t), void *);
void gic_v3_spi_mask(uint32_t);
void gic_v3_spi_unmask(uint32_t);
void gic_v3_spi_detach(uint32_t);
uint64_t gic_v3_spi_count(uint32_t);
kern_return_t hakios_gicv2_qemu_test(uint32_t *);

static uint32_t read32(vm_offset_t base, uint32_t offset)
{
	return *(volatile uint32_t *)(base + offset);
}
static void write32(vm_offset_t base, uint32_t offset, uint32_t value)
{
	*(volatile uint32_t *)(base + offset) = value;
}
static bool valid_spi(uint32_t intid)
{
	return initialized && intid >= GIC_SPI_MIN && intid < gic_lines && intid < GIC_SPURIOUS;
}
static struct gic_spi *find_spi(uint32_t intid)
{
	for (unsigned i = 0; i < GIC_SPI_SLOTS; i++) {
		if (spi_slots[i].intid == intid) { return &spi_slots[i]; }
	}
	return NULL;
}
static void mask_raw(uint32_t intid)
{
	if (gicd && intid < gic_lines) {
		write32(gicd, GICD_ICENABLER(intid / 32), 1u << (intid % 32));
		__builtin_arm_dsb(DSB_SY);
	}
}
void gic_v3_spi_mask(uint32_t intid)
{
	if (valid_spi(intid)) { mask_raw(intid); }
}
void gic_v3_spi_unmask(uint32_t intid)
{
	boolean_t previous = ml_set_interrupts_enabled(FALSE);
	if (valid_spi(intid) && find_spi(intid)) {
		__builtin_arm_dsb(DSB_SY);
		write32(gicd, GICD_ISENABLER(intid / 32), 1u << (intid % 32));
		__builtin_arm_dsb(DSB_SY);
	}
	ml_set_interrupts_enabled(previous);
}
kern_return_t gic_v3_spi_attach(uint32_t intid, bool edge,
    void (*handler)(void *, uint32_t), void *context)
{
	if (!valid_spi(intid) || !handler) { return KERN_INVALID_ARGUMENT; }
	if (!cpu_target || (cpu_target & (cpu_target - 1))) { return KERN_NOT_SUPPORTED; }
	boolean_t previous = ml_set_interrupts_enabled(FALSE);
	if (find_spi(intid)) {
		ml_set_interrupts_enabled(previous);
		return KERN_NAME_EXISTS;
	}
	struct gic_spi *slot = NULL;
	for (unsigned i = 0; i < GIC_SPI_SLOTS; i++) {
		if (!spi_slots[i].intid) { slot = &spi_slots[i]; break; }
	}
	if (!slot) {
		ml_set_interrupts_enabled(previous);
		return KERN_RESOURCE_SHORTAGE;
	}
	mask_raw(intid);
	uint32_t bit = 1u << (intid % 32);
	write32(gicd, GICD_ICPENDR(intid / 32), bit);
	write32(gicd, GICD_IGROUPR(intid / 32), read32(gicd, GICD_IGROUPR(intid / 32)) | bit);
	*(volatile uint8_t *)(gicd + GICD_IPRIORITYR(intid)) = 0xa0;
	/* Read the banked CPU target mask; MPIDR is not a GIC target-bit index. */
	*(volatile uint8_t *)(gicd + GICD_ITARGETSR(intid)) = cpu_target;
	uint32_t shift = (intid % 16) * 2;
	uint32_t config = read32(gicd, GICD_ICFGR(intid / 16)) & ~(2u << shift);
	write32(gicd, GICD_ICFGR(intid / 16), config | ((edge ? 2u : 0u) << shift));
	slot->context = context;
	slot->handler = handler;
	slot->count = 0;
	slot->intid = intid;
	__builtin_arm_dsb(DSB_SY);
	write32(gicd, GICD_ISENABLER(intid / 32), bit);
	__builtin_arm_dsb(DSB_SY);
	ml_set_interrupts_enabled(previous);
	return KERN_SUCCESS;
}
void gic_v3_spi_detach(uint32_t intid)
{
	boolean_t previous = ml_set_interrupts_enabled(FALSE);
	if (valid_spi(intid)) {
		mask_raw(intid);
		write32(gicd, GICD_ICPENDR(intid / 32), 1u << (intid % 32));
		struct gic_spi *slot = find_spi(intid);
		if (slot) {
			slot->intid = 0;
			slot->handler = NULL;
			slot->context = NULL;
			slot->count = 0;
		}
		__builtin_arm_dsb(DSB_SY);
	}
	ml_set_interrupts_enabled(previous);
}
uint64_t gic_v3_spi_count(uint32_t intid)
{
	boolean_t previous = ml_set_interrupts_enabled(FALSE);
	struct gic_spi *slot = valid_spi(intid) ? find_spi(intid) : NULL;
	uint64_t count = slot ? slot->count : 0;
	ml_set_interrupts_enabled(previous);
	return count;
}

void gic_v3_irq_signal(uint32_t phys_id)
{
	if (phys_id != (__builtin_arm_rsr64("MPIDR_EL1") & 0xffffff)) {
		panic("gicv2: cross-core signal unsupported in single-core configuration");
	}
	if (gicd) {
		__builtin_arm_dsb(DSB_SY);
		write32(gicd, GICD_SGIR, 2u << 24);
	}
}
void gic_v3_irq_signal_stop(uint32_t phys_id)
{
	(void)phys_id;
	panic("gicv2: cross-core stop unsupported in single-core configuration");
}
static void gic_irq_handler(__unused void *target, __unused void *refCon,
    __unused void *nub, __unused int source)
{
	for (unsigned served = 0; served < 128; served++) {
		uint32_t iar = read32(gicc, GICC_IAR);
		uint32_t intid = iar & 0x3ff;
		if (intid >= GIC_SPURIOUS) { return; }
		active_iar = iar;
		active = true;
		struct gic_spi *slot = intid >= GIC_SPI_MIN ? find_spi(intid) : NULL;
		if (intid == GIC_VTIMER) {
			os_atomic_inc(&hakios_timer_irqs, relaxed);
			getCpuDatap()->cpu_decrementer = -1;
			rtclock_intr(TRUE);
		} else if (intid == 0) {
			cpu_signal_handler();
		} else if (slot) {
			slot->count++;
			slot->handler(slot->context, intid);
		} else {
			mask_raw(intid);
			gic_unhandled_count++;
			gic_last_unhandled = intid;
		}
		__builtin_arm_dsb(DSB_SY);
		write32(gicc, GICC_EOIR, iar);
		active = false;
	}
	panic("gicv2: IRQ service bound exceeded");
}
void gic_v3_irq_quiesce(void)
{
	if (!gicd) { return; }
	__builtin_arm_wsr64("CNTV_CTL_EL0", CNTV_CTL_EL0_IMASKED);
	write32(gicd, GICD_ICENABLER(0), 0xffff0000u);
	for (uint32_t n = 1; n < (gic_lines + 31) / 32; n++) {
		write32(gicd, GICD_ICENABLER(n), 0xffffffffu);
	}
	if (active) {
		write32(gicc, GICC_EOIR, active_iar);
		active = false;
	}
	__builtin_arm_dsb(DSB_SY);
}
void gic_v3_irq_cpu_shutdown(void)
{
	gic_v3_irq_quiesce();
	if (gicc) {
		write32(gicc, GICC_CTLR, 0);
		__builtin_arm_dsb(DSB_SY);
	}
}
void gic_v3_irq_cpu_init(void)
{
	DTEntry entry;
	void const *property;
	unsigned int size;
	if (initialized) { return; }
	if (ml_get_cpu_count() != 1) { panic("gicv2: exactly one advertised CPU required"); }
	if (SecureDTLookupEntry(NULL, "/arm-io/gic", &entry) != kSuccess ||
	    SecureDTGetProperty(entry, "reg", &property, &size) != kSuccess ||
	    size != 4 * sizeof(uint64_t)) {
		panic("gicv2: unusable distributor/CPU interface property");
	}
	uint64_t const *reg = property;
	if (reg[1] < 0x1000 || reg[3] < 0x1000 || reg[1] > 0x10000 || reg[3] > 0x10000) {
		panic("gicv2: invalid MMIO sizes");
	}
	vm_offset_t soc = pe_arm_get_soc_base_phys();
	gicd = ml_io_map(soc + reg[0], reg[1]);
	gicc = ml_io_map(soc + reg[2], reg[3]);
	if (!gicd || !gicc) { panic("gicv2: MMIO mapping failed"); }
	uint32_t typer = read32(gicd, GICD_TYPER);
	gic_lines = ((typer & 31) + 1) * 32;
	if (gic_lines > GIC_SPURIOUS) { gic_lines = GIC_SPURIOUS; }
	/* Banked SGI/PPI target fields identify this CPU on an MP GIC.
	 * A uniprocessor implementation can expose these as RAZ/WI;
	 * its sole target is implicit. Never infer an MP bit from MPIDR. */
	cpu_target = 0;
	for (unsigned i = 0; i < 32; i += 4) {
		uint32_t targets = read32(gicd, GICD_ITARGETSR(i));
		targets |= targets >> 16;
		targets |= targets >> 8;
		cpu_target |= (uint8_t)targets;
	}
	if (!cpu_target && !((typer >> 5) & 7)) { cpu_target = 1; }
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
	kprintf("gic: v2 MMIO, cpu %d, MIDR 0x%llx, virtual timer PPI %d, lines %u, SPI target 0x%x\n",
	    cpu_number(), hakios_boot_midr, GIC_VTIMER, gic_lines, cpu_target);
}

/* A real pending SPI in QEMU's emulated distributor. Never run on Exynos. */
static void test_irq(void *context, uint32_t intid)
{
	(*(volatile uint32_t *)context)++;
	gic_v3_spi_mask(intid);
}
static bool test_wait(uint32_t intid, uint64_t goal)
{
	uint64_t end = __builtin_arm_rsr64("CNTVCT_EL0") + __builtin_arm_rsr64("CNTFRQ_EL0") / 20;
	while (__builtin_arm_rsr64("CNTVCT_EL0") < end) {
		if (gic_v3_spi_count(intid) == goal) { return true; }
		delay(100);
	}
	return false;
}
kern_return_t hakios_gicv2_qemu_test(uint32_t *flags)
{
	if (pe_arm_get_soc_base_phys() != 0x08000000 || !initialized) { return KERN_NOT_SUPPORTED; }
	const uint32_t id = 47;
	volatile uint32_t observed = 0;
	*flags = 0;
	if (gic_v3_spi_attach(31, true, test_irq, (void *)&observed) == KERN_INVALID_ARGUMENT &&
	    gic_v3_spi_attach(gic_lines, true, test_irq, (void *)&observed) == KERN_INVALID_ARGUMENT) { *flags |= 1; }
	if (gic_v3_spi_attach(id, true, NULL, NULL) == KERN_INVALID_ARGUMENT) { *flags |= 2; }
	kern_return_t attach = gic_v3_spi_attach(id, true, test_irq, (void *)&observed);
	if (attach != KERN_SUCCESS) {
		kprintf("HAKIOS_QEMU_SPI_ATTACH rc=%d flags=0x%x target=0x%x\n", attach, *flags, cpu_target);
		return KERN_FAILURE;
	}
	*flags |= 4;
	if (gic_v3_spi_attach(id, true, test_irq, (void *)&observed) == KERN_NAME_EXISTS) { *flags |= 8; }
	write32(gicd, GICD_ISPENDR(id / 32), 1u << (id % 32));
	__builtin_arm_dsb(DSB_SY);
	if (test_wait(id, 1) && observed == 1) { *flags |= 16; }
	write32(gicd, GICD_ISPENDR(id / 32), 1u << (id % 32));
	__builtin_arm_dsb(DSB_SY);
	delay(1000);
	if (gic_v3_spi_count(id) == 1 && observed == 1) { *flags |= 32; }
	gic_v3_spi_unmask(id);
	if (test_wait(id, 2) && observed == 2) { *flags |= 64; }
	gic_v3_spi_detach(id);
	gic_v3_spi_unmask(id);
	if (!gic_v3_spi_count(id) && !(read32(gicd, GICD_ISENABLER(id / 32)) & (1u << (id % 32)))) { *flags |= 128; }
	if (gic_v3_spi_attach(id, true, test_irq, (void *)&observed) == KERN_SUCCESS) {
		delay(1000);
		if (!gic_v3_spi_count(id) && observed == 2) { *flags |= 256; }
		gic_v3_spi_detach(id);
	}
	kprintf("HAKIOS_QEMU_SPI flags=0x%x observed=%u target=0x%x\n", *flags, observed, cpu_target);
	return *flags == 511 ? KERN_SUCCESS : KERN_FAILURE;
}
#endif
