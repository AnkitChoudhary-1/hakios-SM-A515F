#!/usr/bin/env python3
"""Record exact pinned tree evidence for layout, Mali and user-space gaps."""
import datetime as dt
import hashlib
import json
from pathlib import Path

PROJECT=Path(__file__).resolve().parents[1]
SOURCES=PROJECT.parent/'hakios-assessment/sources'


def main():
    result={'schema_version':1,'captured_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'trees':{}}
    for name in ('hakios-xnu-kernel','hakios-xnu-kernel-mtk','hakios-mt6768','hakios-metal','hackios-xnu-userland'):
        path=SOURCES/(name+'-tree.json')
        data=json.loads(path.read_text(encoding='utf-8'))
        if data.get('truncated'): raise RuntimeError('incomplete tree: '+name)
        paths=[e['path'] for e in data['tree']]
        result['trees'][name]={'commit':data['sha'],'tree_file':str(path),
            'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'truncated':False,
            'relevant_paths':[p for p in paths if any(s in p.lower() for s in
                ('mtk/','mtkloader/','mali','panfrost','mesa','userland/src/metal','exynos','a51'))],
            'has_mtk_loader_layout':any(p.startswith('mtk/loader/') for p in paths),
            'has_mtk_mt6768_layout':any(p.startswith('mtk/mt6768/') for p in paths),
            'has_legacy_mtkloader':any(p.startswith('mtkloader/') for p in paths)}
    result['notes']=[
        'Tree paths establish publication/layout, not that a source component builds or runs.',
        'The pinned MTK README claims mtk/loader and mtk/mt6768; pinned common mtk tree uses legacy paths.',
        'Partial Mali/Metal/Mesa files exist; complete matching Mali user-space integration remains unverified.',
        'Public SDK headers do not supply SpringBoard, Safari or the iOS runtime.']
    (PROJECT/'manifests/research-audit.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    for name,tree in result['trees'].items():
        print(name,tree['commit'],len(tree['relevant_paths']),'relevant paths',flush=True)


if __name__=='__main__': main()
