#!/usr/bin/env python3
import subprocess

code = r"""#include <stdio.h>
#include <stddef.h>
#include <stdint.h>

struct Boot_Video {
	unsigned long   v_baseAddr;
	unsigned long   v_display;
	unsigned long   v_rowBytes;
	unsigned long   v_width;
	unsigned long   v_height;
	unsigned long   v_depth;
};

#define BOOT_LINE_LENGTH 608

typedef struct boot_args {
	uint16_t                Revision;
	uint16_t                Version;
	uint64_t                virtBase;
	uint64_t                physBase;
	uint64_t                memSize;
	uint64_t                topOfKernelData;
	struct Boot_Video       Video;
	uint32_t                machineType;
	void                    *deviceTreeP;
	uint32_t                deviceTreeLength;
	char                    CommandLine[BOOT_LINE_LENGTH];
	uint64_t                bootFlags;
	uint64_t                memSizeActual;
} boot_args;

int main() {
    printf("sizeof(boot_args): %zu\n", sizeof(boot_args));
    printf("offsetof Revision: %zu\n", offsetof(boot_args, Revision));
    printf("offsetof Version: %zu\n", offsetof(boot_args, Version));
    printf("offsetof virtBase: %zu\n", offsetof(boot_args, virtBase));
    printf("offsetof physBase: %zu\n", offsetof(boot_args, physBase));
    printf("offsetof memSize: %zu\n", offsetof(boot_args, memSize));
    printf("offsetof topOfKernelData: %zu\n", offsetof(boot_args, topOfKernelData));
    printf("offsetof Video: %zu\n", offsetof(boot_args, Video));
    printf("offsetof machineType: %zu\n", offsetof(boot_args, machineType));
    printf("offsetof deviceTreeP: %zu\n", offsetof(boot_args, deviceTreeP));
    printf("offsetof deviceTreeLength: %zu\n", offsetof(boot_args, deviceTreeLength));
    printf("offsetof CommandLine: %zu\n", offsetof(boot_args, CommandLine));
    printf("offsetof bootFlags: %zu\n", offsetof(boot_args, bootFlags));
    printf("offsetof memSizeActual: %zu\n", offsetof(boot_args, memSizeActual));
    return 0;
}
"""

def main():
    with open('/tmp/test_boot_args.c', 'w') as f:
        f.write(code)
    subprocess.run(['gcc', '/tmp/test_boot_args.c', '-o', '/tmp/test_boot_args'], check=True)
    res = subprocess.run(['/tmp/test_boot_args'], capture_output=True, text=True, check=True)
    print(res.stdout)

if __name__ == '__main__':
    main()

