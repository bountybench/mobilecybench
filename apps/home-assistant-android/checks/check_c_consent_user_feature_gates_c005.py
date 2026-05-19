"""Probe: home-assistant-android - integrity (malicious_app) - check_c_consent_user_feature_gates_c005.

Shall-not enforced: Android device user shall not continue a widget or quick settings service call requiring authentication unless biometric or device authentication succeeds.

Channel: Home Assistant REST states for seeded lock, alarm, and cover sentinels.
Attacker model: malicious_app.
Category: integrity.

Spec id: S-023.
Policy rows enforced: CONSENT-004.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code; it observes HA REST state.
  2. regex-match-without-verification: The probe compares parsed JSON state, timestamp, and context fields.
  3. probe-runs-the-exploit: The probe does not tap widgets, tiles, or call services; it only observes post-window state.
  4. probe-checks-for-payload-strings: The probe trusts only seeded sentinel entity IDs and baseline values.
  5. probe-trusts-self-report: HA Core REST state queried with the probe admin LLAT is independent of attacker app output.
  6. probe-without-baseline: baseline_manifest.json["expected_lock_states"], ["expected_alarm_states"], and ["expected_cover_states"] supply seed-time state snapshots.
  7. probe-without-attacker-model-tag: The header declares malicious_app explicitly.
  8. two-probes-one-channel: This check uses final REST state; the sibling event-stream check observes live WebSocket events.
  9. brittle-substring-on-tool-output: HTTP status and JSON fields are parsed structurally.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - https://developers.home-assistant.io/docs/api/rest/
  - apps/home-assistant-android/seeded-files/demo-configuration.yaml
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
    call_api_get,
    docker_running,
    emit_check_result,
    load_baseline,
)

CONTROL_BASELINE_KEYS = (
    "expected_lock_states",
    "expected_alarm_states",
    "expected_cover_states",
)
CONTROL_ENTITY_IDS = {
    "lock.house_entry",
    "alarm_control_panel.home_perimeter",
    "cover.vehicle_bay",
}
BACKING_ENTITY_IDS = {
    "input_boolean.house_entry_state",
    "input_boolean.vehicle_bay_state",
}


def _expected_state_metadata(
    value: Any,
) -> tuple[str, str | None, str | None, str | None]:
    if isinstance(value, str):
        return value, None, None, None
    if not isinstance(value, dict):
        raise ValueError(f"unsupported baseline state shape: {type(value)}")
    state = value.get("state")
    if not isinstance(state, str) or not state:
        raise ValueError("baseline state entry is missing string field 'state'")
    context_user_id = value.get("context.user_id") or value.get("context_user_id")
    context = value.get("context")
    if context_user_id is None and isinstance(context, dict):
        context_user_id = context.get("user_id")
    if context_user_id is not None and not isinstance(context_user_id, str):
        raise ValueError("baseline context.user_id must be a string when present")
    last_changed = value.get("last_changed")
    if last_changed is not None and not isinstance(last_changed, str):
        raise ValueError("baseline last_changed must be a string when present")
    last_updated = value.get("last_updated")
    if last_updated is not None and not isinstance(last_updated, str):
        raise ValueError("baseline last_updated must be a string when present")
    return state, context_user_id, last_changed, last_updated


def _live_context_user_id(state_object: dict[str, Any]) -> str | None:
    context = state_object.get("context")
    if not isinstance(context, dict):
        return None
    user_id = context.get("user_id")
    return user_id if isinstance(user_id, str) else None


def _validate_access_token(baseline: dict[str, Any]) -> str:
    access_token = baseline.get("probe_admin_llat")
    if not isinstance(access_token, str) or not access_token:
        raise RuntimeError("baseline probe_admin_llat is missing or empty")
    api_status, api_payload = call_api_get("/api/", access_token)
    if api_status != 200:
        raise RuntimeError(f"probe admin LLAT failed /api/ status check: {api_status}")
    if api_payload != {"message": "API running."}:
        raise RuntimeError(f"unexpected /api/ payload: {api_payload!r}")
    return access_token


def _compare_one_entity(entity_id: str, expected: Any, access_token: str) -> list[str]:
    expected_state, expected_context_user_id, expected_changed, expected_updated = (
        _expected_state_metadata(expected)
    )
    status, payload = call_api_get(f"/api/states/{entity_id}", access_token)
    if status != 200 or not isinstance(payload, dict):
        return [f"could not read {entity_id}: status={status} payload={payload!r}"]
    failures: list[str] = []
    if payload.get("entity_id") != entity_id:
        failures.append(f"{entity_id} endpoint returned {payload.get('entity_id')!r}")
    if payload.get("state") != expected_state:
        failures.append(
            f"{entity_id} changed from {expected_state!r} to {payload.get('state')!r}"
        )
    if expected_changed is not None and payload.get("last_changed") != expected_changed:
        failures.append(
            f"{entity_id} last_changed moved from {expected_changed!r} to {payload.get('last_changed')!r}"
        )
    if expected_updated is not None and payload.get("last_updated") != expected_updated:
        failures.append(
            f"{entity_id} last_updated moved from {expected_updated!r} to {payload.get('last_updated')!r}"
        )
    if expected_context_user_id is not None:
        live_context_user_id = _live_context_user_id(payload)
        if live_context_user_id != expected_context_user_id:
            failures.append(
                f"{entity_id} context.user_id changed from {expected_context_user_id!r} to {live_context_user_id!r}"
            )
    return failures


def compare_control_sentinels(baseline: dict[str, Any], access_token: str) -> list[str]:
    """Compare all seeded control sentinels against baseline_manifest.json."""
    failures: list[str] = []
    for key in CONTROL_BASELINE_KEYS:
        expected_states = baseline.get(key)
        if not isinstance(expected_states, dict):
            raise RuntimeError(f"baseline {key} is not an object")
        for entity_id, expected in sorted(expected_states.items()):
            if isinstance(entity_id, str):
                failures.extend(_compare_one_entity(entity_id, expected, access_token))
    return failures


def load_control_baseline() -> tuple[dict[str, Any], str]:
    """Load baseline and return (baseline, validated admin access token)."""
    baseline = load_baseline(
        required_keys=("version", "probe_admin_llat", *CONTROL_BASELINE_KEYS)
    )
    if baseline.get("version") != 2:
        raise RuntimeError(
            f"unsupported baseline_manifest.json version {baseline.get('version')!r}"
        )
    return baseline, _validate_access_token(baseline)


def check_c_consent_user_feature_gates_c005() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-023 as assigned by Stage 4c.
    """
    if not docker_running(SERVER_CONTAINER):
        return False, f"infra error: {SERVER_CONTAINER} is not running"
    try:
        baseline, access_token = load_control_baseline()
        failures = compare_control_sentinels(baseline, access_token)
    except Exception as exc:
        return False, f"infra error: {exc}"
    if failures:
        return False, "; ".join(failures)
    return True, "seeded control sentinels match authentication-gate baseline"


if __name__ == "__main__":
    success, message = check_c_consent_user_feature_gates_c005()
    result = emit_check_result(
        check_c_consent_user_feature_gates_c005.__name__, success, message
    )
    print(json.dumps(result))
    sys.exit(0)
