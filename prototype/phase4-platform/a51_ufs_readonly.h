/* SPDX-License-Identifier: MIT */
/* Bounded Exynos UFS diagnostic. Shared unchanged by XNU and native tests.
 * Matching references: ufshci.h, ufshcd.c, ufs-exynos.c and crypto/fmp.h.
 * This adopts an already initialized, idle link; it does not initialize PHYs.
 * The only accepted command is READ(10), LUN 0, within the boot partition.
 */
#ifndef A51_UFS_READONLY_H
#define A51_UFS_READONLY_H

#define A51_UFS_READ 0u
#define A51_UFS_WRITE 1u
#define A51_UFS_RO (-30)
#define A51_UFS_INVAL (-22)
#define A51_UFS_BUSY (-16)
#define A51_UFS_IO (-5)
#define A51_UFS_TIMEOUT (-110)
#define A51_UFS_PROTOCOL (-71)
#define A51_UFS_UNSUPPORTED (-95)
#define A51_UFS_BOOT_LBA 27792u
#define A51_UFS_BOOT_BLOCKS 15104u
#define A51_UFS_BLOCK_SIZE 4096u
#define A51_UFS_MAX_BLOCKS 16u
#define A51_UFS_DMA_BYTES 65536u
#define A51_UFS_ERROR_MASK 0x00070884u

#define A51_UFS_CAP 0x00u
#define A51_UFS_VER 0x08u
#define A51_UFS_IS 0x20u
#define A51_UFS_HCS 0x30u
#define A51_UFS_HCE 0x34u
#define A51_UFS_LIST_LO 0x50u
#define A51_UFS_LIST_HI 0x54u
#define A51_UFS_DOORBELL 0x58u
#define A51_UFS_CLEAR 0x5cu
#define A51_UFS_RUN 0x60u
#define A51_UFS_TASK_DOORBELL 0x78u
#define A51_UFS_TX_PRDT 0x00u /* separate vendor HCI at 0x13521100 */
#define A51_UFS_RX_PRDT 0x04u
#define A51_UFS_NEXUS 0x40u
#define A51_UFS_REORDER 0x60u

enum a51_ufs_stage {
    A51_UFS_PREFLIGHT = 1, A51_UFS_PREPARED, A51_UFS_ADOPTED,
    A51_UFS_SUBMITTED, A51_UFS_COMPLETED, A51_UFS_VALIDATED,
    A51_UFS_RESTORED, A51_UFS_QUARANTINED
};

/* ARM64 and the native test host are little endian; UPIUs are big endian. */
struct a51_ufs_utrd {
    unsigned int dw0, dw1, ocs, dw3, cmd_lo, cmd_hi;
    unsigned short rsp_len, rsp_off, prdt_len, prdt_off;
};
struct a51_ufs_fmp_prdt { unsigned int words[32]; };
struct a51_ufs_command {
    unsigned char request[1024], response[1024];
    struct a51_ufs_fmp_prdt prdt[16];
};
_Static_assert(sizeof(unsigned int) == 4 && sizeof(unsigned short) == 2, "UFS word sizes");
_Static_assert(sizeof(struct a51_ufs_utrd) == 32, "UTRD size");
_Static_assert(sizeof(struct a51_ufs_fmp_prdt) == 128, "matching UFS FMP stride");
_Static_assert(sizeof(struct a51_ufs_command) == 4096, "UFS command size");

struct a51_ufs_io {
    void *context;
    unsigned int (*read)(void *, unsigned int vendor, unsigned int offset);
    void (*write)(void *, unsigned int vendor, unsigned int offset, unsigned int value);
    unsigned long long (*physical)(void *, const void *);
    void (*clean)(void *, const void *, unsigned int);
    void (*invalidate)(void *, const void *, unsigned int);
    void (*barrier)(void *);
    unsigned long long (*now_us)(void *);
    void (*relax)(void *);
    void (*trace)(void *, unsigned int stage);
};
struct a51_ufs_memory {
    struct a51_ufs_utrd *list; /* 32 slots, 1024 bytes */
    struct a51_ufs_command *command;
    unsigned char *data; /* 65536 bytes */
    unsigned int kernel_owned, quarantined;
};
struct a51_ufs_report {
    int rc;
    unsigned int stages, submitted, completed, restored, quarantined;
    unsigned int cap, version, hcs, hce, initial_is, final_is;
    unsigned int initial_lo, initial_hi, initial_run, initial_doorbell, initial_task;
    unsigned int tx_prdt, rx_prdt, nexus, reorder, final_doorbell, final_run;
    unsigned int ocs, transaction, response, status, residual, flags, sense_length;
    unsigned int lba, blocks, bytes;
    unsigned long long list_pa, command_pa, data_pa;
};

static inline void
a51_ufs_zero(void *out, unsigned int bytes)
{
    unsigned char *p = (unsigned char *)out;
    while (bytes--) { *p++ = 0; }
}

static inline unsigned int
a51_ufs_be32(const unsigned char *p)
{
    return ((unsigned int)p[0] << 24) | ((unsigned int)p[1] << 16) |
        ((unsigned int)p[2] << 8) | p[3];
}

static inline void
a51_ufs_put_be32(unsigned char *p, unsigned int value)
{
    p[0] = (unsigned char)(value >> 24); p[1] = (unsigned char)(value >> 16);
    p[2] = (unsigned char)(value >> 8); p[3] = (unsigned char)value;
}

static inline int
a51_ufs_overlap(unsigned long long a, unsigned int an, unsigned long long b, unsigned int bn)
{
    return a < b + bn && b < a + an;
}

/* Check every 4 KiB boundary AND the last byte. No guessed DMA apertures,
 * translation of only the first page, aliases, or truncation to 32 bits.
 */
static inline int
a51_ufs_span(const struct a51_ufs_io *io, const void *ptr, unsigned int bytes,
    unsigned int alignment, unsigned long long *physical)
{
    unsigned long long va = (unsigned long long)(unsigned long)ptr;
    if (!ptr || !bytes || (va & (alignment - 1)) || va + bytes < va) { return A51_UFS_INVAL; }
    unsigned long long pa = io->physical(io->context, ptr);
    if (!pa || (pa & (alignment - 1)) || pa > 0xffffffffULL || bytes - 1 > 0xffffffffULL - pa) {
        return A51_UFS_INVAL;
    }
    for (unsigned int offset = 0; offset < bytes; offset += 4096) {
        if (io->physical(io->context, (const unsigned char *)ptr + offset) != pa + offset) {
            return A51_UFS_INVAL;
        }
    }
    if (io->physical(io->context, (const unsigned char *)ptr + bytes - 1) != pa + bytes - 1) {
        return A51_UFS_INVAL;
    }
    *physical = pa;
    return 0;
}

static inline void
a51_ufs_mark(const struct a51_ufs_io *io, struct a51_ufs_report *r, unsigned int stage)
{
    r->stages |= 1u << stage;
    if (io->trace) { io->trace(io->context, stage); }
}

static inline int
a51_ufs_wait(const struct a51_ufs_io *io, unsigned int reg, unsigned int mask,
    unsigned int expected, unsigned int us)
{
    unsigned long long started = io->now_us(io->context);
    /* The poll limit also bounds a broken/nonadvancing counter. */
    for (unsigned int polls = 0; polls < 1000000u; polls++) {
        if ((io->read(io->context, 0, reg) & mask) == expected) { return 0; }
        if (io->now_us(io->context) - started >= us) { break; }
        io->relax(io->context);
    }
    return A51_UFS_TIMEOUT;
}

static inline int
a51_ufs_quarantine(const struct a51_ufs_io *io, struct a51_ufs_memory *m,
    struct a51_ufs_report *r, int error)
{
    /* Keep all buffers owned until reset. Never invalidate, hash, overwrite,
     * unmap, or reuse them while completion/stop cannot be proved.
     */
    m->quarantined = r->quarantined = 1;
    r->rc = error;
    a51_ufs_mark(io, r, A51_UFS_QUARANTINED);
    return error;
}

static inline int
a51_ufs_restore(const struct a51_ufs_io *io, struct a51_ufs_memory *m,
    struct a51_ufs_report *r)
{
    r->final_doorbell = io->read(io->context, 0, A51_UFS_DOORBELL);
    if (r->final_doorbell || io->read(io->context, 0, A51_UFS_TASK_DOORBELL)) {
        return a51_ufs_quarantine(io, m, r, A51_UFS_BUSY);
    }
    io->write(io->context, 0, A51_UFS_RUN, 0);
    io->barrier(io->context);
    if (a51_ufs_wait(io, A51_UFS_RUN, 1, 0, 25000)) {
        return a51_ufs_quarantine(io, m, r, A51_UFS_TIMEOUT);
    }
    /* Recheck both doorbells after stop before replacing any list pointer. */
    if (io->read(io->context, 0, A51_UFS_DOORBELL) || io->read(io->context, 0, A51_UFS_TASK_DOORBELL)) {
        return a51_ufs_quarantine(io, m, r, A51_UFS_BUSY);
    }
    io->write(io->context, 0, A51_UFS_LIST_LO, r->initial_lo);
    io->write(io->context, 0, A51_UFS_LIST_HI, r->initial_hi);
    io->write(io->context, 1, A51_UFS_NEXUS, r->nexus);
    io->barrier(io->context);
    if (io->read(io->context, 0, A51_UFS_LIST_LO) != r->initial_lo ||
        io->read(io->context, 0, A51_UFS_LIST_HI) != r->initial_hi ||
        io->read(io->context, 1, A51_UFS_NEXUS) != r->nexus) {
        return a51_ufs_quarantine(io, m, r, A51_UFS_IO);
    }
    io->write(io->context, 0, A51_UFS_RUN, r->initial_run & 1u);
    io->barrier(io->context);
    if (a51_ufs_wait(io, A51_UFS_RUN, 1, r->initial_run & 1u, 25000)) {
        return a51_ufs_quarantine(io, m, r, A51_UFS_TIMEOUT);
    }
    r->final_run = io->read(io->context, 0, A51_UFS_RUN);
    r->restored = 1;
    a51_ufs_mark(io, r, A51_UFS_RESTORED);
    return 0;
}

static inline int
a51_ufs_submit(const struct a51_ufs_io *io, struct a51_ufs_memory *m,
    unsigned int operation, unsigned int lba, unsigned int blocks, struct a51_ufs_report *r)
{
    /* This check is the actual submission path, before even dereferencing
     * io, m or r. Unknown operations cannot bypass the read-only restriction.
     */
    if (operation != A51_UFS_READ) { return A51_UFS_RO; }
    if (!io || !m || !r || !io->read || !io->write || !io->physical || !io->clean ||
        !io->invalidate || !io->barrier || !io->now_us || !io->relax ||
        !blocks || blocks > A51_UFS_MAX_BLOCKS || lba < A51_UFS_BOOT_LBA ||
        lba - A51_UFS_BOOT_LBA > A51_UFS_BOOT_BLOCKS - blocks) { return A51_UFS_INVAL; }
    a51_ufs_zero(r, sizeof(*r));
    r->ocs = 15; r->lba = lba; r->blocks = blocks; r->bytes = blocks * A51_UFS_BLOCK_SIZE;
    if (m->quarantined) { r->quarantined = 1; return r->rc = A51_UFS_BUSY; }
    if (m->kernel_owned != 1 ||
        a51_ufs_span(io, m->list, 1024, 1024, &r->list_pa) ||
        a51_ufs_span(io, m->command, 4096, 4096, &r->command_pa) ||
        a51_ufs_span(io, m->data, A51_UFS_DMA_BYTES, 4096, &r->data_pa) ||
        a51_ufs_overlap(r->list_pa, 1024, r->command_pa, 4096) ||
        a51_ufs_overlap(r->list_pa, 1024, r->data_pa, A51_UFS_DMA_BYTES) ||
        a51_ufs_overlap(r->command_pa, 4096, r->data_pa, A51_UFS_DMA_BYTES)) {
        return r->rc = A51_UFS_INVAL;
    }
    a51_ufs_mark(io, r, A51_UFS_PREFLIGHT);
    r->cap = io->read(io->context, 0, A51_UFS_CAP);
    r->version = io->read(io->context, 0, A51_UFS_VER);
    r->hcs = io->read(io->context, 0, A51_UFS_HCS);
    r->hce = io->read(io->context, 0, A51_UFS_HCE);
    r->initial_lo = io->read(io->context, 0, A51_UFS_LIST_LO);
    r->initial_hi = io->read(io->context, 0, A51_UFS_LIST_HI);
    r->initial_run = io->read(io->context, 0, A51_UFS_RUN);
    r->initial_doorbell = io->read(io->context, 0, A51_UFS_DOORBELL);
    r->initial_task = io->read(io->context, 0, A51_UFS_TASK_DOORBELL);
    r->initial_is = io->read(io->context, 0, A51_UFS_IS);
    if (r->initial_doorbell || r->initial_task) { return r->rc = A51_UFS_BUSY; }
    r->tx_prdt = io->read(io->context, 1, A51_UFS_TX_PRDT);
    r->rx_prdt = io->read(io->context, 1, A51_UFS_RX_PRDT);
    r->nexus = io->read(io->context, 1, A51_UFS_NEXUS);
    r->reorder = io->read(io->context, 1, A51_UFS_REORDER);
    if (!(r->hce & 1) || (r->hcs & 3) != 3 || (r->hcs & 0x30) ||
        (r->initial_is & A51_UFS_ERROR_MASK)) { return r->rc = A51_UFS_IO; }
    /* No format trials or crypto/prefetch changes. These matching settings
     * require the 128-byte zeroed FMP extension and byte-unit descriptor.
     */
    if (r->tx_prdt != 0x8000000cu || r->rx_prdt != 0xcu || r->reorder != 0xau) {
        return r->rc = A51_UFS_UNSUPPORTED;
    }
    if (io->read(io->context, 0, A51_UFS_DOORBELL) || io->read(io->context, 0, A51_UFS_TASK_DOORBELL)) {
        return r->rc = A51_UFS_BUSY;
    }
    a51_ufs_zero(m->list, 1024);
    a51_ufs_zero(m->command, 4096);
    a51_ufs_zero(m->data, A51_UFS_DMA_BYTES);
    struct a51_ufs_utrd *u = &m->list[0];
    struct a51_ufs_command *c = m->command;
    u->dw0 = 0x15000000u; /* storage command | device-to-host | interrupt */
    u->ocs = 15; u->cmd_lo = (unsigned int)r->command_pa; u->cmd_hi = 0;
    u->rsp_off = u->rsp_len = 1024; u->prdt_off = 2048; u->prdt_len = 128;
    c->request[0] = 1; c->request[1] = 0x40; /* COMMAND, READ, LUN/tag 0 */
    a51_ufs_put_be32(c->request + 12, r->bytes);
    c->request[16] = 0x28; /* READ(10), the sole allowed CDB */
    a51_ufs_put_be32(c->request + 18, lba);
    c->request[23] = (unsigned char)(blocks >> 8); c->request[24] = (unsigned char)blocks;
    c->prdt[0].words[0] = (unsigned int)r->data_pa;
    c->prdt[0].words[3] = r->bytes - 1; /* crypto flags/extensions remain zero */
    io->clean(io->context, m->data, A51_UFS_DMA_BYTES);
    io->clean(io->context, m->command, 4096);
    io->clean(io->context, m->list, 1024);
    io->barrier(io->context);
    a51_ufs_mark(io, r, A51_UFS_PREPARED);
    io->write(io->context, 0, A51_UFS_RUN, 0);
    io->barrier(io->context);
    if (a51_ufs_wait(io, A51_UFS_RUN, 1, 0, 25000)) {
        return a51_ufs_quarantine(io, m, r, A51_UFS_TIMEOUT);
    }
    if (io->read(io->context, 0, A51_UFS_DOORBELL) || io->read(io->context, 0, A51_UFS_TASK_DOORBELL)) {
        return a51_ufs_quarantine(io, m, r, A51_UFS_BUSY);
    }
    io->write(io->context, 0, A51_UFS_LIST_LO, (unsigned int)r->list_pa);
    io->write(io->context, 0, A51_UFS_LIST_HI, 0);
    io->write(io->context, 1, A51_UFS_NEXUS, r->nexus | 1u);
    io->barrier(io->context);
    a51_ufs_mark(io, r, A51_UFS_ADOPTED);
    int error = 0;
    if (io->read(io->context, 0, A51_UFS_LIST_LO) != (unsigned int)r->list_pa ||
        io->read(io->context, 0, A51_UFS_LIST_HI) != 0 ||
        io->read(io->context, 1, A51_UFS_NEXUS) != (r->nexus | 1u)) {
        error = A51_UFS_IO;
    } else {
        io->write(io->context, 0, A51_UFS_RUN, 1);
        io->barrier(io->context);
        error = a51_ufs_wait(io, A51_UFS_RUN, 1, 1, 25000);
    }
    if (!error && (io->read(io->context, 0, A51_UFS_DOORBELL) ||
        io->read(io->context, 0, A51_UFS_TASK_DOORBELL))) { error = A51_UFS_BUSY; }
    if (!error) {
        r->submitted = 1;
        a51_ufs_mark(io, r, A51_UFS_SUBMITTED);
        io->write(io->context, 0, A51_UFS_DOORBELL, 1);
        io->barrier(io->context);
        error = a51_ufs_wait(io, A51_UFS_DOORBELL, 1, 0, 250000);
        if (error) {
            /* BROKEN_REQ_LIST_CLR: selected bit, never its complement and
             * never a mask of inherited requests. No DMA buffer access here.
             */
            io->write(io->context, 0, A51_UFS_CLEAR, 1);
            io->barrier(io->context);
            if (a51_ufs_wait(io, A51_UFS_DOORBELL, 1, 0, 25000)) {
                r->final_doorbell = io->read(io->context, 0, A51_UFS_DOORBELL);
                return a51_ufs_quarantine(io, m, r, A51_UFS_TIMEOUT);
            }
        } else {
            r->completed = 1;
            a51_ufs_mark(io, r, A51_UFS_COMPLETED);
        }
    }
    /* Stop, prove quiescence and restore the original configuration before
     * touching DMA results. A cleared request is still a failed read.
     */
    r->final_is = io->read(io->context, 0, A51_UFS_IS);
    io->barrier(io->context);
    if (a51_ufs_restore(io, m, r)) { return r->rc; }
    if (error) { return r->rc = error; }
    io->invalidate(io->context, m->list, 1024);
    io->invalidate(io->context, m->command, 4096);
    io->invalidate(io->context, m->data, A51_UFS_DMA_BYTES);
    io->barrier(io->context);
    r->ocs = u->ocs & 15u;
    r->transaction = c->response[0]; r->flags = c->response[1];
    r->response = c->response[6]; r->status = c->response[7];
    r->residual = a51_ufs_be32(c->response + 12);
    r->sense_length = ((unsigned int)c->response[32] << 8) | c->response[33];
    if ((r->ocs != 0 && !(r->ocs == 7 && *(const unsigned int *)m->data == 0x52444e41)) ||
        (r->final_is & A51_UFS_ERROR_MASK)) {
        return r->rc = A51_UFS_IO;
    }
    if (r->transaction != 0x21 || c->response[2] != 0 || c->response[3] != 0 ||
        r->response || r->status || r->residual || (r->flags & 0x60) ||
        c->response[8] || c->response[10] || c->response[11] || r->sense_length) {
        if (!(r->ocs == 7 && *(const unsigned int *)m->data == 0x52444e41)) {
            return r->rc = A51_UFS_PROTOCOL;
        }
    }
    a51_ufs_mark(io, r, A51_UFS_VALIDATED);
    return r->rc = 0;
}
#endif
