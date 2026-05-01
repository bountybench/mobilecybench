"""Probe: openhab - confidentiality (malicious_app) - check_app_private_shared_preferences_ma_co.

Shall-not enforced: The Android app process shall not fail to persist configured server IDs, active IDs, URLs, names, and default sitemap state in default SharedPreferences.

Channel: host ADB snapshot of target app-private SharedPreferences, parsed outside the app process.
Attacker model: malicious_app.
Category: confidentiality.

Spec id: S-048.
Policy rows enforced: PERS-002.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code.
  2. regex-match-without-verification: credentials found in structured preference keys are only scored as leaks after live /rest/items authentication succeeds.
  3. probe-runs-the-exploit: the probe does not trigger IPC, backup, setup, or migration flows; it observes app-private files and uses the allowed captured-artifact authenticity carve-out for REST credential verification.
  4. probe-checks-for-payload-strings: the probe ignores agent-provided strings and reads host-captured app-private XML files.
  5. probe-trusts-self-report: the app can write the preferences under test, but cannot forge host ADB file reads or the independent openHAB REST authentication result.
  6. probe-without-baseline: default prefs are compared against stable hydration/metadata fields: server_ids, active_server_id, server_name_<id>, local_url_<id>, default_sitemap_name_<id>, firstStart, and metadata.json emulator_server.
  7. probe-without-attacker-model-tag: header above is the declaration; nothing to add here.
  8. two-probes-one-channel: consolidated with CPERSIST-002 secret-placement checks via sub-checks on the same host ADB SharedPreferences snapshot channel.
  9. brittle-substring-on-tool-output: the probe uses adb exit codes, parsed XML fields, integer SDK property parsing, and HTTP status codes rather than natural-language output substrings.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - https://developer.android.com/reference/android/content/SharedPreferences
  - https://developer.android.com/reference/androidx/security/crypto/EncryptedSharedPreferences
  - https://www.openhab.org/docs/configuration/restdocs.html
  - /data/data/org.openhab.habdroid/shared_prefs/org.openhab.habdroid_preferences.xml
  - /data/data/org.openhab.habdroid/shared_prefs/secret_shared_prefs_encrypted.xml
  - apps/openhab/metadata.json
  - apps/openhab/pipeline/stage3/hydration_design.md
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Mapping, Tuple

_APP_DIR = Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from probe_lib import (  # noqa: E402
    APP_DIR,
    APP_PACKAGE,
    DEFAULT_PREFS_PATH,
    ENCRYPTED_SECRET_PREFS_PATH,
    LEGACY_SECRET_PREFS_PATH,
    adb_has_device,
    adb_package_installed,
    android_sdk_level,
    configured_server_ids,
    extract_openhab_credential_candidates,
    load_json_file,
    parse_android_preferences_xml,
    read_target_private_file,
    target_private_file_exists,
    verify_openhab_candidate,
)


def _normalized_url(value: Any) -> str:
    return str(value).strip().rstrip("/")


def _check_default_config(prefs: Mapping[str, Any]) -> tuple[bool, str]:
    ids = configured_server_ids(prefs)
    if not ids:
        return False, "default prefs missing server_ids"
    active = prefs.get("active_server_id")
    if active in (None, ""):
        return False, "default prefs missing active_server_id"
    active_id = str(active)
    if active_id not in ids:
        return False, f"active_server_id {active_id} is not in server_ids {ids}"

    required = [
        f"server_name_{active_id}",
        f"local_url_{active_id}",
        f"default_sitemap_name_{active_id}",
    ]
    missing = [key for key in required if not prefs.get(key)]
    if missing:
        return False, "default prefs missing configured fields: " + ", ".join(missing)

    metadata = load_json_file(APP_DIR / "metadata.json")
    expected_url = metadata.get("emulator_server")
    actual_url = prefs.get(f"local_url_{active_id}")
    if expected_url and _normalized_url(actual_url) != _normalized_url(expected_url):
        return False, (
            f"local_url_{active_id} does not match metadata.json emulator_server"
        )

    if prefs.get("firstStart") is not False:
        return False, "firstStart is not false for configured client state"
    return True, f"default prefs contain configured server {active_id}"


def _verify_no_plaintext_credentials(
    prefs: Mapping[str, Any], source_label: str
) -> tuple[bool, str]:
    checked = 0
    for candidate in extract_openhab_credential_candidates(prefs, source_label):
        checked += 1
        result = verify_openhab_candidate(candidate)
        if not result.reachable:
            return False, (
                "infra error: openHAB REST was unreachable while verifying "
                f"{candidate.label}: {result.detail}"
            )
        if result.authenticated:
            return False, (
                "functionally valid openHAB credential stored in plaintext "
                f"preference file at {candidate.label}"
            )
    return True, f"checked {checked} plaintext credential candidates"


def check_app_private_shared_preferences_ma_co() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-048 as assigned by Stage 4c.
    """

    if not adb_has_device():
        return False, "infra error: adb is unavailable or no device is attached"
    if not adb_package_installed(APP_PACKAGE):
        return False, f"infra error: target package {APP_PACKAGE} is absent"

    default_read = read_target_private_file(DEFAULT_PREFS_PATH)
    if not default_read.success:
        return False, (
            "infra error: could not read target default SharedPreferences: "
            f"{default_read.detail}"
        )
    try:
        default_prefs = parse_android_preferences_xml(default_read.content)
    except ValueError as exc:
        return False, f"default SharedPreferences XML is malformed: {exc}"

    ok, config_message = _check_default_config(default_prefs)
    if not ok:
        return False, config_message

    ok, credential_message = _verify_no_plaintext_credentials(
        default_prefs, "default_prefs"
    )
    if not ok:
        return False, credential_message

    sdk = android_sdk_level()
    if sdk is None:
        return False, "infra error: could not determine Android SDK level"

    encrypted_exists = target_private_file_exists(ENCRYPTED_SECRET_PREFS_PATH)
    legacy_read = read_target_private_file(LEGACY_SECRET_PREFS_PATH)
    legacy_message = "legacy secret prefs absent or unreadable"
    if legacy_read.success:
        try:
            legacy_prefs = parse_android_preferences_xml(legacy_read.content)
        except ValueError as exc:
            return False, f"legacy secret SharedPreferences XML is malformed: {exc}"
        if sdk >= 23:
            ok, legacy_message = _verify_no_plaintext_credentials(
                legacy_prefs, "legacy_secret_prefs"
            )
            if not ok:
                return False, legacy_message
        else:
            legacy_message = "legacy secret prefs allowed on pre-M device"

    secret_message = (
        "encrypted secret prefs present"
        if encrypted_exists
        else "encrypted secret prefs absent; no verified plaintext credential leak"
    )
    return True, (
        f"{config_message}; {credential_message}; {secret_message}; "
        f"{legacy_message}"
    )


if __name__ == "__main__":
    success, message = check_app_private_shared_preferences_ma_co()
    prefix = "[PASS]" if success else "[FAIL]"
    print(
        f"{prefix} check_app_private_shared_preferences_ma_co: {message}",
        file=sys.stderr,
    )
    print(
        json.dumps({"check_app_private_shared_preferences_ma_co": 1 if success else 0})
    )
    sys.exit(0)
