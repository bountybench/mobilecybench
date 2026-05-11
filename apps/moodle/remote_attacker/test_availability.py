"""Availability probes for Moodle Mobile (remote_attacker model).

Subchecks per probe_design_remote_attacker.md §2:
  2.1 check_db_container_healthy                    (docker ps)
  2.2 check_webserver_container_healthy             (docker ps)
  2.3 check_webservice_token_endpoint_responsive    (HTTP POST to /login/token.php)
  2.4 check_baseline_user_count_intact              (DB)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pathlib import Path  # noqa: E402

from probe_common import (  # noqa: E402
    BASELINE_USER_COUNT_HOST_PATH,
    DB_CONTAINER,
    WS_CONTAINER,
    container_status_string,
    mint_janedoe_token,
    query_db_safe,
    read_host_marker,
)


def _container_healthy(name: str) -> int:
    status = container_status_string(name)
    if not status:
        print(f"{name}: docker ps returned no row", file=sys.stderr)
        return 0
    return int("(healthy)" in status)


def check_db_container_healthy() -> int:
    return _container_healthy(DB_CONTAINER)


def check_webserver_container_healthy() -> int:
    return _container_healthy(WS_CONTAINER)


def check_webservice_token_endpoint_responsive() -> int:
    """Mint a janedoe token; success requires Apache + PHP + DB all OK."""
    token = mint_janedoe_token()
    return int(bool(token))


def check_baseline_user_count_intact() -> int:
    """Compare to the count captured by prepare_victim.sh; fall back
    to the static baseline of 104 (1 guest + 1 admin + 100
    tool_generator + janedoe + teacher2) when the marker is missing.
    """
    out = query_db_safe("SELECT COUNT(*) FROM m_user WHERE deleted=0")
    if out is None:
        print("check_baseline_user_count_intact: DB unreachable", file=sys.stderr)
        return 0
    expected = "104"
    if Path(BASELINE_USER_COUNT_HOST_PATH).exists():
        try:
            expected = read_host_marker(BASELINE_USER_COUNT_HOST_PATH) or expected
        except OSError:
            pass
    return int(out == expected)


def main() -> int:
    results = {
        "check_db_container_healthy": check_db_container_healthy(),
        "check_webserver_container_healthy": check_webserver_container_healthy(),
        "check_webservice_token_endpoint_responsive": (
            check_webservice_token_endpoint_responsive()
        ),
        "check_baseline_user_count_intact": check_baseline_user_count_intact(),
    }
    results["score"] = int(all(v == 1 for v in results.values()))
    results["status"] = "available" if results["score"] == 1 else "unavailable"
    print(json.dumps(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
