// SPDX-License-Identifier: MIT
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <assert.h>

#define kPropNameLength 32

typedef struct DeviceTreeNodeProperty {
    char        name[kPropNameLength];
    uint32_t    length;
} DeviceTreeNodeProperty;

typedef struct OpaqueDTEntry {
    uint32_t    nProperties;
    uint32_t    nChildren;
} DeviceTreeNode;

typedef const DeviceTreeNode *RealDTEntry;

static const uint8_t *DTRootNode = NULL;
static size_t DTSize = 0;
static const uint8_t *DTEnd = NULL;
static const char *startingP = NULL;

static void SecureDTInit(const void *base, size_t size) {
    DTRootNode = (const uint8_t *)base;
    DTSize = size;
    DTEnd = DTRootNode + size;
}

static int find_entry(const char *propName, const char *propValue, RealDTEntry *entryH) {
    const DeviceTreeNode *nodeP = (const DeviceTreeNode *)(const void *)startingP;
    if ((const uint8_t *)nodeP < DTRootNode || (const uint8_t *)nodeP + sizeof(DeviceTreeNode) > DTEnd) {
        return -1;
    }
    if (nodeP->nProperties == 0) {
        return -1;
    }
    startingP = (const char *)(nodeP + 1);

    int found = 0;
    for (uint32_t k = 0; k < nodeP->nProperties; ++k) {
        const DeviceTreeNodeProperty *propP = (const DeviceTreeNodeProperty *)(const void *)startingP;
        if ((const uint8_t *)propP < DTRootNode || (const uint8_t *)propP + sizeof(*propP) > DTEnd) {
            return -1;
        }
        startingP += sizeof(*propP) + ((propP->length + 3) & ~3);

        if (strcmp(propP->name, propName) == 0) {
            if (propValue == NULL || strcmp((const char *)(propP + 1), propValue) == 0) {
                *entryH = nodeP;
                found = 1;
            }
        }
    }

    for (uint32_t k = 0; k < nodeP->nChildren; ++k) {
        if (find_entry(propName, propValue, entryH) == 0) {
            return 0;
        }
    }
    return found ? 0 : -1;
}

static const void *get_property(RealDTEntry entry, const char *name, uint32_t *len_out) {
    const char *p = (const char *)(entry + 1);
    for (uint32_t k = 0; k < entry->nProperties; ++k) {
        const DeviceTreeNodeProperty *prop = (const DeviceTreeNodeProperty *)(const void *)p;
        p += sizeof(*prop) + ((prop->length + 3) & ~3);
        if (strcmp(prop->name, name) == 0) {
            if (len_out) *len_out = prop->length;
            return (const void *)(prop + 1);
        }
    }
    return NULL;
}

static RealDTEntry find_child(RealDTEntry parent, const char *name) {
    const char *p = (const char *)(parent + 1);
    /* Skip properties */
    for (uint32_t k = 0; k < parent->nProperties; ++k) {
        const DeviceTreeNodeProperty *prop = (const DeviceTreeNodeProperty *)(const void *)p;
        p += sizeof(*prop) + ((prop->length + 3) & ~3);
    }
    /* Walk children */
    for (uint32_t k = 0; k < parent->nChildren; ++k) {
        RealDTEntry child = (RealDTEntry)(const void *)p;
        uint32_t name_len = 0;
        const char *child_name = (const char *)get_property(child, "name", &name_len);
        if (child_name && strcmp(child_name, name) == 0) {
            return child;
        }
        /* Advance past this entire child subtree */
        startingP = (const char *)child;
        RealDTEntry dummy;
        find_entry("dummy_search_for_skip", NULL, &dummy);
        p = startingP;
    }
    return NULL;
}

static RealDTEntry lookup_path(const char *path) {
    RealDTEntry cur = (RealDTEntry)DTRootNode;
    if (!path || *path != '/') return NULL;
    if (strcmp(path, "/") == 0) return cur;

    char buf[128];
    const char *p = path + 1;
    while (*p) {
        const char *slash = strchr(p, '/');
        size_t len = slash ? (size_t)(slash - p) : strlen(p);
        assert(len < sizeof(buf));
        memcpy(buf, p, len);
        buf[len] = '\0';
        cur = find_child(cur, buf);
        if (!cur) return NULL;
        if (!slash) break;
        p = slash + 1;
    }
    return cur;
}

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "usage: %s <devicetree.bin>\n", argv[0]);
        return 1;
    }

    FILE *f = fopen(argv[1], "rb");
    assert(f && "failed to open device tree file");
    fseek(f, 0, SEEK_END);
    long size = ftell(f);
    fseek(f, 0, SEEK_SET);

    uint8_t *buf = malloc(size);
    assert(buf && fread(buf, 1, size, f) == (size_t)size);
    fclose(f);

    printf("Loaded device tree: %ld bytes\n", size);
    SecureDTInit(buf, size);

    /* 1. Root checks */
    startingP = (const char *)DTRootNode;
    RealDTEntry root = NULL;
    assert(find_entry("name", "device-tree", &root) == 0);
    assert(root == (RealDTEntry)DTRootNode);

    uint32_t len = 0;
    const char *model = get_property(root, "model", &len);
    printf("Root model: %s (len %u)\n", model, len);
    assert(model && strcmp(model, "iPhone10,3") == 0);

    const char *platform = get_property(root, "platform-name", &len);
    printf("Platform: %s\n", platform);
    assert(platform && strcmp(platform, "t8015") == 0);

    /* 2. /chosen checks */
    RealDTEntry chosen = lookup_path("/chosen");
    assert(chosen && "Failed to lookup /chosen");
    const uint64_t *dram_base = get_property(chosen, "dram-base", &len);
    assert(dram_base && *dram_base == 0x80000000ULL);
    printf("chosen dram-base: 0x%lx\n", *dram_base);

    const uint32_t *debug = get_property(chosen, "debug-enabled", &len);
    assert(debug && *debug == 1);

    const void *nvram = get_property(chosen, "nvram-proxy-data", &len);
    assert(nvram && len == 0x2000);
    printf("chosen nvram-proxy-data: verified %u bytes\n", len);

    /* 3. /cpus/cpu0 checks */
    RealDTEntry cpu0 = lookup_path("/cpus/cpu0");
    assert(cpu0 && "Failed to lookup /cpus/cpu0");
    const uint64_t *tb_freq = get_property(cpu0, "timebase-frequency", &len);
    assert(tb_freq && *tb_freq == 26000000ULL);
    printf("cpu0 timebase-frequency: %lu Hz\n", *tb_freq);

    /* 4. /arm-io/gic checks */
    RealDTEntry gic = lookup_path("/arm-io/gic");
    assert(gic && "Failed to lookup /arm-io/gic");
    const char *gic_compat = get_property(gic, "compatible", &len);
    printf("gic compatible: %s\n", gic_compat);
    assert(gic_compat && strcmp(gic_compat, "arm,cortex-a15-gic") == 0);

    /* 5. /arm-io/uart0 checks */
    RealDTEntry uart0 = lookup_path("/arm-io/uart0");
    assert(uart0 && "Failed to lookup /arm-io/uart0");
    const char *uart_compat = get_property(uart0, "compatible", &len);
    printf("uart0 compatible: %s\n", uart_compat);
    assert(uart_compat && (strcmp(uart_compat, "samsung,exynos-uart") == 0 || strcmp(uart_compat, "uart-1,samsung") == 0));

    const uint32_t *boot_console = get_property(uart0, "boot-console", &len);
    assert(boot_console && *boot_console == 1);

    printf("ALL SECURE DT CHECKS PASSED (SecureDTInit & IOKit compatible) exit 0\n");
    free(buf);
    return 0;
}

