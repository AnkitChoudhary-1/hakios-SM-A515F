"""Apply the scoped Wi-Fi changes to snapshotted sources; no device operations."""
from pathlib import Path

REPO = Path(r'\\wsl.localhost\A51-KernelBuilder\opt\a51-hakios\upstream-a51\hakios')
def replace(text, old, new):
    assert text.count(old) == 1, (old[:100], text.count(old))
    return text.replace(old, new)

p = REPO / 'drivers/wifi/hakios.sta.c'
s = p.read_text()
s = replace(s, 'static bool sta_on;', 'static bool sta_recovering;\nstatic struct hakios_sta_join reconnect; /* last requested network; cleared on explicit leave */\nstatic bool sta_on;')
s = replace(s, 'while (sta_ops == NULL || !(asked_power', 'while (sta_ops == NULL || sta_recovering || !(asked_power')
s = replace(s, 'if (error != 0 && fallback.ssid_length', 'if (!sta_recovering && error != 0 && fallback.ssid_length')
s = replace(s, 'busy = sta_ops != NULL && (sta_calls', 'busy = sta_ops != NULL && (sta_recovering || sta_calls')
s = replace(s, 'asked_join_what = *what;\n\tasked_join = true;', 'reconnect = asked_join_what = *what;\n\tasked_join = true;')
s = replace(s, 'asked_leave = true;\n\tasked_join = false;', 'asked_leave = true;\n\tasked_join = false;\n\tbzero(&reconnect, sizeof(reconnect));')
s = replace(s, 'if ((ops = sta_ops) != NULL) {', 'ops = sta_recovering ? NULL : sta_ops;\n\tif (sta_recovering) {\n\t\tstate->phase = sta_on ? HAKIOS_STA_IDLE : HAKIOS_STA_OFF;\n\t\tstate->last_error = EIO;\n\t}\n\tif (ops != NULL) {')
s = replace(s, 'void\nhakios_sta_lost(int error)', '''/* The driver first blocks sends and cancels its bounded waits. Keep requests and
 * the user's power selection while draining callbacks before shared memory is reset. */
void
hakios_sta_recovery_begin(void)
{
\tlck_mtx_lock(&sta_lock);
\tsta_recovering = true;
\twhile (sta_calls || sta_reads != 0) {
\t\tlck_mtx_sleep(&sta_lock, LCK_SLEEP_DEFAULT, (event_t)&sta_calls, THREAD_UNINT);
\t}
\theard_count = 0;
\tlck_mtx_unlock(&sta_lock);
}

void
hakios_sta_recovery_end(void)
{
\tlck_mtx_lock(&sta_lock);
\t/* Power-off and leave take precedence over rejoining. A newer explicit join wins. */
\tif (sta_on && !asked_join && !asked_leave && reconnect.ssid_length != 0) {
\t\tasked_join_what = reconnect;
\t\tasked_join = true;
\t}
\tsta_recovering = false;
\tlck_mtx_unlock(&sta_lock);
\tthread_wakeup((event_t)&sta_ops);
}

void
hakios_sta_lost(int error)''')
p.write_text(s, newline='\n')
p = REPO / 'xnu/files/bsd/sys/hakios.sta.h'
s = p.read_text()
s = replace(s, 'void     hakios_sta_lost(int error);', 'void     hakios_sta_recovery_begin(void); /* drain callbacks; requests/power remain queued */\nvoid     hakios_sta_recovery_end(void);   /* resume after transport is ready; rejoin desired network */\nvoid     hakios_sta_lost(int error);')
p.write_text(s, newline='\n')

p = REPO / 'devices/a51/drivers/wifi/hakios.a51wifi.c'
s = p.read_text()
s = replace(s, 'static uint32_t wifi_steps;', '''static bool wifi_recovering, wifi_transport_fault, svc_attached;
static unsigned wifi_restarts;
static uint32_t wifi_steps;''')
s = replace(s, 'static bool svc_on;', 'static volatile bool svc_on;')
s = replace(s, '\tif (svc_on) {\n\t\treturn svc_send', '\tif (wifi_steps >= 8) {\n\t\treturn svc_send') if '\tif (svc_on) {\n\t\treturn svc_send' in s else s
# link_send's exact shape is checked below after this edit.
s = replace(s, '\tlck_mtx_lock(&svc_lock);\n\tcache_out(h + HIP_SCOREBOARD, 128);', '\tlck_mtx_lock(&svc_lock);\n\tif (!svc_on) {\n\t\tlck_mtx_unlock(&svc_lock);\n\t\treturn;\n\t}\n\tcache_out(h + HIP_SCOREBOARD, 128);')
s = replace(s, '\tlck_mtx_lock(&svc_lock);\n\tint b = data', '\tlck_mtx_lock(&svc_lock);\n\tif (!svc_on) {\n\t\tlck_mtx_unlock(&svc_lock);\n\t\treturn false;\n\t}\n\tint b = data')
s = replace(s, 'ms < 2000 && svc_vif_cfm < 0', 'ms < 2000 && svc_on && svc_vif_cfm < 0')
s = replace(s, 'ms < 20000 && !scan_done', 'ms < 20000 && svc_on && !scan_done')
s = replace(s, '\treturn scan_cfm > 0 ? EIO : 0;', '\treturn !svc_on ? EIO : scan_cfm > 0 ? EIO : 0;')
s = replace(s, '\tfor (int ms = 0; ms < 20000; ms += 20) {\n\t\tif (link.connected)', '\tfor (int ms = 0; ms < 20000; ms += 20) {\n\t\tif (!svc_on) { error = EIO; break; }\n\t\tif (link.connected)')
s = replace(s, 'svc_op_join(const struct hakios_sta_join *what)\n{', 'svc_op_join(const struct hakios_sta_join *what)\n{\n\tif (!svc_on) { return EIO; }')
s = replace(s, 'svc_join_one(const struct hakios_sta_join *what, uint8_t *tried)\n{', 'svc_join_one(const struct hakios_sta_join *what, uint8_t *tried)\n{\n\tif (!svc_on) { return EIO; }')
s = replace(s, 'svc_disconnect(void)\n{', 'svc_disconnect(void)\n{\n\tif (!svc_on) { return; }')
s = replace(s, '\thakios_sta_attach(&svc_ops);', '\tif (!svc_attached) {\n\t\thakios_sta_attach(&svc_ops);\n\t\tsvc_attached = true;\n\t} else {\n\t\thakios_sta_recovery_end();\n\t}\n\twifi_recovering = false;')
s = replace(s, '\tif (wifi_conf(ssid, sizeof(ssid), psk, sizeof(psk), pmk, &have_pmk, &open)) {', '\tif (wifi_restarts == 0 && wifi_conf(ssid, sizeof(ssid), psk, sizeof(psk), pmk, &have_pmk, &open)) {')
s = replace(s, '\tsvc_mbox = mbox;\n\tbzero(ctl_used', '\tsvc_mbox = mbox;\n\tctl_next = dat_next = 0;\n\tsvc.dat_busy = 0;\n\tscan_count = 0;\n\tsvc_vif_lost = false;\n\twifi_transport_fault = false;\n\tbzero(ctl_used')
start = s.index('\tuint32_t panic_seen = 0;', s.index('svc_run(vm_offset_t mbox)'))
end = s.index('\t\tsvc_reclaim();\n\t\tlink_progress();', start)
s = s[:start] + '''\tuint64_t checked = 0, progress = now_ms();
\tuint8_t previous[6] = {0};
\tfor (;;) {
\t\tif (now_ms() - checked >= 1000) {
\t\t\tchecked = now_ms();
\t\t\tif (wifi_panic_valid()) {
\t\t\t\twifi_fault(mbox, "validated firmware panic");
\t\t\t\treturn;
\t\t\t}
\t\t\tuint8_t firmware[6];
\t\t\tbool pending;
\t\t\tlck_mtx_lock(&svc_lock);
\t\t\tcache_out(h + HIP_SCOREBOARD, 128);
\t\t\tmemcpy(firmware, (const void *)(h + HIP_SCOREBOARD + 64), 6);
\t\t\tpending = *(volatile uint8_t *)(h + HIP_SCOREBOARD + Q_FH_CTRL) != firmware[Q_FH_CTRL] ||
\t\t\t    *(volatile uint8_t *)(h + HIP_SCOREBOARD + Q_FH_DAT) != firmware[Q_FH_DAT] ||
\t\t\t    *(volatile uint8_t *)(h + HIP_SCOREBOARD + Q_TH_RFB) != firmware[Q_TH_RFB];
\t\t\tlck_mtx_unlock(&svc_lock);
\t\t\tif (!pending || memcmp(previous, firmware, 6) != 0) { progress = checked; }
\t\t\tmemcpy(previous, firmware, 6);
\t\t\t/* No reset for an idle hotspot: outstanding queues AND no firmware progress are required. */
\t\t\tif (pending && checked - progress >= 15000) {
\t\t\t\twifi_fault(mbox, "outstanding HIP queues stalled for 15 seconds");
\t\t\t\treturn;
\t\t\t}
\t\t}
\t\t/* Every configured to-host stream must be acknowledged and consumed, not only HIP bit 7. */
\t\twr(mbox + MBOX_INTCR0, 0xffu << 16);
\t\twifi_aux_service(mbox);
\t\tuint32_t got = hip_take(mbox, Q_TH_CTRL, svc_take) + hip_take(mbox, Q_TH_DAT, svc_take);
\t\tif (wifi_transport_fault) { wifi_fault(mbox, "invalid/full transport ring"); return; }
''' + s[end:]
helpers = '''/* Retain a small binary log tail for a failure dump; do not print firmware log payloads live. */
static uint32_t wifi_log_tail[64], wifi_log_words;

static void
wifi_aux_drain(vm_offset_t mbox, uint32_t ring, uint32_t index, uint32_t count, uint32_t size, unsigned bit, bool logs)
{
\tvm_offset_t mx = wlbt_memory + mx_heap;
\tcache_out(mx + index, 8);
\tuint32_t r = rd(mx + index), w = rd(mx + index + 4);
\tif (r >= count || w >= count) { wifi_transport_fault = true; return; }
\tfor (unsigned budget = 0; r != w && budget < count; budget++) {
\t\tvm_offset_t packet = mx + ring + r * size;
\t\tcache_out(packet, size);
\t\tif (logs) { wifi_log_tail[wifi_log_words++ % 64] = rd(packet); }
\t\telse if (ring == MX_TOAP_RING) {
\t\t\tconst uint8_t *p = (const uint8_t *)packet;
\t\t\tsvc_event("management channel %u message %u", p[0], p[1]);
\t\t\tif (p[0] == 0 && p[1] == 9) { wifi_transport_fault = true; } /* MM_SYSERR_IND */
\t\t}
\t\tr = (r + 1) % count;
\t}
\tif (r != rd(mx + index)) {
\t\tw32(mx + index, r);
\t\tcache_out(mx + index, 4);
\t\twr(mbox + MBOX_INTGR1, 1u << bit);
\t}
}

static void
wifi_aux_service(vm_offset_t mbox)
{
\twifi_aux_drain(mbox, MX_TOAP_RING, MX_TOAP_RIDX, MX_PACKETS, MX_PACKET_SIZE, 1, false);
\twifi_aux_drain(mbox, 0x1000, 0x1800, 512, 4, 3, false);
\twifi_aux_drain(mbox, 0x3000, 0x3800, 512, 4, 1, false);
\twifi_aux_drain(mbox, 0x5000, 0x9000, 4096, 4, 4, true);
}

/* Samsung fw_panic_record.c: version 2, byte length, XOR checksum seeded a5a5a5a5.
 * Bounds and checksum avoid resetting the radio while the record is only partly written. */
static bool
wifi_panic_valid(void)
{
\tuint32_t record[256];
\tif (!runtime_panic_offset || runtime_panic_offset > WLBT_MEMORY - sizeof(record)) { return false; }
\tcache_out(wlbt_memory + runtime_panic_offset, sizeof(record));
\tmemcpy(record, (const void *)(wlbt_memory + runtime_panic_offset), sizeof(record));
\tuint32_t bytes = record[1];
\tif (record[0] != 2 || bytes < 20 || bytes >= sizeof(record) || (bytes & 3)) { return false; }
\tuint32_t sum = 0xa5a5a5a5;
\tfor (unsigned i = 0; i < bytes / 4 - 1; i++) { sum ^= record[i]; }
\treturn sum == record[bytes / 4 - 1] && (record[2] || record[3]);
}

static void
wifi_fault(vm_offset_t mbox, const char *reason)
{
\t/* Publish the send/reclaim gate under the same lock as all queue producers. */
\tlck_mtx_lock(&svc_lock);
\tsvc_on = false;
\tlck_mtx_unlock(&svc_lock);
\twifi_recovering = true;
\thakios_net_link_state(false);
\thakios_sta_lost(EIO);
\thakios_sta_recovery_begin(); /* bounded operation waits abort when svc_on becomes false */
\tlink.connected = false;
\tsvc.phase = HAKIOS_STA_IDLE;
\tsvc.last_error = EIO;
\ta51wpa_forget();
\tsvc_event("radio recovery: %s; attempt %u/3, tx %llu rx %llu mailbox %x", reason,
\t    wifi_restarts + 1, svc.sent, svc.received, rd(mbox + MBOX_INTSR0));
\twifi_dump[0] = 0;
\tif (runtime_panic_offset && runtime_panic_offset <= WLBT_MEMORY - 1024) {
\t\tcache_out(wlbt_memory + runtime_panic_offset, 1024);
\t\tdump_words("recovery-panic", (const uint32_t *)(wlbt_memory + runtime_panic_offset), 256);
\t}
\tdump_words("recovery-log-tail", wifi_log_tail, 64);
\tprintf("%s", wifi_dump);
}

'''
s = replace(s, '/* The driver\'s thread from here on. */', helpers + '/* The driver\'s thread from here on. */')
s = replace(s, 'vm_offset_t pmu = ml_io_map(PMU_PHYS, 0x1000), mbox', 'vm_offset_t pmu = ml_io_map(PMU_PHYS, 0x2000), mbox')
s = replace(s, 'if ((rd(pmu + CENTRAL_SEQ_WLBT_STATUS) >> 16 & 0xff) != 0 || (rd(pmu + WLBT_CTRL_S) & WLBT_START)) {', 'uint32_t sequencer = (rd(pmu + CENTRAL_SEQ_WLBT_STATUS) >> 16) & 0xff;\n\tif (sequencer != (wifi_restarts ? 0x80u : 0u) || (!wifi_restarts && (rd(pmu + WLBT_CTRL_S) & WLBT_START))) {')
s = replace(s, '\tmemcpy((void *)wlbt_memory, fw, (size_t)size);', '\tbzero((void *)wlbt_memory, WLBT_MEMORY); /* only after verified reset/initial stopped state */\n\tmemcpy((void *)wlbt_memory, fw, (size_t)size);')
s = replace(s, '\t\t\t\tsvc_run(mbox);                  /* (does not return) */', '\t\t\t\tsvc_run(mbox); /* returns only after quiescing for firmware recovery */\n\t\t\t\treturn;')
reset = '''/* Exact Exynos9610 Samsung platform_mif_pmu_reset(case 2) register sequence.
 * Never clear/reuse the shared memory unless the sequencer confirms state 0x80. */
static bool
wifi_reset(void)
{
\tvm_offset_t pmu = ml_io_map(PMU_PHYS, 0x2000);
\tif (!pmu) { return false; }
\twr(pmu + WLBT_CTRL_NS, rd(pmu + WLBT_CTRL_NS) | MASK_PWR_REQ);
\twr(pmu + CENTRAL_SEQ_WLBT_CONFIGURATION, rd(pmu + CENTRAL_SEQ_WLBT_CONFIGURATION) & ~(1u << 16));
\tstatic const uint32_t config[][3] = {
\t    {0x1360, 3, 0}, {0x1364, 1, 0}, {0x1368, 3, 0},
\t    {0x136c, 1, 0}, {0x1370, 1, 1}, {0x1374, 1, 0},
\t};
\tfor (unsigned i = 0; i < sizeof(config)/sizeof(config[0]); i++) {
\t\twr(pmu + config[i][0], (rd(pmu + config[i][0]) & ~config[i][1]) | config[i][2]);
\t}
\twr(pmu + WLBT_CTRL_NS, rd(pmu + WLBT_CTRL_NS) | WLBT_RESET_SET);
\t__asm__ volatile ("dsb sy");
\tfor (unsigned ms = 0; ms < 500; ms += 10) {
\t\tif (((rd(pmu + CENTRAL_SEQ_WLBT_STATUS) >> 16) & 0xff) == 0x80) {
\t\t\twr(pmu + WLBT_CTRL_NS, rd(pmu + WLBT_CTRL_NS) & ~MASK_PWR_REQ);
\t\t\tsvc_event("radio reset confirmed: sequencer 0x80");
\t\t\treturn true;
\t\t}
\t\tIOSleep(10);
\t}
\tsvc_event("radio reset TIMEOUT: status %x debug %x; shared memory retained",
\t    rd(pmu + CENTRAL_SEQ_WLBT_STATUS), rd(pmu + WLBT_DEBUG));
\treturn false;
}

'''
s = replace(s, '/* Step 1\'s second half, once the small image is there:', reset + '/* Step 1\'s second half, once the small image is there:')
s = replace(s, '\t\twifi_step2(fw, size);\n\t}', '''\t\tfor (;;) {
\t\t\twifi_step2(fw, size);
\t\t\tif (!wifi_recovering) { break; }
\t\t\tif (wifi_restarts >= 3) { svc_event("radio recovery exhausted (3 restarts); reboot required"); break; }
\t\t\tif (!wifi_reset()) { break; }
\t\t\twifi_restarts++;
\t\t\tIOSleep(wifi_restarts * 5000);
\t\t}
\t}''')
# Reject invalid firmware before attempting allocations/start; reset uses this same immutable image.
s = replace(s, '\t\t/* the core\'s 16 MB, in one piece', '''\t\tif (!magic || !header_ok || !const_ok || !fw_ok || size > WLBT_MEMORY ||
\t\t    runtime < size || runtime > WLBT_MEMORY - MX_HEAP_SIZE - HIP_TOTAL - 8192) {
\t\t\twifi_said("firmware bounds/CRC invalid: refusing radio start");
\t\t\treturn;
\t\t}
\t\t/* the core's 16 MB, in one piece''')
p.write_text(s, newline='\n')
print('Applied channel servicing, panic/stall recovery, and station quiescence changes.')
