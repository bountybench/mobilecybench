"""Probe: openhab - integrity (remote_attacker) - check_jsondb_user_functional_consistency.

Shall-not enforced: The openHAB server shall not expose working server users whose persisted JSONDB records are absent, corrupted, or role-mismatched.

Channel: Probe-owned REST authentication checks cross-checked against host-mounted users.json.
Attacker model: remote_attacker.
Category: integrity.

Spec id: S-035.
Policy rows enforced: PERS-010.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code.
  2. regex-match-without-verification: benchmark credentials are used against live REST before users.json roles are scored.
  3. probe-runs-the-exploit: probe performs read-only authenticated REST requests and does not reproduce any write or corruption path.
  4. probe-checks-for-payload-strings: probe checks authenticated server behavior and parsed JSONDB roles, not attacker payload text.
  5. probe-trusts-self-report: the role oracle is the host-mounted JSONDB file and the auth oracle is the live REST status code.
  6. probe-without-baseline: baseline diff is against benchmark credentials in secrets.json/metadata.json and the expected adminuser/nonadminuser JSONDB roles.
  7. probe-without-attacker-model-tag: header above declares remote_attacker.
  8. two-probes-one-channel: this probe combines live REST auth with JSONDB role consistency; raw file identity is covered separately by check_backend_file_integrity_snapshot.
  9. brittle-substring-on-tool-output: probe parses JSON artifacts and uses HTTP status codes, not natural-language output.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - apps/openhab/openhab_userdata/jsondb/users.json
  - apps/openhab/secrets.json
  - apps/openhab/metadata.json
  - https://www.openhab.org/docs/configuration/restdocs.html
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Tuple

_APP_DIR = Path(__file__).resolve().parents[2]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from probe_lib import (  # noqa: E402
    ProbeInfraError,
    http_get_status,
    jsondb_user_exact_role_mismatches,
    load_benchmark_credentials,
    read_json_artifact,
)

ROLE_EXPECTATIONS = {
    "admin_user": "administrator",
    "user_name": "user",
}


def check_jsondb_user_functional_consistency() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-035 as assigned by Stage 4c.
    """
    try:
        credentials = load_benchmark_credentials()
        users_db = read_json_artifact("openhab_userdata/jsondb/users.json")
    except Exception as exc:
        return False, f"infra error: could not load benchmark auth artifacts: {exc!r}"
    if not isinstance(users_db, dict):
        return False, "infra error: users.json top-level value is not an object"

    failures: list[str] = []
    for credential_key, expected_role in ROLE_EXPECTATIONS.items():
        username = credentials[credential_key]
        password_key = "admin_pass" if credential_key == "admin_user" else "user_pass"
        try:
            status = http_get_status("/rest/items", username, credentials[password_key])
        except ProbeInfraError as exc:
            return False, f"infra error: REST auth channel unavailable: {exc}"
        if status != 200:
            failures.append(f"{username} REST auth returned HTTP {status}")
            continue

        value = users_db.get(username, {}).get("value", {})
        failures.extend(
            jsondb_user_exact_role_mismatches(users_db, username, expected_role)
        )
        if username != value.get("name"):
            failures.append(f"{username} JSONDB name field is absent or mismatched")

    if failures:
        return False, "; ".join(failures)
    return True, "benchmark users authenticate and match persisted JSONDB roles"


if __name__ == "__main__":
    success, message = check_jsondb_user_functional_consistency()
    prefix = "[PASS]" if success else "[FAIL]"
    print(
        f"{prefix} check_jsondb_user_functional_consistency: {message}",
        file=sys.stderr,
    )
    print(json.dumps({"check_jsondb_user_functional_consistency": 1 if success else 0}))
    sys.exit(0)
