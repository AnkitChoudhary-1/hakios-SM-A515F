# A51 intermittent internet investigation — 22 November 2026

Owner report: Safari initially loads webpages, then stops. Owner answered “okay. no” to the combined error/duration/toggle question; this does not establish a precise failure interval or error text. Logs were exported through the existing diagnostic loader, with no flash, installation, network reconfiguration, shutdown or reboot. Initial and final loader status: running 0 0.

## Evidence

Capture: wifi-investigation/20261122T152915-950361Z. Source hashes and selected lines are in network-evidence.json in that folder. Snapshot logs overlap and must not be counted as independent packet histories.

- Initial retained panic record: zero at 72 seconds; joined an open network at 5180 MHz at 76 seconds.
- At 672, 732 and 792 seconds, Wi-Fi remains phase 4/error 0. Transmit counts rise 183 → 194 → 215, while receive count stays 141. Busy data blocks rise 24 → 35 → 56; firmware queue indices remain unchanged.
- The later panic record is b50ff/25002a02. The local driver interprets these fields as a panic log reference and panic ID; the exact fault has not been decoded. Do not assume the ID means HOST_NOT_RESPONSIVE merely because comments document an earlier occurrence of that condition.
- Throughout these samples, DHCP reports joined=1/up=1, IPv4 172.28.223.196, router 172.28.223.8 and populated IPv4/IPv6 DNS. Configured IP/router/DNS do not prove actual packet exchange or DNS functionality.
- At 852 seconds, phase becomes 1 and control blocks increase; at 854 seconds, MLME-DEL-VIF.cfm: -1 is recorded. In the current local source, -1 means no confirmation received before the two-second wait expired, rather than a firmware-provided rejection code. Later DHCP state shows no joined network or address.

## Assessment and targeted solution

The evidence strongly supports a stalled Wi-Fi firmware/transport after a firmware panic, rather than just loss of DHCP configuration. The exact trigger and full running-source provenance remain unverified. Safari launch/service warnings do not explain the independently stalled radio counters.

Current local devices/a51/drivers/wifi/hakios.a51wifi.c detects a changed panic record but only logs it in the service loop (around line 1970). svc_op_power (around line 1850) performs a logical leave/state change without a firmware hardware restart. This can leave the UI claiming a connection after packet exchange has stopped and explains why a toggle may fail to recover a dead firmware. These are local-source findings, not a hash-verified reconstruction of the running kernel.

A future fix should trace the panic trigger and correct its cause; stop reporting a healthy link when firmware fails; and provide bounded firmware/transport recovery with safe queue/block cleanup, restart, rejoin and DHCP reconfiguration. Recovery must coordinate all radio users and callbacks rather than clearing live buffers or repeatedly resetting hardware. Renewing DHCP alone cannot revive stalled firmware. Preserve a failure dump before recovery. Validate repeated Safari/HTTPS access, failure recovery and sustained traffic beyond the observed failure interval before claiming stability.

At the conclusion of the 22 November read-only investigation, no driver, package or phone changes had been applied. The Wi-Fi diagnosis did not establish the cause of Instagram's logo hang.

## Implementation follow-up — 23 November 2026

The bounded firmware/transport recovery candidate was installed from TWRP at 01:03:16 UTC and tested in `wifi-stability-recovery/device-tests/20261123T011048-027970Z`. See `A51-WiFi-firmware-recovery.md` for the changes, hashes and exact event evidence. Three firmware panics caused confirmed resets and resumed RX traffic at kernel times 753, 910 and 997 seconds. A fourth panic at 1095 seconds exhausted the recovery limit; the owner reported hotspot disconnection. Initial Safari success and recovery success do not establish stability: the recurrent firmware trigger remains unresolved. The collector completed without stopping/rebooting iOS. The earlier source descriptions above record the pre-fix state.

New read-only logs reproduce the same panic/stalled-RX condition while Instagram displays a post-login loading circle. Reopening Instagram produced an explicit `NSURLErrorDomain -1001` request timeout. Networking is a demonstrated problem during this hang; a separate app fault is still possible.
