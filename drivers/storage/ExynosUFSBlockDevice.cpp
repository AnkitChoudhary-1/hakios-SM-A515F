/* SPDX-License-Identifier: MIT */
/*
 * ExynosUFSBlockDevice.cpp - Darwin IOKit Block Storage Device Interface
 *
 * Implements read-only block dispatch for Darwin VFS / IOBlockStorageDevice.
 */

#include "ExynosUFSBlockDevice.h"

int ExynosUFSBlockDevice_Init(ExynosUFSBlockDevice *bdev, uintptr_t ufs_mmio_vaddr)
{
    if (!bdev) return UFS_ERR_INVALID_PARAM;

    int rc = ExynosUFSHost_Init(&bdev->host, ufs_mmio_vaddr);
    if (rc != UFS_SUCCESS) return rc;

    bdev->block_size = UFS_SECTOR_SIZE;
    bdev->total_blocks = UFS_TOTAL_SECTORS_128GB;
    bdev->is_writable = false; /* Read-only lock */

    return UFS_SUCCESS;
}

int ExynosUFSBlockDevice_ReadBlocks(ExynosUFSBlockDevice *bdev, uint64_t block_addr, uint32_t count, void *buf)
{
    if (!bdev) return UFS_ERR_INVALID_PARAM;
    return ExynosUFSHost_ReadSectors(&bdev->host, (uint32_t)block_addr, count, buf);
}

int ExynosUFSBlockDevice_WriteBlocks(ExynosUFSBlockDevice *bdev, uint64_t block_addr, uint32_t count, const void *buf)
{
    if (!bdev) return UFS_ERR_INVALID_PARAM;
    /* Explicit rejection: always returns UFS_ERR_WRITE_PROHIBITED */
    return ExynosUFSHost_WriteSectors(&bdev->host, (uint32_t)block_addr, count, buf);
}

bool ExynosUFSBlockDevice_IsWritable(const ExynosUFSBlockDevice *bdev)
{
    if (!bdev) return false;
    return bdev->is_writable;
}
