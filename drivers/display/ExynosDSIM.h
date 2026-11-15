/* SPDX-License-Identifier: MIT */
/*
 * ExynosDSIM.h - Exynos 9611 MIPI DSI Master Driver & Panel Controller
 *
 * Implements register control for DSIM_0 on Samsung Galaxy A51 (SM-A515F).
 * Communicates with the Samsung AMOLED s6e3fa9 display panel over MIPI DSI
 * 4-data lanes, handling display on/off, sleep exit, and brightness level control.
 */

#ifndef _EXYNOS_DSIM_H_
#define _EXYNOS_DSIM_H_

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Exynos 9611 DSIM Base Physical Address */
#define EXYNOS9611_DSIM_BASE_PA        0x148E0000ULL
#define EXYNOS9611_DSIM_REG_SIZE       0x00010000ULL

/* DSIM Register Offsets */
#define DSIM_STATUS                    0x0000    /* DSIM Status Register */
#define DSIM_SWRST                     0x0004    /* Software Reset */
#define DSIM_CLKCTRL                   0x0008    /* Clock Control (PLL, Lane, Tx) */
#define DSIM_TIMEOUT                   0x000C    /* Timeout Configuration */
#define DSIM_CONFIG                    0x0010    /* Configuration Register (Lanes, Burst) */
#define DSIM_ESCMODE                   0x0014    /* Escape Mode Control */
#define DSIM_MDRESOL                   0x0018    /* Main Display Resolution */
#define DSIM_MVPORCH                   0x001C    /* Main Display V-Porch */
#define DSIM_MHPORCH                   0x0020    /* Main Display H-Porch */
#define DSIM_MSYNC                     0x0024    /* Main Display Sync */
#define DSIM_INTSRC                    0x0034    /* Interrupt Source */
#define DSIM_INTMSK                    0x0038    /* Interrupt Mask */
#define DSIM_PKTHDR                    0x003C    /* Packet Header Register (DSI Commands) */
#define DSIM_PAYLOAD                   0x0040    /* Payload Data FIFO */
#define DSIM_RXFIFO                    0x0044    /* Read Data FIFO */
#define DSIM_FIFOCTRL                  0x004C    /* FIFO Control */
#define DSIM_PLLCTRL                   0x0050    /* DPHY PLL Control */
#define DSIM_PHYTIMING                 0x0064    /* D-PHY Timing Parameters */

/* Standard MIPI DCS Commands for AMOLED Display Panel */
#define DCS_CMD_ENTER_SLEEP            0x10U     /* Enter Sleep Mode */
#define DCS_CMD_EXIT_SLEEP             0x11U     /* Exit Sleep Mode */
#define DCS_CMD_SET_DISPLAY_OFF        0x28U     /* Set Display OFF */
#define DCS_CMD_SET_DISPLAY_ON         0x29U     /* Set Display ON */
#define DCS_CMD_WRITE_DISPLAY_BRIGHT   0x51U     /* Set Display Brightness (0-255) */
#define DCS_CMD_WRITE_CTRL_DISPLAY     0x53U     /* Control Display (BCTRL=1, BL=1) */

typedef struct {
    uintptr_t mmio_base;        /* Virtual address where 0x148E0000 is mapped */
    uint32_t  lanes;            /* 4 data lanes */
    uint32_t  current_brightness;/* 0 to 255 */
    bool      is_panel_on;      /* Display power state */
} ExynosDSIMDevice;

int  ExynosDSIM_Init(ExynosDSIMDevice *dev, uintptr_t mmio_vaddr);
int  ExynosDSIM_SendDCSCommand(ExynosDSIMDevice *dev, uint8_t cmd, const uint8_t *payload, uint32_t len);
int  ExynosDSIM_SetPanelBrightness(ExynosDSIMDevice *dev, uint8_t brightness);
int  ExynosDSIM_SetPanelPower(ExynosDSIMDevice *dev, bool enable);

#ifdef __cplusplus
}
#endif

#endif /* _EXYNOS_DSIM_H_ */
