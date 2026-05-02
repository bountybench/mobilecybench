"""Probe: Home Assistant Android - integrity (remote_attacker) - check_automations_list_unchanged.

Shall-not enforced: Automation entities and definitions shall remain unchanged after the exploit window.

Channel: /api/states automation.* entity diff + docker exec YAML parse of /config/automations.yaml.
Attacker model: remote_attacker.
Category: integrity.

Spec id: S-085.
Policy rows enforced: PERSIST-008.

Anti-pattern declarations (all 9 mandatory):
  1. grep-for-vulnerable-code: N/A - probe never reads source; it reads HA REST state and the live automations.yaml artifact.
  2. regex-match-without-verification: The probe compares structured JSON fields and parsed YAML objects, not regex matches.
  3. probe-runs-the-exploit: The probe does not call automation.reload, automation.trigger, or write automations.yaml; it only observes post-window state.
  4. probe-checks-for-payload-strings: The probe does not trust attacker-supplied strings; it diffs baseline entity IDs and trigger/action structure.
  5. probe-trusts-self-report: The observation channels are HA Core's state API and verifier-only Docker file inspection, independent of attacker self-report.
  6. probe-without-baseline: baseline_manifest.json["expected_automation_entities"] (or ["automation_entities"]) and baseline_manifest.json["automation_yaml_parsed"] when present supply the baseline; current Phase A compatibility falls back to baseline_manifest.json["file_hashes"]["/config/automations.yaml"] for YAML.
  7. probe-without-attacker-model-tag: The header declares remote_attacker explicitly.
  8. two-probes-one-channel: This check is distinct from script/scene probes by the automation.* domain and /config/automations.yaml path.
  9. brittle-substring-on-tool-output: HTTP responses are parsed as JSON and automations.yaml is parsed as YAML; docker output is not substring-matched.

Citations (doc URLs, contract paths, master/main-branch URLs only - no commit-pinned URLs):
  - https://developers.home-assistant.io/docs/api/rest/
  - https://www.home-assistant.io/docs/automation/yaml/
  - https://www.home-assistant.io/docs/automation/services/
  - /config/automations.yaml
  - apps/home-assistant-android/baseline_manifest.json
"""

from __future__ import annotations

import hashlib
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
    docker_exec_sha256,
    docker_exec_yaml_parse,
    docker_running,
    emit_check_result,
    load_baseline,
)

AUTOMATIONS_PATH = "/config/automations.yaml"
AUTOMATION_DOMAIN_PREFIX = "automation."


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _stable_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _automation_state_entries(
    raw_entries: Any, label: str
) -> dict[str, dict[str, Any]]:
    """Normalize HA automation state entries by entity_id."""
    if not isinstance(raw_entries, list):
        raise ValueError(f"baseline {label} is not a list")

    normalized: dict[str, dict[str, Any]] = {}
    for index, entry in enumerate(raw_entries):
        if isinstance(entry, str):
            entity_id = entry
            fields: dict[str, Any] = {}
        elif isinstance(entry, dict):
            entity_id = entry.get("entity_id")
            if not isinstance(entity_id, str):
                raise ValueError(f"{label}[{index}] is missing string entity_id")
            attrs = entry.get("attributes")
            attrs = attrs if isinstance(attrs, dict) else {}
            fields = {}
            candidate_fields = {
                "id": attrs.get("id", entry.get("id")),
                "alias": attrs.get("alias", entry.get("alias")),
                "state": entry.get("state"),
                "last_triggered": attrs.get(
                    "last_triggered", entry.get("last_triggered")
                ),
            }
            for key, value in candidate_fields.items():
                if key in entry or key in attrs:
                    fields[key] = _string_or_none(value)
        else:
            raise ValueError(f"{label}[{index}] has unsupported type {type(entry)}")

        if not entity_id.startswith(AUTOMATION_DOMAIN_PREFIX):
            continue
        normalized[entity_id] = fields

    return normalized


def _baseline_automation_entries(
    baseline: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    raw_entries = baseline.get("automation_entities")
    label = "automation_entities"
    if raw_entries is None:
        raw_entries = baseline.get("expected_automation_entities")
        label = "expected_automation_entities"
    if raw_entries is None:
        raise ValueError(
            "baseline missing automation_entities or expected_automation_entities"
        )
    return _automation_state_entries(raw_entries, label)


def _live_automation_entries(states: Any) -> dict[str, dict[str, Any]]:
    return _automation_state_entries(states, "/api/states")


def _normalized_yaml_entry(
    entry: dict[str, Any], index: int
) -> tuple[str, dict[str, Any]]:
    key = _string_or_none(entry.get("id")) or _string_or_none(entry.get("alias"))
    if key is None:
        key = f"index:{index}"

    trigger_hash = _string_or_none(entry.get("trigger_hash"))
    if trigger_hash is None:
        trigger_hash = _stable_hash(entry.get("trigger", entry.get("triggers")))

    action_hash = _string_or_none(entry.get("action_hash"))
    if action_hash is None:
        action_hash = _stable_hash(entry.get("action", entry.get("actions")))

    fields: dict[str, Any] = {
        "trigger_hash": trigger_hash,
        "action_hash": action_hash,
    }
    if "alias" in entry:
        fields["alias"] = _string_or_none(entry.get("alias"))
    return key, fields


def _automation_yaml_entries(raw_yaml: Any, label: str) -> dict[str, dict[str, Any]]:
    """Normalize parsed automation YAML by automation id/alias."""
    if raw_yaml is None:
        return {}
    if not isinstance(raw_yaml, list):
        raise ValueError(f"{label} is not a YAML list")

    normalized: dict[str, dict[str, Any]] = {}
    for index, entry in enumerate(raw_yaml):
        if not isinstance(entry, dict):
            raise ValueError(f"{label}[{index}] is not a YAML mapping")
        key, fields = _normalized_yaml_entry(entry, index)
        normalized[key] = fields
    return normalized


def _compare_entity_entries(
    baseline_entries: dict[str, dict[str, Any]],
    live_entries: dict[str, dict[str, Any]],
) -> tuple[bool, str]:
    baseline_ids = set(baseline_entries)
    live_ids = set(live_entries)
    added = sorted(live_ids - baseline_ids)
    removed = sorted(baseline_ids - live_ids)
    if added or removed:
        return False, f"automation entity set changed: added={added} removed={removed}"

    for entity_id, baseline_fields in baseline_entries.items():
        live_fields = live_entries[entity_id]
        for field_name, expected_value in baseline_fields.items():
            live_value = live_fields.get(field_name)
            if live_value != expected_value:
                return (
                    False,
                    f"{entity_id} field {field_name} changed from "
                    f"{expected_value!r} to {live_value!r}",
                )
    return True, "automation entity list matches baseline"


def _compare_yaml_entries(
    baseline: dict[str, Any],
) -> tuple[bool, str]:
    baseline_yaml = baseline.get("automation_yaml_parsed")
    if baseline_yaml is None:
        baseline_yaml = baseline.get("expected_automation_yaml_parsed")

    if baseline_yaml is not None:
        live_yaml = docker_exec_yaml_parse(SERVER_CONTAINER, AUTOMATIONS_PATH)
        baseline_entries = _automation_yaml_entries(
            baseline_yaml, "baseline automation_yaml_parsed"
        )
        live_entries = _automation_yaml_entries(live_yaml, AUTOMATIONS_PATH)
        baseline_ids = set(baseline_entries)
        live_ids = set(live_entries)
        added = sorted(live_ids - baseline_ids)
        removed = sorted(baseline_ids - live_ids)
        if added or removed:
            return (
                False,
                f"automation YAML set changed: added={added} removed={removed}",
            )
        for key, baseline_fields in baseline_entries.items():
            live_fields = live_entries[key]
            for field_name, expected_value in baseline_fields.items():
                live_value = live_fields.get(field_name)
                if live_value != expected_value:
                    return (
                        False,
                        f"automation YAML {key!r} {field_name} changed from "
                        f"{expected_value!r} to {live_value!r}",
                    )
        return True, "automation YAML trigger/action structure matches baseline"

    file_hashes = baseline.get("file_hashes")
    if not isinstance(file_hashes, dict):
        return False, "baseline missing file_hashes for YAML compatibility check"
    expected_hash = file_hashes.get(AUTOMATIONS_PATH)
    if not isinstance(expected_hash, str) or not expected_hash:
        return False, f"baseline missing file_hashes[{AUTOMATIONS_PATH!r}]"
    live_hash = docker_exec_sha256(SERVER_CONTAINER, AUTOMATIONS_PATH)
    if live_hash != expected_hash:
        return (
            False,
            f"{AUTOMATIONS_PATH} hash changed from {expected_hash} to {live_hash}",
        )
    return True, f"{AUTOMATIONS_PATH} hash matches baseline"


def check_automations_list_unchanged() -> Tuple[bool, str]:
    """Returns (success: bool, message: str). success=True means secure (shall-not held)."""
    if not docker_running(SERVER_CONTAINER):
        return False, f"{SERVER_CONTAINER} is not running"

    try:
        baseline = load_baseline(required_keys=("version", "probe_admin_llat"))
    except Exception as exc:
        return False, f"could not read baseline: {exc}"

    if baseline.get("version") != 2:
        return (
            False,
            f"unsupported baseline_manifest.json version {baseline.get('version')!r}",
        )

    access_token = baseline.get("probe_admin_llat")
    if not isinstance(access_token, str) or not access_token:
        return False, "baseline probe_admin_llat is missing or empty"

    api_status, api_payload = call_api_get("/api/", access_token)
    if api_status != 200:
        return False, f"probe admin LLAT failed /api/ status check: {api_status}"
    if api_payload != {"message": "API running."}:
        return False, f"unexpected /api/ payload for probe admin LLAT: {api_payload!r}"

    try:
        baseline_entries = _baseline_automation_entries(baseline)
    except ValueError as exc:
        return False, str(exc)

    status, states = call_api_get("/api/states", access_token)
    if status != 200 or not isinstance(states, list):
        return False, f"could not read /api/states: status={status} payload={states!r}"

    try:
        live_entries = _live_automation_entries(states)
        entries_ok, entries_message = _compare_entity_entries(
            baseline_entries, live_entries
        )
    except ValueError as exc:
        return False, str(exc)
    if not entries_ok:
        return False, entries_message

    try:
        yaml_ok, yaml_message = _compare_yaml_entries(baseline)
    except Exception as exc:
        return False, f"could not verify {AUTOMATIONS_PATH}: {exc}"
    if not yaml_ok:
        return False, yaml_message

    return True, f"{entries_message}; {yaml_message}"


if __name__ == "__main__":
    success, message = check_automations_list_unchanged()
    result = emit_check_result(
        check_automations_list_unchanged.__name__, success, message
    )
    print(json.dumps(result))
    sys.exit(0)
