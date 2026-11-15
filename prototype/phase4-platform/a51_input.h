/* SPDX-License-Identifier: MIT */
/* Matching MSS100 format-10 decoder, GPIO transitions and bounded I2C read.
 * Host fixtures establish the protocol only; hardware events remain distinct.
 */
#ifndef A51_INPUT_H
#define A51_INPUT_H
#define A51_INPUT_SLOTS 10u
#define A51_INPUT_EVENT_BYTES 16u
#define A51_INPUT_MAX_EVENTS 16u
#define A51_INPUT_TOUCH 1u
#define A51_INPUT_KEY 2u
#define A51_INPUT_PRESS 1u
#define A51_INPUT_MOVE 2u
#define A51_INPUT_RELEASE 3u
#define A51_INPUT_INVAL (-22)
#define A51_INPUT_PROTOCOL (-71)
#define A51_INPUT_BUSY (-16)
#define A51_INPUT_TIMEOUT (-110)
#define A51_INPUT_NACK (-6)
#define A51_INPUT_ARBITRATION (-11)
#define A51_INPUT_IO (-5)

struct a51_input_event {
    unsigned int kind, code, state, slot, raw_x, raw_y, x, y;
    unsigned long long counter;
    unsigned char packet[A51_INPUT_EVENT_BYTES];
};
_Static_assert(sizeof(struct a51_input_event) == 56, "input event ABI");
struct a51_touch_state { unsigned int active; };
struct a51_key_state {
    unsigned int initialized, stable, candidate;
    unsigned long long changed_us, observed_us;
};

static inline int
a51_touch_decode(const unsigned char *p, unsigned int bytes, unsigned int format,
    struct a51_input_event *e)
{
    if (!p || !e || bytes != 16 || format != 10) { return A51_INPUT_INVAL; }
    unsigned int state = p[0] >> 6, type = p[0] & 3;
    /* Format 10 state 0 means no event; the matching Android driver ignores it. */
    if (!state || type == 0) { return 0; }
    unsigned int id = (p[0] >> 2) & 15;
    if (type != 1 || !id || id > A51_INPUT_SLOTS) { return A51_INPUT_PROTOCOL; }
    e->kind = A51_INPUT_TOUCH; e->code = 0; e->state = state; e->slot = id - 1;
    e->raw_x = ((unsigned int)p[1] << 4) | (p[3] >> 4);
    e->raw_y = ((unsigned int)p[2] << 4) | (p[3] & 15);
    e->x = (e->raw_x * 1079u + 2047u) / 4095u;
    e->y = (e->raw_y * 2399u + 2047u) / 4095u;
    for (unsigned int i = 0; i < 16; i++) { e->packet[i] = p[i]; }
    return 1;
}

/* Reject an entire malformed packet before changing the touch state. */
static inline int
a51_touch_packet(struct a51_touch_state *s, const unsigned char *p, unsigned int bytes,
    unsigned int format, unsigned long long counter, struct a51_input_event *out,
    unsigned int capacity)
{
    if (!s || !p || !out || !bytes || bytes > 127 || bytes % 16 || format != 10 || capacity < bytes / 16) {
        return A51_INPUT_INVAL;
    }
    struct a51_input_event scratch = {0};
    for (unsigned int i = 0; i < bytes; i += 16) {
        int rc = a51_touch_decode(p + i, 16, format, &scratch);
        if (rc < 0) { return rc; }
    }
    unsigned int count = 0;
    for (unsigned int i = 0; i < bytes; i += 16) {
        int rc = a51_touch_decode(p + i, 16, format, &out[count]);
        if (!rc) { continue; }
        struct a51_input_event *e = &out[count++];
        e->counter = counter;
        if (e->state == A51_INPUT_RELEASE) { s->active &= ~(1u << e->slot); }
        else { s->active |= 1u << e->slot; }
    }
    return (int)count;
}

static inline unsigned int
a51_keys_sample(struct a51_key_state *s, unsigned int gpa1, unsigned long long us,
    unsigned long long counter, struct a51_input_event *out)
{
    if (!s || !out) { return 0; }
    unsigned int pressed = (~gpa1 >> 5) & 7u; /* active low: volume up/down, power */
    if (!s->initialized) {
        s->initialized = 1; s->stable = s->candidate = pressed;
        s->changed_us = s->observed_us = us;
        return 0; /* a snapshot is not a transition */
    }
    if (us < s->observed_us) {
        /* Restart the candidate's interval after any clock regression. */
        s->candidate = pressed; s->changed_us = s->observed_us = us;
        return 0;
    }
    s->observed_us = us;
    if (pressed != s->candidate) { s->candidate = pressed; s->changed_us = us; return 0; }
    if (us - s->changed_us < 20000) { return 0; }
    static const unsigned int codes[3] = {115, 114, 116};
    unsigned int changed = s->stable ^ pressed, count = 0;
    for (unsigned int i = 0; i < 3; i++) {
        if (!(changed & (1u << i))) { continue; }
        struct a51_input_event *e = &out[count++];
        e->kind = A51_INPUT_KEY; e->code = codes[i];
        e->state = (pressed >> i) & 1u; e->slot = 0;
        e->raw_x = e->raw_y = e->x = e->y = 0; e->counter = counter;
        for (unsigned int j = 0; j < 16; j++) { e->packet[j] = 0; }
    }
    s->stable = pressed;
    return count;
}

#define A51_I2C_CON 0u
#define A51_I2C_STAT 4u
#define A51_I2C_DATA 12u
#define A51_I2C_ACK 128u
#define A51_I2C_IRQ 32u
#define A51_I2C_PENDING 16u
#define A51_I2C_BUSY 32u
#define A51_I2C_ENABLE 16u
#define A51_I2C_ARB 8u
#define A51_I2C_LASTBIT 1u
struct a51_i2c_io {
    void *context;
    unsigned int (*read)(void *, unsigned int);
    void (*write)(void *, unsigned int, unsigned int);
    unsigned long long (*now_us)(void *);
    void (*delay_us)(void *, unsigned int);
    void (*barrier)(void *);
};
struct a51_i2c_report {
    int rc;
    unsigned int initial_con, initial_stat, final_con, final_stat, received, stopped, restored;
};

static inline int
a51_i2c_wait(const struct a51_i2c_io *io, unsigned int reg, unsigned int mask,
    unsigned int expected, unsigned int us)
{
    unsigned long long start = io->now_us(io->context);
    for (unsigned int polls = 0; polls < 20000; polls++) {
        if (reg == A51_I2C_CON && (io->read(io->context, A51_I2C_STAT) & A51_I2C_ARB)) {
            return A51_INPUT_ARBITRATION;
        }
        if ((io->read(io->context, reg) & mask) == expected) { return 0; }
        if (io->now_us(io->context) - start >= us) { break; }
        io->delay_us(io->context, 5);
    }
    return A51_INPUT_TIMEOUT;
}

static inline int
a51_i2c_ack(const struct a51_i2c_io *io)
{
    int rc = a51_i2c_wait(io, A51_I2C_CON, A51_I2C_PENDING, A51_I2C_PENDING, 5000);
    if (rc) { return rc; }
    return (io->read(io->context, A51_I2C_STAT) & A51_I2C_LASTBIT) ? A51_INPUT_NACK : 0;
}

/* Fixed MSS100 address, a two-byte register selector followed by a bounded
 * read. It cannot write panel settings, flash firmware, or arbitrary slaves.
 * No retry, clock/pin/power reset or inherited-busy cancellation is performed.
 */
static inline int
a51_i2c_mss_read(const struct a51_i2c_io *io, unsigned int *quarantined,
    unsigned char page, unsigned char reg, unsigned char *out, unsigned int bytes,
    struct a51_i2c_report *r)
{
    if (!io || !quarantined || !out || !r || !io->read || !io->write || !io->now_us ||
        !io->delay_us || !io->barrier || !bytes || bytes > 127 || page != 2 ||
        (reg != 4 && reg != 0x10 && reg != 0x11)) { return A51_INPUT_INVAL; }
    *r = (struct a51_i2c_report){0};
    if (*quarantined) { return r->rc = A51_INPUT_BUSY; }
    r->initial_con = io->read(io->context, A51_I2C_CON);
    r->initial_stat = io->read(io->context, A51_I2C_STAT);
    if ((r->initial_stat & (A51_I2C_BUSY | A51_I2C_ARB)) ||
        (r->initial_con & A51_I2C_PENDING)) { return r->rc = A51_INPUT_BUSY; }
    unsigned char received[127];
    unsigned int con = (r->initial_con & ~A51_I2C_PENDING) | A51_I2C_ACK | A51_I2C_IRQ;
    io->write(io->context, A51_I2C_STAT, 0xc0 | A51_I2C_ENABLE);
    io->write(io->context, A51_I2C_CON, con);
    io->write(io->context, A51_I2C_DATA, 0x48u << 1);
    io->delay_us(io->context, 5);
    io->write(io->context, A51_I2C_STAT, 0xc0 | A51_I2C_ENABLE | A51_I2C_BUSY);
    io->barrier(io->context);
    int error = a51_i2c_ack(io);
    unsigned char prefix[2] = {page, reg};
    for (unsigned int i = 0; !error && i < 2; i++) {
        io->write(io->context, A51_I2C_DATA, prefix[i]);
        io->delay_us(io->context, 5);
        io->write(io->context, A51_I2C_CON, con & ~A51_I2C_PENDING);
        io->barrier(io->context);
        error = a51_i2c_ack(io);
    }
    if (!error) {
        /* Keep the preceding pending flag until the repeated START is set. */
        io->write(io->context, A51_I2C_STAT, 0x80 | A51_I2C_ENABLE);
        io->write(io->context, A51_I2C_DATA, (0x48u << 1) | 1u);
        io->delay_us(io->context, 5);
        io->write(io->context, A51_I2C_STAT, 0x80 | A51_I2C_ENABLE | A51_I2C_BUSY);
        io->write(io->context, A51_I2C_CON, con & ~A51_I2C_PENDING);
        io->barrier(io->context);
        error = a51_i2c_ack(io);
    }
    for (unsigned int i = 0; !error && i < bytes; i++) {
        unsigned int next_con = con & ~A51_I2C_PENDING;
        if (i + 1 == bytes) { next_con &= ~A51_I2C_ACK; } /* NACK the final byte */
        io->write(io->context, A51_I2C_CON, next_con);
        io->barrier(io->context);
        error = a51_i2c_wait(io, A51_I2C_CON, A51_I2C_PENDING, A51_I2C_PENDING, 5000);
        if (!error) { received[i] = (unsigned char)io->read(io->context, A51_I2C_DATA); r->received++; }
    }
    /* Matching controller STOP order: STAT.BUSY=0, CON.PENDING=0, wait. */
    unsigned int stat = io->read(io->context, A51_I2C_STAT);
    io->write(io->context, A51_I2C_STAT, stat & ~(A51_I2C_BUSY | A51_I2C_ARB | A51_I2C_LASTBIT));
    io->write(io->context, A51_I2C_CON, con & ~(A51_I2C_PENDING | A51_I2C_IRQ));
    io->barrier(io->context);
    int stop = a51_i2c_wait(io, A51_I2C_STAT, A51_I2C_BUSY, 0, 25000);
    if (stop) { *quarantined = 1; r->rc = stop; }
    else {
        r->stopped = 1;
        io->write(io->context, A51_I2C_STAT, r->initial_stat & (0xc0 | A51_I2C_ENABLE));
        io->write(io->context, A51_I2C_CON, r->initial_con & ~A51_I2C_PENDING);
        io->barrier(io->context);
        r->rc = error;
    }
    r->final_con = io->read(io->context, A51_I2C_CON);
    r->final_stat = io->read(io->context, A51_I2C_STAT);
    if (r->stopped) {
        if (r->final_con != (r->initial_con & ~A51_I2C_PENDING) ||
            (r->final_stat & (0xc0 | A51_I2C_ENABLE | A51_I2C_BUSY | A51_I2C_ARB)) !=
                (r->initial_stat & (0xc0 | A51_I2C_ENABLE))) {
            *quarantined = 1; r->rc = A51_INPUT_IO;
        } else { r->restored = 1; }
    }
    /* Failed transfers never expose partial or unrestored data to the decoder. */
    if (!r->rc && r->restored) {
        for (unsigned int i = 0; i < bytes; i++) { out[i] = received[i]; }
    }
    return r->rc;
}
#endif
