"""Exercise the actual recovery policy using host sanitizers; never contacts the phone."""
from pathlib import Path
import hashlib
import subprocess
import tempfile
import json
from datetime import datetime, timezone
repo = Path('/opt/a51-hakios/upstream-a51/hakios')
policy = repo / 'userland/src/net-recovery-policy.h'
with tempfile.TemporaryDirectory(prefix='a51-net-recovery-') as tmp:
    tmp = Path(tmp)
    (tmp/'policy.h').write_bytes(policy.read_bytes())
    (tmp/'test.c').write_text(r'''
#include <assert.h>
#include "policy.h"
#define D(t,k,j,u,d,i,r,v) net_recovery_due(&s,t,k,j,u,d,i,r,v)
int main(void) {
    assert(!net_ipv4_usable(0xa9fe88ed)); /* owner's 169.254.136.237 */
    assert(net_ipv4_usable(0xac1cdfc4)); /* original 172.28.223.196 */
    assert(!net_ipv4_usable(0) && !net_ipv4_usable(0x7f000001));
    assert(!net_ipv4_usable(0xffffffff) && !net_ipv4_usable(0xe0000001));
    struct net_recovery_state s = {0};
    assert(!D(0,1,1,1,1,0,0,0));
    assert(!D(59,1,1,1,1,0,0,0));
    assert(D(60,1,1,1,1,0,0,0));
    assert(!D(179,1,1,1,1,0,0,0));
    assert(D(180,1,1,1,1,0,0,0));
    assert(!D(181,1,1,1,1,1,1,0)); /* healthy lease resets persistence */
    assert(!s.bad);
    assert(!D(182,1,1,1,1,0,0,0));
    assert(!D(240,1,1,1,1,0,0,0));
    assert(!D(300,1,0,1,1,0,0,0)); /* offline resets */
    assert(!D(400,1,1,0,1,0,0,0)); /* interface down */
    assert(!D(500,1,1,1,0,0,0,0)); /* static/manual or no DHCP service */
    assert(!D(600,0,1,1,1,0,0,0)); /* configd state unknown */
    assert(!D(700,1,1,1,1,0,0,1)); /* IPv6-only left alone */
    assert(!D(800,1,1,1,1,0,1,0)); /* existing route left alone */
    assert(!D(900,1,1,1,1,1,0,0)); /* local valid IPv4 left alone */
    assert(!D(1000,1,1,1,1,0,0,0));
    assert(D(1060,1,1,1,1,0,0,0));
}
''')
    subprocess.run(['clang','-std=c11','-O1','-g','-Wall','-Wextra','-Werror',
                    '-fsanitize=address,undefined',str(tmp/'test.c'),'-o',str(tmp/'test')],check=True)
    subprocess.run([str(tmp/'test')],check=True)
text = (repo/'userland/src/net_test.m').read_text()
assert 'State:/Network/Interface/%@/RefreshConfiguration' in text
assert 'SCDynamicStoreNotifyValue(session' in text
body = text.split('static void recover(',1)[1].split('/* ---- wrongjoin',1)[0]
assert 'dhcp(' not in body and 'sleep(10)' in body
out = Path(__file__).resolve().parents[1]/'full-quality-recovery'
(out/'recovery-tests.json').write_text(json.dumps(dict(passed=True,
    at_utc=datetime.now(timezone.utc).isoformat(),policy_sha256=hashlib.sha256(policy.read_bytes()).hexdigest(),
    cases='IPv4 classification, persistence, cooldown, failed attempt throttling, recovery, disconnect, down, manual, unknown, IPv6, existing route',
    hardware_dhcp_recovery_verified=False),indent=2)+'\n')
print('DHCP recovery policy and integration checks passed under ASan/UBSan.')
