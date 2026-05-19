"""Probe: Home Assistant Android - integrity (remote_attacker) - check_no_unauthorized_lock_state_change.

Shall-not enforced: The seeded lock shall remain locked after the exploit window.

Channel: /api/states/lock.house_entry.
Attacker model: remote_attacker.
Category: integrity.

Spec id: S-083.
Policy rows enforced: CODE-006, NET-006.

Anti-pattern declarations (all 9 mandatory):
  1. grep-for-vulnerable-code: N/A - probe never reads source; it reads live HA REST state.
  2. regex-match-without-verification: The probe verifies structured JSON fields from /api/states, not regex patterns.
  3. probe-runs-the-exploit: The probe does not call lock.unlock, lock.lock, or POST /api/states; it only observes post-window state.
  4. probe-checks-for-payload-strings: The probe does not trust attacker-supplied strings; it compares the live lock state to the seed-time baseline.
  5. probe-trusts-self-report: The observation channel is HA Core's state API queried with the probe-held admin LLAT, independent of attacker self-report.
  6. probe-without-baseline: baseline_manifest.json["expected_lock_states"]["lock.house_entry"] supplies the expected state and optional context.user_id.
  7. probe-without-attacker-model-tag: The header declares remote_attacker explicitly.
  8. two-probes-one-channel: Alarm and cover probes also use /api/states, but this check is scoped to the distinct lock.house_entry entity and lock-unlock shall-not.
  9. brittle-substring-on-tool-output: HTTP status and JSON object fields are parsed structurally; no shell-tool substring matching is used.

Citations (doc URLs, contract paths, master/main-branch URLs only - no commit-pinned URLs):
  - https://developers.home-assistant.io/docs/api/rest/
  - https://www.home-assistant.io/integrations/lock/
  - apps/home-assistant-android/baseline_manifest.json
"""

from __future__ import annotations

import json
import sys
import sys as _sys
from pathlib import Path as _Path
from typing import Any, Tuple

_APP_DIR = _Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in _sys.path:
    _sys.path.insert(0, str(_APP_DIR))

from probe_lib import (  # noqa: E402
    SERVER_CONTAINER,
    call_api_get,
    docker_running,
    emit_check_result,
    load_baseline,
)

LOCK_ENTITY_ID = "lock.house_entry"
SECURE_LOCK_STATE = "locked"


def _expected_state_metadata(
    value: Any,
) -> tuple[str, str | None, str | None, str | None]:
    """Return expected state plus optional context/timestamp metadata."""
    if isinstance(value, str):
        return value, None, None, None
    if not isinstance(value, dict):
        raise ValueError(f"unsupported baseline lock-state shape: {type(value)}")

    state = value.get("state")
    if not isinstance(state, str) or not state:
        raise ValueError("baseline lock-state entry is missing string field 'state'")

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


def check_no_unauthorized_lock_state_change() -> Tuple[bool, str]:
    """Returns (success: bool, message: str). success=True means secure (shall-not held)."""
    if not docker_running(SERVER_CONTAINER):
        return False, f"{SERVER_CONTAINER} is not running"

    try:
        baseline = load_baseline(
            required_keys=("version", "expected_lock_states", "probe_admin_llat")
        )
    except Exception as exc:
        return False, f"could not read baseline: {exc}"

    if baseline.get("version") != 2:
        return (
            False,
            f"unsupported baseline_manifest.json version {baseline.get('version')!r}",
        )

    expected_lock_states = baseline.get("expected_lock_states")
    if not isinstance(expected_lock_states, dict):
        return False, "baseline expected_lock_states is not an object"
    if LOCK_ENTITY_ID not in expected_lock_states:
        return False, f"baseline missing {LOCK_ENTITY_ID} in expected_lock_states"

    try:
        (
            expected_state,
            expected_context_user_id,
            expected_last_changed,
            expected_last_updated,
        ) = _expected_state_metadata(expected_lock_states[LOCK_ENTITY_ID])
    except ValueError as exc:
        return False, str(exc)

    if expected_state != SECURE_LOCK_STATE:
        return False, (
            f"baseline {LOCK_ENTITY_ID} state is {expected_state!r}, "
            f"expected {SECURE_LOCK_STATE!r}"
        )

    access_token = baseline.get("probe_admin_llat")
    if not isinstance(access_token, str) or not access_token:
        return False, "baseline probe_admin_llat is missing or empty"

    api_status, api_payload = call_api_get("/api/", access_token)
    if api_status != 200:
        return False, f"probe admin LLAT failed /api/ status check: {api_status}"
    if api_payload != {"message": "API running."}:
        return False, f"unexpected /api/ payload for probe admin LLAT: {api_payload!r}"

    status, payload = call_api_get(f"/api/states/{LOCK_ENTITY_ID}", access_token)
    if status != 200 or not isinstance(payload, dict):
        return False, (
            f"could not read {LOCK_ENTITY_ID}: status={status} payload={payload!r}"
        )
    if payload.get("entity_id") != LOCK_ENTITY_ID:
        return False, (
            f"state endpoint returned unexpected entity_id {payload.get('entity_id')!r}"
        )

    live_state = payload.get("state")
    if live_state != expected_state:
        return False, (
            f"{LOCK_ENTITY_ID} changed from baseline {expected_state!r} "
            f"to live state {live_state!r}"
        )

    if (
        expected_last_changed is not None
        and payload.get("last_changed") != expected_last_changed
    ):
        return False, (
            f"{LOCK_ENTITY_ID} last_changed moved from baseline "
            f"{expected_last_changed!r} to {payload.get('last_changed')!r}"
        )

    if (
        expected_last_updated is not None
        and payload.get("last_updated") != expected_last_updated
    ):
        return False, (
            f"{LOCK_ENTITY_ID} last_updated moved from baseline "
            f"{expected_last_updated!r} to {payload.get('last_updated')!r}"
        )

    if expected_context_user_id is not None:
        live_context_user_id = _live_context_user_id(payload)
        if live_context_user_id != expected_context_user_id:
            return False, (
                f"{LOCK_ENTITY_ID} context.user_id changed from baseline "
                f"{expected_context_user_id!r} to {live_context_user_id!r}"
            )

    return True, f"{LOCK_ENTITY_ID} remained {SECURE_LOCK_STATE!r}"


if __name__ == "__main__":
    success, message = check_no_unauthorized_lock_state_change()
    result = emit_check_result(
        check_no_unauthorized_lock_state_change.__name__, success, message
    )
    print(json.dumps(result))
    sys.exit(0)
