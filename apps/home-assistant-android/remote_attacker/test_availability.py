#!/usr/bin/env python3
"""Entrypoint for remote_attacker availability probes.

Re-exercises the same liveness checks as the top-level test_availability.py.
The legacy file was a thin importlib wrapper; with the per-file restructure we
import the same check_* functions directly so that the per-check JSON keys
match across both entrypoints.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

from checks.check_c_consent_user_feature_gates_c001 import (  # noqa: E402
    check_c_consent_user_feature_gates_c001,
)
from checks.check_c_consent_user_feature_gates_c002 import (  # noqa: E402
    check_c_consent_user_feature_gates_c002,
)
from checks.check_c_net_selected_server_trust_c009 import (  # noqa: E402
    check_c_net_selected_server_trust_c009,
)
from checks.check_c_net_selected_server_trust_c010 import (  # noqa: E402
    check_c_net_selected_server_trust_c010,
)
from checks.check_c_net_selected_server_trust_c011 import (  # noqa: E402
    check_c_net_selected_server_trust_c011,
)
from checks.check_companion_process_alive import (  # noqa: E402
    check_companion_process_alive,
)
from checks.check_ha_core_responding import check_ha_core_responding  # noqa: E402
from checks.check_no_notification_channel_silenced import (  # noqa: E402
    check_no_notification_channel_silenced,
)
from checks.check_notification_delivery_succeeds import (  # noqa: E402
    check_notification_delivery_succeeds,
)
from checks.check_tls_proxy_responding import (  # noqa: E402
    check_tls_proxy_responding,
)


def main() -> int:
    checks = [
        check_ha_core_responding,
        check_tls_proxy_responding,
        check_companion_process_alive,
        check_notification_delivery_succeeds,
        check_no_notification_channel_silenced,
        check_c_consent_user_feature_gates_c001,
        check_c_consent_user_feature_gates_c002,
        check_c_net_selected_server_trust_c009,
        check_c_net_selected_server_trust_c010,
        check_c_net_selected_server_trust_c011,
    ]
    results: dict[str, int] = {}
    overall_success = True
    for check in checks:
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
