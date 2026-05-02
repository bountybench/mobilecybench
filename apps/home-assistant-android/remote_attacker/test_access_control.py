#!/usr/bin/env python3
"""Entrypoint for remote_attacker access-control probes.

Aggregates the RA-C admin-identity / admin-refresh-token / admin-only-endpoint
checks. Each check is a self-contained file under
apps/home-assistant-android/checks/.

The RA-I admin-only-endpoint sub-check lives in this entrypoint (rather than
test_integrity.py) for legacy scoring continuity; remote_attacker/
test_integrity.py remains a no-checks aggregator that emits a documented
status string.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

from checks.check_admin_endpoints_reject_nonadmin_extended import (  # noqa: E402
    check_admin_endpoints_reject_nonadmin_extended,
)
from checks.check_admin_identity_intact import check_admin_identity_intact  # noqa: E402
from checks.check_admin_only_endpoints_reject_nonadmin import (  # noqa: E402
    check_admin_only_endpoints_reject_nonadmin,
)
from checks.check_c_ctrl_registration_auth_control_c001 import (  # noqa: E402
    check_c_ctrl_registration_auth_control_c001,
)
from checks.check_c_ctrl_registration_auth_control_c002 import (  # noqa: E402
    check_c_ctrl_registration_auth_control_c002,
)
from checks.check_c_ctrl_registration_auth_control_c004 import (  # noqa: E402
    check_c_ctrl_registration_auth_control_c004,
)
from checks.check_c_ctrl_registration_auth_control_c005 import (  # noqa: E402
    check_c_ctrl_registration_auth_control_c005,
)
from checks.check_c_ctrl_registration_auth_control_c007 import (  # noqa: E402
    check_c_ctrl_registration_auth_control_c007,
)
from checks.check_c_ctrl_registration_auth_control_c012 import (  # noqa: E402
    check_c_ctrl_registration_auth_control_c012,
)
from checks.check_c_net_selected_server_trust_c001 import (  # noqa: E402
    check_c_net_selected_server_trust_c001,
)
from checks.check_c_net_selected_server_trust_c007 import (  # noqa: E402
    check_c_net_selected_server_trust_c007,
)
from checks.check_c_net_selected_server_trust_c008 import (  # noqa: E402
    check_c_net_selected_server_trust_c008,
)
from checks.check_no_new_admin_refresh_tokens import (  # noqa: E402
    check_no_new_admin_refresh_tokens,
)


def main() -> int:
    checks = [
        check_no_new_admin_refresh_tokens,
        check_admin_identity_intact,
        check_admin_only_endpoints_reject_nonadmin,
        check_admin_endpoints_reject_nonadmin_extended,
        check_c_ctrl_registration_auth_control_c004,
        check_c_ctrl_registration_auth_control_c012,
        check_c_net_selected_server_trust_c001,
        check_c_ctrl_registration_auth_control_c005,
        check_c_ctrl_registration_auth_control_c007,
        check_c_net_selected_server_trust_c007,
        check_c_net_selected_server_trust_c008,
        check_c_ctrl_registration_auth_control_c002,
        check_c_ctrl_registration_auth_control_c001,
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
