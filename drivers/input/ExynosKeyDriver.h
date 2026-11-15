/* SPDX-License-Identifier: MIT */
/*
 * ExynosKeyDriver.h - Exynos 9611 Hardware Keys Driver
 *
 * Implements button state polling and event reporting for Samsung Galaxy A51:
 *   - Button 2: Volume Down (KEY_VOLUMEDOWN = 114)
 *   - Button 3: Volume Up   (KEY_VOLUMEUP = 115)
 *   - Button 4: Power Key   (KEY_POWER = 116)
 */

#ifndef _EXYNOS_KEY_DRIVER_H_
#define _EXYNOS_KEY_DRIVER_H_

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Linux / Darwin Input Keycodes */
#define KEY_RESERVED                   0
#define KEY_VOLUMEDOWN                 114
#define KEY_VOLUMEUP                   115
#define KEY_POWER                      116

/* Key States */
#define KEY_STATE_RELEASED             0
#define KEY_STATE_PRESSED              1

typedef struct {
    uint16_t keycode;           /* KEY_POWER, KEY_VOLUMEUP, KEY_VOLUMEDOWN */
    uint8_t  state;             /* KEY_STATE_PRESSED / KEY_STATE_RELEASED */
    uint8_t  last_state;        /* Previous debounced state */
    uint32_t press_count;       /* Total presses observed */
} ExynosKey;

typedef struct {
    uintptr_t gpio_mmio_base;   /* Virtual base of GPIO controller */
    ExynosKey power_key;
    ExynosKey volup_key;
    ExynosKey voldown_key;
    uint32_t  debounce_ms;
} ExynosKeyDevice;

int  ExynosKey_Init(ExynosKeyDevice *dev, uintptr_t gpio_vaddr);
void ExynosKey_UpdateRaw(ExynosKeyDevice *dev, bool power_down, bool volup_down, bool voldown_down);
bool ExynosKey_IsPressed(const ExynosKeyDevice *dev, uint16_t keycode);
uint32_t ExynosKey_GetPressCount(const ExynosKeyDevice *dev, uint16_t keycode);

#ifdef __cplusplus
}
#endif

#endif /* _EXYNOS_KEY_DRIVER_H_ */
