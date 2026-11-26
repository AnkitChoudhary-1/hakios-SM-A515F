"""Record saved full-quality hardware evidence. Never contacts or changes the phone."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save_json(path, data):
    path.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')


def require(value, message):
    if not value:
        raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--reviewed-home-screenshot', required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    candidate = run.parent.parent
    manifest_path = candidate / 'boot-package-manifest.json'
    manifest = read_json(manifest_path)
    test = read_json(run / 'test-manifest.json')
    evidence = read_json(run / 'hardware-evidence.json')
    require(manifest['profile'] == 'full-quality', 'Unexpected package profile')
    require(test['collection_completed'] and test['last_loader_result'] == 'running 0 0',
            'Collection did not finish with the kernel running')
    require(test['manual_return'] and test['kernel_return_after_seconds'] == 0,
            'Automatic return is enabled')
    for entry, component in [('kernel', 'kernel'), ('ramdisk', 'root.apfs')]:
        require(test['entries'][entry]['sha256'] == manifest['components'][component]['sha256'],
                f'Tested component differs from current package: {entry}')
    screenshot = run / args.reviewed_home_screenshot
    require(screenshot.parent == run and screenshot.is_file() and screenshot.suffix == '.png',
            'Reviewed screenshot must be a PNG in this run')
    logs = sorted(run.glob('log-*.txt'))
    rows = sorted({line for path in logs
                   for line in path.read_text(encoding='utf-8', errors='replace').splitlines()})
    command_lines = [row.removeprefix('cmdline: ') for row in rows
                     if row.startswith('cmdline: ') and '=' in row]
    require(len(command_lines) == 1, 'Missing or conflicting kernel command line')
    command_line = command_lines[0]
    effective = dict(pair.split('=', 1) for pair in command_line.split() if '=' in pair)
    expected = dict(pair.split('=', 1) for pair in test['cmdline'].split())
    require(all(effective.get(key) == value for key, value in expected.items()),
            'An intended boot setting was lost')
    forbidden = {'fbscale', 'fbwidth', 'fbheight', 'ui_lite', 'vblur', 'wallpaper_freeze'}
    require(not forbidden.intersection(effective), 'Visual-quality override present')
    geometry = [row for row in rows
                if 'initial main screen size:{1125, 2436} scale:3' in row]
    require(geometry, 'Full render geometry was not logged')
    clock_rows = [row for row in rows if 'a51gpu: verified clocks:' in row]
    clock_values = []
    for row in clock_rows:
        match = re.search(r'A53s (\d+) A73s (\d+) GPU (\d+) kHz; guard faults (\d+)', row)
        if match:
            clock_values.append(tuple(map(int, match.groups())))
    require(clock_values and all(value == (1638000, 2080000, 683000, 0)
                                 for value in clock_values), 'Clocks or guards differ from candidate')
    requests = [row for row in rows if 'a51gpu: clock request:' in row]
    for domain, rate in [(2, 1638000), (3, 2080000), (4, 683000)]:
        require(any(f'domain {domain} requested {rate} observed {rate} kHz ack 1' in row
                    for row in requests), f'Initial request was not verified: {domain}')
    thermal = []
    for row in rows:
        match = re.search(r'temperatures (\d+), (\d+), (\d+) \(hottest (\d+), (\d+), (\d+)\); '
                          r'(\d+) steps down, (\d+) up', row)
        if match:
            thermal.append(tuple(map(int, match.groups())))
    gpu_rows = [row for row in rows if 'a51gpu: kept GPU:' in row]
    windows = evidence['gesture_gap_windows_including_long_stalls']
    status_bar = [row for row in rows if '_UIStatusBarVisualProvider_Split1125' in row]
    renderer = [row for row in rows if 'OpenGL ES 3.1 Mesa 25.0.7; Mali-G72 (Panfrost)' in row]
    install_events = [json.loads(row) for row in
                      (candidate.parent / 'installation-events.jsonl').read_text().splitlines()]
    image = next(package for package in manifest['packages'] if package['mode'] == 'diagnostic')
    readbacks = [event for event in install_events
                 if event['event'] == 'partition-readback-verified'
                 and event['serial'] == manifest['serial'] and event['partition'] == 'recovery'
                 and event['sha256'] == image['sha256']]
    require(readbacks, 'No matching recovery read-back event')
    report = dict(
        recorded_at_utc=datetime.now(timezone.utc).isoformat(),
        run=str(run), recovery_readback_event=readbacks[-1],
        tested_components=test['entries'], full_effective_cmdline=command_line,
        effective_cmdline_bytes=len(command_line.encode()),
        all_intended_boot_arguments_present=True,
        geometry_log=geometry, status_bar_log=status_bar, renderer_log=renderer,
        verified_rates_khz=dict(a53=1638000, a73=2080000, gpu=683000),
        unique_clock_guard_reports=clock_rows, initial_requests=requests,
        temperature_maxima_c=dict(zip(['a53', 'a73', 'gpu'],
                                     [max(value[i] for value in thermal) for i in (3, 4, 5)]))
                                     if thermal else None,
        maximum_reported_downsteps=max((value[6] for value in thermal), default=None),
        gpu_job_reports=gpu_rows,
        home_screenshot=dict(file=screenshot.name, sha256=hashlib.sha256(screenshot.read_bytes()).hexdigest(),
                             review='Home icons/text, original wallpaper, translucent dock and split status bar visible; '
                                    'a still image cannot verify animation FPS or rule out intermittent corruption.'),
        owner_feedback=evidence['owner_feedback'],
        observed_gesture_window_copy_rate_range=[min(window['copy_fps_including_all_observed_gaps'] for window in windows),
                                                max(window['copy_fps_including_all_observed_gaps'] for window in windows)]
                                                if windows else None,
        maximum_observed_gesture_copy_gap_ms=max((window['maximum_gap_ms'] for window in windows), default=None),
        hardware_scaling_implemented=False, direct_scanout_implemented=False,
        sustained_50_60_fps_verified=False, limitations=evidence['limitations'])
    save_json(run / 'runtime-verification.json', report)
    provenance = dict(run=str(run.relative_to(candidate)), evidence='runtime-verification.json',
                      home_verified_from_screenshot=True, clocks_verified=True,
                      sustained_50_60_fps_verified=False, owner_feedback=evidence['owner_feedback'])
    manifest['phone_boot_tested'] = True
    manifest['hardware_test'] = provenance
    save_json(manifest_path, manifest)
    sources_path = candidate / 'source-changes.json'
    sources = read_json(sources_path)
    sources['hardware_tested'] = True
    sources['hardware_test'] = provenance
    save_json(sources_path, sources)
    print(json.dumps({key: report[key] for key in
                      ['verified_rates_khz', 'temperature_maxima_c',
                       'observed_gesture_window_copy_rate_range', 'maximum_observed_gesture_copy_gap_ms',
                       'sustained_50_60_fps_verified']}, indent=2))


if __name__ == '__main__':
    main()
