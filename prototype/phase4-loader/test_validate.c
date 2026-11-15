/* SPDX-License-Identifier: MIT */
/* Exercise the exact pre-write validator with native address/UB sanitizers. */
#include "validate.h"
#include "fdt_guard.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct sample {
    struct loader_config c;
    struct toc_entry t[MAX_TOC];
    unsigned char p[4096];
};
static unsigned checks;
static void check(int ok, const char *name)
{
    if (!ok) { fprintf(stderr, "FAIL %s\n", name); exit(1); }
    checks++;
}
static void make(struct sample *s)
{
    memset(s, 0, sizeof(*s));
    for (unsigned i = 0; i < sizeof(s->p); i++) s->p[i] = (unsigned char)(i * 13 + 7);
    memcpy(s->p + 64, "XNULDRST", 8);
    s->t[0] = (struct toc_entry){0, ARENA_BASE, 1024, 0, 0, 0};
    s->t[1] = (struct toc_entry){1024, ARENA_BASE + 4096, 736, 4096 - 736, 0, 0};
    s->t[2] = (struct toc_entry){0, ARENA_BASE + 8192, 0, MAX_KERNEL_LOG, 0, 0};
    for (unsigned i = 0; i < 3; i++) s->t[i].crc = phase4_crc32(s->p + s->t[i].source, s->t[i].copy);
    s->c = (struct loader_config){
        .magic = CONFIG_MAGIC, .version = 1, .count = 3, .payload_bytes = sizeof(s->p),
        .arena_base = ARENA_BASE, .arena_limit = ARENA_LIMIT, .entry = ARENA_BASE,
        .bootargs = ARENA_BASE + 4096, .stub_slot = ARENA_BASE + 64, .slide = SLIDE_BITS,
        .kernel_base = ARENA_BASE, .kernel_limit = ARENA_BASE + 8192 + MAX_KERNEL_LOG,
        .log_pa = ARENA_BASE + 8192, .log_capacity = MAX_KERNEL_LOG,
        .log_len_pa = ARENA_BASE + 8188, .watchdog_count = 32768, .nonce_hi = 1, .nonce_lo = 2
    };
}
static int validate(struct sample *s)
{
    return phase4_validate(&s->c, s->t, 3 * sizeof(s->t[0]), s->p, sizeof(s->p), IMAGE_BASE, IMAGE_BASE + 0x4000);
}
#define BAD(name, mutation, error) do { make(&s); mutation; check(validate(&s) == error, name); } while (0)

int main(int argc, char **argv)
{
    struct sample s;
    check(phase4_crc32((const unsigned char *)"123456789", 9) == 0xcbf43926, "independent CRC32 test vector");
    check(phase4_crc32((const unsigned char *)"", 0) == 0, "empty CRC");
    check(phase4_span(UINT64_MAX, 0, UINT64_MAX, UINT64_MAX), "empty span at upper endpoint");
    check(!phase4_span(UINT64_MAX - 1, 3, 0, UINT64_MAX), "wrapped span rejected");
    check(!phase4_span(5, 0, 9, 4), "inverted span rejected");
    check(phase4_overlap(UINT64_MAX - 1, 2, UINT64_MAX, 1), "overlap at integer ceiling");
    check(!phase4_overlap(1, 4, 5, 4), "adjacent spans are distinct");
    make(&s);
    check(validate(&s) == VALID_OK, "valid copied and zeroed segments");
    check(phase4_validate(&s.c, s.t, 144, s.p, sizeof(s.p), LEGACY_IMAGE_BASE, LEGACY_IMAGE_BASE + 0x4000) == VALID_OK, "original Phase 2 firmware placement");
    check(phase4_validate(&s.c, s.t, 144, s.p, sizeof(s.p), MEASURED_IMAGE_BASE, MEASURED_IMAGE_BASE + 0x4000) == VALID_OK, "accepted-carrier measured firmware placement");
    check(phase4_validate(NULL, s.t, 144, s.p, sizeof(s.p), IMAGE_BASE, IMAGE_BASE + 0x4000) == VALID_CONFIG, "null config");
    check(phase4_validate(&s.c, NULL, 144, s.p, sizeof(s.p), IMAGE_BASE, IMAGE_BASE + 0x4000) == VALID_CONFIG, "null TOC");
    check(phase4_validate(&s.c, s.t, 144, NULL, sizeof(s.p), IMAGE_BASE, IMAGE_BASE + 0x4000) == VALID_CONFIG, "null payload");
    check(phase4_validate(&s.c, s.t, 143, s.p, sizeof(s.p), IMAGE_BASE, IMAGE_BASE + 0x4000) == VALID_CONFIG, "truncated TOC extent");
    check(phase4_validate(&s.c, s.t, 144, s.p, sizeof(s.p), IMAGE_BASE + 4096, IMAGE_BASE + 0x4000) == VALID_CONFIG, "unknown runtime placement");
    check(phase4_validate(&s.c, s.t, 144, s.p, sizeof(s.p), IMAGE_BASE, IMAGE_BASE + IMAGE_BYTES - 1) == VALID_CONFIG, "payload crosses image slot");
    BAD("wrong magic", s.c.magic ^= 1, VALID_CONFIG);
    BAD("wrong schema", s.c.version = 2, VALID_CONFIG);
    BAD("empty TOC", s.c.count = 0, VALID_CONFIG);
    BAD("excessive count", s.c.count = MAX_TOC + 1, VALID_CONFIG);
    BAD("overflowing count", s.c.count = UINT64_MAX, VALID_CONFIG);
    BAD("payload size mismatch", s.c.payload_bytes++, VALID_CONFIG);
    BAD("unknown diagnostic", s.c.diagnostic = 5, VALID_CONFIG);
    BAD("unknown checkpoint", s.c.checkpoint = 41, VALID_CONFIG);
    BAD("short watchdog", s.c.watchdog_count = 99, VALID_CONFIG);
    BAD("oversize watchdog", s.c.watchdog_count = 65536, VALID_CONFIG);
    BAD("wrong slide", s.c.slide++, VALID_CONFIG);
    BAD("zero nonce", s.c.nonce_hi = s.c.nonce_lo = 0, VALID_CONFIG);
    BAD("changed arena base", s.c.arena_base++, VALID_LAYOUT);
    BAD("changed arena limit", s.c.arena_limit++, VALID_LAYOUT);
    BAD("kernel outside arena", s.c.kernel_base--, VALID_LAYOUT);
    BAD("inverted kernel", s.c.kernel_limit = s.c.kernel_base, VALID_LAYOUT);
    BAD("unaligned entry", s.c.entry++, VALID_LAYOUT);
    BAD("entry crosses kernel", s.c.entry = s.c.kernel_limit, VALID_LAYOUT);
    BAD("unaligned BootArgs", s.c.bootargs++, VALID_LAYOUT);
    BAD("BootArgs crosses arena", s.c.bootargs = ARENA_LIMIT - 8, VALID_LAYOUT);
    BAD("unaligned slot", s.c.stub_slot++, VALID_LAYOUT);
    BAD("slot crosses kernel", s.c.stub_slot = s.c.kernel_limit - 8, VALID_LAYOUT);
    BAD("log exceeds kernel", s.c.log_pa = s.c.kernel_limit - 4, VALID_LAYOUT);
    BAD("wrong log capacity", s.c.log_capacity++, VALID_LAYOUT);
    BAD("unaligned log length", s.c.log_len_pa++, VALID_LAYOUT);
    BAD("log length outside kernel", s.c.log_len_pa = s.c.kernel_limit, VALID_LAYOUT);
    BAD("reserved TOC data", s.t[0].reserved = 1, VALID_TOC);
    BAD("CRC exceeds 32 bits", s.t[0].crc |= UINT64_C(1) << 32, VALID_TOC);
    BAD("source overflow", s.t[0].source = UINT64_MAX, VALID_TOC);
    BAD("source endpoint crossed", s.t[0].source = sizeof(s.p) - 1, VALID_TOC);
    BAD("copy plus zero overflow", s.t[0].zero = UINT64_MAX, VALID_TOC);
    BAD("empty segment", s.t[0].copy = s.t[0].zero = 0, VALID_TOC);
    BAD("destination below arena", s.t[0].destination--, VALID_TOC);
    BAD("destination above arena", s.t[0].destination = ARENA_LIMIT, VALID_TOC);
    BAD("overlapping destinations", s.t[1].destination = ARENA_BASE + 512, VALID_TOC);
    BAD("source CRC corruption", s.p[0] ^= 1, VALID_CRC);
    BAD("unbacked entry", s.c.entry = ARENA_BASE + 2048, VALID_BACKING);
    BAD("zero-only entry", s.c.entry = ARENA_BASE + 8192, VALID_BACKING);
    BAD("unbacked BootArgs", s.c.bootargs = ARENA_BASE + 1024, VALID_BACKING);
    BAD("short copied BootArgs", s.t[1].copy = 735; s.t[1].zero++; s.t[1].crc = phase4_crc32(s.p + 1024, 735), VALID_BACKING);
    BAD("unbacked slot", s.c.stub_slot = ARENA_BASE + 1000, VALID_BACKING);
    BAD("uncovered log", s.t[2].zero--, VALID_BACKING);
    BAD("uncovered log length", s.c.log_len_pa = ARENA_BASE + 2048, VALID_BACKING);
    BAD("slot magic differs despite valid CRC", s.p[64] ^= 1; s.t[0].crc = phase4_crc32(s.p, 1024), VALID_SLOT);
    make(&s);
    s.c.count = MAX_TOC;
    for (unsigned i = 3; i < MAX_TOC; i++)
        s.t[i] = (struct toc_entry){0, ARENA_BASE + 0x200000 + i * 4, 4, 0, phase4_crc32(s.p, 4), 0};
    check(phase4_validate(&s.c, s.t, sizeof(s.t), s.p, sizeof(s.p), IMAGE_BASE, IMAGE_BASE + 0x4000) == VALID_OK, "maximum TOC count");
    unsigned seed = 0x51a004;
    for (unsigned i = 0; i < 3000; i++) {
        make(&s);
        seed = seed * 1664525u + 1013904223u;
        unsigned char *target = i % 3 == 0 ? (unsigned char *)&s.c : i % 3 == 1 ? (unsigned char *)s.t : s.p;
        unsigned size = i % 3 == 0 ? sizeof(s.c) : i % 3 == 1 ? 144 : sizeof(s.p);
        target[seed % size] ^= (unsigned char)(1u << (i % 8));
        int rc = validate(&s);
        check(rc >= VALID_OK && rc <= VALID_SLOT, "mutated fixture remains bounded");
    }
    check(argc == 2, "original FDT supplied");
    FILE *f = fopen(argv[1], "rb");
    check(f != NULL && fseek(f, 0, SEEK_END) == 0, "FDT file opened");
    long n = ftell(f);
    check(n > 40 && n <= 2 * 1024 * 1024 && fseek(f, 0, SEEK_SET) == 0, "FDT file bounded");
    unsigned char *dt = malloc((size_t)n), *mut = malloc((size_t)n);
    check(dt && mut && fread(dt, 1, (size_t)n, f) == (size_t)n, "FDT read exactly");
    fclose(f);
#define FDT(p, z, pa, base) phase4_fdt_guard(p, z, pa, 0x80000000, ARENA_BASE, INITIAL_MEMORY_LIMIT, base)
    check(FDT(dt, (unsigned)n, 0x8a100000, IMAGE_BASE), "original FDT covers memory budget");
    check(FDT(dt, (unsigned)n, 0x8a100000, LEGACY_IMAGE_BASE), "original FDT at Phase 2 placement");
    check(FDT(dt, (unsigned)n, 0x8a100000, MEASURED_IMAGE_BASE), "original FDT at accepted-carrier measured placement");
    for (unsigned z = 0; z < 40; z++) check(!FDT(dt, z, 0x8a100000, IMAGE_BASE), "short FDT rejected");
    check(!FDT(dt, (unsigned)n - 1, 0x8a100000, IMAGE_BASE), "truncated FDT rejected");
    check(!FDT(dt, (unsigned)n, ARENA_BASE, IMAGE_BASE), "FDT over arena rejected");
    check(!FDT(dt, (unsigned)n, IMAGE_BASE, IMAGE_BASE), "FDT over Image rejected");
    memcpy(mut, dt, (size_t)n); mut[0] ^= 1;
    check(!FDT(mut, (unsigned)n, 0x8a100000, IMAGE_BASE), "corrupt FDT magic rejected");
    for (unsigned i = 0; i < 1000; i++) {
        memcpy(mut, dt, (size_t)n);
        seed = seed * 1664525u + 1013904223u;
        mut[seed % (unsigned)n] ^= (unsigned char)(1u << (i % 8));
        int rc = FDT(mut, (unsigned)n, 0x8a100000, IMAGE_BASE);
        check(rc == 0 || rc == 1, "mutated original FDT remains bounded");
    }
    free(mut); free(dt);
    printf("PHASE4_VALIDATE_PASS checks=%u ASAN_UBSAN=1\n", checks);
    return 0;
}
