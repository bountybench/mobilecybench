#!/usr/bin/env python3
"""Entrypoint for malicious_app availability probes.

Aggregates only the MA-AV checks assigned to this slot.
"""
from __future__ import annotations

import json
import sys

from checks.check_notification_delivery_succeeds import (
    check_notification_delivery_succeeds,
)
from probe_lib import run_check_functions

CHECKS = [
    check_notification_delivery_succeeds,
]


def main() -> int:
    print(json.dumps(run_check_functions(CHECKS), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
