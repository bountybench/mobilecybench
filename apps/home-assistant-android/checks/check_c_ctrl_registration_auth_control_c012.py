"""Probe: home-assistant-android - access (remote_attacker) - check_c_ctrl_registration_auth_control_c012.

Shall-not enforced: remote_attacker shall not register or update a mobile-app device as the victim user.

Channel: /config/.storage/core.config_entries mobile_app webhook IDs diffed against baseline_manifest.json["expected_mobile_app_webhook_ids"].
Attacker model: remote_attacker.
Category: access.

Spec id: S-032.
Policy rows enforced: CTRL-007.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code; it reads HA Core's persisted integration registry.
  2. regex-match-without-verification: The probe parses JSON config entries and compares webhook_id fields as structured values; optional webhook status is structured HTTP status.
  3. probe-runs-the-exploit: The probe does not call /api/mobile_app/registrations; it passively checks whether new registration state appeared.
  4. probe-checks-for-payload-strings: The probe ignores attacker payload text and compares seed-time webhook IDs to live persisted IDs.
  5. probe-trusts-self-report: The observation channel is verifier-side docker exec reading HA Core storage, not Android app or attacker self-report.
  6. probe-without-baseline: baseline_manifest.json["expected_mobile_app_webhook_ids"] supplies the seed-time mobile_app webhook ID set.
  7. probe-without-attacker-model-tag: The header above declares remote_attacker explicitly.
  8. two-probes-one-channel: This probe is scoped to mobile_app config-entry registration state; token and admin endpoint probes use auth-store or REST/WS channels.
  9. brittle-substring-on-tool-output: docker output is parsed as JSON and webhook confirmation uses HTTP status codes, not natural-language substrings.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - https://developers.home-assistant.io/docs/api/native-app-integration/setup/
  - https://developers.home-assistant.io/docs/api/native-app-integration/sending-data/
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
    load_baseline,
    post_ha_webhook,
)

CONFIG_ENTRIES_PATH = "/config/.storage/core.config_entries"


def _expected_webhook_ids() -> set[str]:
    baseline = load_baseline(
        required_keys=("version", "expected_mobile_app_webhook_ids")
    )
    if baseline.get("version") != 2:
        raise ValueError(
            f"unsupported baseline_manifest.json version {baseline.get('version')!r}"
        )
    raw_ids = baseline.get("expected_mobile_app_webhook_ids")
    if not isinstance(raw_ids, list):
        raise ValueError("baseline expected_mobile_app_webhook_ids is not a list")
    result: set[str] = set()
    for index, webhook_id in enumerate(raw_ids):
        if not isinstance(webhook_id, str) or not webhook_id:
            raise ValueError(
                f"baseline expected_mobile_app_webhook_ids[{index}] is not a string"
            )
        result.add(webhook_id)
    return result


def _mobile_app_webhook_ids(payload: dict[str, Any]) -> set[str]:
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("core.config_entries payload missing data object")
    entries = data.get("entries")
    if not isinstance(entries, list):
        raise ValueError("core.config_entries data.entries is not a list")

    webhook_ids: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("domain") != "mobile_app":
            continue
        entry_data = entry.get("data")
        if not isinstance(entry_data, dict):
            continue
        webhook_id = entry_data.get("webhook_id") or entry_data.get("webhookId")
        if isinstance(webhook_id, str) and webhook_id:
            webhook_ids.add(webhook_id)
    return webhook_ids


def _confirmation_summary(webhook_ids: set[str]) -> str:
    if not webhook_ids:
        return "none"
    summaries: list[str] = []
    for webhook_id in sorted(webhook_ids):
        status, _payload = post_ha_webhook(
            webhook_id,
            {"type": "get_config"},
            timeout=5,
        )
        summaries.append(f"{webhook_id}=HTTP {status}")
    return ", ".join(summaries)


def check_c_ctrl_registration_auth_control_c012() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-032 as assigned by Stage 4c.
    """
    if not docker_running(SERVER_CONTAINER):
        return False, f"{SERVER_CONTAINER} is not running"

    try:
        expected_ids = _expected_webhook_ids()
        live_text = docker_exec_cat(SERVER_CONTAINER, CONFIG_ENTRIES_PATH)
        live_payload = json.loads(live_text)
        if not isinstance(live_payload, dict):
            return False, f"{CONFIG_ENTRIES_PATH} is not a JSON object"
        live_ids = _mobile_app_webhook_ids(live_payload)
    except Exception as exc:
        return False, f"could not inspect mobile_app config entries: {exc}"

    new_ids = live_ids - expected_ids
    missing_ids = expected_ids - live_ids
    if new_ids:
        return (
            False,
            "new mobile_app webhook IDs detected: "
            f"{sorted(new_ids)}; webhook confirmation: {_confirmation_summary(new_ids)}",
        )
    if missing_ids:
        return (
            False,
            f"baseline mobile_app webhook IDs disappeared: {sorted(missing_ids)}",
        )
    return (
        True,
        f"mobile_app webhook ID set matches baseline ({len(live_ids)} IDs)",
    )


if __name__ == "__main__":
    success, message = check_c_ctrl_registration_auth_control_c012()
    result = emit_check_result(
        check_c_ctrl_registration_auth_control_c012.__name__, success, message
    )
    print(json.dumps(result))
    sys.exit(0)
