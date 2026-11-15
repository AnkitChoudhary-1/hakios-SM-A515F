#!/usr/bin/env python3
"""Fixed diagnostic binding, never a current memory-placement certificate."""
import re
from decimal import Decimal
import arena_probe as arena

PLAN = '30fb6aab6df7e405591b53105f0b1a22f5011c7b8636926ced2c8c06952e4e13'
NAME = 'hakios_ownership_probe'


def flags():
    return {'phone_queries': True, 'phone_writes': True,
        'android_module_execution_verified': True,
        'fixed_diagnostic_plan_binding_verified': True,
        'active_owned_interval': False, 'external_ownership_certificate': False,
        'safe_for_loader_placement': False, 'a51_destination_selected': False,
        'a51_loader_execution_verified': False, 'payload_copied': False,
        'standalone_payload_execution_verified': False,
        'platform_handoff_verified': False, 'payload_fault_logs_verified': False,
        'android_recovery_return_demonstrated': False, 'phase_2_device_gate_passed': False}


def transaction_script(normal, second, failure, path):
    for identity in (normal, second, failure):
        arena.require(re.fullmatch('[0-9a-f]{16}', identity), 'invalid run id')
    arena.require(len({normal, second, failure}) == 3 and
        path == '/data/local/tmp/hakios-ownership-probe-' + normal + '.ko', 'bad transaction identity')
    return f'''owner_dir=/sys/module/{NAME}/ownership
cleanup_owner() {{
 if [ -d /sys/module/{NAME} ]; then rmmod {NAME}; fi
 rm -f {path}
}}
trap cleanup_owner EXIT
snapshot() {{
 printf 'OWNER_STATUS %s ' "$1"
 cat "$owner_dir/status" || exit 40
}}
reject() {{
 printf '%s\\n' "$1" > "$owner_dir/command"
 owner_rc=$?
 printf 'OWNER_TRANSACTION reject=%s rc=%d\\n' "$2" "$owner_rc"
 [ "$owner_rc" -ne 0 ] || exit 41
}}
accept() {{
 printf '%s\\n' "$1" > "$owner_dir/command" || exit 42
 printf 'OWNER_TRANSACTION accept=%s\\n' "$2"
}}
insmod {path} run_id={normal} || exit 43
printf 'OWNER_TRANSACTION load=first\\n'
grep '^{NAME} ' /proc/modules || exit 44
snapshot initial
owner_token=$(cat "$owner_dir/status" | sed -n 's/.* token=\\([0-9a-f]*\\) plan=.*/\\1/p')
[ "${{#owner_token}}" -eq 32 ] || exit 45
case "$owner_token" in 0*) owner_wrong=1${{owner_token#?}} ;; *) owner_wrong=0${{owner_token#?}} ;; esac
reject "bind:$owner_wrong:{PLAN}:1" wrong_token
reject "bind:$owner_token:{'0' * 64}:1" wrong_plan
reject "bind:$owner_token:{PLAN}:01" malformed
reject "bind:$owner_token:{PLAN}:2" future
snapshot rejected_initial
accept "bind:$owner_token:{PLAN}:1" bind_first
snapshot bound_first
reject "bind:$owner_token:{PLAN}:1" replay
snapshot rejected_replay
accept "bind:$owner_token:{PLAN}:2" bind_next
sleep 1
snapshot held_next
grep '^{NAME} ' /proc/modules || exit 46
accept "release:$owner_token:{PLAN}:3" release_first
snapshot released
reject "bind:$owner_token:{PLAN}:4" after_release
snapshot rejected_release
rmmod {NAME} || exit 47
printf 'OWNER_TRANSACTION unload=first\\n'
insmod {path} run_id={second} || exit 48
printf 'OWNER_TRANSACTION load=second\\n'
snapshot second_initial
owner_second=$(cat "$owner_dir/status" | sed -n 's/.* token=\\([0-9a-f]*\\) plan=.*/\\1/p')
[ "${{#owner_second}}" -eq 32 ] && [ "$owner_second" != "$owner_token" ] || exit 49
reject "bind:$owner_token:{PLAN}:1" previous_lifetime
snapshot second_rejected
accept "bind:$owner_second:{PLAN}:1" bind_second
snapshot second_bound
rmmod {NAME} || exit 50
printf 'OWNER_TRANSACTION unload=second\\n'
insmod {path} run_id={failure} fail_after_alloc=1
owner_rc=$?
printf 'OWNER_TRANSACTION failure_load=%d\\n' "$owner_rc"
[ "$owner_rc" -ne 0 ] || exit 51
test ! -d /sys/module/{NAME} || exit 52'''


def reconstruct(transaction, logs, normal, second, failure):
    """Reconstruct closed history only, with exact globally ordered events."""
    status_pattern = (r'^OWNER_STATUS (\w+) run=([0-9a-f]{16}) token=([0-9a-f]{32}) '
        r'plan=([0-9a-f]{64}) active=([01]) bound=([01]) last_seq=(\d+) bytes=(\d+)$')
    statuses = []
    markers = []
    loaded = []
    trace = []
    for line in transaction.splitlines():
        if line.startswith('OWNER_STATUS '):
            match = re.fullmatch(status_pattern, line)
            arena.require(match is not None, 'malformed status observation')
            label, run, token, plan, active, bound, seq, size = match.groups()
            arena.require(plan == PLAN, 'wrong observed plan')
            arena.require(seq == str(int(seq)) and size == str(int(size)), 'noncanonical status integer')
            statuses.append((label, run, token, int(active), int(bound), int(seq), int(size)))
            trace.append('status=' + label)
        elif line.startswith('OWNER_TRANSACTION '):
            markers.append(line)
            trace.append(line.removeprefix('OWNER_TRANSACTION '))
        elif line.startswith(NAME + ' '):
            arena.require(re.fullmatch(NAME + r' \d+ 0 - Live 0x[0-9a-f]+(?: \(O\))?', line), 'invalid Live record')
            loaded.append(line)
            trace.append('live')
    arena.require(len(statuses) == 10 and len(loaded) == 2, 'missing status/hold observations')
    a, b = statuses[0][2], statuses[7][2]
    arena.require(a != b, 'allocation token reused')
    expected = [
        ('initial', normal, a, 1, 0, 0, 65536),
        ('rejected_initial', normal, a, 1, 0, 0, 65536),
        ('bound_first', normal, a, 1, 1, 1, 65536),
        ('rejected_replay', normal, a, 1, 1, 1, 65536),
        ('held_next', normal, a, 1, 1, 2, 65536),
        ('released', normal, a, 0, 0, 3, 0),
        ('rejected_release', normal, a, 0, 0, 3, 0),
        ('second_initial', second, b, 1, 0, 0, 65536),
        ('second_rejected', second, b, 1, 0, 0, 65536),
        ('second_bound', second, b, 1, 1, 1, 65536)]
    arena.require(statuses == expected, 'state progression differs')
    expected_markers = [
        'load=first', 'reject=wrong_token rc=1', 'reject=wrong_plan rc=1',
        'reject=malformed rc=1', 'reject=future rc=1', 'accept=bind_first',
        'reject=replay rc=1', 'accept=bind_next', 'accept=release_first',
        'reject=after_release rc=1', 'unload=first', 'load=second',
        'reject=previous_lifetime rc=1', 'accept=bind_second', 'unload=second', 'failure_load=1']
    arena.require(markers == ['OWNER_TRANSACTION ' + m for m in expected_markers], 'transaction statuses differ')
    arena.require(trace == ['load=first', 'live', 'status=initial',
        'reject=wrong_token rc=1', 'reject=wrong_plan rc=1', 'reject=malformed rc=1',
        'reject=future rc=1', 'status=rejected_initial', 'accept=bind_first',
        'status=bound_first', 'reject=replay rc=1', 'status=rejected_replay',
        'accept=bind_next', 'status=held_next', 'live', 'accept=release_first',
        'status=released', 'reject=after_release rc=1', 'status=rejected_release',
        'unload=first', 'load=second', 'status=second_initial',
        'reject=previous_lifetime rc=1', 'status=second_rejected', 'accept=bind_second',
        'status=second_bound', 'unload=second', 'failure_load=1'], 'transaction observation/action order changed')
    # Strip only the kernel dmesg prefix, reject every other byte/event suffix.
    events = []
    previous_time = None
    for line in logs.splitlines():
        match = re.fullmatch(r'\[\s*(\d+(?:\.\d+)?)\] (HAKIOS_OWNER .*)', line)
        arena.require(match is not None, 'invalid lifecycle framing')
        timestamp = Decimal(match.group(1))
        arena.require(previous_time is None or previous_time <= timestamp, 'kernel timestamps reversed')
        previous_time = timestamp
        events.append(match.group(2))
    arena.require(len(events) == 21, 'unexpected lifecycle count')
    tokens, addresses = [], []
    for pos, run in [(0, normal), (12, second), (18, failure)]:
        match = re.fullmatch(r'HAKIOS_OWNER run=' + run + r' token=([0-9a-f]{32}) stage=acquire phys=(0x[0-9a-f]+) bytes=65536', events[pos])
        arena.require(match is not None, 'acquire identity/extent changed')
        token, address = match.groups()
        value = int(address, 16)
        arena.require(value > 0 and value % 65536 == 0 and value + 65536 < 2**64, 'invalid observed span')
        tokens.append(token)
        addresses.append(address)
    arena.require(len(set(tokens)) == 3 and tokens[:2] == [a, b], 'status/event lifetime disagreement')
    patterns = []
    def prefix(run, token):
        return 'HAKIOS_OWNER run=' + run + ' token=' + token + ' stage='
    def ready(p):
        return p + 'ready plan=' + PLAN + ' regions=6 zero=pass pattern=pass'
    def bind(p, seq, address):
        return p + 'bind plan=' + PLAN + ' seq=' + str(seq) + ' regions=6 phys=' + address + ' bytes=65536 pattern=pass'
    def reject(p, code, seq, active):
        return p + f'reject code={code} last_seq={seq} active={active}'
    def release(p, address, reason, seq):
        return p + 'release phys=' + address + f' bytes=65536 reason={reason} integrity=pass cleared=pass seq={seq}'
    p = prefix(normal, a)
    patterns += [events[0], ready(p), reject(p, 2, 0, 1), reject(p, 3, 0, 1),
        reject(p, 1, 0, 1), reject(p, 4, 0, 1), bind(p, 1, addresses[0]),
        reject(p, 4, 1, 1), bind(p, 2, addresses[0]),
        release(p, addresses[0], 'requested_release', 3), reject(p, 5, 3, 0), p + 'unloaded']
    p = prefix(second, b)
    patterns += [events[12], ready(p), reject(p, 2, 0, 1), bind(p, 1, addresses[1]),
        release(p, addresses[1], 'unload', 1), p + 'unloaded']
    p = prefix(failure, tokens[2])
    patterns += [events[18], ready(p), release(p, addresses[2], 'requested_init_failure', 0)]
    arena.require(events == patterns, 'global lifecycle/binding progression changed')
    return {'scope': 'historical_closed_android_diagnostic_bindings',
        'allocation_count': 3, 'successful_bindings': 3, 'rejected_requests': 7,
        'lifecycle_events': 21, 'status_observations': 10,
        'all_allocations_released': True, 'active_owned_interval': False,
        'safe_for_loader_placement': False, 'cross_boot_device_test': False,
        'lifetimes': [{'run_id': run, 'token': token, 'historical_phys': address,
            'bytes': 65536, 'released': True} for run, token, address in zip(
                [normal, second, failure], tokens, addresses)]}
