#!/usr/bin/env python3
"""Retain nested build logs, repository identities, tool versions and artifacts."""
import argparse
import datetime as dt
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

ROOT=Path('/opt/a51-hakios/src/hakios-xnu-kernel')
DOCS=Path('/mnt/c/Users/Ankit/Desktop/A51/hakios-a51')

def query(argv):
    p=subprocess.run(argv,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    return {'command':argv,'exit_code':p.returncode,'output':p.stdout.decode(errors='replace')}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-exit',type=int)
    args=parser.parse_args()
    stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    output=DOCS/'evidence/build-snapshots'/stamp
    output.mkdir(parents=True)
    result={'schema_version':1,'captured_utc':stamp,'build_exit_code':args.build_exit,'repositories':{},'tools':{},'artifacts':[],
            'snapshot':str(output),'notes':'A snapshot records existence and identity, not successful build or boot.'}
    paths=['.','xnu-src/xnu-8796.121.2','xnu-src/hfs-627.100.6','xnu-deps/AvailabilityVersions','xnu-deps/libdispatch',
           'xnu-deps/libpthread','xnu-deps/mm_bootstrap_cmds','xnu-deps/tcsh','xnu-deps/unifdef']
    for name in paths:
        path=ROOT/name
        if not (path/'.git').exists(): continue
        result['repositories'][name]={'head':query(['git','-C',str(path),'rev-parse','HEAD']),
            'status':query(['git','-C',str(path),'status','--short'])}
    for name,argv in {'clang':['clang','--version'],'lld':['ld.lld','--version'],
                      'qemu':['qemu-system-aarch64','--version'],'dsymutil':['dsymutil','--version'],
                      'cctools':['/opt/a51-hakios/theos/toolchain/linux/iphone/bin/ld','-v']}.items():
        result['tools'][name]=query(argv)
    for name in ('hakios-kernel','xnuloader/loader.efi','userland/hello','qemu/payload.bin'):
        path=ROOT/name
        if path.is_file():
            result['artifacts'].append({'path':str(path),'size':path.stat().st_size,
                'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'file':query(['file',str(path)])})
    for path in [ROOT/'xnu-build.log',*(ROOT/'xnu-deps').glob('*.log')]:
        if path.is_file(): shutil.copy2(path,output/path.name)
    shutil.copy2(ROOT/'.config',output/'kernel.config')
    result['project_scripts']=[{'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
                               for p in sorted((DOCS/'scripts').glob('*')) if p.is_file()]
    (output/'manifest.json').write_text(json.dumps(result,indent=2)+'\n')
    (DOCS/'manifests/build-current.json').write_text(json.dumps(result,indent=2)+'\n')
    print('Build evidence snapshot:',output,flush=True)

if __name__=='__main__': main()
