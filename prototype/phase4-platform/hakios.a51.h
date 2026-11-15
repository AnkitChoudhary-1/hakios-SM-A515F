/* SPDX-License-Identifier: MIT */
/* Versioned fixed-size kernel/user ABI; no pointers or arbitrary MMIO requests. */
#ifndef HAKIOS_A51_H
#define HAKIOS_A51_H
#define HAKIOS_A51_ABI_VERSION 1u
#define HAKIOS_A51_REG_MAX 192u
#define HAKIOS_A51_GPIO    (1u << 0)
#define HAKIOS_A51_I2C     (1u << 1)
#define HAKIOS_A51_DSIM    (1u << 2)
#define HAKIOS_A51_DECON   (1u << 3)
#define HAKIOS_A51_UFS     (1u << 4)
#define HAKIOS_A51_DPP     (1u << 5)
#define HAKIOS_A51_SYSMMU  (1u << 6)
#define HAKIOS_A51_ALL     0x7fu

struct hakios_a51_register {
    unsigned long long pa;
    unsigned int value;
    unsigned int group;
};
struct hakios_a51_snapshot {
    unsigned int version;
    unsigned int count;
    unsigned int groups;
    unsigned int sequence;
    unsigned long long counter;
    struct hakios_a51_register regs[HAKIOS_A51_REG_MAX];
};
_Static_assert(sizeof(struct hakios_a51_register) == 16, "A51 register ABI");
_Static_assert(sizeof(struct hakios_a51_snapshot) == 3096, "A51 snapshot ABI");

/* UFS 2.1 Hardware Block Transfer and Write-Prohibition Result */
struct hakios_a51_ufs_result {
    unsigned int version;              /* ABI version = 1 */
    unsigned int hcs;                  /* Host Controller Status */
    unsigned int hce;                  /* Host Controller Enable */
    unsigned int ufs_version;          /* UFSHCI Version (0x0210) */
    unsigned int single_lba;           /* Target LBA (27792) */
    unsigned int single_blocks;        /* 1 (4096 bytes) */
    int          single_rc;            /* Read status code (0 = success) */
    unsigned int single_ocs;           /* Overall Command Status (0 = success) */
    unsigned char single_sha256[32];   /* SHA-256 over transferred DRAM buffer */
    unsigned int multi_lba;            /* Target LBA (27792) */
    unsigned int multi_blocks;         /* 16 (65536 bytes / 64 KiB) */
    int          multi_rc;             /* Read status code (0 = success) */
    unsigned int multi_ocs;            /* Overall Command Status (0 = success) */
    unsigned char multi_sha256[32];    /* SHA-256 over transferred DRAM buffer */
    int          write_rc;             /* Must be -30 (UFS_ERR_WRITE_PROHIBITED) */
    unsigned int write_rejected;       /* Prohibited write count (>= 1) */
    unsigned int doorbell_after_write; /* Must be 0 (doorbell never rung) */
    unsigned int diag_rs;              /* UTRLRSR status */
    unsigned int diag_dbr;             /* UTRLDBR status */
    unsigned int diag_dest_pa_lo;      /* Physical address low 32 */
    unsigned int diag_dest_pa_hi;      /* Physical address high 32 */
};
_Static_assert(sizeof(struct hakios_a51_ufs_result) == 140, "A51 UFS result ABI");

#endif
