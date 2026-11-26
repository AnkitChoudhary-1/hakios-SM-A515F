"""Summarize saved diagnostic snapshots; no phone commands or success assumptions."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import statistics
import subprocess
import sys


def percentile(values, p):
    ordered = sorted(values)
    return ordered[round((len(ordered)-1)*p)] if ordered else None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('run', type=Path)
    ap.add_argument('--feedback', required=True)
    args = ap.parse_args()
    logs = sorted(args.run.glob('log-*.txt'))
    if not logs:
        ap.error('No snapshots found')
    rows, traces, capacities, failed = set(), set(), set(), set()
    manifest = json.loads((args.run/'test-manifest.json').read_text(encoding='utf-8'))
    for path in logs:
        for row in path.read_text(encoding='utf-8', errors='replace').splitlines():
            rows.add(row)
            match = re.search(r'IOSurface binding capacity (\d+), live (\d+)', row)
            if match:
                capacities.add((int(match[1]), int(match[2])))
            match = re.search(r'(?:-texImageIOSurface:.*texture|-attachImage: texture) (\d+).*not done', row)
            if match:
                failed.add(int(match[1]))
            at = row.find('tl: ')
            if at >= 0:
                traces.add(row[at:].strip())
    shows, swaps, gestures = {}, {}, set()
    for row in traces:
        w = row.split()
        try:
            if w[1] == 'v' and len(w) >= 9:
                shows[int(w[2])] = int(w[8])
            elif w[1] == 's' and len(w) >= 5:
                swaps[int(w[2])] = int(w[4])
            elif w[1] == 'p' and len(w) >= 8 and int(w[2]) in (1, 4):
                gestures.add(int(w[7]))
        except (ValueError, IndexError):
            continue
    times = sorted(shows[sid] for sid in shows if sid in swaps)
    windows = []
    gestures = sorted(gestures)
    for i, start in enumerate(gestures):
        end = min(gestures[i+1] if i+1 < len(gestures) else start+2500000, start+2500000)
        selected = [t for t in times if start <= t < end]
        gaps = [b-a for a, b in zip(selected, selected[1:]) if b > a]
        if not gaps:
            continue
        windows.append(dict(start_us=start, end_us=end, traced_frames=len(selected), steps=len(gaps),
                            copy_fps_including_all_observed_gaps=1000000 * len(gaps) / sum(gaps),
                            median_gap_ms=statistics.median(gaps)/1000,
                            p95_gap_ms=percentile(gaps, .95)/1000,
                            maximum_gap_ms=max(gaps)/1000,
                            gaps_over_20ms=sum(x > 20000 for x in gaps),
                            gaps_over_34_5ms=sum(x > 34500 for x in gaps),
                            gaps_over_100ms=sum(x > 100000 for x in gaps)))
    analysis = subprocess.run([sys.executable, str(Path(__file__).with_name('analyze-a51-frames.py')),
                               *map(str, logs)], capture_output=True, text=True, encoding='utf-8', check=True)
    (args.run/'frame-analysis.txt').write_text(analysis.stdout, encoding='utf-8')
    evidence = dict(updated_at_utc=datetime.now(timezone.utc).isoformat(),
                    owner_feedback=args.feedback, collector_manifest=manifest,
                    observed_capacities=[dict(capacity=c, live_before_growth=n) for c, n in sorted(capacities)],
                    table_exhaustion_observed=any('more textures with IOSurfaces' in row for row in rows),
                    allocation_failure_observed=any('IOSurface binding allocation failed' in row for row in rows),
                    distinct_failed_attachment_texture_ids=sorted(failed),
                    shown_frame_trace_count=len(times), gesture_trace_count=len(gestures),
                    gesture_gap_windows_including_long_stalls=windows,
                    navigation_verified=False, black_boxes_fixed_on_hardware=False,
                    sustained_50_60_fps_verified=False, speaker_playback_implemented=False,
                    limitations=['Snapshots can lose events; absence of a warning is limited to captured logs.',
                                 'Trace FPS counts framebuffer copy completions, not distinct panel scanouts; DECON may replace pending frames.',
                                 'The upstream FPS analysis excludes gaps >=100 ms; separate windows retain long stalls.',
                                 'All-gap windows can include deliberate pauses after a gesture; interpret them with the controlled workload.',
                                 'Gesture workloads are not matched to the earlier run.',
                                 'Pipelined draw/GPU/idle estimates are not an additive latency budget.',
                                 'Owner feedback does not confirm black boxes or navigation.'],
                    snapshots=[dict(file=f.name, bytes=f.stat().st_size,
                                    sha256=hashlib.sha256(f.read_bytes()).hexdigest()) for f in logs])
    (args.run/'hardware-evidence.json').write_text(json.dumps(evidence, indent=2)+'\n', encoding='utf-8')
    print(analysis.stdout.splitlines()[0])
    print('Capacity transitions:', sorted(capacities))
    print('Failed attachment IDs:', sorted(failed))
    print('Owner feedback:', args.feedback)


if __name__ == '__main__':
    main()
