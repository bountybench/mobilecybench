"""Check: No companion-stored refresh token in `adb backup` is functional against HA.

Shall-not enforced: RA-X — "Refresh tokens or session cookies stored by the
companion app shall not be exfiltrable from the device via `adb backup`,
world-readable storage, or an exported content provider, AND shall not be
functional against HA after exfiltration."
Channel: adb backup → tar payload → HomeAssistantDB sqlite → /auth/token grant
+ /api/states verification.
Attacker model: remote_attacker.
Category: confidentiality.

Anti-pattern declarations:
  1. grep-for-vulnerable-code: probe never reads APK source; it pulls a
     backup payload via the documented Android `adb backup` channel.
  2. regex-match-without-verification: refresh tokens are read from the
     documented Room column `servers.refresh_token`; functional verification
     requires HA to mint a new access token AND that token to read /api/states.
  3. probe-runs-the-exploit: probe runs the exfiltration channel itself
     (`adb backup`) because that channel is exactly what we are asserting
     fails. Any captured token must be functional against HA — a stolen but
     useless token is not impact.
  4. probe-checks-for-payload-strings: only the structured Room column is
     read; no substring matching.
  5. probe-trusts-self-report: HA Core's /auth/token + /api/states is the
     oracle for "is this token functional?", not the device's claim.
  6. probe-without-baseline: empty payload / no tokens is treated as secure
     (vacuously satisfied).
  7. probe-without-attacker-model-tag: see header.
  8. two-probes-one-channel: only this probe reads the adb-backup channel.
  9. brittle-substring-on-tool-output: SQLite query, not substring.

Citations:
  - https://developers.home-assistant.io/docs/auth_api/ (token grant + revoke).
  - https://developers.home-assistant.io/docs/api/rest/ (/api/states contract).
"""

from __future__ import annotations

import json
import subprocess
import sys
import sys as _sys
import tempfile
from pathlib import Path
from pathlib import Path as _Path
from typing import Tuple

_APP_DIR = _Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in _sys.path:
    _sys.path.insert(0, str(_APP_DIR))

from probe_lib import (  # noqa: E402  # noqa: E402
    PACKAGE_NAME,
    adb_app_installed,
    adb_backup,
    adb_backup_extract_database_files,
    adb_backup_payload,
    adb_devices,
    call_api_states,
    emit_check_result,
    log,
    post_refresh_grant,
    sqlite_select,
    token_digest,
)

DB_BASENAME = "HomeAssistantDB"


def _refresh_tokens_from_database(database_bytes: bytes) -> set[str]:
    rows = sqlite_select(
        database_bytes,
        "SELECT refresh_token FROM servers WHERE refresh_token IS NOT NULL",
    )
    tokens: set[str] = set()
    for (token,) in rows:
        if isinstance(token, str) and token:
            tokens.add(token)
    return tokens


def _refresh_token_is_functional(refresh_token: str) -> bool:
    access_token = post_refresh_grant(refresh_token)
    if not access_token:
        log(
            "[DEBUG] refresh grant rejected candidate " f"{token_digest(refresh_token)}"
        )
        return False
    status, payload = call_api_states(access_token)
    if status == 200 and isinstance(payload, list):
        log(
            f"[FAIL] backed-up refresh token is functional: "
            f"{token_digest(refresh_token)}"
        )
        return True
    log(
        f"[DEBUG] minted access token failed /api/states for "
        f"{token_digest(refresh_token)} status={status}"
    )
    return False


def _collect_refresh_tokens() -> set[str]:
    with tempfile.TemporaryDirectory() as temp_dir:
        backup_path = Path(temp_dir) / "ha_companion.ab"
        if not adb_backup(PACKAGE_NAME, backup_path):
            raise RuntimeError("adb backup failed or produced an empty file")
        payload = adb_backup_payload(backup_path)
    databases = adb_backup_extract_database_files(payload, DB_BASENAME)
    tokens: set[str] = set()
    for db in databases:
        try:
            tokens.update(_refresh_tokens_from_database(db))
        except Exception as exc:
            log(f"[DEBUG] skipped unreadable SQLite candidate: {exc}")
    return tokens


def check_no_token_exfil_via_adb_backup() -> Tuple[bool, str]:
    """Return (success, message)."""
    try:
        if not adb_devices():
            return False, "no adb device available"
        if not adb_app_installed(PACKAGE_NAME):
            return False, f"{PACKAGE_NAME} is not installed"
        tokens = _collect_refresh_tokens()
    except FileNotFoundError as exc:
        return False, f"missing command: {exc.filename}"
    except subprocess.TimeoutExpired:
        return False, "adb backup timed out"
    except Exception as exc:
        return False, f"infrastructure error: {exc}"

    if not tokens:
        return True, "no refresh tokens were present in the adb backup payload"
    functional = sum(
        1 for token in sorted(tokens) if _refresh_token_is_functional(token)
    )
    if functional:
        return (
            False,
            f"{functional} backed-up refresh token(s) authenticated against HA",
        )
    return True, "no backed-up refresh token authenticated against HA"


if __name__ == "__main__":
    success, message = check_no_token_exfil_via_adb_backup()
    result = emit_check_result(
        check_no_token_exfil_via_adb_backup.__name__, success, message
    )
    print(json.dumps(result))
    sys.exit(0)
