"""Summarize a completed read-only collection, validating retained fault records."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re


RECOVERY = re.compile(
    r"^tl: wifi at (\d+)s radio recovery: (.*); attempt (\d+)/(\d+), "
    r"tx (\d+) rx (\d+) mailbox ([0-9a-f]+)$")
WORDS = re.compile(r"^tl: wifi fault r4-panic ([0-9a-f]+):((?: [0-9a-f]{8})+)$")


def summarize(folder):
    collection_path = folder / "collection.json"
    collection_bytes = collection_path.read_bytes()
    collection = json.loads(collection_bytes)
    if not collection.get("collection_completed") or collection.get("error"):
        raise ValueError("Collection is incomplete or reports an error")
    if collection.get("stop_or_reboot_requested") is not False:
        raise ValueError("Unexpected stop/reboot flag")
    events, seen, failures, captures, errors = [], set(), {}, [], []
    for snapshot in collection["snapshots"]:
        raw = (folder / snapshot["log"]).read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != snapshot["sha256"]:
            raise ValueError(f"Snapshot hash changed: {snapshot['log']}")
        lines = raw.decode(errors="replace").splitlines()
        captures.append({key: snapshot[key] for key in
                         ("log", "sha256", "at_utc", "elapsed_seconds", "loader_result")})
        for item in snapshot["wifi"]:
            number, line = item["line"], item["text"]
            if lines[number - 1] != line:
                raise ValueError("Stored line reference differs from raw log")
            ref = {"log": snapshot["log"], "line": number, "text": line}
            if line not in seen:
                events.append(ref)
                seen.add(line)
            match = RECOVERY.fullmatch(line)
            if not match:
                continue
            kernel_time, reason, attempt, limit, tx, rx, mailbox = match.groups()
            key = (int(kernel_time), int(attempt))
            if key in failures:
                continue
            parts, part_refs, queue = {}, [], None
            # Fault tracing immediately follows the recovery line. Other log
            # messages can interleave, so stop at the next recovery event.
            for next_number in range(number, min(number + 150, len(lines))):
                next_line = lines[next_number]
                if RECOVERY.fullmatch(next_line):
                    break
                word_match = WORDS.fullmatch(next_line)
                if word_match:
                    offset = int(word_match[1], 16)
                    if offset & 3 or offset in parts:
                        break
                    parts[offset] = [int(word, 16) for word in word_match[2].split()]
                    part_refs.append({"log": snapshot["log"], "line": next_number + 1})
                if next_line.startswith("tl: wifi fault queues "):
                    queue = {"log": snapshot["log"], "line": next_number + 1,
                             "text": next_line}
                    break
            words, expected_offset = [], 0
            for offset, part in sorted(parts.items()):
                if offset != expected_offset:
                    raise ValueError("Panic record has a missing or overlapping fragment")
                words.extend(part)
                expected_offset += len(part) * 4
            if not words:
                continue  # A later snapshot may retain the complete event.
            if len(words) < 5 or words[0] != 2 or words[1] != len(words) * 4:
                raise ValueError("Incomplete or unexpected version-2 panic record")
            checksum = 0xA5A5A5A5
            for word in words[:-1]:
                checksum ^= word
            if checksum != words[-1]:
                raise ValueError("Panic record checksum mismatch")
            # Samsung mxman.c uses word 3 in the 53/54-word version-2 layout.
            code = words[3] if len(words) in (53, 54) else None
            failures[key] = {
                "kernel_seconds": int(kernel_time), "reason": reason,
                "attempt": int(attempt), "restart_limit": int(limit),
                "tx": int(tx), "rx": int(rx), "raw_mailbox_status": int(mailbox, 16),
                "event": ref, "record_evidence": part_refs, "queues": queue,
                "record_version": words[0], "record_bytes": words[1],
                "record_words": [f"{word:08x}" for word in words],
                "checksum_valid": True, "full_panic_code": f"{code:08x}" if code is not None else None,
                "optional_stack_field_precedes_checksum": len(words) > 53,
                "fault_reason_decoded": False,
            }
        # Error entries contain only status/time, never request URLs or tokens.
        errors.extend({"log": snapshot["log"], **item} for item in snapshot["url_errors"])
    recovery_count = sum(bool(RECOVERY.fullmatch(e["text"])) for e in events)
    if len(failures) != recovery_count:
        raise ValueError("A recovery event lacks a complete validated fault record")
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "collection": {"file": collection_path.name,
                       "sha256": hashlib.sha256(collection_bytes).hexdigest(),
                       **{key: collection[key] for key in
                          ("started_at_utc", "finished_at_utc", "host_collection_seconds",
                           "interval_seconds", "collection_completed", "phone_partition_writes",
                           "kernel_start_requested", "stop_or_reboot_requested")}},
        "snapshot_count": len(captures), "captures": captures,
        "last_loader_result": captures[-1]["loader_result"],
        "last_elapsed_seconds": captures[-1]["elapsed_seconds"],
        "failures": sorted(failures.values(), key=lambda e: e["kernel_seconds"]),
        "unique_wifi_events": events, "url_error_observations": errors,
        "stable_internet_demonstrated": False,
        "instagram_feed_loading_demonstrated": False,
        "user_observations": [
            {"response": "yes workimg", "interpretation": "Safari loaded after recovery; Instagram status unclear"}
        ],
        "limits": [
            "Overlapping snapshots are deduplicated by complete Wi-Fi event text.",
            "Raw firmware records establish panics; numeric code alone does not identify their trigger.",
            "Host collection ending does not stop or reboot iOS.",
            "Association, DHCP state, RX progress and one Safari success do not establish sustained stability."
        ],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    args = parser.parse_args()
    evidence = summarize(args.folder.resolve())
    target = args.folder / "runtime-evidence.json"
    target.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"file": str(target), "snapshots": evidence["snapshot_count"],
                      "failures": len(evidence["failures"]),
                      "last_loader_result": evidence["last_loader_result"]}))
