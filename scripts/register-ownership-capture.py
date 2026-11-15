#!/usr/bin/env python3
"""Associate the completed pilot capture with its immutable recorder snapshots."""
import importlib.util
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ownership_device', PROJECT / 'scripts/test-ownership-probe-device.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
path = module.register_capture_binding(PROJECT / 'evidence/phase-2/ownership-probe-device/20261111T141913580938Z')
print('CAPTURE_SOURCE_BINDING ' + path.relative_to(PROJECT).as_posix())
