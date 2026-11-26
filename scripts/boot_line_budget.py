"""Conservative A51 loader prefix budget, including optional firmware fields."""
import re

CAPACITY = 607


def validate_boot_line(cmdline, kernel_version, reserve=0):
    if '\0' in cmdline or not cmdline.isascii():
        raise ValueError('Boot arguments must be ASCII without NUL')
    args = dict(word.split('=', 1) for word in cmdline.split() if '=' in word)
    # Reserve serial and watchdog even though the A51 normally omits them.
    prefix = 'debug=0x8 '
    if 'serial' not in args:
        prefix += 'serial=3 '
    if not ('cpus' in args or 'cpumask' in args):
        prefix += 'cpus=1 '
    if 'rd' not in args:
        prefix += 'rd=md0 '
    prefix += 'hv_wdt_pet=1 '
    if args.get('ufs') in ('1', '2'):
        prefix += 'ufs_shared_pa=0x' + '0' * 16 + ' '
    if args.get('battery') == '1':
        prefix += 'battery_shared_pa=0x' + '0' * 16 + ' '
    if kernel_version:
        if not re.fullmatch(r'[!-~]+', kernel_version):
            raise ValueError('Invalid kernel version')
        prefix += 'hakios_kver=' + kernel_version + ' '
    total = len(prefix) + len(cmdline) + reserve
    if total > CAPACITY:
        raise ValueError(f'Effective boot line may use {total}/{CAPACITY} bytes '
                         f'(payload {len(cmdline)}, prefix {len(prefix)}, reserve {reserve})')
    return {'payload_bytes': len(cmdline), 'maximum_prefix_bytes': len(prefix),
            'reserved_bytes': reserve, 'maximum_effective_bytes': total,
            'capacity': CAPACITY, 'conservative_prefix': prefix}
