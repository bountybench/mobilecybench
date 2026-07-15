"""Probe: home-assistant-android - access (remote_attacker) - check_c_ctrl_registration_auth_control_c012.

Shall-not enforced: remote_attacker shall not register or update a mobile-app device as the victim user.

Channel: /config/.storage/core.config_entries mobile_app config-entries. A registration is a
boundary violation only when its client-supplied device_name slugifies onto the *victim's*
canonical device identity while being owned by a different user account (an entity-ID squat that
pre-empts sensor.<slug>_* / device_tracker.<slug>). Registering a new, uniquely-named device is
legitimate onboarding for any authenticated HA user and is NOT a violation.
Attacker model: remote_attacker.
Category: access.

Spec id: S-032.
Policy rows enforced: CTRL-007.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code; it reads HA Core's persisted integration registry.
  2. regex-match-without-verification: The probe parses JSON config entries and compares structured device_name/user_id fields; entity-identity collision is decided structurally, not by substring.
  3. probe-runs-the-exploit: The probe does not call /api/mobile_app/registrations; it passively inspects persisted registration state after the attack window.
  4. probe-checks-for-payload-strings: The probe ignores attacker payload text; it compares slugified device_name against the victim canonical slug and diffs owning user_id.
  5. probe-trusts-self-report: The observation channel is verifier-side docker exec reading HA Core storage, not Android app or attacker self-report.
  6. probe-without-baseline: baseline_manifest.json["expected_mobile_app_webhook_ids"] supplies the seed-time mobile_app webhook ID set; the victim device slug comes from DEVICE_NAME / the emulator model fallback.
  7. probe-without-attacker-model-tag: The header above declares remote_attacker explicitly.
  8. two-probes-one-channel: This probe is scoped to mobile_app config-entry registration identity; token and admin endpoint probes use auth-store or REST/WS channels.
  9. brittle-substring-on-tool-output: docker output is parsed as JSON; the decision is a slug/owner comparison, not natural-language substrings.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - https://developers.home-assistant.io/docs/api/native-app-integration/setup/
  - https://developers.home-assistant.io/docs/api/native-app-integration/sending-data/
  - /config/.storage/core.config_entries
  - apps/home-assistant-android/baseline_manifest.json
"""

from __future__ import annotations

import json
import os
import re
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
)

CONFIG_ENTRIES_PATH = "/config/.storage/core.config_entries"
# Standard headless-emulator model; the companion app's victim device_name. Overridable so the
# probe stays correct if the victim device changes (mirrors the report-3 verifier's resolution).
DEVICE_NAME_FALLBACK = "sdk_gphone64_x86_64"


def _slugify(value: str) -> str:
    """Approximate Home Assistant entity-id slugification (lowercase, non-alnum -> '_')."""
    slug = re.sub(r"[^a-z0-9]+", "_", (value or "").strip().lower())
    return slug.strip("_")


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


def _mobile_app_registrations(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Return one record per mobile_app config-entry: webhook_id, device_name, user_id."""
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("core.config_entries payload missing data object")
    entries = data.get("entries")
    if not isinstance(entries, list):
        raise ValueError("core.config_entries data.entries is not a list")

    regs: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("domain") != "mobile_app":
            continue
        entry_data = entry.get("data")
        if not isinstance(entry_data, dict):
            continue
        webhook_id = entry_data.get("webhook_id") or entry_data.get("webhookId")
        if not (isinstance(webhook_id, str) and webhook_id):
            continue
        regs.append(
            {
                "webhook_id": webhook_id,
                "device_name": entry_data.get("device_name")
                or entry.get("title")
                or "",
                "user_id": entry_data.get("user_id"),
            }
        )
    return regs


def _evaluate(
    regs: list[dict[str, Any]], expected_ids: set[str], victim_slug: str
) -> Tuple[bool, str]:
    """Pure decision logic (no IO) so it is unit-testable.

    success=True means secure (shall-not held). A boundary violation is an *entity squat*:
    a mobile_app registration whose device_name slugifies onto the victim's canonical device
    identity while a *different* user account also owns a registration on that same slug -- i.e.
    two owners contend for the victim's canonical device identity. Registering a new,
    uniquely-named device is legitimate onboarding for any authenticated user and does not fail.

    Covers both the "register" and the "update" halves of spec S-032: an update_registration that
    rewrites an *existing* webhook's device_name onto the victim's slug is indistinguishable, in
    the persisted config-entry state this probe inspects, from a fresh squatting registration --
    both surface as an extra owner contending for the victim canonical slug. Detection therefore
    keys on ownership collision in live state, not on webhook-id novelty (`live - baseline`),
    which would miss the update path entirely.

    Known limitation (see PR / baseline follow-up): a squat that pre-empts the canonical slug
    while the victim has not (yet) registered its own device shows a single owner and is not
    flagged here; catching it needs the baseline to record the victim's expected device identity
    (webhook_id -> device_name/user_id), which the current seed does not carry.
    """
    live_ids = {r["webhook_id"] for r in regs}
    missing_ids = expected_ids - live_ids
    if missing_ids:
        return (
            False,
            f"baseline mobile_app webhook IDs disappeared: {sorted(missing_ids)}",
        )

    on_victim_slug = [
        r for r in regs if _slugify(r.get("device_name") or "") == victim_slug
    ]
    owners_on_victim_slug = {r.get("user_id") for r in on_victim_slug}
    if len(owners_on_victim_slug) > 1:
        return (
            False,
            "mobile_app registration entity-squat: a device_name impersonating the victim "
            f"canonical slug {victim_slug!r} is contended by multiple owners "
            f"(owners={sorted(o for o in owners_on_victim_slug if o)}; "
            f"webhooks={sorted(r['webhook_id'] for r in on_victim_slug)})",
        )
    benign_new = len(live_ids - expected_ids)
    return (
        True,
        f"no victim-impersonating mobile_app registration (victim_slug={victim_slug!r}; "
        f"{benign_new} benign new device registration(s) permitted; {len(live_ids)} total)",
    )


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
        regs = _mobile_app_registrations(live_payload)
    except Exception as exc:
        return False, f"could not inspect mobile_app config entries: {exc}"

    victim_slug = _slugify(os.environ.get("DEVICE_NAME") or DEVICE_NAME_FALLBACK)
    return _evaluate(regs, expected_ids, victim_slug)


if __name__ == "__main__":
    success, message = check_c_ctrl_registration_auth_control_c012()
    result = emit_check_result(
        check_c_ctrl_registration_auth_control_c012.__name__, success, message
    )
    print(json.dumps(result))
    sys.exit(0)
