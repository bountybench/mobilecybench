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
from checks.check_c_consent_telemetry_permissions_c001 import (  # noqa: E402
    check_c_consent_telemetry_permissions_c001,
)
from checks.check_c_consent_telemetry_permissions_c002 import (  # noqa: E402
    check_c_consent_telemetry_permissions_c002,
)
from checks.check_c_consent_telemetry_permissions_c004 import (  # noqa: E402
    check_c_consent_telemetry_permissions_c004,
)
from checks.check_c_consent_telemetry_permissions_c005 import (  # noqa: E402
    check_c_consent_telemetry_permissions_c005,
)
from checks.check_c_consent_telemetry_permissions_c010 import (  # noqa: E402
    check_c_consent_telemetry_permissions_c010,
)
from checks.check_c_consent_telemetry_permissions_c011 import (  # noqa: E402
    check_c_consent_telemetry_permissions_c011,
)
from checks.check_c_data_outbound_mobile_events_c001 import (  # noqa: E402
    check_c_data_outbound_mobile_events_c001,
)
from checks.check_c_data_outbound_mobile_events_c002 import (  # noqa: E402
    check_c_data_outbound_mobile_events_c002,
)
from checks.check_c_data_outbound_mobile_events_c003 import (  # noqa: E402
    check_c_data_outbound_mobile_events_c003,
)
from checks.check_c_data_outbound_mobile_events_c004 import (  # noqa: E402
    check_c_data_outbound_mobile_events_c004,
)
from checks.check_c_exec_webview_network_code_c001 import (  # noqa: E402
    check_c_exec_webview_network_code_c001,
)
from checks.check_c_exec_webview_network_code_c005 import (  # noqa: E402
    check_c_exec_webview_network_code_c005,
)
from checks.check_c_exec_webview_network_code_c006 import (  # noqa: E402
    check_c_exec_webview_network_code_c006,
)
from checks.check_c_exec_webview_network_code_c007 import (  # noqa: E402
    check_c_exec_webview_network_code_c007,
)
from checks.check_c_exec_webview_network_code_c012 import (  # noqa: E402
    check_c_exec_webview_network_code_c012,
)
from checks.check_c_ffi_native_bridge_c003 import (  # noqa: E402
    check_c_ffi_native_bridge_c003,
)
from checks.check_c_net_selected_server_trust_c005 import (  # noqa: E402
    check_c_net_selected_server_trust_c005,
)
from checks.check_c_net_selected_server_trust_c006 import (  # noqa: E402
    check_c_net_selected_server_trust_c006,
)
from checks.check_c_persist_files_cert_server_state_c005 import (  # noqa: E402
    check_c_persist_files_cert_server_state_c005,
)
from checks.check_no_location_spoofing_via_webhook import (  # noqa: E402
    check_no_location_spoofing_via_webhook,
)
from checks.check_no_sensor_state_injection_via_webhook import (  # noqa: E402
    check_no_sensor_state_injection_via_webhook,
)
from checks.check_no_unauthorized_alarm_state_change import (  # noqa: E402
    check_no_unauthorized_alarm_state_change,
)
from checks.check_no_unauthorized_lock_state_change import (  # noqa: E402
    check_no_unauthorized_lock_state_change,
)
from checks.check_scripts_list_unchanged import (  # noqa: E402
    check_scripts_list_unchanged,
)

CHECKS = [
    check_no_unauthorized_lock_state_change,
    check_no_unauthorized_alarm_state_change,
    check_automations_list_unchanged,
    check_auth_provider_functional_diff,
    check_no_sensor_state_injection_via_webhook,
    check_no_location_spoofing_via_webhook,
    check_scripts_list_unchanged,
    check_c_exec_webview_network_code_c001,
    check_c_ffi_native_bridge_c003,
    check_c_exec_webview_network_code_c006,
    check_c_exec_webview_network_code_c005,
    check_c_exec_webview_network_code_c007,
    check_c_consent_telemetry_permissions_c001,
    check_c_consent_telemetry_permissions_c002,
    check_c_data_outbound_mobile_events_c003,
    check_c_data_outbound_mobile_events_c004,
    check_c_net_selected_server_trust_c005,
    check_c_consent_telemetry_permissions_c004,
    check_c_consent_telemetry_permissions_c005,
    check_c_consent_telemetry_permissions_c010,
    check_c_consent_telemetry_permissions_c011,
    check_c_data_outbound_mobile_events_c001,
    check_c_data_outbound_mobile_events_c002,
    check_c_exec_webview_network_code_c012,
    check_c_net_selected_server_trust_c006,
    check_c_persist_files_cert_server_state_c005,
]


def main() -> int:
    results: dict[str, int] = {}
    overall_success = True
    for check in CHECKS:
        try:
            success, message = check()
        except Exception as exc:
            success, message = False, f"infrastructure error: {exc}"
        results[check.__name__] = 1 if success else 0
        prefix = "[PASS]" if success else "[FAIL]"
        print(f"{prefix} {check.__name__}: {message}", file=sys.stderr)
        if not success:
            overall_success = False
    results["score"] = 1 if overall_success else 0
    print(json.dumps(results, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
