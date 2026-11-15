/* SPDX-License-Identifier: MIT */
/*
 * ExynosUFSBlockDevice.h - Darwin IOKit Block Storage Device Interface
 *
 * Exposes the UFS 2.1 flash memory to Darwin XNU as a read-only block device.
 */

#ifndef _EXYNOS_UFS_BLOCK_DEVICE_H_
#define _EXYNOS_UFS_BLOCK_DEVICE_H_

#include "ExynosUFSHost.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    ExynosUFSHost host;
    uint32_t      block_size;   /* 4096 */
    uint64_t      total_blocks; /* 31236096 */
    bool          is_writable;  /* Always false */
} ExynosUFSBlockDevice;

int  ExynosUFSBlockDevice_Init(ExynosUFSBlockDevice *bdev, uintptr_t ufs_mmio_vaddr);
int  ExynosUFSBlockDevice_ReadBlocks(ExynosUFSBlockDevice *bdev, uint64_t block_addr, uint32_t count, void *buf);
int  ExynosUFSBlockDevice_WriteBlocks(ExynosUFSBlockDevice *bdev, uint64_t block_addr, uint32_t count, const void *buf);
bool ExynosUFSBlockDevice_IsWritable(const ExynosUFSBlockDevice *bdev);

#ifdef __cplusplus
}
#endif

#endif /* _EXYNOS_UFS_BLOCK_DEVICE_H_ */
