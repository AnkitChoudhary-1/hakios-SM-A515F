from pathlib import Path
import hashlib
import shutil
import json
base=Path(__file__).resolve().parents[1]/'full-quality-recovery'
repo=Path(r'\\wsl.localhost\A51-KernelBuilder\opt\a51-hakios\upstream-a51\hakios')
rel='xnu/files/iokit/Kernel/MiniIOMobileFramebuffer.cpp'
src=repo/rel
target=repo/'xnu-src/xnu-8796.121.2/iokit/Kernel/MiniIOMobileFramebuffer.cpp'
manifest=json.loads((base/'source-changes.json').read_text())
expected=manifest['files'][rel]['after_sha256']
assert hashlib.sha256(src.read_bytes()).hexdigest()==expected
assert hashlib.sha256(target.read_bytes()).hexdigest()==expected
shutil.copy2(base/'kernel-build-console-synced.txt',base/'kernel-build-first-declaration-failure.txt')
text=src.read_text().replace('#include <kern/sched_prim.h>',
    '/* Internal scheduler primitive is omitted from IOKit export headers. */\nextern "C" processor_t thread_bind(processor_t processor);')
src.write_text(text,newline='\n')
shutil.copy2(src,target)
manifest['files'][rel]['after_sha256']=hashlib.sha256(src.read_bytes()).hexdigest()
(base/'source-changes.json').write_text(json.dumps(manifest,indent=2)+'\n')
