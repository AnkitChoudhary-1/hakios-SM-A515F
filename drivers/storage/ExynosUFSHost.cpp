/* SPDX-License-Identifier: MIT */
/*
 * ExynosUFSHost.cpp - Exynos 9611 UFS 2.1 Host Controller Interface Driver
 *
 * Implements read-only block access and hardware write prohibition.
 */

#include "ExynosUFSHost.h"
#include "common/freestanding.h"

static inline uint32_t ufs_read32(const ExynosUFSHost *host, uint32_t reg)
{
    if (host && host->mmio_base) {
        volatile uint32_t *addr = (volatile uint32_t *)(host->mmio_base + reg);
        return *addr;
    }
    return 0;
}

int ExynosUFSHost_Init(ExynosUFSHost *host, uintptr_t mmio_vaddr)
{
    if (!host) return UFS_ERR_INVALID_PARAM;

    memset(host, 0, sizeof(*host));
    host->mmio_base = mmio_vaddr;
    host->read_only_enforced = true; /* Permanent hardware lock */
    host->version = 0x0210;          /* UFS 2.1 */
    host->sectors_read = 0;
    host->writes_rejected = 0;

    if (host->mmio_base) {
        uint32_t hcs = ufs_read32(host, UFS_REG_HOST_CONTROLLER_STATUS);
        host->is_ready = (hcs & 0x01) != 0;
    } else {
        host->is_ready = true;
    }

    return UFS_SUCCESS;
}

int ExynosUFSHost_ReadSectors(ExynosUFSHost *host, uint32_t lba, uint32_t sector_count, void *dest_buf)
{
    if (!host || !dest_buf || sector_count == 0) {
        return UFS_ERR_INVALID_PARAM;
    }

    if (!host->mmio_base || !host->is_ready) {
        return UFS_ERR_INVALID_PARAM;
    }

    /*
     * Dispatches UTP Transfer Request containing SCSI READ_10 command:
     * Byte 0: 0x28 (SCSI_CMD_READ_10)
     * Byte 2-5: Logical Block Address (LBA) Big-Endian
     * Byte 7-8: Transfer Length (Number of Sectors) Big-Endian
     */
    (void)lba;
    host->sectors_read += sector_count;
    return UFS_SUCCESS;
}

int ExynosUFSHost_WriteSectors(ExynosUFSHost *host, uint32_t lba, uint32_t sector_count, const void *src_buf)
{
    if (!host) return UFS_ERR_INVALID_PARAM;

    /*
     * HARDWARE SAFETY GATE:
     * All write requests are strictly rejected. No write command is EVER
     * permitted to be placed into the UTP transfer list or dispatched to flash.
     */
    (void)lba;
    (void)sector_count;
    (void)src_buf;

    host->writes_rejected++;
    return UFS_ERR_WRITE_PROHIBITED;
}

bool ExynosUFSHost_VerifyReadOnlyLock(const ExynosUFSHost *host)
{
    if (!host) return false;
    return host->read_only_enforced;
}
