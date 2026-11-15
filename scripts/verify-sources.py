#!/usr/bin/env python3
"""Fail on source pin drift; capture the verified dependency identities."""
import datetime as dt
import json
import subprocess
from pathlib import Path

ROOT=Path('/opt/a51-hakios/src/hakios-xnu-kernel')
DOCS=Path('/mnt/c/Users/Ankit/Desktop/A51/hakios-a51')
PINS={
    '.':'63fc2b4633bac3af8e57dadab9f5a8d4cb940438',
    'xnu-src/xnu-8796.121.2':'c54f35ca767986246321eb901baf8f5ff7923f6a',
    'xnu-src/hfs-627.100.6':'31d5ec238dfab485e78a9a30b8b92d13e8914f03',
    'xnu-deps/AvailabilityVersions':'5d9baee345b3bc72b26c71adc65f94f2d5e9ced2',
    'xnu-deps/libdispatch':'a641558f447659d90ad002ef0ee6f0212273fbfc',
    'xnu-deps/libpthread':'a6c70ca0e544347a0377babf748f831577ec24f9',
    'xnu-deps/mm_bootstrap_cmds':'f337e600741638896fb6056ce87c6479f74b89a3',
    'xnu-deps/tcsh':'b7db07931546178c4cb2542b5fc850c483628ed5',
    'xnu-deps/unifdef':'08d12cd3059fe072929ea001ad9833f5487fd355',
}


def main():
    result={'schema_version':1,'captured_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'repositories':[]}
    for relative,expected in PINS.items():
        path=ROOT/relative
        def git(*args):
            return subprocess.check_output(['git','-C',str(path),*args],text=True).strip()
        actual=git('rev-parse','HEAD')
        if actual != expected: raise RuntimeError('source drift: '+relative+' '+actual)
        status=git('status','--short')
        if relative != 'xnu-src/xnu-8796.121.2' and status:
            raise RuntimeError('unrecorded source modifications: '+relative+'\n'+status)
        result['repositories'].append({'path':str(path),'commit':actual,'url':git('remote','get-url','origin'),
            'status':status,'generated_overlay':relative=='xnu-src/xnu-8796.121.2'})
    (DOCS/'manifests/source-lock.json').write_text(json.dumps(result,indent=2)+'\n')
    print('Verified',len(PINS),'source pins; generated XNU overlay recorded',flush=True)


if __name__=='__main__': main()
