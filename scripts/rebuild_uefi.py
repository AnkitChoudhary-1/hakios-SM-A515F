"""Incremental rebuild of the existing, patched A51 Mu-Silicium tree under WSL.

Preserves applied patches; does not call the wrapper that resets/reapplies them.
"""
import os
import pathlib
import subprocess

REPO = pathlib.Path('/opt/a51-hakios/upstream-a51/hakios')
OUT = pathlib.Path(__file__).resolve().parents[1]
env = os.environ.copy()
env['PATH'] = str(REPO / 'venv/bin') + ':' + env['PATH']
with (OUT / 'a51-uefi-build.log').open('w') as log:
    subprocess.run([str(REPO / 'venv/bin/python3'),
                    'Platforms/Samsung/a51Pkg/DeviceBuild.py',
                    'TARGET=RELEASE', 'ENABLE_SECUREBOOT=0',
                    'FD_BASE=0xa0000000', 'FD_SIZE=0x200000',
                    'FD_BLOCKS=0x200', 'DEVICE_MODEL=0'],
                   cwd=REPO / 'Mu-Silicium', env=env, stdout=log,
                   stderr=subprocess.STDOUT, check=True)
print('Incremental A51 UEFI rebuild complete; see a51-uefi-build.log.')
