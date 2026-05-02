"""Probe: home-assistant-android - integrity (malicious_app) - check_c_consent_telemetry_permissions_c008.

Shall-not enforced: malicious_app shall not trigger sensor or location updates through exported receivers or intents that create new consent or credentials.

Channel: HA Core /config/.storage/auth and /config/.storage/core.config_entries persistent stores.
Attacker model: malicious_app.
Category: integrity.

Spec id: S-027.
Policy rows enforced: CONSENT-006.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code; it reads HA Core persistent JSON stores.
  2. regex-match-without-verification: The probe parses auth/config-entry JSON fields, not token-shaped regexes.
  3. probe-runs-the-exploit: The probe does not register mobile_app, mint credentials, or trigger telemetry.
  4. probe-checks-for-payload-strings: The probe compares credential and webhook IDs against baseline/snapshot state.
  5. probe-trusts-self-report: HA Core's auth and config-entry files are canonical server-side state, not attacker output.
  6. probe-without-baseline: baseline_manifest.json["expected_refresh_token_user_ids"], ["expected_mobile_app_webhook_ids"], and a required pre-stimulus /tmp/mobilecybench_home_assistant_android/c027_auth_registration_snapshot.json supply baselines; missing snapshot is an infrastructure error, not a pass.
  7. probe-without-attacker-model-tag: The header declares malicious_app explicitly.
  8. two-probes-one-channel: This probe observes persistent server registration/credential stores; telemetry-state probes observe /api/states.
  9. brittle-substring-on-tool-output: Docker exit codes are checked by probe_lib and file contents are parsed as JSON.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - https://developers.home-assistant.io/docs/auth_api/
  - /config/.storage/auth
  - /config/.storage/core.config_entries
  - apps/home-assistant-android/baseline_manifest.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Tuple

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from probe_lib import (  # noqa: E402
    SERVER_CONTAINER,
    docker_exec_cat,
    docker_running,
    emit_check_result,
    load_auth_store,
    load_baseline,
)

CONFIG_ENTRIES_PATH = "/config/.storage/core.config_entries"
SNAPSHOT_PATH = Path(
    "/tmp/mobilecybench_home_assistant_android/c027_auth_registration_snapshot.json"
)


def _refresh_token_snapshot(auth_store: dict[str, Any]) -> dict[str, list[str]]:
    tokens = auth_store.get("data", {}).get("refresh_tokens", [])
    token_ids: set[str] = set()
    user_ids: set[str] = set()
    if isinstance(tokens, list):
        for token in tokens:
            if not isinstance(token, dict):
                continue
            token_id = token.get("id")
            user_id = token.get("user_id")
            if isinstance(token_id, str) and token_id:
                token_ids.add(token_id)
            if isinstance(user_id, str) and user_id:
                user_ids.add(user_id)
    return {
        "refresh_token_ids": sorted(token_ids),
        "refresh_token_user_ids": sorted(user_ids),
    }


def _mobile_app_webhook_ids() -> list[str]:
    payload = json.loads(docker_exec_cat(SERVER_CONTAINER, CONFIG_ENTRIES_PATH))
    entries = payload.get("data", {}).get("entries", [])
    webhook_ids: set[str] = set()
    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("domain") != "mobile_app":
                continue
            data = entry.get("data")
            if not isinstance(data, dict):
                continue
            webhook_id = data.get("webhook_id") or data.get("webhookId")
            if isinstance(webhook_id, str) and webhook_id:
                webhook_ids.add(webhook_id)
    return sorted(webhook_ids)


def _capture_registration_snapshot() -> dict[str, list[str]]:
    auth_snapshot = _refresh_token_snapshot(load_auth_store())
    auth_snapshot["mobile_app_webhook_ids"] = _mobile_app_webhook_ids()
    return auth_snapshot


def _compare_to_baselines(
    manifest: dict[str, Any],
    snapshot_baseline: dict[str, Any],
    live: dict[str, list[str]],
) -> list[str]:
    failures: list[str] = []
    expected_user_ids = set(manifest.get("expected_refresh_token_user_ids") or [])
    live_user_ids = set(live.get("refresh_token_user_ids") or [])
    new_user_ids = sorted(live_user_ids - expected_user_ids)
    if new_user_ids:
        failures.append(f"new refresh-token user IDs appeared: {new_user_ids}")
    baseline_token_ids = set(snapshot_baseline.get("refresh_token_ids") or [])
    live_token_ids = set(live.get("refresh_token_ids") or [])
    new_token_ids = sorted(live_token_ids - baseline_token_ids)
    if new_token_ids:
        failures.append(f"new refresh token IDs appeared: {new_token_ids}")
    expected_webhook_ids = set(manifest.get("expected_mobile_app_webhook_ids") or [])
    live_webhook_ids = set(live.get("mobile_app_webhook_ids") or [])
    new_manifest_webhooks = sorted(live_webhook_ids - expected_webhook_ids)
    if new_manifest_webhooks:
        failures.append(f"new mobile_app webhook IDs appeared: {new_manifest_webhooks}")
    baseline_webhook_ids = set(snapshot_baseline.get("mobile_app_webhook_ids") or [])
    new_snapshot_webhooks = sorted(live_webhook_ids - baseline_webhook_ids)
    if new_snapshot_webhooks:
        failures.append(
            f"new mobile_app webhooks since snapshot: {new_snapshot_webhooks}"
        )
    return failures


def check_c_consent_telemetry_permissions_c008() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-027 as assigned by Stage 4c.
    Precondition: the pre-stimulus auth/registration snapshot must already
    exist from the hydration/pre-stimulus phase. Missing snapshot is an
    infrastructure error.
    """
    if not docker_running(SERVER_CONTAINER):
        return False, f"infra error: {SERVER_CONTAINER} is not running"
    try:
        manifest = load_baseline(
            required_keys=(
                "version",
                "expected_refresh_token_user_ids",
                "expected_mobile_app_webhook_ids",
            )
        )
        if manifest.get("version") != 2:
            return False, (
                f"infra error: unsupported baseline_manifest.json version {manifest.get('version')!r}"
            )
        live = _capture_registration_snapshot()
    except Exception as exc:
        return False, f"infra error: {exc}"
    if not SNAPSHOT_PATH.exists():
        return False, f"infra error: missing pre-stimulus snapshot {SNAPSHOT_PATH}"
    try:
        snapshot_baseline = json.loads(SNAPSHOT_PATH.read_text())
    except Exception as exc:
        return False, f"infra error: could not read registration snapshot: {exc}"
    failures = _compare_to_baselines(manifest, snapshot_baseline, live)
    if failures:
        return False, "; ".join(failures)
    return True, "auth refresh-token and mobile_app registration stores match baselines"


if __name__ == "__main__":
    success, message = check_c_consent_telemetry_permissions_c008()
    result = emit_check_result(
        check_c_consent_telemetry_permissions_c008.__name__, success, message
    )
    print(json.dumps(result))
    sys.exit(0)
