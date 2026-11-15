/* SPDX-License-Identifier: MIT */
#ifndef _FREESTANDING_H_
#define _FREESTANDING_H_

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

static inline void *freestanding_memset(void *s, int c, unsigned long n)
{
    unsigned char *p = (unsigned char *)s;
    while (n--) { *p++ = (unsigned char)c; }
    return s;
}

static inline void *freestanding_memcpy(void *dest, const void *src, unsigned long n)
{
    unsigned char *d = (unsigned char *)dest;
    const unsigned char *s = (const unsigned char *)src;
    while (n--) { *d++ = *s++; }
    return dest;
}

#ifndef memset
#define memset freestanding_memset
#endif

#ifndef memcpy
#define memcpy freestanding_memcpy
#endif

#ifdef __cplusplus
}
#endif

#endif /* _FREESTANDING_H_ */
