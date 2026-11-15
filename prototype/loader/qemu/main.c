#include "probe.h"
#include "identity.h"

/* Nonzero initializer keeps the assembly entry record outside cleared BSS. */
struct hp_entry boot_entry = { .current_el = UINT64_MAX };
static uint8_t arena[4096] __attribute__((aligned(16)));
static const uint8_t input[16] = "HAKIOS-PROBE-v1!";
static uint32_t returned;
static void uart_char(char c) {
    volatile uint32_t *uart = (volatile uint32_t *)(uintptr_t)0x09000000;
    while (uart[6] & (1u << 5)) { }
    uart[0] = (uint32_t)(unsigned char)c;
}
static void uart(const char *s) { while (*s) uart_char(*s++); }
static void hex(const uint8_t *p, size_t n) {
    static const char digits[] = "0123456789abcdef";
    while (n--) { uart_char(digits[*p >> 4]); uart_char(digits[*p++ & 15]); }
}
static int32_t payload(struct hp_payload_view *v, void *context) {
    (void)context;
    if (v->size != sizeof input || v->fuel <= sizeof input) return -1;
    for (size_t i = 0; i < sizeof input; i++) {
        if (v->bytes[i] != input[i]) return -2;
        --v->fuel;
    }
    for (size_t i = 0; i < v->bss_size; i++) if (v->bss[i]) return -3;
    v->bss[0] = 0x51;
    return 0;
}
static int32_t return_simulation(uint32_t status, void *context) {
    (void)context;
    returned = status == HP_OK;
    return returned ? 0 : -1;
}
static void poweroff(void) {
    /* QEMU virt direct-boot PSCI HVC SYSTEM_OFF, not an Exynos reset route. */
    register uint64_t call asm("x0") = 0x84000008;
    asm volatile("hvc #0" : "+r"(call) : : "memory");
}
void qemu_main(void) {
    uart("HAKIOS_QEMU_PROBE_V1\n");
    if (boot_entry.current_el != 1) { uart("QEMU_PROBE_BAD_EL\n"); poweroff(); return; }
    const struct hp_plan plan = {
        .version = HP_VERSION, .mode = HP_QEMU_VIRT, .entry_flags = HP_ENTRY_FLAGS_ALL,
        .entry = boot_entry,
        .build_sha256 = HP_BUILD_SHA256, .input_sha256 = HP_INPUT_SHA256,
        /* This prototype does not consume the firmware-supplied FDT. */
        .region = { {0, 16}, {256, 256}, {512, 256}, {768, 256}, {1024, 1792} },
        .fuel = 64
    };
    for (size_t i = 0; i < sizeof arena; i++) arena[i] = 0xa5;
    for (size_t i = 0; i < sizeof input; i++) arena[i] = input[i];
    const struct hp_callbacks callbacks = { payload, return_simulation, 0 };
    struct hp_result result = hp_run(arena, sizeof arena, &plan, &callbacks);
    int valid = result.status == HP_OK && result.frames == HP_FRAME_COUNT &&
        result.payload_called && result.return_called && returned && result.fuel_remaining == 48;
    for (uint32_t i = 0; i < result.frames; i++) {
        const uint8_t *f = arena + 1024 + i * HP_FRAME_SIZE;
        valid = valid && hp_frame_valid(f, HP_FRAME_SIZE, i);
        uart("FRAME "); hex(f, HP_FRAME_SIZE); uart("\n");
    }
    uart(valid ? "QEMU_PROBE_PASS\n" : "QEMU_PROBE_FAIL\n");
    poweroff();
}
