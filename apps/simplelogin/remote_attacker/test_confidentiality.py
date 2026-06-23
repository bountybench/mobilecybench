#!/usr/bin/env python3
"""Remote-attacker wrapper for SimpleLogin confidentiality passive probes."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))
spec = importlib.util.spec_from_file_location(
    "simplelogin_confidentiality_probe", APP_DIR / "test_confidentiality.py"
)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)
module.ATTACKER_MODEL = "remote_attacker"

if __name__ == "__main__":
    sys.exit(module.main(sys.argv))
