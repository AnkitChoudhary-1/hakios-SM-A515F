"""Bounded read-only USB observation. Never starts/stops/reboots the phone."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import time

from run_diagnostic import Loader


def summarize(path):
    raw = path.read_bytes()
    lines = raw.decode(errors="replace").splitlines()
    wifi = []
    url_errors = []
    app_starts = []
    for number, line in enumerate(lines, 1):
        if line.startswith(("tl: wifi", "net_test: DHCP", "tl: net DHCP")):
            wifi.append({"line": number, "text": line})
        if "NSURLErrorDomain" in line:
            code = re.search(r"(?:Code[= :]+|NSURLErrorDomain\s+)(-?\d+)", line)
            if code:
                # Save only status/time, never request URLs, tokens or userInfo.
                timestamp = re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?", line)
                url_errors.append({"line": number, "code": int(code[1]),
                                   "time": timestamp[0] if timestamp else None})
        if "Instagram: started as uid" in line:
            app_starts.append({"line": number, "text": line})
    return {"log": path.name, "sha256": hashlib.sha256(raw).hexdigest(),
            "wifi": wifi, "url_errors": url_errors, "instagram_starts": app_starts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-dir", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=900)
    parser.add_argument("--interval", type=int, default=45)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 3600 or not 10 <= args.interval <= 60:
        parser.error("seconds must be 1..3600 and interval 10..60")
    folder = args.package_dir.resolve() / "device-tests" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S-%fZ")
    folder.mkdir(parents=True)
    record = {"started_at_utc": datetime.now(timezone.utc).isoformat(),
              "host_collection_seconds": args.seconds, "interval_seconds": args.interval,
              "phone_partition_writes": False, "kernel_start_requested": False,
              "stop_or_reboot_requested": False, "snapshots": []}
    target = folder / "collection.json"
    loader = Loader(folder)
    print(f"Read-only monitoring: {folder}", flush=True)
    try:
        loader.verify()
        start = time.monotonic()
        count = 0
        while True:
            state = loader.variable("result")
            name = f"snapshot-{count:03}"
            loader.log(name)
            summary = summarize(folder / (name + ".txt"))
            summary.update({"at_utc": datetime.now(timezone.utc).isoformat(),
                            "elapsed_seconds": round(time.monotonic() - start, 2),
                            "loader_result": state})
            if state.startswith("running") and count % 2 == 0:
                loader.screenshot(name)
                summary["screenshot"] = name + ".png"
            record["snapshots"].append(summary)
            target.write_text(json.dumps(record, indent=2) + "\n")
            stats = [item["text"] for item in summary["wifi"]
                     if re.search(r"phase \d+ error", item["text"])]
            print(f"{summary['elapsed_seconds']:.0f}s: {state}; " +
                  (stats[-1] if stats else "no packet sample yet"), flush=True)
            previous_events = {item['text'] for prior in record['snapshots'][:-1]
                               for item in prior['wifi']}
            for item in summary['wifi']:
                if item['text'] not in previous_events and re.search(
                        r'radio recovery:|radio reset confirmed:|radio recovery exhausted', item['text']):
                    print(item['text'], flush=True)
            remaining = args.seconds - (time.monotonic() - start)
            if not state.startswith("running") or remaining <= 0:
                break
            count += 1
            time.sleep(min(args.interval, remaining))
        record["collection_completed"] = True
    except Exception as error:
        record["error"] = str(error)
        raise
    finally:
        record["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        target.write_text(json.dumps(record, indent=2) + "\n")
        print("Host collection ended. No stop or reboot sent.", flush=True)


if __name__ == "__main__":
    main()
