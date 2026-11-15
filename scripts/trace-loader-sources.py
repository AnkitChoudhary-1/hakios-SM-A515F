#!/usr/bin/env python3
"""Capture or replay the host-only A51 entry/memory/log/return source trace."""
import argparse
import datetime as dt
from pathlib import Path

from source_trace import PROJECT, FALSE_FLAGS, capture_trace, contained, json_bytes, sha256, verify_trace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument('--capture', action='store_true')
    operation.add_argument('--verify-trace', help='project-relative timestamped report.json')
    parser.add_argument('--spec', default='manifests/loader-source-trace.json', help='project-relative capture specification')
    args = parser.parse_args()
    if args.verify_trace:
        verify_trace(contained(PROJECT, args.verify_trace))
        return
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder = contained(PROJECT, 'evidence/phase-2/source-trace/' + stamp)
    report = capture_trace(contained(PROJECT, args.spec), folder)
    path = folder / 'report.json'
    pointer = {
        'schema_version': 1, 'report': path.relative_to(PROJECT).as_posix(),
        'sha256': sha256(path.read_bytes()), 'counts': report['counts'],
        'scope': report['scope'], **{key: False for key in FALSE_FLAGS},
    }
    pointer_path = PROJECT / 'manifests/loader-source-trace-current.json'
    temporary = pointer_path.with_suffix('.json.tmp')
    temporary.write_bytes(json_bytes(pointer))
    temporary.replace(pointer_path)
    print('TRACE', pointer['report'])
    print('SHA256', pointer['sha256'])


if __name__ == '__main__':
    main()
