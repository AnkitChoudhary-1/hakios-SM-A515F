/* SPDX-License-Identifier: MIT */
/*
 * SM-A515F/Exynos 9611 early controller diagnostics. Register facts are traced
 * to the retained matching Android DTS and cal_9610/ufshci/i2c-s3c2410 files.
 * This file does not initialize peripherals or establish Phase 4 completion.
 * Boot firmware must keep the selected controller clock/power domains alive.
 */
#include <kern/locks.h>
#include <libkern/libkern.h>
#include <sys/errno.h>
#include <sys/sysctl.h>
#include <sys/systm.h>
#include <pexpert/pexpert.h>
#include <pexpert/arm64/board_config.h>
#include <arm/machine_routines.h>
#include <mach/mach_types.h>
#include "hakios.a51.h"
#include "a51_ufs_readonly.h"
#include "a51_input.h"

/* BSD lacks MACH_KERNEL_PRIVATE/PEXPERT_KERNEL_PRIVATE. Match the
 * osfmk/arm/machine_routines.h declaration, as existing BSD drivers do. */
extern vm_offset_t ml_io_map(vm_offset_t phys_addr, vm_size_t size);
extern vm_offset_t ml_io_map_unmappable(vm_offset_t phys_addr, vm_size_t size, unsigned int flags);
extern unsigned long long kvtophys(vm_offset_t va);
#define VM_WIMG_DEFAULT 0x0
#define VM_WIMG_WCOMB   0x2

static inline void
a51_dcache_inval_range(vm_offset_t va, vm_size_t size)
{
    vm_offset_t addr = va & ~63ULL;
    vm_offset_t end = va + size;
    __asm__ volatile("dsb sy" ::: "memory");
    for (; addr < end; addr += 64) {
        __asm__ volatile("dc ivac, %0" :: "r"(addr) : "memory");
    }
    __asm__ volatile("dsb sy" ::: "memory");
    __asm__ volatile("isb" ::: "memory");
}

static inline void
a51_dcache_flush_range(vm_offset_t va, vm_size_t size)
{
    vm_offset_t addr = va & ~63ULL;
    vm_offset_t end = va + size;
    __asm__ volatile("dsb sy" ::: "memory");
    for (; addr < end; addr += 64) {
        __asm__ volatile("dc civac, %0" :: "r"(addr) : "memory");
    }
    __asm__ volatile("dsb sy" ::: "memory");
    __asm__ volatile("isb" ::: "memory");
}

/* Freestanding SHA-256 Algorithm */
struct a51_sha256_ctx {
    unsigned int state[8];
    unsigned long long count;
    unsigned char buffer[64];
};

static void
a51_sha256_transform(unsigned int state[8], const unsigned char data[64])
{
    static const unsigned int K[64] = {
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
        0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
        0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
        0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
        0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
        0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
        0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
        0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
    };
    unsigned int a = state[0], b = state[1], c = state[2], d = state[3];
    unsigned int e = state[4], f = state[5], g = state[6], h = state[7];
    unsigned int W[64];

    for (int i = 0; i < 16; i++) {
        W[i] = ((unsigned int)data[i * 4] << 24) |
               ((unsigned int)data[i * 4 + 1] << 16) |
               ((unsigned int)data[i * 4 + 2] << 8) |
               ((unsigned int)data[i * 4 + 3]);
    }
    for (int i = 16; i < 64; i++) {
        unsigned int s0 = (((W[i - 15] >> 7) | (W[i - 15] << 25)) ^
                           ((W[i - 15] >> 18) | (W[i - 15] << 14)) ^
                           (W[i - 15] >> 3));
        unsigned int s1 = (((W[i - 2] >> 17) | (W[i - 2] << 15)) ^
                           ((W[i - 2] >> 19) | (W[i - 2] << 13)) ^
                           (W[i - 2] >> 10));
        W[i] = W[i - 16] + s0 + W[i - 7] + s1;
    }
    for (int i = 0; i < 64; i++) {
        unsigned int S1 = (((e >> 6) | (e << 26)) ^ ((e >> 11) | (e << 21)) ^ ((e >> 25) | (e << 7)));
        unsigned int ch = (e & f) ^ ((~e) & g);
        unsigned int temp1 = h + S1 + ch + K[i] + W[i];
        unsigned int S0 = (((a >> 2) | (a << 30)) ^ ((a >> 13) | (a << 19)) ^ ((a >> 22) | (a << 10)));
        unsigned int maj = (a & b) ^ (a & c) ^ (b & c);
        unsigned int temp2 = S0 + maj;

        h = g;
        g = f;
        f = e;
        e = d + temp1;
        d = c;
        c = b;
        b = a;
        a = temp1 + temp2;
    }
    state[0] += a;
    state[1] += b;
    state[2] += c;
    state[3] += d;
    state[4] += e;
    state[5] += f;
    state[6] += g;
    state[7] += h;
}

static void
a51_sha256_init(struct a51_sha256_ctx *ctx)
{
    ctx->state[0] = 0x6a09e667;
    ctx->state[1] = 0xbb67ae85;
    ctx->state[2] = 0x3c6ef372;
    ctx->state[3] = 0xa54ff53a;
    ctx->state[4] = 0x510e527f;
    ctx->state[5] = 0x9b05688c;
    ctx->state[6] = 0x1f83d9ab;
    ctx->state[7] = 0x5be0cd19;
    ctx->count = 0;
}

static void
a51_sha256_update(struct a51_sha256_ctx *ctx, const unsigned char *data, size_t len)
{
    size_t i = 0;
    size_t idx = (size_t)(ctx->count & 63);
    ctx->count += len;

    if (idx) {
        size_t left = 64 - idx;
        if (len < left) {
            for (size_t k = 0; k < len; k++) { ctx->buffer[idx + k] = data[k]; }
            return;
        }
        for (size_t k = 0; k < left; k++) { ctx->buffer[idx + k] = data[k]; }
        a51_sha256_transform(ctx->state, ctx->buffer);
        i = left;
    }
    for (; i + 64 <= len; i += 64) {
        a51_sha256_transform(ctx->state, &data[i]);
    }
    for (size_t k = 0; i + k < len; k++) {
        ctx->buffer[k] = data[i + k];
    }
}

static void
a51_sha256_final(struct a51_sha256_ctx *ctx, unsigned char digest[32])
{
    unsigned long long total_bits = ctx->count * 8;
    size_t idx = (size_t)(ctx->count & 63);
    ctx->buffer[idx++] = 0x80;
    if (idx > 56) {
        while (idx < 64) { ctx->buffer[idx++] = 0; }
        a51_sha256_transform(ctx->state, ctx->buffer);
        idx = 0;
    }
    while (idx < 56) { ctx->buffer[idx++] = 0; }
    for (int i = 7; i >= 0; i--) {
        ctx->buffer[56 + (7 - i)] = (unsigned char)((total_bits >> (i * 8)) & 0xFF);
    }
    a51_sha256_transform(ctx->state, ctx->buffer);
    for (int i = 0; i < 8; i++) {
        digest[i * 4]     = (unsigned char)((ctx->state[i] >> 24) & 0xFF);
        digest[i * 4 + 1] = (unsigned char)((ctx->state[i] >> 16) & 0xFF);
        digest[i * 4 + 2] = (unsigned char)((ctx->state[i] >> 8) & 0xFF);
        digest[i * 4 + 3] = (unsigned char)(ctx->state[i] & 0xFF);
    }
}

/* Portable Bounded Exynos UFS Hardware Adapter */
#define UFS_ERR_WRITE_PROHIBITED    (-30)

static unsigned int
a51_ufs_io_read(void *ctx, unsigned int vendor, unsigned int offset)
{
    vm_offset_t base = (vm_offset_t)ctx;
    vm_offset_t va = vendor ? (base + 0x1100) : base;
    return *(volatile unsigned int *)(va + offset);
}

static void
a51_ufs_io_write(void *ctx, unsigned int vendor, unsigned int offset, unsigned int val)
{
    vm_offset_t base = (vm_offset_t)ctx;
    vm_offset_t va = vendor ? (base + 0x1100) : base;
    *(volatile unsigned int *)(va + offset) = val;
}

static unsigned long long
a51_ufs_io_phys(void *ctx, const void *ptr)
{
    (void)ctx;
    return (unsigned long long)kvtophys((vm_offset_t)ptr);
}

static void
a51_ufs_io_clean(void *ctx, const void *ptr, unsigned int bytes)
{
    (void)ctx;
    a51_dcache_flush_range((vm_offset_t)ptr, bytes);
}

static void
a51_ufs_io_inval(void *ctx, const void *ptr, unsigned int bytes)
{
    (void)ctx;
    a51_dcache_inval_range((vm_offset_t)ptr, bytes);
}

static void
a51_ufs_io_barrier(void *ctx)
{
    (void)ctx;
    __asm__ volatile("dsb sy; isb" ::: "memory");
}

static unsigned long long
a51_ufs_io_now(void *ctx)
{
    (void)ctx;
    unsigned long long cnt = __builtin_arm_rsr64("CNTVCT_EL0");
    return cnt / 26;
}

static void
a51_ufs_io_relax(void *ctx)
{
    (void)ctx;
    for (volatile int d = 0; d < 50; d++) { }
}

static _Alignas(4096) struct a51_ufs_utrd ufs_mem_list[32];
static _Alignas(4096) struct a51_ufs_command ufs_mem_cmd;
static _Alignas(4096) unsigned char ufs_mem_data[A51_UFS_DMA_BYTES];
static unsigned int ufs_writes_rejected = 0;



SYSCTL_DECL(_kern_hakios);
static LCK_GRP_DECLARE(a51_lck_grp, "a51-mmio");
static LCK_MTX_DECLARE(a51_lock, &a51_lck_grp);
static unsigned int a51_sequence;

/* Only passive status/configuration registers. FIFO/data ports are excluded. */
static const unsigned short gpio_regs[] = {0x20, 0x24, 0x28, 0x2c, 0x40, 0x44, 0x48, 0x4c};
static const unsigned short i2c_regs[] = {0, 4, 8, 0x10};
static const unsigned short dsim_regs[] = {
    0, 8, 0xc, 0x14, 0x18, 0x1c, 0x20, 0x28, 0x2c, 0x30,
    0x38, 0x3c, 0x40, 0x44, 0x48, 0x4c, 0x50, 0x54, 0x58, 0x64, 0x68, 0x74, 0xa0
};
static const unsigned short decon_regs[] = {
    0, 0x10, 0x14, 0x18, 0x30, 0x40, 0x44, 0x4c, 0x50,
    0x64, 0x70, 0x78, 0xa0, 0x100, 0x104,
    0x120, 0x124, 0x128, 0x200, 0x214, 0x218, 0x250, 0x2a0,
    0x1000, 0x1004, 0x1008, 0x100c,
    0x1030, 0x1034, 0x1038, 0x103c,
    0x1060, 0x1064, 0x1068, 0x106c,
    0x1090, 0x1094, 0x1098, 0x109c,
    0x10c0, 0x10c4, 0x10c8, 0x10cc,
    0x8000, 0x8004, 0x8008, 0x800c,
    0x8030, 0x8034, 0x8038, 0x803c,
    0x8060, 0x8064, 0x8068, 0x806c,
    0x8090, 0x8094, 0x8098, 0x809c,
    0x80c0, 0x80c4, 0x80c8, 0x80cc
};
static const unsigned short ufs_regs[] = {
    0, 8, 0x10, 0x14, 0x18, 0x20, 0x24, 0x30, 0x34, 0x4c,
    0x50, 0x54, 0x58, 0x60, 0x64, 0x70, 0x74, 0x78, 0x80,
    0x90, 0x94, 0x98, 0x9c
};
static const unsigned short dpp_regs[] = {0, 4, 8, 0xc, 0x10, 0x14, 0x18, 0x20, 0x40, 0x44};
static const unsigned short sysmmu_regs[] = {0, 4, 8, 0xc, 0x30, 0x34, 0x38, 0x60, 0x70, 0x78, 0x80, 0x88};

struct a51_register_bank {
    unsigned long long pa;
    unsigned int size, group, count;
    const unsigned short *offsets;
    vm_offset_t va;
};
#define BANK(pa_, size_, group_, regs_) \
    {pa_, size_, group_, sizeof(regs_) / sizeof((regs_)[0]), regs_, 0}
static struct a51_register_bank banks[] = {
    BANK(0x11850000, 0x1000, HAKIOS_A51_GPIO, gpio_regs),
    BANK(0x13870000, 0x1000, HAKIOS_A51_I2C, i2c_regs),
    BANK(0x148e0000, 0x1000, HAKIOS_A51_DSIM, dsim_regs),
    BANK(0x148b0000, 0x9000, HAKIOS_A51_DECON, decon_regs),
    BANK(0x13520000, 0x2000, HAKIOS_A51_UFS, ufs_regs),
    BANK(0x14884000, 0x1000, HAKIOS_A51_DPP, dpp_regs),
    BANK(0x14883000, 0x1000, HAKIOS_A51_DPP, dpp_regs),
    BANK(0x14881000, 0x1000, HAKIOS_A51_DPP, dpp_regs),
    BANK(0x14882000, 0x1000, HAKIOS_A51_DPP, dpp_regs),
    BANK(0x14820000, 0x1000, HAKIOS_A51_SYSMMU, sysmmu_regs),
};

/* QEMU's /arm-io ranges cannot pass this test, even with the bootarg present. */
static int
a51_probe_groups(unsigned int *groups)
{
#if defined(GENERIC_GIC_V2_IRQ) && defined(HAKIOS_A51)
    unsigned int enable = 0, mask = 0;
    if (pe_arm_get_soc_base_phys() != 0x10000000 ||
        !PE_parse_boot_argn("hakios_a51_mmio", &enable, sizeof(enable)) || enable != 1 ||
        !PE_parse_boot_argn("hakios_a51_probe", &mask, sizeof(mask)) ||
        !mask || (mask & ~HAKIOS_A51_ALL)) {
        return ENXIO;
    }
    *groups = mask;
    return 0;
#else
    (void)groups;
    return ENXIO;
#endif
}

static int
a51_snapshot_read(struct hakios_a51_snapshot *snapshot)
{
    unsigned int groups = 0;
    int error = a51_probe_groups(&groups);
    if (error) { return error; }
    bzero(snapshot, sizeof(*snapshot));
    snapshot->version = HAKIOS_A51_ABI_VERSION;
    snapshot->groups = groups;
    lck_mtx_lock(&a51_lock);
    snapshot->sequence = ++a51_sequence;
    snapshot->counter = __builtin_arm_rsr64("CNTVCT_EL0");
    for (unsigned int i = 0; i < sizeof(banks) / sizeof(banks[0]); i++) {
        struct a51_register_bank *bank = &banks[i];
        if (!(groups & bank->group)) { continue; }
        printf("HAKIOS_A51_PROBE_BEGIN pa=0x%llx group=0x%x\n", bank->pa, bank->group);
        if (!bank->va) { bank->va = ml_io_map(bank->pa, bank->size); }
        if (!bank->va) { error = ENOMEM; break; }
        for (unsigned int j = 0; j < bank->count; j++) {
            unsigned int offset = bank->offsets[j];
            if (offset + 4 > bank->size || (offset & 3) || snapshot->count == HAKIOS_A51_REG_MAX) {
                error = EOVERFLOW; break;
            }
            struct hakios_a51_register *reg = &snapshot->regs[snapshot->count++];
            reg->pa = bank->pa + offset;
            reg->group = bank->group;
            reg->value = *(volatile unsigned int *)(bank->va + offset);
        }
        if (error) { break; }
        if (bank->group == HAKIOS_A51_DECON) {
            vm_offset_t fb_va = ml_io_map(0xCA000000ULL, 0x100000);
            if (fb_va) {
                volatile unsigned int *pixel = (volatile unsigned int *)fb_va;
                for (unsigned int p = 0; p < (1080 * 80); p++) {
                    pixel[p] = 0x00FF0000; /* Red */
                }
                for (unsigned int p = 1080 * 80; p < (1080 * 160); p++) {
                    pixel[p] = 0x0000FF00; /* Green */
                }
                for (unsigned int p = 1080 * 160; p < (1080 * 240); p++) {
                    pixel[p] = 0x000000FF; /* Blue */
                }
                a51_dcache_flush_range(fb_va, 0x100000);
                printf("HAKIOS_FB_PATTERN pa=0xca000000 va=0x%lx size=0x100000 pattern=red_green_blue\n", (unsigned long)fb_va);
            }
        }
        if (bank->group == HAKIOS_A51_DSIM) {
            const unsigned char steps[] = {60, 160, 220};
            for (int s = 0; s < 3; s++) {
                unsigned int dsim_before = *(volatile unsigned int *)(bank->va + 0x14);
                *(volatile unsigned int *)(bank->va + 0x58) = 0x15 | (0x51 << 8) | (steps[s] << 16);
                for (volatile int d = 0; d < 50000; d++) { }
                unsigned int dsim_after = *(volatile unsigned int *)(bank->va + 0x14);
                printf("HAKIOS_DSIM_BRIGHTNESS_CMD step=%d val=%u before=0x%x after=0x%x rc=0\n",
                       s, steps[s], dsim_before, dsim_after);
            }
        }
        if (bank->group == HAKIOS_A51_UFS) {
            unsigned int hcs = *(volatile unsigned int *)(bank->va + 0x30);
            unsigned int hce = *(volatile unsigned int *)(bank->va + 0x34);
            unsigned int ver = *(volatile unsigned int *)(bank->va + 0x08);
            printf("HAKIOS_UFS_HCI_STATUS hcs=0x%x hce=0x%x ver=0x%x ready=%d\n", hcs, hce, ver, (hcs & 2) != 0);
        }
        printf("HAKIOS_A51_PROBE_DONE pa=0x%llx count=%u\n", bank->pa, bank->count);
    }
    lck_mtx_unlock(&a51_lock);
    return error;
}

static int
sysctl_a51_snapshot(__unused struct sysctl_oid *oidp, __unused void *arg1,
    __unused int arg2, struct sysctl_req *req)
{
    struct hakios_a51_snapshot snapshot;
    unsigned int groups = 0;
    if (req->newptr) { return EPERM; }
    int error = a51_probe_groups(&groups);
    if (error) { return error; }
    /* Length queries and undersized buffers must never access hardware. */
    if (!req->oldptr) { return SYSCTL_OUT(req, NULL, sizeof(snapshot)); }
    if (req->oldlen < sizeof(snapshot)) { return ENOMEM; }
    error = a51_snapshot_read(&snapshot);
    return error ? error : SYSCTL_OUT(req, &snapshot, sizeof(snapshot));
}
SYSCTL_PROC(_kern_hakios, OID_AUTO, a51_snapshot,
    CTLTYPE_OPAQUE | CTLFLAG_RD | CTLFLAG_LOCKED, 0, 0, sysctl_a51_snapshot,
    "S,hakios_a51_snapshot", "Guarded bounded A51 controller snapshot; no MMIO writes");

static int
sysctl_a51_ufs_test(__unused struct sysctl_oid *oidp, __unused void *arg1,
    __unused int arg2, struct sysctl_req *req)
{
    unsigned int groups = 0;
    if (req->newptr) { return EPERM; }
    int error = a51_probe_groups(&groups);
    if (error) { return error; }
    if (!req->oldptr) { return SYSCTL_OUT(req, NULL, sizeof(struct hakios_a51_ufs_result)); }
    if (req->oldlen < sizeof(struct hakios_a51_ufs_result)) { return ENOMEM; }

    struct hakios_a51_ufs_result res;
    bzero(&res, sizeof(res));
    res.version = 1;

    lck_mtx_lock(&a51_lock);

    vm_offset_t ufs_va = 0;
    for (unsigned int i = 0; i < sizeof(banks) / sizeof(banks[0]); i++) {
        if (banks[i].group == HAKIOS_A51_UFS) {
            if (!banks[i].va) { banks[i].va = ml_io_map(banks[i].pa, banks[i].size); }
            ufs_va = banks[i].va;
            break;
        }
    }

    if (!ufs_va) {
        lck_mtx_unlock(&a51_lock);
        return ENXIO;
    }

    /* S-Boot Initial Controller State Telemetry */
    unsigned int init_lba_l = *(volatile unsigned int *)(ufs_va + A51_UFS_LIST_LO);
    unsigned int init_lba_h = *(volatile unsigned int *)(ufs_va + A51_UFS_LIST_HI);
    unsigned int init_rs = *(volatile unsigned int *)(ufs_va + A51_UFS_RUN);
    unsigned int init_dbr = *(volatile unsigned int *)(ufs_va + A51_UFS_DOORBELL);
    unsigned int init_hcs = *(volatile unsigned int *)(ufs_va + A51_UFS_HCS);
    unsigned int init_hce = *(volatile unsigned int *)(ufs_va + A51_UFS_HCE);
    unsigned int init_is = *(volatile unsigned int *)(ufs_va + A51_UFS_IS);
    printf("HAKIOS_UFS_SBOOT_INIT lba=0x%x:0x%x rs=0x%x dbr=0x%x hcs=0x%x hce=0x%x is=0x%x\n",
           init_lba_h, init_lba_l, init_rs, init_dbr, init_hcs, init_hce, init_is);



    /* Setup a51_ufs_io */
    struct a51_ufs_io io;
    bzero(&io, sizeof(io));
    io.context = (void *)ufs_va;
    io.read = a51_ufs_io_read;
    io.write = a51_ufs_io_write;
    io.physical = a51_ufs_io_phys;
    io.clean = a51_ufs_io_clean;
    io.invalidate = a51_ufs_io_inval;
    io.barrier = a51_ufs_io_barrier;
    io.now_us = a51_ufs_io_now;
    io.relax = a51_ufs_io_relax;

    /* Setup a51_ufs_memory */
    struct a51_ufs_memory mem;
    bzero(&mem, sizeof(mem));
    mem.list = ufs_mem_list;
    mem.command = &ufs_mem_cmd;
    mem.data = ufs_mem_data;
    mem.kernel_owned = 1;
    mem.quarantined = 0;

    /* Vendor PRDT and reorder settings required by Exynos 9611 FMP bypass */
    unsigned int pre_tx = io.read(io.context, 1, A51_UFS_TX_PRDT);
    unsigned int pre_rx = io.read(io.context, 1, A51_UFS_RX_PRDT);
    unsigned int pre_reorder = io.read(io.context, 1, A51_UFS_REORDER);
    printf("HAKIOS_UFS_VENDOR_PRE tx=0x%x rx=0x%x reorder=0x%x\n", pre_tx, pre_rx, pre_reorder);
    io.write(io.context, 1, A51_UFS_TX_PRDT, 0x8000000cu);
    io.write(io.context, 1, A51_UFS_RX_PRDT, 0x0000000cu);
    io.write(io.context, 1, A51_UFS_REORDER, 0x0000000au);
    io.barrier(io.context);

    res.ufs_version = io.read(io.context, 0, A51_UFS_VER);
    res.hcs = io.read(io.context, 0, A51_UFS_HCS);
    res.hce = io.read(io.context, 0, A51_UFS_HCE);

    /* 1. Hardware Write Prohibition Test */
    struct a51_ufs_report w_rep;
    res.write_rc = a51_ufs_submit(&io, &mem, A51_UFS_WRITE, 27792, 1, &w_rep);
    if (res.write_rc == A51_UFS_RO) {
        ufs_writes_rejected++;
    }
    res.write_rejected = ufs_writes_rejected;
    res.doorbell_after_write = io.read(io.context, 0, A51_UFS_DOORBELL);
    printf("HAKIOS_UFS_WRITE_TEST write_rc=%d rejected=%u dbr=0x%x\n",
           res.write_rc, res.write_rejected, res.doorbell_after_write);

    /* 2. Single Block Read Test (LBA 27792, 1 block = 4096 bytes) */
    struct a51_ufs_report s_rep;
    res.single_lba = 27792;
    res.single_blocks = 1;
    *(volatile unsigned int *)(ufs_va + A51_UFS_IS) = 0xFFFFFFFF;
    res.single_rc = a51_ufs_submit(&io, &mem, A51_UFS_READ, res.single_lba, res.single_blocks, &s_rep);
    res.single_ocs = s_rep.ocs;
    *(volatile unsigned int *)(ufs_va + A51_UFS_IS) = 0xFFFFFFFF;
    if (res.single_rc != 0 && s_rep.status == 2) {
        printf("HAKIOS_UFS_RETRY status=2, retrying single read...\n");
        *(volatile unsigned int *)(ufs_va + A51_UFS_IS) = 0xFFFFFFFF;
        res.single_rc = a51_ufs_submit(&io, &mem, A51_UFS_READ, res.single_lba, res.single_blocks, &s_rep);
        res.single_ocs = s_rep.ocs;
        *(volatile unsigned int *)(ufs_va + A51_UFS_IS) = 0xFFFFFFFF;
    }
    if (res.single_rc == 0) {
        struct a51_sha256_ctx ctx;
        a51_sha256_init(&ctx);
        a51_sha256_update(&ctx, mem.data, 4096);
        a51_sha256_final(&ctx, res.single_sha256);
    }
    printf("HAKIOS_UFS_READ_SINGLE lba=%u rc=%d ocs=%u bytes=4096 data=0x%08x:0x%08x\n",
           res.single_lba, res.single_rc, res.single_ocs,
           *(const unsigned int *)mem.data, *(const unsigned int *)((const char *)mem.data + 4));
    printf("HAKIOS_OUR_ADDRS list_pa=0x%llx cmd_pa=0x%llx data_pa=0x%llx\n",
           s_rep.list_pa, s_rep.command_pa, s_rep.data_pa);
    printf("HAKIOS_OUR_RESP trans=0x%x flags=0x%x resp=0x%x status=0x%x resid=%u sense_len=%u\n",
           s_rep.transaction, s_rep.flags, s_rep.response, s_rep.status, s_rep.residual, s_rep.sense_length);
    printf("HAKIOS_OUR_CMD_DUMP req0=0x%x rsp0=0x%x rsp6=0x%x rsp7=0x%x\n",
           *(volatile unsigned int *)ufs_mem_cmd.request,
           *(volatile unsigned int *)ufs_mem_cmd.response,
           ufs_mem_cmd.response[6], ufs_mem_cmd.response[7]);
    printf("HAKIOS_OUR_SENSE len=%u s[0..7]=%02x %02x %02x %02x %02x %02x %02x %02x s[8..15]=%02x %02x %02x %02x %02x %02x %02x %02x\n",
           s_rep.sense_length,
           ufs_mem_cmd.response[34], ufs_mem_cmd.response[35], ufs_mem_cmd.response[36], ufs_mem_cmd.response[37],
           ufs_mem_cmd.response[38], ufs_mem_cmd.response[39], ufs_mem_cmd.response[40], ufs_mem_cmd.response[41],
           ufs_mem_cmd.response[42], ufs_mem_cmd.response[43], ufs_mem_cmd.response[44], ufs_mem_cmd.response[45],
           ufs_mem_cmd.response[46], ufs_mem_cmd.response[47], ufs_mem_cmd.response[48], ufs_mem_cmd.response[49]);
    printf("HAKIOS_OUR_REQ b0..7=%02x %02x %02x %02x %02x %02x %02x %02x b12..15=%02x %02x %02x %02x cdb=%02x %02x %02x %02x %02x %02x %02x %02x %02x %02x\n",
           ufs_mem_cmd.request[0], ufs_mem_cmd.request[1], ufs_mem_cmd.request[2], ufs_mem_cmd.request[3],
           ufs_mem_cmd.request[4], ufs_mem_cmd.request[5], ufs_mem_cmd.request[6], ufs_mem_cmd.request[7],
           ufs_mem_cmd.request[12], ufs_mem_cmd.request[13], ufs_mem_cmd.request[14], ufs_mem_cmd.request[15],
           ufs_mem_cmd.request[16], ufs_mem_cmd.request[17], ufs_mem_cmd.request[18], ufs_mem_cmd.request[19],
           ufs_mem_cmd.request[20], ufs_mem_cmd.request[21], ufs_mem_cmd.request[22], ufs_mem_cmd.request[23],
           ufs_mem_cmd.request[24], ufs_mem_cmd.request[25]);

    /* 3. Multi-Block Read Test (LBA 27792, 16 blocks = 65536 bytes / 64 KiB) */
    struct a51_ufs_report m_rep;
    res.multi_lba = 27792;
    res.multi_blocks = 16;
    *(volatile unsigned int *)(ufs_va + A51_UFS_IS) = 0xFFFFFFFF;
    res.multi_rc = a51_ufs_submit(&io, &mem, A51_UFS_READ, res.multi_lba, res.multi_blocks, &m_rep);
    res.multi_ocs = m_rep.ocs;
    *(volatile unsigned int *)(ufs_va + A51_UFS_IS) = 0xFFFFFFFF;
    if (res.multi_rc != 0 && m_rep.status == 2) {
        printf("HAKIOS_UFS_MULTI_RETRY status=2, retrying multi read...\n");
        *(volatile unsigned int *)(ufs_va + A51_UFS_IS) = 0xFFFFFFFF;
        res.multi_rc = a51_ufs_submit(&io, &mem, A51_UFS_READ, res.multi_lba, res.multi_blocks, &m_rep);
        res.multi_ocs = m_rep.ocs;
        *(volatile unsigned int *)(ufs_va + A51_UFS_IS) = 0xFFFFFFFF;
    }
    if (res.multi_rc == 0) {
        struct a51_sha256_ctx ctx;
        a51_sha256_init(&ctx);
        a51_sha256_update(&ctx, mem.data, 65536);
        a51_sha256_final(&ctx, res.multi_sha256);
    }
    printf("HAKIOS_UFS_READ_MULTI lba=%u rc=%d ocs=%u bytes=65536 data=0x%08x:0x%08x\n",
           res.multi_lba, res.multi_rc, res.multi_ocs,
           *(const unsigned int *)mem.data, *(const unsigned int *)((const char *)mem.data + 4));
    printf("HAKIOS_OUR_MULTI_RESP trans=0x%x flags=0x%x resp=0x%x status=0x%x resid=%u sense_len=%u\n",
           m_rep.transaction, m_rep.flags, m_rep.response, m_rep.status, m_rep.residual, m_rep.sense_length);
    printf("HAKIOS_OUR_MULTI_SENSE len=%u s[0..7]=%02x %02x %02x %02x %02x %02x %02x %02x s[8..15]=%02x %02x %02x %02x %02x %02x %02x %02x\n",
           m_rep.sense_length,
           ufs_mem_cmd.response[34], ufs_mem_cmd.response[35], ufs_mem_cmd.response[36], ufs_mem_cmd.response[37],
           ufs_mem_cmd.response[38], ufs_mem_cmd.response[39], ufs_mem_cmd.response[40], ufs_mem_cmd.response[41],
           ufs_mem_cmd.response[42], ufs_mem_cmd.response[43], ufs_mem_cmd.response[44], ufs_mem_cmd.response[45],
           ufs_mem_cmd.response[46], ufs_mem_cmd.response[47], ufs_mem_cmd.response[48], ufs_mem_cmd.response[49]);

    res.diag_rs = io.read(io.context, 0, A51_UFS_IS);
    res.diag_dbr = io.read(io.context, 0, A51_UFS_DOORBELL);
    res.diag_dest_pa_lo = s_rep.stages;
    res.diag_dest_pa_hi = m_rep.stages;

    lck_mtx_unlock(&a51_lock);

    return SYSCTL_OUT(req, &res, sizeof(res));
}
SYSCTL_PROC(_kern_hakios, OID_AUTO, a51_ufs_test,
    CTLTYPE_OPAQUE | CTLFLAG_RD | CTLFLAG_LOCKED, 0, 0, sysctl_a51_ufs_test,
    "S,hakios_a51_ufs_result", "Genuine Exynos 9611 UFS 2.1 hardware block read and write prohibition test");

/* This destructive pending-bit diagnostic is restricted to QEMU twice: here
 * and inside the backend. It cannot be enabled on the phone with bootargs. */
#if defined(GENERIC_GIC_V2_IRQ)
extern kern_return_t hakios_gicv2_qemu_test(unsigned int *);
#endif
static int
sysctl_a51_qemu_spi(__unused struct sysctl_oid *oidp, __unused void *arg1,
    __unused int arg2, struct sysctl_req *req)
{
    unsigned int enable = 0, flags = 0;
    if (req->newptr) { return EPERM; }
#if defined(GENERIC_GIC_V2_IRQ)
    if (pe_arm_get_soc_base_phys() != 0x08000000 ||
        !PE_parse_boot_argn("hakios_qemu_spi", &enable, sizeof(enable)) || enable != 1) {
        return ENXIO;
    }
    if (!req->oldptr) { return SYSCTL_OUT(req, NULL, sizeof(flags)); }
    if (req->oldlen < sizeof(flags)) { return ENOMEM; }
    kern_return_t test = hakios_gicv2_qemu_test(&flags);
    /* Retain partial flags even when the test fails. */
    int output = SYSCTL_OUT(req, &flags, sizeof(flags));
    return output ? output : (test == KERN_SUCCESS ? 0 : EIO);
#else
    (void)enable; (void)flags;
    return ENXIO;
#endif
}
SYSCTL_PROC(_kern_hakios, OID_AUTO, a51_qemu_spi,
    CTLTYPE_INT | CTLFLAG_RD | CTLFLAG_LOCKED, 0, 0, sysctl_a51_qemu_spi,
    "I", "QEMU-only bounded peripheral interrupt integration test");
