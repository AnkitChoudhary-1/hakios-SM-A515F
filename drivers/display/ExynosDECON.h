/* SPDX-License-Identifier: MIT */
/*
 * ExynosDECON.h - Exynos 9611 Display Enhancement Controller (DECON) Driver
 *
 * Implements direct register control for DECON_F on Samsung Galaxy A51 (SM-A515F).
 * Controls hardware overlay windows, pixel format routing, and memory scanning
 * from the preserved Samsung S-Boot bootloader framebuffer at 0xCA000000.
 */

#ifndef _EXYNOS_DECON_H_
#define _EXYNOS_DECON_H_

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Exynos 9611 DECON Base Physical Address */
#define EXYNOS9611_DECON_BASE_PA       0x148B0000ULL
#define EXYNOS9611_DECON_REG_SIZE      0x00001000ULL

/* Samsung S-Boot Preserved Bootloader Framebuffer */
#define EXYNOS9611_BOOT_FB_BASE_PA     0xCA000000ULL
#define EXYNOS9611_BOOT_FB_WIDTH       1080U
#define EXYNOS9611_BOOT_FB_HEIGHT      2400U
#define EXYNOS9611_BOOT_FB_BPP         32U       /* 32 bits per pixel */
#define EXYNOS9611_BOOT_FB_STRIDE      4320U     /* 1080 * 4 bytes */
#define EXYNOS9611_BOOT_FB_SIZE        10368000U /* 1080 * 2400 * 4 bytes (~10 MB) */

/* DECON Register Offsets */
#define DECON_VIDCON0                  0x0000    /* Video Control 0 (Operating Mode & Clocks) */
#define DECON_VIDCON1                  0x0004    /* Video Control 1 (Signal Polarity & Timing) */
#define DECON_VIDTCON0                 0x0010    /* Video Timing 0 (VBP, VFP, VSPW) */
#define DECON_VIDTCON1                 0x0014    /* Video Timing 1 (HBP, HFP, HSPW) */
#define DECON_VIDTCON2                 0x0018    /* Video Timing 2 (Vertical & Horizontal Active) */
#define DECON_WINCON0                  0x0020    /* Window 0 Control */
#define DECON_WINCON1                  0x0024    /* Window 1 Control */
#define DECON_VIDOSD0A                 0x0040    /* Window 0 Position Top-Left */
#define DECON_VIDOSD0B                 0x0044    /* Window 0 Position Bottom-Right */
#define DECON_VIDOSD0C                 0x0048    /* Window 0 Alpha / Size */
#define DECON_VIDW00ADD0B0             0x00A0    /* Window 0 Buffer Start Address (Physical) */
#define DECON_VIDW00ADD1B0             0x00A4    /* Window 0 Buffer End Address (Physical) */
#define DECON_VIDW00ADD2               0x00A8    /* Window 0 Buffer Stride */
#define DECON_SHADOWCON                0x0034    /* Shadow Control (Window Enable Masks) */
#define DECON_UPDATE                   0x0038    /* Shadow Update Trigger */
#define DECON_VIDINTCON0               0x0110    /* Video Interrupt Control 0 */
#define DECON_VIDINTCON1               0x0114    /* Video Interrupt Status 0 */

/* VIDCON0 Bitfields */
#define VIDCON0_ENVID                  (1U << 0) /* Video Output Enable */
#define VIDCON0_ENVID_F                (1U << 1) /* Direct Video Output Enable */
#define VIDCON0_CLKVAL_F(v)            (((v) & 0xFFU) << 6)
#define VIDCON0_CLKDIR                 (1U << 4)

/* WINCONx Bitfields */
#define WINCON_ENWIN                   (1U << 0) /* Window Enable */
#define WINCON_BPPMODE_ARGB8888        (0xDU << 2)/* 32-bit ARGB8888 mode */
#define WINCON_HAWSW                   (1U << 16)/* Half-word Swap */
#define WINCON_WSW                     (1U << 15)/* Word Swap */

/* UPDATE Bitfields */
#define DECON_UPDATE_STANDALONE        (1U << 0) /* Trigger shadow register commit */

/* Structure describing DECON display geometry and framebuffer mapping */
typedef struct {
    uintptr_t mmio_base;        /* Virtual address where 0x148B0000 is mapped */
    uint64_t  fb_phys_addr;     /* Physical address of framebuffer (0xCA000000) */
    void     *fb_virt_addr;     /* Virtual address of framebuffer memory */
    uint32_t  width;            /* 1080 */
    uint32_t  height;           /* 2400 */
    uint32_t  stride;           /* 4320 bytes */
    uint32_t  bpp;              /* 32 */
    bool      is_enabled;       /* Whether DECON is active */
} ExynosDECONDevice;

/* DECON Hardware Driver APIs */
int  ExynosDECON_Init(ExynosDECONDevice *dev, uintptr_t mmio_vaddr, void *fb_vaddr);
int  ExynosDECON_PreserveBootloaderFB(ExynosDECONDevice *dev);
void ExynosDECON_SetFramebufferAddress(ExynosDECONDevice *dev, uint64_t phys_addr);
void ExynosDECON_FillRect(ExynosDECONDevice *dev, uint32_t x, uint32_t y, uint32_t w, uint32_t h, uint32_t argb_color);
void ExynosDECON_DrawTestPattern(ExynosDECONDevice *dev);
void ExynosDECON_TriggerUpdate(ExynosDECONDevice *dev);

#ifdef __cplusplus
}
#endif

#endif /* _EXYNOS_DECON_H_ */
