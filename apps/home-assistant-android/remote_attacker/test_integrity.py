#!/usr/bin/env python3
"""Entrypoint for remote_attacker integrity probes.

Aggregates RA-I checks that observe post-exploit HA state. The legacy
admin-only-endpoint sub-check still lives in remote_attacker/test_access_control.py
for access-cell continuity.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

from checks.check_auth_provider_functional_diff import (  # noqa: E402
    check_auth_provider_functional_diff,
)
from checks.check_automations_list_unchanged import (  # noqa: E402
    check_automations_list_unchanged,
)
from checks.check_c_consent_telemetry_permissions_c010 import (  # noqa: E402
    check_c_consent_telemetry_permissions_c010,
)
from checks.check_no_location_spoofing_via_webhook import (  # noqa: E402
    check_no_location_spoofing_via_webhook,
)
from checks.check_scripts_list_unchanged import (  # noqa: E402
    check_scripts_list_unchanged,
)
from probe_lib import run_check_functions  # noqa: E402

CHECKS = [
    check_automations_list_unchanged,
    check_auth_provider_functional_diff,
    check_no_location_spoofing_via_webhook,
    check_scripts_list_unchanged,
    check_c_consent_telemetry_permissions_c010,
]


def main() -> int:
    print(json.dumps(run_check_functions(CHECKS), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
