/* SPDX-License-Identifier: MIT */
/*
 * MelfasTouchDriver.cpp - Melfas MMS449 I2C Touchscreen Controller Driver
 *
 * Implements Melfas multi-touch report packet decoding and I2C polling.
 */

#include "MelfasTouchDriver.h"
#include "common/freestanding.h"

/* Exynos High-Speed I2C register offsets */
#define HSI2C_CTL                      0x0000
#define HSI2C_FIFO_CTL                 0x0004
#define HSI2C_TRAIL_CTL                0x0008
#define HSI2C_INT_EN                   0x0020
#define HSI2C_INT_STAT                 0x0024
#define HSI2C_FIFO_STAT                0x0030
#define HSI2C_TXDATA                   0x0034
#define HSI2C_RXDATA                   0x0038
#define HSI2C_CONF                     0x0040
#define HSI2C_AUTO_CONF                0x0044
#define HSI2C_ADDR                     0x0084

int MelfasTouch_Init(MelfasTouchDevice *dev, uintptr_t i2c_vaddr)
{
    if (!dev) return -1;

    memset(dev, 0, sizeof(*dev));
    dev->i2c_mmio_base = i2c_vaddr;
    dev->slave_addr = MELFAS_MMS449_I2C_ADDR;
    dev->active_touches = 0;
    dev->event_count = 0;

    return 0;
}

int MelfasTouch_DecodePacket(MelfasTouchDevice *dev, const uint8_t *raw_buf, uint32_t len)
{
    if (!dev || !raw_buf || len < 6) {
        return -1;
    }

    /*
     * Melfas MMS449 packet format:
     * Byte 0: Header / Event Status:
     *   Bits [3:0]: Finger ID (0..9)
     *   Bits [5:4]: Event Action (0=none, 1=down, 2=move, 3=up)
     * Byte 1: X[7:0]
     * Byte 2: Y[7:0]
     * Byte 3: {Y[11:8], X[11:8]}
     * Byte 4: Pressure / Touch size
     * Byte 5: Checksum / Flags
     */
    uint8_t hdr = raw_buf[0];
    uint8_t finger_id = hdr & 0x0FU;
    uint8_t action = (hdr >> 4) & 0x03U;

    if (finger_id >= MELFAS_MAX_FINGERS) {
        return -1;
    }

    uint16_t x = (uint16_t)raw_buf[1] | (((uint16_t)(raw_buf[3] & 0x0FU)) << 8);
    uint16_t y = (uint16_t)raw_buf[2] | (((uint16_t)(raw_buf[3] >> 4)) << 8);
    uint8_t pressure = raw_buf[4];

    /* Bound coordinate limits to physical FHD+ panel size (1080x2400) */
    if (x > MELFAS_TOUCH_MAX_X) x = MELFAS_TOUCH_MAX_X;
    if (y > MELFAS_TOUCH_MAX_Y) y = MELFAS_TOUCH_MAX_Y;

    MelfasTouchPoint *pt = &dev->points[finger_id];
    pt->finger_id = finger_id;
    pt->action = action;
    pt->x = x;
    pt->y = y;
    pt->pressure = pressure;

    if (action == MELFAS_EVENT_TOUCH_DOWN || action == MELFAS_EVENT_TOUCH_MOVE) {
        pt->active = true;
        dev->active_touches |= (1U << finger_id);
    } else if (action == MELFAS_EVENT_TOUCH_UP) {
        pt->active = false;
        dev->active_touches &= ~(1U << finger_id);
    }

    dev->event_count++;
    return 0;
}

int MelfasTouch_Poll(MelfasTouchDevice *dev)
{
    if (!dev || !dev->i2c_mmio_base) {
        return 0;
    }

    /* Check RX FIFO status */
    volatile uint32_t *fifo_stat = (volatile uint32_t *)(dev->i2c_mmio_base + HSI2C_FIFO_STAT);
    uint32_t rx_count = (*fifo_stat >> 16) & 0x7FU;

    if (rx_count >= 6) {
        uint8_t packet[6];
        volatile uint32_t *rx_data = (volatile uint32_t *)(dev->i2c_mmio_base + HSI2C_RXDATA);
        for (int i = 0; i < 6; i++) {
            packet[i] = (uint8_t)(*rx_data & 0xFF);
        }
        return MelfasTouch_DecodePacket(dev, packet, 6);
    }

    return 0;
}

void MelfasTouch_GetPrimaryTouch(const MelfasTouchDevice *dev, uint16_t *out_x, uint16_t *out_y, bool *out_down)
{
    if (!dev) {
        if (out_down) *out_down = false;
        return;
    }

    /* Return finger 0 state by default */
    const MelfasTouchPoint *p0 = &dev->points[0];
    if (out_x) *out_x = p0->x;
    if (out_y) *out_y = p0->y;
    if (out_down) *out_down = p0->active;
}
