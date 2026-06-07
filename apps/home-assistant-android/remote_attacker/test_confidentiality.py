#!/usr/bin/env python3
"""Entrypoint for remote_attacker confidentiality probes."""
from __future__ import annotations

import json
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

from checks.check_c_persist_client_private_state_c007 import (  # noqa: E402
    check_c_persist_client_private_state_c007,
)
from probe_lib import run_check_functions  # noqa: E402

CHECKS = [
    check_c_persist_client_private_state_c007,
]


def main() -> int:
    print(json.dumps(run_check_functions(CHECKS), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
