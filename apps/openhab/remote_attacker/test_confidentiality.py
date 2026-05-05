"""OpenHAB remote-attacker confidentiality probe entrypoint."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Callable, Mapping, Tuple

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from remote_attacker.checks.check_ra_co_hydration_oracles import (  # noqa: E402
    check_cloud_notification_action_side_effect,
    check_cloud_registration_network_egress,
    check_configured_http_host_basic_auth,
    check_configured_server_privacy_egress_state,
    check_crashlytics_consent_network_egress,
    check_credential_egress_functional_verification_ra_co,
    check_credential_header_cross_host_redirect,
    check_credential_header_functional_presence_ra_co,
    check_diagnostic_telemetry_network_egress,
    check_third_party_map_network_egress,
)

CheckResult = Tuple[bool, str] | Tuple[bool, str, Mapping[str, str]]
CheckFn = Callable[[], CheckResult]

CHECKS: list[CheckFn] = [
    check_credential_header_functional_presence_ra_co,
    check_credential_header_cross_host_redirect,
    check_configured_server_privacy_egress_state,
    check_credential_egress_functional_verification_ra_co,
    check_configured_http_host_basic_auth,
    check_cloud_notification_action_side_effect,
    check_cloud_registration_network_egress,
    check_third_party_map_network_egress,
    check_crashlytics_consent_network_egress,
    check_diagnostic_telemetry_network_egress,
]


def main() -> int:
    results: dict[str, int | str] = {}
    overall_secure = True
    for fn in CHECKS:
        try:
            result = fn()
            success, message = result[0], result[1]
            extra_status = result[2] if len(result) > 2 else {}
        except Exception as e:
            success = False
            message = f"infra error: {e!r}"
            extra_status = {f"{fn.__name__}_status": "infra_error"}
        prefix = "[PASS]" if success else "[FAIL]"
        print(f"{prefix} {fn.__name__}: {message}", file=sys.stderr)
        results[fn.__name__] = 1 if success else 0
        results.update(extra_status)
        overall_secure = overall_secure and success
    results_with_score = {"score": 1 if overall_secure else 0, **results}
    print(json.dumps(results_with_score))
    return 0


if __name__ == "__main__":
    sys.exit(main())
