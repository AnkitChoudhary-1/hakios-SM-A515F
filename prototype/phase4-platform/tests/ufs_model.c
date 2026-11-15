/* SPDX-License-Identifier: MIT */
/* Execute the actual portable core against an independently checked HCI/DMA model. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "a51_ufs_readonly.h"

static unsigned checks, cases;
#define CHECK(x) do { checks++; if (!(x)) { fprintf(stderr, "line %u: %s\n", __LINE__, #x); exit(1); } } while (0)
static _Alignas(4096) struct a51_ufs_utrd list[32];
static _Alignas(4096) struct a51_ufs_command command_buffer;
static _Alignas(4096) unsigned char data[65536];
enum fault { NONE, NEVER_COMPLETE, CLEAR_FAIL, STOP_FAIL, RESTORE_STOP_FAIL,
    RESTORE_POINTER_FAIL, START_FAIL, ADOPT_POINTER_FAIL, FOREIGN_TASK,
    OCS_BAD, TRANSACTION_BAD, LUN_BAD, TAG_BAD, STATUS_BAD, RESPONSE_BAD,
    RESIDUAL_BAD, FLAGS_BAD, EHS_BAD, SEGMENT_BAD, SENSE_BAD, HCI_BAD,
    RESTORE_START_FAIL };
struct model {
    unsigned standard[128], vendor[128], reads, writes, translations, cleans, invalidates;
    unsigned barriers, polls, submitted, clear_mask, phases, fault, phys_fault;
    unsigned restoring, stopped, last_write_reg;
    unsigned long long us;
};

static void dma_complete(struct model *m)
{
    struct a51_ufs_utrd *u = list;
    const unsigned char *q = command_buffer.request;
    /* Byte units, storage/read/interrupt bits, fixed LUN/tag/CDB and a single bypass FMP entry. */
    CHECK(u->dw0 == 0x15000000u && !u->dw1 && !u->dw3);
    CHECK(u->cmd_lo == 0x84002000 && !u->cmd_hi);
    CHECK(u->rsp_off == 1024 && u->rsp_len == 1024 && u->prdt_off == 2048 && u->prdt_len == 128);
    CHECK(q[0] == 1 && q[1] == 0x40 && !q[2] && !q[3] && q[16] == 0x28);
    unsigned blocks = ((unsigned)q[23] << 8) | q[24];
    unsigned lba = a51_ufs_be32(q + 18), bytes = a51_ufs_be32(q + 12);
    CHECK(blocks > 0 && blocks <= 16 && bytes == blocks * 4096);
    CHECK(lba >= 27792 && lba + blocks <= 42896);
    CHECK(command_buffer.prdt[0].words[0] == 0x84010000 && !command_buffer.prdt[0].words[1]);
    CHECK(!command_buffer.prdt[0].words[2] && command_buffer.prdt[0].words[3] == bytes - 1);
    for (unsigned i = 4; i < 32; i++) CHECK(!command_buffer.prdt[0].words[i]);
    for (unsigned i = 1; i < 32; i++) {
        const unsigned char *p = (const unsigned char *)&list[i];
        for (unsigned j = 0; j < 32; j++) CHECK(!p[j]);
    }
    CHECK(m->cleans == 3 && m->barriers >= 4);
    for (unsigned i = 0; i < bytes; i++) data[i] = (unsigned char)((i * 37u + lba) & 255u);
    list[0].ocs = m->fault == OCS_BAD ? 7 : 0;
    unsigned char *p = command_buffer.response;
    p[0] = m->fault == TRANSACTION_BAD ? 0x3f : 0x21;
    if (m->fault == LUN_BAD) p[2] = 1;
    if (m->fault == TAG_BAD) p[3] = 1;
    if (m->fault == STATUS_BAD) p[7] = 2;
    if (m->fault == RESPONSE_BAD) p[6] = 1;
    if (m->fault == RESIDUAL_BAD) a51_ufs_put_be32(p + 12, 4096);
    if (m->fault == FLAGS_BAD) p[1] = 0x20;
    if (m->fault == EHS_BAD) p[8] = 1;
    if (m->fault == SEGMENT_BAD) p[11] = 18;
    if (m->fault == SENSE_BAD) p[33] = 18;
    m->standard[A51_UFS_IS / 4] = m->fault == HCI_BAD ? 0x10000 : 1;
    m->standard[A51_UFS_DOORBELL / 4] = 0;
    if (m->fault == FOREIGN_TASK) m->standard[A51_UFS_TASK_DOORBELL / 4] = 2;
}
static unsigned rd(void *context, unsigned vendor, unsigned offset)
{
    struct model *m = context; m->reads++;
    CHECK(vendor <= 1 && !(offset & 3) && offset < 512);
    if (!vendor && offset == A51_UFS_DOORBELL && m->submitted &&
        m->standard[offset / 4] && ++m->polls == 3 &&
        m->fault != NEVER_COMPLETE && m->fault != CLEAR_FAIL) dma_complete(m);
    return (vendor ? m->vendor : m->standard)[offset / 4];
}
static void wr(void *context, unsigned vendor, unsigned offset, unsigned value)
{
    struct model *m = context; m->writes++; m->last_write_reg = offset;
    CHECK(vendor <= 1 && !(offset & 3) && offset < 512);
    /* The core may change only the owned slot/list/run state and its nexus bit. */
    CHECK(vendor ? offset == A51_UFS_NEXUS :
        (offset == A51_UFS_RUN || offset == A51_UFS_LIST_LO || offset == A51_UFS_LIST_HI ||
         offset == A51_UFS_DOORBELL || offset == A51_UFS_CLEAR));
    if (!vendor && offset == A51_UFS_RUN && value == 0) {
        if (m->submitted || m->stopped) m->restoring = 1;
        if (m->fault == STOP_FAIL || (m->restoring && m->fault == RESTORE_STOP_FAIL)) return;
        m->stopped++;
    }
    if (!vendor && offset == A51_UFS_RUN && value == 1 && m->fault == START_FAIL && !m->restoring) return;
    if (!vendor && offset == A51_UFS_RUN && value == 1 && m->fault == RESTORE_START_FAIL && m->restoring) return;
    if (!vendor && offset == A51_UFS_LIST_LO &&
        ((m->fault == ADOPT_POINTER_FAIL && value == 0x84000000) ||
         (m->fault == RESTORE_POINTER_FAIL && value == 0x8f000000))) return;
    if (!vendor && offset == A51_UFS_DOORBELL) {
        CHECK(value == 1 && m->standard[A51_UFS_RUN / 4] == 1);
        CHECK(m->standard[A51_UFS_LIST_LO / 4] == 0x84000000 && !m->standard[A51_UFS_LIST_HI / 4]);
        CHECK(m->vendor[A51_UFS_NEXUS / 4] == 0xaaaaaaaa + 1);
        m->submitted++;
    }
    if (!vendor && offset == A51_UFS_CLEAR) {
        CHECK(value == 1); m->clear_mask = value;
        if (m->fault != CLEAR_FAIL) m->standard[A51_UFS_DOORBELL / 4] &= ~value;
        return;
    }
    (vendor ? m->vendor : m->standard)[offset / 4] = value;
}
static unsigned long long physical(void *context, const void *pointer)
{
    struct model *m = context; m->translations++;
    uintptr_t v = (uintptr_t)pointer;
    const void *bases[3] = {list, &command_buffer, data};
    const unsigned sizes[3] = {1024, 4096, 65536};
    const unsigned long long pas[3] = {0x84000000, 0x84002000, 0x84010000};
    for (unsigned i = 0; i < 3; i++) {
        uintptr_t base = (uintptr_t)bases[i];
        if (v < base || v - base >= sizes[i]) continue;
        unsigned long long pa = pas[i] + (v - base);
        if (i == 2) {
            if (m->phys_fault == 1) pa += 0x100000000ULL;
            if (m->phys_fault == 2 && v - base == 4096) pa += 4096;
            if (m->phys_fault == 3 && v - base == 65535) pa++;
            if (m->phys_fault == 4) pa = 0x84002000 + (v - base);
            if (m->phys_fault == 5) pa++;
            if (m->phys_fault == 6) pa = 0xfffff000ULL + (v - base);
            if (m->phys_fault == 7) pa = 0;
        }
        return pa;
    }
    return 0;
}
static void clean(void *context, const void *p, unsigned bytes)
{
    struct model *m = context; CHECK(!m->submitted);
    CHECK((p == list && bytes == 1024) || (p == &command_buffer && bytes == 4096) || (p == data && bytes == 65536));
    m->cleans++;
}
static void invalidate(void *context, const void *p, unsigned bytes)
{
    struct model *m = context; (void)p; (void)bytes;
    CHECK(m->restoring && !m->standard[A51_UFS_DOORBELL / 4]);
    CHECK(m->standard[A51_UFS_LIST_LO / 4] == 0x8f000000 && m->vendor[A51_UFS_NEXUS / 4] == 0xaaaaaaaa);
    m->invalidates++;
}
static void barrier(void *p) { ((struct model *)p)->barriers++; }
static unsigned long long now_us(void *p) { return ((struct model *)p)->us; }
static void relax(void *p) { ((struct model *)p)->us += 1000; }
static void trace(void *p, unsigned stage) { ((struct model *)p)->phases |= 1u << stage; }
static void init(struct model *m, struct a51_ufs_io *io, struct a51_ufs_memory *memory)
{
    memset(m, 0, sizeof(*m)); memset(list, 0xa5, sizeof(list));
    memset(&command_buffer, 0xa5, sizeof(command_buffer)); memset(data, 0xa5, sizeof(data));
    m->standard[A51_UFS_CAP / 4] = 31; m->standard[A51_UFS_VER / 4] = 0x210;
    m->standard[A51_UFS_HCS / 4] = 3; m->standard[A51_UFS_HCE / 4] = 1;
    m->standard[A51_UFS_LIST_LO / 4] = 0x8f000000; m->standard[A51_UFS_RUN / 4] = 1;
    m->vendor[A51_UFS_TX_PRDT / 4] = 0x8000000c; m->vendor[A51_UFS_RX_PRDT / 4] = 12;
    m->vendor[A51_UFS_REORDER / 4] = 10; m->vendor[A51_UFS_NEXUS / 4] = 0xaaaaaaaa;
    *io = (struct a51_ufs_io){m, rd, wr, physical, clean, invalidate, barrier, now_us, relax, trace};
    *memory = (struct a51_ufs_memory){list, &command_buffer, data, 1, 0};
    cases++;
}
int main(void)
{
    struct model m; struct a51_ufs_io io; struct a51_ufs_memory memory; struct a51_ufs_report report;
    for (unsigned op = 1; op < 256; op++) {
        CHECK(a51_ufs_submit((void *)(uintptr_t)1, (void *)(uintptr_t)1, op, 0, 0, (void *)(uintptr_t)1) == -30);
    }
    CHECK(a51_ufs_submit(NULL, NULL, A51_UFS_READ, 27792, 1, NULL) == -22);
    for (unsigned i = 0; i < 5; i++) {
        init(&m, &io, &memory);
        unsigned lba = i == 0 ? 27791 : i == 1 ? 42896 : 27792;
        unsigned blocks = i == 2 ? 0 : i == 3 ? 17 : i == 4 ? 0xffffffffu : 1;
        CHECK(a51_ufs_submit(&io, &memory, 0, lba, blocks, &report) == -22);
        CHECK(!m.reads && !m.writes && !m.cleans && !m.translations);
    }
    for (unsigned i = 1; i <= 7; i++) {
        init(&m, &io, &memory); m.phys_fault = i;
        CHECK(a51_ufs_submit(&io, &memory, 0, 27792, 1, &report) == -22);
        CHECK(!m.reads && !m.writes && !m.cleans && data[0] == 0xa5);
    }
    init(&m, &io, &memory); memory.kernel_owned = 0;
    CHECK(a51_ufs_submit(&io, &memory, 0, 27792, 1, &report) == -22 && !m.translations);
    init(&m, &io, &memory); memory.data++;
    CHECK(a51_ufs_submit(&io, &memory, 0, 27792, 1, &report) == -22 && !m.writes);
    const unsigned regs[] = {A51_UFS_DOORBELL, A51_UFS_TASK_DOORBELL, A51_UFS_HCE, A51_UFS_HCS, A51_UFS_IS};
    for (unsigned i = 0; i < 5; i++) {
        init(&m, &io, &memory);
        /* Matching ufshci.h: bit 11 is fatal; bit 10 is benign UIC completion. */
        m.standard[regs[i] / 4] = i < 2 ? 0x80000000 : i == 4 ? 0x800 : 0;
        CHECK(a51_ufs_submit(&io, &memory, 0, 27792, 1, &report) == (i < 2 ? -16 : -5));
        CHECK(!m.writes && !m.cleans && data[0] == 0xa5);
    }
    const unsigned vendor_regs[] = {A51_UFS_TX_PRDT, A51_UFS_RX_PRDT, A51_UFS_REORDER};
    for (unsigned i = 0; i < 3; i++) {
        init(&m, &io, &memory); m.vendor[vendor_regs[i] / 4] = 0;
        CHECK(a51_ufs_submit(&io, &memory, 0, 27792, 1, &report) == -95);
        CHECK(!m.writes && !m.cleans);
    }
    for (unsigned blocks = 1; blocks <= 16; blocks += 15) {
        init(&m, &io, &memory);
        m.standard[A51_UFS_IS / 4] = 0x400;
        CHECK(a51_ufs_submit(&io, &memory, 0, 27792, blocks, &report) == 0);
        CHECK(report.submitted == 1 && report.completed == 1 && report.restored == 1 && !report.quarantined);
        CHECK(report.bytes == blocks * 4096 && report.ocs == 0 && m.invalidates == 3);
        for (unsigned i = 0; i < report.bytes; i++) CHECK(data[i] == (unsigned char)((i * 37u + 27792) & 255));
        CHECK(m.standard[A51_UFS_RUN / 4] == 1 && m.standard[A51_UFS_LIST_LO / 4] == 0x8f000000);
        CHECK(m.vendor[A51_UFS_NEXUS / 4] == 0xaaaaaaaa && report.stages == m.phases);
    }
    for (unsigned f = OCS_BAD; f <= HCI_BAD; f++) {
        init(&m, &io, &memory); m.fault = f;
        CHECK(a51_ufs_submit(&io, &memory, 0, 27792, 1, &report) == (f == OCS_BAD || f == HCI_BAD ? -5 : -71));
        CHECK(report.completed && report.restored && !report.quarantined);
        CHECK(!(report.stages & (1u << A51_UFS_VALIDATED)));
    }
    init(&m, &io, &memory); m.fault = NEVER_COMPLETE;
    CHECK(a51_ufs_submit(&io, &memory, 0, 27792, 1, &report) == -110);
    CHECK(m.clear_mask == 1 && report.restored && !report.completed && !m.invalidates);
    const unsigned unsafe[] = {CLEAR_FAIL, STOP_FAIL, RESTORE_STOP_FAIL, RESTORE_POINTER_FAIL,
        FOREIGN_TASK, RESTORE_START_FAIL};
    for (unsigned i = 0; i < sizeof(unsafe) / sizeof(unsafe[0]); i++) {
        init(&m, &io, &memory); m.fault = unsafe[i];
        CHECK(a51_ufs_submit(&io, &memory, 0, 27792, 1, &report) < 0);
        CHECK(memory.quarantined && report.quarantined && !report.restored && !m.invalidates);
        unsigned reads = m.reads, writes = m.writes, translations = m.translations;
        CHECK(a51_ufs_submit(&io, &memory, 0, 27792, 16, &report) == -16);
        CHECK(m.reads == reads && m.writes == writes && m.translations == translations);
    }
    const unsigned clean_failure[] = {START_FAIL, ADOPT_POINTER_FAIL};
    for (unsigned i = 0; i < 2; i++) {
        init(&m, &io, &memory); m.fault = clean_failure[i];
        CHECK(a51_ufs_submit(&io, &memory, 0, 27792, 1, &report) < 0);
        CHECK(!m.submitted && report.restored && !memory.quarantined && !m.invalidates);
    }
    printf("{\"suite\":\"ufs\",\"cases\":%u,\"checks\":%u,\"passed\":true}\n", cases, checks);
    return 0;
}
