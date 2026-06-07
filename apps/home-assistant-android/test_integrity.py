#!/usr/bin/env python3
"""Entrypoint for malicious_app integrity probes.

Aggregates the legacy MA-I auth-store-drift check. See the docstring of
`checks/check_legacy_auth_store_drift.py` for the documented coverage gap
explaining why this probe is intentionally weak in this round.
"""
from __future__ import annotations

import json
import sys

from checks.check_c_consent_telemetry_permissions_c007 import (
    check_c_consent_telemetry_permissions_c007,
)
from checks.check_legacy_auth_store_drift import check_legacy_auth_store_drift
from probe_lib import run_check_functions

CHECKS = [
    check_legacy_auth_store_drift,
    check_c_consent_telemetry_permissions_c007,
]


def main() -> int:
    print(json.dumps(run_check_functions(CHECKS), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
