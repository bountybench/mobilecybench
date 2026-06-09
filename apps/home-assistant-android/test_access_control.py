#!/usr/bin/env python3
"""Entrypoint for malicious_app access-control probes."""
from __future__ import annotations

import json
import sys

from checks.check_c_ipc_android_entrypoints_c002 import (
    check_c_ipc_android_entrypoints_c002,
)
from probe_lib import run_check_functions

CHECKS = [
    check_c_ipc_android_entrypoints_c002,
]


def main() -> int:
    print(json.dumps(run_check_functions(CHECKS), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
