#!/usr/bin/env python3
"""Retain read-only pstore attachment evidence after the restored device cycle."""
from pathlib import Path
import json
import shlex
from phase3_support import command, packet_new, packet_index, json_write


def main():
    packet = packet_new("return-inspection", Path(__file__))
    records = []
    queries = [
        ("root", "id"),
        ("boot-id", "cat /proc/sys/kernel/random/boot_id"),
        ("pstore-files", "ls -ln /sys/fs/pstore"),
        ("current-attachment", "dmesg | grep -E 'persistent_ram:|ramoops:|pstore:'"),
        ("prior-attachment", "if test -f /sys/fs/pstore/console-ramoops-0; then grep -E 'persistent_ram:|ramoops:|pstore:|HAKIOS_P3|HAKIOS_LOADER' /sys/fs/pstore/console-ramoops-0; else exit 3; fi"),
        ("configuration", "zcat /proc/config.gz | grep -E 'CONFIG_PSTORE|CONFIG_RANDOMIZE_BASE'"),
    ]
    for name, query in queries:
        command(packet, records, name, ["adb", "-s", "A51_SERIAL_HERE", "shell", "su", "-c", shlex.quote(query)], check=False)
    result = {"packet": packet.as_posix(), "device_reads": True, "device_writes": False, "reboots": 0}
    json_write(packet / "result.json", result)
    packet_index(packet)
    for name in ("pstore-files", "current-attachment", "prior-attachment", "configuration"):
        print(name + ":\n" + (packet / (name + ".stdout")).read_text(errors="replace"))
    print(json.dumps(result))


if __name__ == "__main__":
    main()
