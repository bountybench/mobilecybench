#!/usr/bin/env python3
"""Termux remote-attacker access-control probe.

Termux has no backend service; remote-attacker mode uses the same closed-world
device oracles as malicious-app mode but labels the attacker model explicitly.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "termux_access_probe", APP_DIR / "test_access_control.py"
)
if spec is None or spec.loader is None:
    raise ImportError("cannot load parent Termux access-control probe")
module = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(APP_DIR))
spec.loader.exec_module(module)
module.ATTACKER_MODEL = "remote_attacker"

if __name__ == "__main__":
    sys.exit(module.main())
