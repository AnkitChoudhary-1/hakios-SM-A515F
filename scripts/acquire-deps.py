#!/usr/bin/env python3
"""Acquire build inputs in WSL, recording immutable URLs, commits and hashes.

Release assets lack authenticated vendor digests here except the macOS SDK;
first-download toolchain hashes are local provenance, not vendor attestation.
Subsequent acquisitions check the retained hashes before unpacking.
"""
import datetime as dt
import hashlib
import json
import subprocess
import urllib.request
from pathlib import Path

ROOT = Path('/opt/a51-hakios')
DOCS = Path('/mnt/c/Users/Ankit/Desktop/A51/hakios-a51')
LOCK = DOCS / 'manifests/dependencies.json'
SDK_COMMIT = '0222fd5413cf4b9af096f37b4621afa2688572f7'

def cmd(*args):
    print('COMMAND', json.dumps(args), flush=True)
    subprocess.run(args, check=True)

def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()

def main():
    ROOT.joinpath('downloads').mkdir(parents=True, exist_ok=True)
    lock = json.loads(LOCK.read_text()) if LOCK.exists() else {'schema_version':1,'assets':{},'repositories':{}}
    def save():
        lock['updated_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
        LOCK.write_text(json.dumps(lock, indent=2)+'\n')
    def fetch(name, url, vendor_hash=None):
        path = ROOT / 'downloads' / name
        if not path.exists():
            cmd('curl','-L','--fail','--retry','3','-o',str(path)+'.partial',url)
            Path(str(path)+'.partial').rename(path)
        digest = sha(path)
        expected = vendor_hash or lock['assets'].get(name,{}).get('sha256')
        if expected and digest != expected:
            raise RuntimeError('checksum mismatch: '+name)
        lock['assets'][name] = {'url':url,'sha256':digest,'size':path.stat().st_size,
                                'checksum_basis':'vendor checksum' if vendor_hash else 'first-download local hash',
                                'path':str(path)}
        save()
        return path
    toolchain = fetch('iOSToolchain-x86_64-test-210562a.tar.xz',
        'https://github.com/L1ghtmann/llvm-project/releases/download/test-210562a/iOSToolchain-x86_64.tar.xz')
    tool_dir = ROOT / 'theos/toolchain'
    tool_dir.mkdir(parents=True,exist_ok=True)
    if not (tool_dir / 'linux/iphone/bin/ld').exists():
        cmd('tar','-xJf',str(toolchain),'-C',str(tool_dir))
    sdk_repo = ROOT / 'theos/sdks-git'
    if not (sdk_repo / '.git').exists():
        cmd('git','init',str(sdk_repo))
        cmd('git','-C',str(sdk_repo),'remote','add','origin','https://github.com/theos/sdks.git')
        cmd('git','-C',str(sdk_repo),'config','core.sparseCheckout','true')
        (sdk_repo / '.git/info/sparse-checkout').write_text('/iPhoneOS16.5.sdk/\n')
        cmd('git','-C',str(sdk_repo),'fetch','--depth=1','--filter=blob:none','origin',SDK_COMMIT)
        cmd('git','-C',str(sdk_repo),'checkout','--detach',SDK_COMMIT)
    actual = subprocess.check_output(['git','-C',str(sdk_repo),'rev-parse','HEAD'],text=True).strip()
    if actual != SDK_COMMIT:
        raise RuntimeError('unexpected SDK commit '+actual)
    lock['repositories']['theos-sdks']={'url':'https://github.com/theos/sdks.git','commit':actual,'selected':'iPhoneOS16.5.sdk','path':str(sdk_repo)}
    save()
    sdk_link = ROOT / 'theos/sdks/iPhoneOS16.5.sdk'
    sdk_link.parent.mkdir(parents=True,exist_ok=True)
    if not sdk_link.exists():
        sdk_link.symlink_to('../sdks-git/iPhoneOS16.5.sdk', target_is_directory=True)
    checksum_url = 'https://github.com/joseluisq/macosx-sdks/releases/download/13.3/sha256sum.txt'
    checksum_file = fetch('MacOSX13.3-sdk-sha256sum.txt',checksum_url)
    vendor = checksum_file.read_text().split()[0]
    mac = fetch('MacOSX13.3.sdk.tar.xz','https://github.com/joseluisq/macosx-sdks/releases/download/13.3/MacOSX13.3.sdk.tar.xz',vendor)
    dest = ROOT / 'src/hakios-xnu-kernel/xnu-deps'
    if not (dest / 'MacOSX13.3.sdk/System/Library/Frameworks/Kernel.framework/Headers/DriverKit').exists():
        cmd('tar','-xJf',str(mac),'-C',str(dest),'--wildcards','*MacOSX13.3.sdk/System/Library/Frameworks/Kernel.framework*')
    print('Dependencies acquired; lock:',LOCK,flush=True)

if __name__ == '__main__':
    main()
