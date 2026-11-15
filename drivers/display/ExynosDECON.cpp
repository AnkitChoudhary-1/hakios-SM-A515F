/* SPDX-License-Identifier: MIT */
/*
 * ExynosDECON.cpp - Exynos 9611 Display Enhancement Controller (DECON) Driver
 *
 * Implements register configuration for DECON_F on Samsung Galaxy A51 (SM-A515F).
 * Preserves the Samsung S-Boot bootloader display pipeline, configures Window 0
 * for 32bpp ARGB8888 scanning from 0xCA000000, and provides software rendering primitives.
 */

#include "ExynosDECON.h"
#include "common/freestanding.h"

static inline void decon_write32(ExynosDECONDevice *dev, uint32_t reg, uint32_t val)
{
    if (dev && dev->mmio_base) {
        volatile uint32_t *addr = (volatile uint32_t *)(dev->mmio_base + reg);
        *addr = val;
    }
}

static inline uint32_t decon_read32(ExynosDECONDevice *dev, uint32_t reg)
{
    if (dev && dev->mmio_base) {
        volatile uint32_t *addr = (volatile uint32_t *)(dev->mmio_base + reg);
        return *addr;
    }
    return 0;
}

int ExynosDECON_Init(ExynosDECONDevice *dev, uintptr_t mmio_vaddr, void *fb_vaddr)
{
    if (!dev) {
        return -1;
    }

    dev->mmio_base = mmio_vaddr;
    dev->fb_phys_addr = EXYNOS9611_BOOT_FB_BASE_PA;
    dev->fb_virt_addr = fb_vaddr;
    dev->width = EXYNOS9611_BOOT_FB_WIDTH;
    dev->height = EXYNOS9611_BOOT_FB_HEIGHT;
    dev->stride = EXYNOS9611_BOOT_FB_STRIDE;
    dev->bpp = EXYNOS9611_BOOT_FB_BPP;
    dev->is_enabled = false;

    return ExynosDECON_PreserveBootloaderFB(dev);
}

int ExynosDECON_PreserveBootloaderFB(ExynosDECONDevice *dev)
{
    if (!dev) {
        return -1;
    }

    /*
     * If MMIO registers are available, read the existing hardware state.
     * S-Boot leaves DECON running with Window 0 active.
     */
    if (dev->mmio_base) {
        uint32_t vidcon0 = decon_read32(dev, DECON_VIDCON0);
        uint32_t wincon0 = decon_read32(dev, DECON_WINCON0);
        uint32_t cur_fb_pa = decon_read32(dev, DECON_VIDW00ADD0B0);

        /* If hardware already points to a valid physical address, preserve it */
        if (cur_fb_pa >= 0x80000000ULL && cur_fb_pa < 0x200000000ULL) {
            dev->fb_phys_addr = cur_fb_pa;
        }

        /* Ensure Window 0 is set to 32bpp ARGB8888 with correct stride */
        wincon0 |= WINCON_ENWIN | WINCON_BPPMODE_ARGB8888 | WINCON_WSW;
        decon_write32(dev, DECON_WINCON0, wincon0);

        /* Set buffer addresses and stride */
        uint32_t buf_end = (uint32_t)(dev->fb_phys_addr + (dev->stride * dev->height));
        decon_write32(dev, DECON_VIDW00ADD0B0, (uint32_t)dev->fb_phys_addr);
        decon_write32(dev, DECON_VIDW00ADD1B0, buf_end);
        decon_write32(dev, DECON_VIDW00ADD2, dev->stride);

        /* Enable Window 0 in shadow control and trigger update */
        decon_write32(dev, DECON_SHADOWCON, 0x01);
        decon_write32(dev, DECON_UPDATE, DECON_UPDATE_STANDALONE);

        dev->is_enabled = (vidcon0 & VIDCON0_ENVID) != 0;
    } else {
        /* Preserved virtual mapping path (standalone frame buffer) */
        dev->is_enabled = (dev->fb_virt_addr != (void *)0);
    }

    return 0;
}

void ExynosDECON_SetFramebufferAddress(ExynosDECONDevice *dev, uint64_t phys_addr)
{
    if (!dev) return;

    dev->fb_phys_addr = phys_addr;
    if (dev->mmio_base) {
        uint32_t buf_end = (uint32_t)(phys_addr + (dev->stride * dev->height));
        decon_write32(dev, DECON_VIDW00ADD0B0, (uint32_t)phys_addr);
        decon_write32(dev, DECON_VIDW00ADD1B0, buf_end);
        decon_write32(dev, DECON_UPDATE, DECON_UPDATE_STANDALONE);
    }
}

void ExynosDECON_TriggerUpdate(ExynosDECONDevice *dev)
{
    if (dev && dev->mmio_base) {
        decon_write32(dev, DECON_UPDATE, DECON_UPDATE_STANDALONE);
    }
}

void ExynosDECON_FillRect(ExynosDECONDevice *dev, uint32_t x, uint32_t y, uint32_t w, uint32_t h, uint32_t argb_color)
{
    if (!dev || !dev->fb_virt_addr) return;

    uint32_t *fb = (uint32_t *)dev->fb_virt_addr;
    uint32_t max_x = dev->width;
    uint32_t max_y = dev->height;

    if (x >= max_x || y >= max_y) return;
    if (x + w > max_x) w = max_x - x;
    if (y + h > max_y) h = max_y - y;

    for (uint32_t row = y; row < y + h; row++) {
        uint32_t *line = fb + (row * (dev->stride / 4));
        for (uint32_t col = x; col < x + w; col++) {
            line[col] = argb_color;
        }
    }
}

void ExynosDECON_DrawTestPattern(ExynosDECONDevice *dev)
{
    if (!dev || !dev->fb_virt_addr) return;

    /* Fill background with deep dark slate: 0xFF101418 */
    ExynosDECON_FillRect(dev, 0, 0, dev->width, dev->height, 0xFF101418);

    /* Draw 4 primary color bars across top */
    uint32_t bar_h = 300;
    uint32_t bar_w = dev->width / 4;
    ExynosDECON_FillRect(dev, bar_w * 0, 100, bar_w, bar_h, 0xFFFF0000); /* Red */
    ExynosDECON_FillRect(dev, bar_w * 1, 100, bar_w, bar_h, 0xFF00FF00); /* Green */
    ExynosDECON_FillRect(dev, bar_w * 2, 100, bar_w, bar_h, 0xFF0000FF); /* Blue */
    ExynosDECON_FillRect(dev, bar_w * 3, 100, bar_w, bar_h, 0xFFFFFFFF); /* White */

    /* Draw central verification crosshair grid */
    uint32_t cx = dev->width / 2;
    uint32_t cy = dev->height / 2;
    ExynosDECON_FillRect(dev, cx - 150, cy - 2, 300, 4, 0xFF00E5FF); /* Cyan H-bar */
    ExynosDECON_FillRect(dev, cx - 2, cy - 150, 4, 300, 0xFF00E5FF); /* Cyan V-bar */

    /* Draw screen border indicator (5px border around entire FHD+ 1080x2400 perimeter) */
    ExynosDECON_FillRect(dev, 0, 0, dev->width, 5, 0xFFFFCC00);               /* Top Gold border */
    ExynosDECON_FillRect(dev, 0, dev->height - 5, dev->width, 5, 0xFFFFCC00); /* Bottom Gold border */
    ExynosDECON_FillRect(dev, 0, 0, 5, dev->height, 0xFFFFCC00);               /* Left Gold border */
    ExynosDECON_FillRect(dev, dev->width - 5, 0, 5, dev->height, 0xFFFFCC00); /* Right Gold border */

    ExynosDECON_TriggerUpdate(dev);
}
