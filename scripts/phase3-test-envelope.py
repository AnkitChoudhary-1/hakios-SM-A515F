#!/usr/bin/env python3
"""Check retained original console bytes and reject damaged attribution/logs."""
import json
from pathlib import Path
import struct
from phase3_support import PROJECT, packet_new, packet_index, packet_verify, json_write, require
from phase3_envelope import decode


def main():
    selected = json.loads((PROJECT / "manifests/phase3-loader-qemu-full.json").read_text())
    source = PROJECT / selected["packet"]
    packet_verify(source)
    raw = (source / "console.bin").read_bytes()
    parsed = decode(raw, selected["nonce"])
    require(parsed["log"] == (source / "kernel-user.log").read_bytes() and parsed["complete_log"], "Original log replay differs")
    size = struct.unpack_from("<I", raw, 8)[0]
    direct = raw[12:12 + size]
    require(decode(direct, selected["nonce"])["log"] == parsed["log"], "Direct pstore replay differs")
    header, body = direct.split(b"\n", 1)
    log_start = direct.index(b"HAKIOS_P3_LOG_BEGIN\n") + len(b"HAKIOS_P3_LOG_BEGIN\n")
    damaged = bytearray(direct)
    damaged[log_start + 100] ^= 1
    wrong_size = bytearray(raw)
    struct.pack_into("<I", wrong_size, 4, size + 1)
    mutations = {
        "wrong-nonce": direct.replace(selected["nonce"].encode(), b"0" * 32, 1),
        "duplicate-stage": header + b" stage=5\n" + body,
        "missing-stage": b" ".join(p for p in header.split(b" ") if not p.startswith(b"stage=")) + b"\n" + body,
        "log-byte-corruption": bytes(damaged),
        "truncated-footer": direct[:-1],
        "missing-begin": direct.replace(b"HAKIOS_P3_LOG_BEGIN", b"HAKIOS_P3_LOG_BEGON", 1),
        "negative-length": b" ".join(b"copied=-1" if p.startswith(b"copied=") else p for p in header.split(b" ")) + b"\n" + body,
        "unbounded-length": b" ".join(b"requested=1572865" if p.startswith(b"requested=") else p for p in header.split(b" ")) + b"\n" + body,
        "unbounded-copy": b" ".join(b"copied=524288" if p.startswith(b"copied=") else p for p in header.split(b" ")) + b"\n" + body,
        "bad-crc": b" ".join(b"crc32=ffffffff" if p.startswith(b"crc32=") else p for p in header.split(b" ")) + b"\n" + body,
        "wrapped-header": bytes(wrong_size),
        "oversized-region": raw + b"\0",
        "empty-capture": b"",
    }
    rejected = {}
    for name, data in mutations.items():
        try:
            decode(data, selected["nonce"])
        except ValueError as exc:
            rejected[name] = str(exc)
        else:
            raise ValueError("Damaged capture accepted: " + name)
    packet = packet_new("envelope-integrity", Path(__file__))
    (packet / "phase3_envelope.py").write_bytes((PROJECT / "scripts/phase3_envelope.py").read_bytes())
    json_write(packet / "result.json", {"passed": True, "original_packet": selected["packet"],
               "nonce": selected["nonce"], "log": parsed["log_pin"], "original_replays": 2,
               "rejected": rejected, "device_operations": False, "phase_3_device_gate_passed": False})
    packet_index(packet)
    print(json.dumps({"packet": packet.relative_to(PROJECT).as_posix(), "passed": True,
                      "original_replays": 2, "corruptions_rejected": len(rejected)}), flush=True)


if __name__ == "__main__":
    main()
