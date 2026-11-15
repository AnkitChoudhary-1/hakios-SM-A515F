/* SPDX-License-Identifier: MIT */
/*
 * ExynosDSIM.cpp - Exynos 9611 MIPI DSI Master Driver & Panel Controller
 *
 * Implements DCS command dispatch over MIPI DSI for Samsung AMOLED s6e3fa9 on A51.
 */

#include "ExynosDSIM.h"

static inline void dsim_write32(ExynosDSIMDevice *dev, uint32_t reg, uint32_t val)
{
    if (dev && dev->mmio_base) {
        volatile uint32_t *addr = (volatile uint32_t *)(dev->mmio_base + reg);
        *addr = val;
    }
}

static inline uint32_t dsim_read32(ExynosDSIMDevice *dev, uint32_t reg)
{
    if (dev && dev->mmio_base) {
        volatile uint32_t *addr = (volatile uint32_t *)(dev->mmio_base + reg);
        return *addr;
    }
    return 0;
}

int ExynosDSIM_Init(ExynosDSIMDevice *dev, uintptr_t mmio_vaddr)
{
    if (!dev) return -1;

    dev->mmio_base = mmio_vaddr;
    dev->lanes = 4;
    dev->current_brightness = 200; /* Default readable brightness */
    dev->is_panel_on = true;

    /* If MMIO is present, check existing hardware status initialized by S-Boot */
    if (dev->mmio_base) {
        uint32_t status = dsim_read32(dev, DSIM_STATUS);
        dev->is_panel_on = (status != 0);
    }

    return 0;
}

int ExynosDSIM_SendDCSCommand(ExynosDSIMDevice *dev, uint8_t cmd, const uint8_t *payload, uint32_t len)
{
    if (!dev || !dev->mmio_base) {
        return 0; /* Simulated / preserver path succeeds */
    }

    /* Wait for Tx FIFO ready */
    uint32_t timeout = 10000;
    while ((dsim_read32(dev, DSIM_FIFOCTRL) & (1U << 24)) && --timeout) {
        /* Tx FIFO full, wait */
    }

    if (len == 0) {
        /* Short DCS Write without parameter (Data Type 0x05) */
        uint32_t header = (0x05U) | ((uint32_t)cmd << 8);
        dsim_write32(dev, DSIM_PKTHDR, header);
    } else if (len == 1) {
        /* Short DCS Write with 1 parameter (Data Type 0x15) */
        uint32_t header = (0x15U) | ((uint32_t)cmd << 8) | ((uint32_t)payload[0] << 16);
        dsim_write32(dev, DSIM_PKTHDR, header);
    } else {
        /* Long DCS Write (Data Type 0x39) */
        uint32_t total_payload = len + 1;
        uint32_t header = (0x39U) | (total_payload << 8);

        /* Write payload bytes: first byte is command, followed by parameters */
        uint32_t word = cmd;
        int shift = 8;
        for (uint32_t i = 0; i < len; i++) {
            word |= ((uint32_t)payload[i]) << shift;
            shift += 8;
            if (shift == 32 || i == len - 1) {
                dsim_write32(dev, DSIM_PAYLOAD, word);
                word = 0;
                shift = 0;
            }
        }
        dsim_write32(dev, DSIM_PKTHDR, header);
    }

    return 0;
}

int ExynosDSIM_SetPanelBrightness(ExynosDSIMDevice *dev, uint8_t brightness)
{
    if (!dev) return -1;

    /* Write 0x51 WRITE_DISPLAY_BRIGHTNESS */
    uint8_t val = brightness;
    int rc = ExynosDSIM_SendDCSCommand(dev, DCS_CMD_WRITE_DISPLAY_BRIGHT, &val, 1);
    if (rc == 0) {
        dev->current_brightness = brightness;
    }
    return rc;
}

int ExynosDSIM_SetPanelPower(ExynosDSIMDevice *dev, bool enable)
{
    if (!dev) return -1;

    if (enable) {
        /* Exit sleep (0x11) followed by display on (0x29) */
        ExynosDSIM_SendDCSCommand(dev, DCS_CMD_EXIT_SLEEP, (const uint8_t *)0, 0);
        ExynosDSIM_SendDCSCommand(dev, DCS_CMD_SET_DISPLAY_ON, (const uint8_t *)0, 0);
        dev->is_panel_on = true;
    } else {
        /* Display off (0x28) followed by enter sleep (0x10) */
        ExynosDSIM_SendDCSCommand(dev, DCS_CMD_SET_DISPLAY_OFF, (const uint8_t *)0, 0);
        ExynosDSIM_SendDCSCommand(dev, DCS_CMD_ENTER_SLEEP, (const uint8_t *)0, 0);
        dev->is_panel_on = false;
    }
    return 0;
}
