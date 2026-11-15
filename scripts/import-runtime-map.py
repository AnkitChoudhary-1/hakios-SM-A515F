#!/usr/bin/env python3
"""Import/replay retained Android observations locally; no phone or payload access."""
import argparse
import datetime as dt
from pathlib import Path
import shutil
import runtime_observations as observations


def capture(report_path):
    started = observations.stamp()
    report, count = observations.load_source(report_path)
    projection = observations.normalize(report)
    diagnostics = observations.demonstrations(projection)
    # Bound both derived outputs before creating a packet or writing any bytes.
    projection_bytes = observations.bounded_encode(projection)
    diagnostic_bytes = observations.bounded_encode(diagnostics)
    tag = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder = observations.PROJECT / 'evidence/phase-2/runtime-map' / tag
    folder.mkdir(parents=True, exist_ok=False)
    for key, name in (('report', 'live-report.json'), ('index', 'live-index.json')):
        path = report_path if key == 'report' else report_path.parent / 'index.json'
        destination = folder / 'inputs' / name
        destination.parent.mkdir(exist_ok=True)
        shutil.copyfile(path, destination)
    tools = {}
    for name in observations.TOOLS:
        source = observations.PROJECT / 'scripts' / name
        destination = folder / 'tools' / name
        destination.parent.mkdir(exist_ok=True)
        shutil.copyfile(source, destination)
        tools[name] = observations.identity(source)
    (folder / 'map.json').write_bytes(projection_bytes)
    (folder / 'diagnostics.json').write_bytes(diagnostic_bytes)
    result = {'format': 'hakios.a51-runtime-map-result', 'schema_version': 1,
              'created': started, 'finished': observations.stamp(),
              'source': {key: {'path': path.relative_to(observations.PROJECT).as_posix(), **observations.identity(path)}
                         for key, path in (('report', report_path), ('index', report_path.parent / 'index.json'))},
              'source_capture_files': count, 'tools': tools,
              'counts': observations.counts_for(projection, diagnostics), 'flags': projection['flags'],
              'phone_queries': False, 'phone_writes': False}
    (folder / 'result.json').write_bytes(observations.bounded_encode(result))
    (folder / 'index.json').write_bytes(observations.bounded_encode(observations.packet_index(folder)))
    verified = observations.validate_packet(folder)
    pointer = {'schema_version': 1, 'result': (folder / 'result.json').relative_to(observations.PROJECT).as_posix(),
               **observations.identity(folder / 'result.json'), 'scope': projection['scope'],
               'safe_for_loader_placement': False, 'phase_2_device_gate_passed': False}
    (observations.PROJECT / 'manifests/runtime-map-current.json').write_bytes(observations.bounded_encode(pointer))
    print('RUNTIME_MAP_RESULT ' + str(folder / 'result.json'))
    print('RUNTIME_MAP_VERIFIED ' + observations.canonical(verified['counts']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--import-report', type=Path)
    action.add_argument('--verify-result', type=Path)
    args = parser.parse_args()
    if args.import_report:
        path = args.import_report.resolve()
        capture(path)
    else:
        observations.require(args.verify_result.name == 'result.json', 'expected result.json')
        result = observations.validate_packet(args.verify_result.resolve().parent)
        print('RUNTIME_MAP_VERIFIED ' + observations.canonical(result['counts']))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
