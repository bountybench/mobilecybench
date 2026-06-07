#!/usr/bin/env python3
"""Entrypoint for remote_attacker availability probes.

Aggregates only the RA-AV checks assigned to this slot.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

from checks.check_c_net_selected_server_trust_c009 import (  # noqa: E402
    check_c_net_selected_server_trust_c009,
)
from checks.check_c_net_selected_server_trust_c010 import (  # noqa: E402
    check_c_net_selected_server_trust_c010,
)
from checks.check_companion_process_alive import (  # noqa: E402
    check_companion_process_alive,
)
from checks.check_ha_core_responding import check_ha_core_responding  # noqa: E402
from checks.check_tls_proxy_responding import (  # noqa: E402
    check_tls_proxy_responding,
)
from probe_lib import run_check_functions  # noqa: E402

CHECKS = [
    check_companion_process_alive,
    check_ha_core_responding,
    check_tls_proxy_responding,
    check_c_net_selected_server_trust_c009,
    check_c_net_selected_server_trust_c010,
]


def main() -> int:
    print(json.dumps(run_check_functions(CHECKS), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
