#!/usr/bin/env python3
"""One-time source adaptation and documentation rollback checkpoint; host only."""
import hashlib
import json
from pathlib import Path
import shutil

PROJECT = Path(__file__).resolve().parents[1]
BASE = PROJECT / 'evidence/phase-2/cpu-state-preparation/20261111-p2-017'

def pin(path):
    data = path.read_bytes()
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}

def main():
    BASE.mkdir(parents=True, exist_ok=False)
    files = ['README.md', 'state.json', 'docs/STATE.md', 'docs/INDEX.md',
             'docs/IMPLEMENTATION-LOG.md', 'docs/HANDOFF.md', 'docs/ENTRY-CONTRACT.md',
             'docs/LOADER-DESIGN.md']
    before = BASE / 'before'
    before.mkdir()
    copied = {}
    for rel in files:
        target = before / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PROJECT / rel, target)
        copied[rel] = pin(target)
    roadmap = PROJECT.parent / 'hakios-assessment/ROADMAP.md'
    shutil.copy2(roadmap, before / 'ROADMAP.md')
    copied['../hakios-assessment/ROADMAP.md'] = pin(roadmap)
    source = PROJECT / 'scripts/build-page-probe.py'
    text = source.read_text(encoding='utf-8')
    adapted = text.replace('page-probe', 'cpu-state').replace('page_probe', 'cpu_state')
    adapted = adapted.replace('PAGE_PROBE', 'CPU_STATE')
    adapted = adapted.replace('android_cpu_state_host_build', 'android_cpu_state_capture_host_build')
    target = PROJECT / 'scripts/build-cpu-state.py'
    if target.exists():
        raise ValueError('one-time destination exists')
    target.write_text(adapted, encoding='utf-8', newline='\n')
    (BASE / 'checkpoint.json').write_text(json.dumps({'before': copied,
        'builder_source': {'path': 'scripts/build-page-probe.py', **pin(source)},
        'builder_adaptation': {'path': 'scripts/build-cpu-state.py', **pin(target)},
        'phone_operations': False}, indent=2) + '\n', encoding='utf-8')
    print('CPU_STATE_PREPARATION ' + BASE.relative_to(PROJECT).as_posix())

if __name__ == '__main__':
    main()
