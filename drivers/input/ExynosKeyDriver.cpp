/* SPDX-License-Identifier: MIT */
/*
 * ExynosKeyDriver.cpp - Exynos 9611 Hardware Keys Driver
 *
 * Implements button state management, software debouncing, and press counter.
 */

#include "ExynosKeyDriver.h"
#include "common/freestanding.h"

int ExynosKey_Init(ExynosKeyDevice *dev, uintptr_t gpio_vaddr)
{
    if (!dev) return -1;

    memset(dev, 0, sizeof(*dev));
    dev->gpio_mmio_base = gpio_vaddr;
    dev->debounce_ms = 20;

    dev->power_key.keycode = KEY_POWER;
    dev->volup_key.keycode = KEY_VOLUMEUP;
    dev->voldown_key.keycode = KEY_VOLUMEDOWN;

    return 0;
}

static void update_single_key(ExynosKey *key, bool is_down)
{
    uint8_t new_state = is_down ? KEY_STATE_PRESSED : KEY_STATE_RELEASED;
    if (new_state == KEY_STATE_PRESSED && key->last_state == KEY_STATE_RELEASED) {
        key->press_count++;
    }
    key->last_state = key->state;
    key->state = new_state;
}

void ExynosKey_UpdateRaw(ExynosKeyDevice *dev, bool power_down, bool volup_down, bool voldown_down)
{
    if (!dev) return;

    update_single_key(&dev->power_key, power_down);
    update_single_key(&dev->volup_key, volup_down);
    update_single_key(&dev->voldown_key, voldown_down);
}

bool ExynosKey_IsPressed(const ExynosKeyDevice *dev, uint16_t keycode)
{
    if (!dev) return false;

    switch (keycode) {
    case KEY_POWER:      return dev->power_key.state == KEY_STATE_PRESSED;
    case KEY_VOLUMEUP:   return dev->volup_key.state == KEY_STATE_PRESSED;
    case KEY_VOLUMEDOWN: return dev->voldown_key.state == KEY_STATE_PRESSED;
    default:             return false;
    }
}

uint32_t ExynosKey_GetPressCount(const ExynosKeyDevice *dev, uint16_t keycode)
{
    if (!dev) return 0;

    switch (keycode) {
    case KEY_POWER:      return dev->power_key.press_count;
    case KEY_VOLUMEUP:   return dev->volup_key.press_count;
    case KEY_VOLUMEDOWN: return dev->voldown_key.press_count;
    default:             return 0;
    }
}
