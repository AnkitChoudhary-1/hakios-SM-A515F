#!/usr/bin/env python3
"""Correct one historical recorder crash without inventing a child result."""
import datetime as dt
import json
import shutil
from pathlib import Path

PROJECT=Path(__file__).resolve().parents[1]


def main():
    folder=PROJECT/'runs/20261110T160301868151Z-install-host-deps'
    meta=folder/'metadata.json'
    original=folder/'metadata.original.json'
    if not original.exists(): shutil.copy2(meta,original)
    record=json.loads(original.read_text(encoding='utf-8'))
    record.update(status='recorder_failed',exit_code=None,child_exit_code_known=False,
        annotation_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
        error='Recorder crashed printing U+2192 under Windows cp1252. Child exit and finish time were not captured.',
        recovery='run.py now uses UTF-8 output. Recorded installation retry 20261110T160420746447Z passed.')
    meta.write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
    (folder/'CORRECTION.md').write_text(
        '# Historical recorder failure\n\nOriginal metadata is preserved in metadata.original.json. '
        'The old running status was stale. The Unicode recorder exception interrupted capture; '
        'the child outcome is unknown. Later installation success does not establish this run succeeded.\n',encoding='utf-8')
    with (PROJECT/'runs/events.jsonl').open('a',encoding='utf-8') as events:
        events.write(json.dumps(record)+'\n')
    print('Annotated historical recorder failure; original metadata and output retained.')


if __name__=='__main__': main()
