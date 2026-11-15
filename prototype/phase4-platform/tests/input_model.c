/* SPDX-License-Identifier: MIT */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "a51_input.h"
static unsigned checks, cases;
#define CHECK(x) do { checks++; if (!(x)) { fprintf(stderr,"line %u: %s\n",__LINE__,#x); exit(1); } } while (0)

enum fault { OK, NACK, ARBITRATION, TIMEOUT, STOP_TIMEOUT, RESTORE_FAIL };
struct bus {
    unsigned con, stat, data, initial_con, initial_stat, writes, reads, steps, fault;
    unsigned active, prefix, repeated, rx, index, size, stopped, final_nack;
    unsigned stop_order, setup, started;
    unsigned long long us;
};
static void step(struct bus *b)
{
    b->steps++;
    if (b->fault == TIMEOUT) return;
    b->con |= A51_I2C_PENDING;
    if (b->fault == ARBITRATION) b->stat |= A51_I2C_ARB;
    if (b->fault == NACK) b->stat |= A51_I2C_LASTBIT;
    if (b->rx) { b->data = (b->index * 17u + 10u) & 255u; b->index++; }
}
static unsigned rd(void *p, unsigned reg)
{
    struct bus *b = p; b->reads++;
    CHECK(reg == 0 || reg == 4 || reg == 12);
    return reg == 0 ? b->con : reg == 4 ? b->stat : b->data;
}
static void wr(void *p, unsigned reg, unsigned value)
{
    struct bus *b = p; b->writes++;
    CHECK(reg == 0 || reg == 4 || reg == 12);
    if (reg == A51_I2C_DATA) {
        if (!b->active) { CHECK(value == 0x90); b->setup = 1; }
        else if (b->repeated && !b->rx) { CHECK(value == 0x91); b->setup = 2; }
        else { CHECK(b->prefix < 2 && value == (b->prefix ? 4u : 2u)); b->prefix++; }
        b->data = value; return;
    }
    if (reg == A51_I2C_STAT) {
        if (b->active && (value & 0xc0) == 0x80 && !(value & A51_I2C_BUSY)) {
            CHECK(b->prefix == 2 && (b->con & A51_I2C_PENDING)); b->repeated = 1;
        }
        if ((value & A51_I2C_BUSY) && !b->active) {
            CHECK(b->setup == 1 && (b->con & A51_I2C_ACK)); b->active = 1; b->started++; b->stat = value; step(b); return;
        }
        if (b->repeated && (value & A51_I2C_BUSY) && !b->rx) {
            CHECK(b->setup == 2 && (b->con & A51_I2C_PENDING)); b->started++; b->stat = value; return;
        }
        if (b->active && !(value & A51_I2C_BUSY) && !b->repeated) { b->stop_order = 1; }
        if (b->active && b->repeated && b->rx && !(value & A51_I2C_BUSY)) { b->stop_order = 1; }
        if (b->stopped && b->fault == RESTORE_FAIL) return;
        b->stat = value;
        if (b->stop_order && b->fault == STOP_TIMEOUT) b->stat |= A51_I2C_BUSY;
        return;
    }
    unsigned pending = b->con & A51_I2C_PENDING;
    b->con = value;
    if (b->stop_order) {
        CHECK(!(value & A51_I2C_PENDING)); b->active = 0; b->stopped = 1;
        if (b->fault != STOP_TIMEOUT) b->stat &= ~A51_I2C_BUSY;
        return;
    }
    if (b->active && pending && !(value & A51_I2C_PENDING)) {
        if (b->repeated && !b->rx) { b->rx = 1; /* address ACK, not receive data */ step(b); b->index = 0; }
        else if (b->rx) {
            if (b->index + 1 == b->size) { CHECK(!(value & A51_I2C_ACK)); b->final_nack = 1; }
            else CHECK(value & A51_I2C_ACK);
            step(b);
        } else step(b);
    }
}
static unsigned long long now(void *p) { return ((struct bus *)p)->us; }
static void delay(void *p, unsigned us) { ((struct bus *)p)->us += us; }
static void barrier(void *p) { (void)p; }
static void init(struct bus *b, struct a51_i2c_io *io, unsigned size)
{
    *b = (struct bus){0}; b->con = b->initial_con = 0x47; b->stat = b->initial_stat = 0x10; b->size = size;
    *io = (struct a51_i2c_io){b, rd, wr, now, delay, barrier}; cases++;
}
static void packet(unsigned char *p, unsigned id, unsigned state, unsigned x, unsigned y)
{
    memset(p, 0, 16); p[0] = (unsigned char)((state << 6) | (id << 2) | 1);
    p[1] = (unsigned char)(x >> 4); p[2] = (unsigned char)(y >> 4);
    p[3] = (unsigned char)(((x & 15) << 4) | (y & 15));
}
int main(void)
{
    struct a51_input_event events[8], before[8]; unsigned char p[128]; struct a51_touch_state touch = {0};
    for (unsigned id = 1; id <= 10; id++) for (unsigned state = 1; state <= 3; state++) {
        cases++; packet(p, id, state, state == 1 ? 0 : 4095, state == 1 ? 0 : 4095);
        CHECK(a51_touch_packet(&touch, p, 16, 10, 123, events, 8) == 1);
        CHECK(events[0].slot == id - 1 && events[0].state == state && events[0].counter == 123);
        CHECK(events[0].x == (state == 1 ? 0 : 1079) && events[0].y == (state == 1 ? 0 : 2399));
        CHECK((touch.active & (1u << (id - 1))) == (state == 3 ? 0 : (1u << (id - 1))));
        CHECK(!memcmp(events[0].packet, p, 16));
    }
    for (unsigned raw = 0; raw <= 4095; raw++) {
        packet(p, 1, 2, raw, 4095 - raw);
        CHECK(a51_touch_decode(p, 16, 10, events) == 1);
        CHECK(events[0].raw_x == raw && events[0].raw_y == 4095 - raw);
        CHECK(events[0].x <= 1079 && events[0].y <= 2399);
    }
    memset(events, 0xa5, sizeof(events)); memcpy(before, events, sizeof(events)); touch.active = 0x100;
    packet(p, 1, 1, 123, 456); packet(p + 16, 11, 1, 0, 0);
    CHECK(a51_touch_packet(&touch, p, 32, 10, 456, events, 8) == -71);
    CHECK(touch.active == 0x100 && !memcmp(before, events, sizeof(events)));
    CHECK(a51_touch_packet(&touch, p, 15, 10, 0, events, 8) == -22);
    CHECK(a51_touch_packet(&touch, p, 128, 10, 0, events, 8) == -22);
    CHECK(a51_touch_packet(&touch, p, 32, 10, 0, events, 1) == -22);
    CHECK(a51_touch_packet(&touch, p, 16, 0, 0, events, 8) == -22);
    packet(p, 0, 1, 0, 0); CHECK(a51_touch_decode(p, 16, 10, events) == -71);
    packet(p, 1, 0, 0, 0); CHECK(a51_touch_decode(p, 16, 10, events) == 0);
    struct a51_key_state keys = {0};
    CHECK(!a51_keys_sample(&keys, 0xff, 0, 0, events));
    CHECK(!a51_keys_sample(&keys, 0xdf, 1000, 1, events));
    CHECK(!a51_keys_sample(&keys, 0xff, 2000, 2, events));
    CHECK(!a51_keys_sample(&keys, 0xdf, 3000, 3, events));
    CHECK(!a51_keys_sample(&keys, 0xdf, 22999, 4, events));
    CHECK(a51_keys_sample(&keys, 0xdf, 23000, 5, events) == 1);
    CHECK(events[0].code == 115 && events[0].state == 1 && events[0].counter == 5);
    CHECK(!a51_keys_sample(&keys, 0xff, 24000, 6, events));
    CHECK(a51_keys_sample(&keys, 0xff, 44000, 7, events) == 1 && events[0].state == 0);
    CHECK(!a51_keys_sample(&keys, 0x1f, 45000, 8, events));
    CHECK(a51_keys_sample(&keys, 0x1f, 65000, 9, events) == 3);
    CHECK(events[0].code == 115 && events[1].code == 114 && events[2].code == 116);
    /* A regressed clock must not prematurely debounce a new transition. */
    CHECK(!a51_keys_sample(&keys, 0xff, 66000, 10, events));
    CHECK(!a51_keys_sample(&keys, 0xff, 100, 11, events));
    CHECK(!a51_keys_sample(&keys, 0xff, 20099, 12, events));
    CHECK(a51_keys_sample(&keys, 0xff, 20100, 13, events) == 3);
    CHECK(events[0].state == 0 && events[1].state == 0 && events[2].state == 0);
    struct bus b; struct a51_i2c_io io; struct a51_i2c_report report; unsigned quarantine = 0;
    unsigned char out[128];
    for (unsigned size = 1; size <= 127; size += size == 1 ? 3 : 123) {
        init(&b, &io, size); quarantine = 0;
        CHECK(a51_i2c_mss_read(&io, &quarantine, 2, 4, out, size, &report) == 0);
        CHECK(report.received == size && report.stopped && report.restored && !quarantine);
        CHECK(b.started == 2 && b.prefix == 2 && b.final_nack);
        CHECK(b.con == b.initial_con && b.stat == b.initial_stat);
        for (unsigned i = 0; i < size; i++) CHECK(out[i] == (unsigned char)((i * 17u + 10u) & 255));
    }
    for (unsigned f = NACK; f <= TIMEOUT; f++) {
        init(&b, &io, 4); b.fault = f; quarantine = 0;
        memset(out, 0xa5, sizeof(out));
        CHECK(a51_i2c_mss_read(&io, &quarantine, 2, 4, out, 4, &report) == (f == NACK ? -6 : f == ARBITRATION ? -11 : -110));
        CHECK(!report.received && report.stopped && report.restored && !quarantine);
        CHECK(out[0] == 0xa5 && out[3] == 0xa5);
        CHECK(b.con == b.initial_con && b.stat == b.initial_stat);
    }
    for (unsigned f = STOP_TIMEOUT; f <= RESTORE_FAIL; f++) {
        init(&b, &io, 4); b.fault = f; quarantine = 0;
        memset(out, 0xa5, sizeof(out));
        CHECK(a51_i2c_mss_read(&io, &quarantine, 2, 4, out, 4, &report) < 0);
        CHECK(quarantine == 1);
        CHECK(!report.restored && out[0] == 0xa5 && out[3] == 0xa5);
        unsigned writes = b.writes, reads = b.reads;
        CHECK(a51_i2c_mss_read(&io, &quarantine, 2, 4, out, 4, &report) == -16);
        CHECK(b.writes == writes && b.reads == reads);
    }
    for (unsigned f = 0; f < 3; f++) {
        init(&b, &io, 4); quarantine = 0;
        if (f == 0) b.stat |= A51_I2C_BUSY;
        if (f == 1) b.con |= A51_I2C_PENDING;
        if (f == 2) b.stat |= A51_I2C_ARB;
        CHECK(a51_i2c_mss_read(&io, &quarantine, 2, 4, out, 4, &report) == -16);
        CHECK(!b.writes);
    }
    init(&b, &io, 4);
    CHECK(a51_i2c_mss_read(&io, &quarantine, 3, 4, out, 4, &report) == -22 && !b.reads);
    CHECK(a51_i2c_mss_read(&io, &quarantine, 2, 5, out, 4, &report) == -22 && !b.writes);
    printf("{\"suite\":\"input\",\"cases\":%u,\"checks\":%u,\"passed\":true}\n", cases, checks);
    return 0;
}
