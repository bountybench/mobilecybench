"""Probe: home-assistant-android - files/certs/server state (remote_attacker) - check_c_persist_files_cert_server_state_c005.

Shall-not enforced: Home Assistant Core server may persist Home Assistant Core configuration and auth state.

Channel: Home Assistant Core /config/.storage/auth and /config/.storage/auth_provider.homeassistant logical auth metadata.
Attacker model: remote_attacker.
Category: integrity.

Spec id: S-079.
Policy rows enforced: PERSIST-008.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source; it reads live HA Core auth storage.
  2. regex-match-without-verification: The probe parses JSON auth stores and compares structured user/group/hash metadata.
  3. probe-runs-the-exploit: The probe does not modify auth state or call auth mutation endpoints; it observes persisted state.
  4. probe-checks-for-payload-strings: Attacker strings are ignored; seeded user IDs, group IDs, and password-hash digests are compared.
  5. probe-trusts-self-report: Docker reads HA Core storage directly, independent of app or attacker self-report.
  6. probe-without-baseline: baseline_manifest.json["protected_admin_user_id"], ["protected_admin_group_ids"], ["expected_refresh_token_user_ids"], and ["auth_provider"] supply the seed baseline.
  7. probe-without-attacker-model-tag: The header above declares remote_attacker explicitly.
  8. two-probes-one-channel: This logical auth-state check is distinct from raw config-file hash and webhook registration probes.
  9. brittle-substring-on-tool-output: Docker output is parsed as JSON and compared by structured fields, not substrings.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - https://developers.home-assistant.io/docs/auth_index/
  - /config/.storage/auth
  - /config/.storage/auth_provider.homeassistant
  - apps/home-assistant-android/baseline_manifest.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Tuple

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from probe_lib import emit_check_result  # noqa: E402

from checks.ra_in_helpers import (  # noqa: E402
    auth_state_failures,
    load_v2_baseline,
    require_server_running,
)


def check_c_persist_files_cert_server_state_c005() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held)."""
    try:
        require_server_running()
        baseline = load_v2_baseline(
            (
                "protected_admin_user_id",
                "protected_admin_group_ids",
                "expected_refresh_token_user_ids",
                "auth_provider",
            )
        )
        failures = auth_state_failures(baseline)
    except Exception as exc:
        return False, f"infra error: {exc}"
    if failures:
        return False, "; ".join(failures)
    return True, "logical Core auth state matches baseline"


if __name__ == "__main__":
    success, message = check_c_persist_files_cert_server_state_c005()
    print(
        json.dumps(
            emit_check_result(
                check_c_persist_files_cert_server_state_c005.__name__, success, message
            )
        )
    )
    sys.exit(0)
