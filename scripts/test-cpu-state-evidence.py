#!/usr/bin/env python3
"""Meaningful replay and forged-state rejection tests; no ADB calls."""
import argparse
import datetime as dt
import importlib.util
import json
from pathlib import Path
import shutil

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('cpu_state_verifier', PROJECT / 'scripts/test-cpu-state-device.py')
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packet', required=True)
    args = parser.parse_args()
    original = PROJECT / args.packet
    verifier.verify(original)
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    root = PROJECT / 'evidence/phase-2/cpu-state-corruption' / stamp
    root.mkdir(parents=True, exist_ok=False)
    cases = [
        ('phase_promotion', lambda r: r['flags'].update(phase_2_device_gate_passed=True), 'records/flags'),
        ('architectural_write_claim', lambda r: r['flags'].update(architectural_register_writes=True), 'records/flags'),
        ('boolean_cpu', lambda r: r['cpu_records'][1].update(cpu=True), 'records/flags'),
        ('forged_translation', lambda r: r['cpu_records'][0].update(tcr=0), 'records/flags'),
        ('arbitrary_command', lambda r: r['queries'][0].update(command='uname -a'), 'command changed'),
        ('forged_remote_status', lambda r: r['queries'][0].update(exit_code=1), 'remote success'),
        ('different_module', None, 'host module binding'),
        ('extra_file', None, 'packet enumeration')]
    results = []
    for name, mutate, expected in cases:
        target = root / name
        shutil.copytree(original, target)
        record = json.loads((target / 'result.json').read_text(encoding='utf-8'))
        if mutate:
            mutate(record)
            verifier.transport.write_json(target / 'result.json', record)
        if name == 'different_module':
            module = target / 'hakios_cpu_state.ko'
            data = bytearray(module.read_bytes())
            data[-1] ^= 1
            module.write_bytes(data)
        if name == 'extra_file':
            (target / 'unexpected.txt').write_text('not indexed\n')
        index = json.loads((target / 'index.json').read_text(encoding='utf-8'))
        for relative in index['files']:
            index['files'][relative] = verifier.pin(target / relative)
        verifier.transport.write_json(target / 'index.json', index)
        try:
            verifier.verify(target)
        except ValueError as exc:
            if expected not in str(exc):
                raise ValueError(name + ' reached wrong guard: ' + str(exc)) from exc
            results.append({'case': name, 'rejected': True, 'reason': str(exc)})
        else:
            raise ValueError('forgery accepted: ' + name)
    verifier.transport.write_json(root / 'result.json', {'original': args.packet,
        'original_pin': verifier.pin(original / 'result.json'), 'cases': results,
        'phone_operations': False})
    print('CPU_STATE_EVIDENCE_GUARDS 8/8 rejected ' + root.relative_to(PROJECT).as_posix())

if __name__ == '__main__':
    main()
