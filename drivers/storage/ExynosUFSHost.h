/* SPDX-License-Identifier: MIT */
/*
 * ExynosUFSHost.h - Exynos 9611 UFS 2.1 Host Controller Interface Driver
 *
 * Implements UFS 2.1 Host Controller register initialization and command
 * submission on Samsung Galaxy A51 (SM-A515F).
 *
 * CRITICAL SAFETY REQUIREMENT:
 * The driver operates in STRICT READ-ONLY MODE. All storage write commands
 * (SCSI WRITE_6, WRITE_10, WRITE_16, FORMAT, UNMAP, ERASE) are blocked at
 * the hardware driver boundary to guarantee 100% preservation of internal flash.
 */

#ifndef _EXYNOS_UFS_HOST_H_
#define _EXYNOS_UFS_HOST_H_

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Exynos 9611 UFS HCI Base Physical Address */
#define EXYNOS9611_UFS_BASE_PA         0x13520000ULL
#define EXYNOS9611_UFS_REG_SIZE        0x00010000ULL

/* Standard UFS HCI Register Offsets */
#define UFS_REG_CAPABILITIES           0x0000    /* Controller Capabilities */
#define UFS_REG_UFS_VERSION            0x0008    /* UFS Version (0x0210 for UFS 2.1) */
#define UFS_REG_HOST_CONTROLLER_STATUS 0x0030    /* Host Controller Status (HCS) */
#define UFS_REG_HOST_CONTROLLER_ENABLE 0x0034    /* Host Controller Enable (HCE) */
#define UFS_REG_UTP_TRANSFER_REQ_LIST  0x0050    /* Transfer Request List Base Address */
#define UFS_REG_UTP_TASK_REQ_LIST      0x0070    /* Task Management Request List */

/* SCSI Command Opcodes */
#define SCSI_CMD_TEST_UNIT_READY       0x00U
#define SCSI_CMD_REQUEST_SENSE         0x03U
#define SCSI_CMD_INQUIRY               0x12U
#define SCSI_CMD_READ_CAPACITY_10      0x25U
#define SCSI_CMD_READ_10               0x28U
#define SCSI_CMD_READ_16               0x88U
#define SCSI_CMD_WRITE_10              0x2AU
#define SCSI_CMD_WRITE_16              0x8AU

/* Error Codes */
#define UFS_SUCCESS                    0
#define UFS_ERR_INVALID_PARAM         -1
#define UFS_ERR_TIMEOUT               -2
#define UFS_ERR_WRITE_PROHIBITED      -30       /* Write operations permanently forbidden */

/* Sector geometry for UFS storage */
#define UFS_SECTOR_SIZE                4096U     /* Standard UFS 4KB hardware blocks */
#define UFS_TOTAL_SECTORS_128GB        31236096U /* 128 GB in 4KB sectors */

typedef struct {
    uintptr_t mmio_base;        /* Virtual address of 0x13520000 */
    uint32_t  version;          /* 0x0210 */
    bool      is_ready;         /* Controller ready state */
    bool      read_only_enforced;/* Always TRUE */
    uint64_t  sectors_read;     /* Read statistics */
    uint64_t  writes_rejected;  /* Count of blocked write attempts */
} ExynosUFSHost;

int  ExynosUFSHost_Init(ExynosUFSHost *host, uintptr_t mmio_vaddr);
int  ExynosUFSHost_ReadSectors(ExynosUFSHost *host, uint32_t lba, uint32_t sector_count, void *dest_buf);
int  ExynosUFSHost_WriteSectors(ExynosUFSHost *host, uint32_t lba, uint32_t sector_count, const void *src_buf);
bool ExynosUFSHost_VerifyReadOnlyLock(const ExynosUFSHost *host);

#ifdef __cplusplus
}
#endif

#endif /* _EXYNOS_UFS_HOST_H_ */
