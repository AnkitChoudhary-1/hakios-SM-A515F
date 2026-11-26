from pathlib import Path
import json
import hashlib
BASE=Path(__file__).resolve().parents[1]
REPO=Path(r'\\wsl.localhost\A51-KernelBuilder\opt\a51-hakios\upstream-a51\hakios')
p=REPO/'userland/src/eagl.c'
text=p.read_text()
if '#include <errno.h>' not in text:
    text=text.replace('#include <stdbool.h>','#include <stdbool.h>\n#include <errno.h>')
p.write_text(text,newline='\n')
p=REPO/'userland/src/net_test.m'
text=p.read_text().replace('bool known = session != NULL, up = false, ipv4 = false, ipv6 = false, router = false, dhcp_service = false;',
    'bool known = session != NULL, up = false, ipv4 = false, ipv6 = false, router = false, dhcp_service = false, manual_service = false;')
text=text.replace('if (![method[@"ConfigMethod"] isEqual:@"DHCP"]) continue;',
    'if (![method[@"ConfigMethod"] isEqual:@"DHCP"]) { manual_service = true; continue; }')
text=text.replace('known, joined, up, dhcp_service, ipv4, router, ipv6)',
    'known, joined, up, dhcp_service && !manual_service, ipv4, router, ipv6)')
p.write_text(text,newline='\n')
job=(BASE/'scripts/rc.jobs.a51-audio-performance').read_text()
(BASE/'scripts/rc.jobs.a51-scheduling-recovery').write_text(
    '# The watcher is indefinite; it never stops or reboots iOS.\n/redwood/bin/net_test wait 55 recover en0 &\n'+job,newline='\n')
p=BASE/'full-quality-recovery/source-changes.json'
record=json.loads(p.read_text())
for rel,item in record['files'].items():
    item['after_sha256']=hashlib.sha256((REPO/rel).read_bytes()).hexdigest()
p.write_text(json.dumps(record,indent=2)+'\n')
