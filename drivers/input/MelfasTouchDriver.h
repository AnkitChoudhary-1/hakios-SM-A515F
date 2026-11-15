/* SPDX-License-Identifier: MIT */
/*
 * MelfasTouchDriver.h - Melfas MMS449 I2C Touchscreen Controller Driver
 *
 * Implements I2C event polling and packet decoding for the Samsung Galaxy A51
 * capacitive multi-touch panel (sec_touchscreen on I2C bus 4, slave 0x48).
 * Converts touch hardware events into normalized coordinates (1080x2400).
 */

#ifndef _MELFAS_TOUCH_DRIVER_H_
#define _MELFAS_TOUCH_DRIVER_H_

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Exynos 9611 I2C-4 Base Physical Address & Touch Slave Address */
#define EXYNOS9611_I2C4_BASE_PA        0x13870000ULL
#define MELFAS_MMS449_I2C_ADDR         0x48U

/* Melfas Panel Resolution */
#define MELFAS_TOUCH_MAX_X             1080U
#define MELFAS_TOUCH_MAX_Y             2400U
#define MELFAS_MAX_FINGERS             10U

/* Melfas Packet Event Types */
#define MELFAS_EVENT_NONE              0x00U
#define MELFAS_EVENT_TOUCH_DOWN        0x01U
#define MELFAS_EVENT_TOUCH_MOVE        0x02U
#define MELFAS_EVENT_TOUCH_UP          0x03U

/* Structure representing a single finger touch point */
typedef struct {
    uint8_t  finger_id;         /* 0 to 9 */
    uint8_t  action;            /* MELFAS_EVENT_* */
    uint16_t x;                 /* 0 to 1080 */
    uint16_t y;                 /* 0 to 2400 */
    uint8_t  pressure;          /* 0 to 255 */
    uint8_t  area;              /* Touch contact size */
    bool     active;            /* True if finger is currently on screen */
} MelfasTouchPoint;

/* Touch state container */
typedef struct {
    uintptr_t i2c_mmio_base;    /* Virtual address of I2C-4 registers */
    uint8_t   slave_addr;       /* 0x48 */
    uint32_t  active_touches;   /* Bitmask of active fingers */
    MelfasTouchPoint points[MELFAS_MAX_FINGERS];
    uint64_t  event_count;      /* Total events processed */
} MelfasTouchDevice;

int  MelfasTouch_Init(MelfasTouchDevice *dev, uintptr_t i2c_vaddr);
int  MelfasTouch_Poll(MelfasTouchDevice *dev);
int  MelfasTouch_DecodePacket(MelfasTouchDevice *dev, const uint8_t *raw_buf, uint32_t len);
void MelfasTouch_GetPrimaryTouch(const MelfasTouchDevice *dev, uint16_t *out_x, uint16_t *out_y, bool *out_down);

#ifdef __cplusplus
}
#endif

#endif /* _MELFAS_TOUCH_DRIVER_H_ */
