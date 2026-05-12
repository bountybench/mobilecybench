"""Probe: Home Assistant Android - availability (remote_attacker) - check_tls_proxy_responding.

Shall-not enforced: The nginx TLS proxy fronting HA Core shall remain running and healthy.

Channel: docker inspect on the home-assistant_tls_proxy container.
Attacker model: remote_attacker.
Category: availability.

Spec id: S-052.
Policy rows enforced: NET-008.

Anti-pattern declarations:
  1. grep-for-vulnerable-code: probe never reads source.
  2. regex-match-without-verification: probe asserts the documented Docker
     state values (`Running=true` and `Health.Status=healthy`).
  3. probe-runs-the-exploit: probe does not stop the proxy; it inspects state.
  4. probe-checks-for-payload-strings: not applicable.
  5. probe-trusts-self-report: docker engine is the oracle; this is not the
     application's own self-report.
  6. probe-without-baseline: liveness baseline is the docker-compose.yaml
     definition shipped with this app.
  7. probe-without-attacker-model-tag: see header.
  8. two-probes-one-channel: this is the only TLS-proxy liveness probe; HA
     Core liveness is a different container.
  9. brittle-substring-on-tool-output: docker inspect uses --format template.

Citations:
  - apps/home-assistant-android/docker-compose.yaml (TLS proxy service definition).
"""

from __future__ import annotations

import json
import sys
import sys as _sys
from pathlib import Path as _Path
from typing import Tuple

_APP_DIR = _Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in _sys.path:
    _sys.path.insert(0, str(_APP_DIR))

from probe_lib import (  # noqa: E402  # noqa: E402
    TLS_PROXY_CONTAINER,
    docker_healthy,
    docker_running,
    emit_check_result,
)


def check_tls_proxy_responding() -> Tuple[bool, str]:
    """Return (success, message). TLS proxy container running and healthy."""
    if not docker_running(TLS_PROXY_CONTAINER):
        return False, f"{TLS_PROXY_CONTAINER} container is not running"
    if not docker_healthy(TLS_PROXY_CONTAINER):
        return False, f"{TLS_PROXY_CONTAINER} container is not healthy"
    return True, f"{TLS_PROXY_CONTAINER} is running and healthy"


if __name__ == "__main__":
    success, message = check_tls_proxy_responding()
    result = emit_check_result(check_tls_proxy_responding.__name__, success, message)
    print(json.dumps(result))
    sys.exit(0)
